#!/usr/bin/env python3
"""Recompute every published count and the two SVG figures from public evidence."""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import html
import json
import math
import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MODELS = DATA / "models"
PROMPT = "Invent a literary novel title. Title only."
CARTOGRAPH = re.compile(r"\bcartograph\w*", re.I)
CARTOGRAPHER = re.compile(r"\bcartographer\b", re.I)
CARTOGRAPHY = re.compile(r"\bcartography\b", re.I)
OF_HEAD = re.compile(r"^The (.+?) of\s+", re.I)


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Nominal 95% Wilson interval under an IID Bernoulli approximation."""
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / denominator
    return center - margin, center + margin


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def normalize_title(value: str) -> str:
    """Remove transcript-only wrappers; preserve lexical content and punctuation."""
    value = value.strip()
    wrappers = (("**", "**"), ("__", "__"), ("*", "*"), ("_", "_"),
                ('"', '"'), ("“", "”"))
    while True:
        for left, right in wrappers:
            if value.startswith(left) and value.endswith(right) and len(value) > len(left) + len(right):
                value = value[len(left):-len(right)].strip()
                break
        else:
            return value


def summarize(identifier: str, label: str, tier: str, raw_values: list[str]) -> dict:
    raw = [value.strip() for value in raw_values]
    values = [normalize_title(value) for value in raw]
    counts = collections.Counter(values)
    mode_count = max(counts.values())
    pair_count = len(values) * (len(values) - 1) // 2
    collisions = sum(count * (count - 1) // 2 for count in counts.values())
    heads = collections.Counter()
    for value in values:
        match = OF_HEAD.match(value)
        if match:
            heads[match.group(1)] += 1
    families = {"cartograph*": sum(bool(CARTOGRAPH.search(value)) for value in values)}
    families.update({f"The {head} of …": count for head, count in heads.items()})
    family_count = max(families.values())
    dominant_families = sorted(family for family, count in families.items() if count == family_count)
    interval = wilson_interval(families["cartograph*"], len(values))
    return {
        "id": identifier, "label": label, "tier": tier, "n": len(values),
        "hits": families["cartograph*"],
        "cartographer": sum(bool(CARTOGRAPHER.search(value)) for value in values),
        "cartography": sum(bool(CARTOGRAPHY.search(value)) for value in values),
        "raw_unique": len(set(raw)), "unique": len(counts), "mode_count": mode_count,
        "modes": sorted(title for title, count in counts.items() if count == mode_count),
        "mode_share": mode_count / len(values),
        "collision_rate": collisions / pair_count if pair_count else 0.0,
        "wilson_low": interval[0], "wilson_high": interval[1],
        "counts": counts, "heads": heads, "dominant_families": dominant_families,
        "dominant_family": " / ".join(dominant_families),
        "dominant_family_count": family_count, "values": values,
    }


def check_sha256_sidecar(sidecar: Path, payload: Path | None = None) -> None:
    expected, recorded_path = sidecar.read_text().strip().split(maxsplit=1)
    target = payload or ROOT / recorded_path
    assert hashlib.sha256(target.read_bytes()).hexdigest() == expected, sidecar


def load_primary(write_ledger: bool = False) -> list[dict]:
    original_rows = csv_rows(DATA / "luna_codex_200.csv")
    failures = csv_rows(DATA / "luna_codex_failed_attempts.csv")
    assert len(original_rows) == 200
    assert [int(row["sample"]) for row in original_rows] == list(range(1, 201))
    assert len({row["session_id"] for row in original_rows}) == 200
    assert all(row["prompt"] == PROMPT for row in original_rows)
    assert all(int(row["cartograph"]) == bool(CARTOGRAPH.search(row["raw_answer"])) for row in original_rows)
    assert len(failures) == 1 and failures[0]["failure"] == "Usage limit"
    assert failures[0]["session_id"] not in {row["session_id"] for row in original_rows}
    original = summarize("luna_codex", "Luna / original Codex (low)", "PRIMARY / AUDITED",
                         [row["raw_answer"] for row in original_rows])
    assert (original["hits"], original["cartographer"], original["cartography"], original["unique"]) == (199, 157, 42, 28)
    assert original["counts"]["The Cartographer of Vanishing Hours"] == 58

    attempt_files = ["luna_container_attempts.csv", "luna_container_extension_80.csv",
                     "luna_container_final_extension.csv", "luna_container_completion_47.csv"]
    source_rows = [(name, ordinal, row) for name in attempt_files
                   for ordinal, row in enumerate(csv_rows(DATA / name), 1)]
    attempts = [row for _, _, row in source_rows]
    valid = [row for row in attempts if row["valid"] == "True"]
    # This is a derived view, never an additional cohort in the analysis.
    ledger = []
    for name, ordinal, row in source_rows:
        if row["valid"] != "True":
            continue
        ledger.append({
            "sample": str(len(ledger) + 1), "source_file": name,
            "source_row": str(ordinal), "session_id": row["session_id"],
            "started_utc": row["started_utc"], "prompt": row["prompt"],
            "raw_answer": row["raw_answer"],
            "cartograph": str(int(bool(CARTOGRAPH.search(row["raw_answer"])))),
            "valid": row["valid"],
        })
    ledger_path = DATA / "luna_reduced_context_200.csv"
    if write_ledger:
        with ledger_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(ledger[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(ledger)
    assert csv_rows(ledger_path) == ledger, "Consolidated ledger differs from source segments"
    assert len(attempts) == 202 and len(valid) == 200
    assert len({row["session_id"] for row in attempts}) == 202
    assert all(row["prompt"] == PROMPT for row in attempts)
    invalid = [row for row in attempts if row["valid"] != "True"]
    assert len(invalid) == 2
    # The compact initial ledger predates the explicit failure column; its lone
    # nonzero, answerless attempt is documented by the frozen initial evidence.
    assert invalid[0]["returncode"] == "1" and not invalid[0]["raw_answer"]
    assert invalid[1]["failure"] == "Unexpected stderr"
    container = summarize("luna_container", "Luna / reduced-context container (low)", "PRIMARY / AUDITED",
                          [row["raw_answer"] for row in valid])
    assert (container["hits"], container["cartographer"], container["cartography"], container["unique"]) == (198, 154, 44, 28)
    assert container["counts"]["The Cartographer of Vanishing Roads"] == 48
    returned = [row["raw_answer"] for row in attempts if row["raw_answer"].strip()]
    assert (sum(bool(CARTOGRAPH.search(value)) for value in returned), len(returned)) == (199, 201)

    for name in ("luna_container_extension_protocol", "luna_container_final_protocol", "luna_container_completion_protocol"):
        check_sha256_sidecar(DATA / f"{name}.sha256")
        protocol = json.loads((DATA / f"{name}.json").read_text())
        assert protocol["prompt"] == PROMPT and protocol["model"] == "gpt-5.6-luna"
        assert protocol["reasoning_effort"] == "low"
    context = json.loads((DATA / "context/manifest.json").read_text())
    for relative, expected in context["export_sha256"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected

    original["attempts"] = 201
    original["halves"] = [sum(bool(CARTOGRAPH.search(row["raw_answer"])) for row in half)
                          for half in (original_rows[:100], original_rows[100:])]
    original["session_ids"] = [row["session_id"] for row in original_rows] + [failures[0]["session_id"]]
    container["attempts"] = 202
    container["halves"] = [sum(bool(CARTOGRAPH.search(row["raw_answer"])) for row in half)
                           for half in (valid[:100], valid[100:])]
    container["session_ids"] = [row["session_id"] for row in attempts]
    return [original, container]


def verify_terra() -> collections.Counter:
    base = MODELS / "logged"
    check_sha256_sidecar(base / "terra_container_protocol.sha256", base / "terra_container_protocol.json")
    protocol = json.loads((base / "terra_container_protocol.json").read_text())
    assert protocol["prompt"] == PROMPT and protocol["model"] == "gpt-5.6-terra"
    assert protocol["reasoning_effort"] == "low" and protocol["hard_attempt_ceiling"] == 50
    source_paths = {
        "runner": ROOT / "analysis/run_terra_container.py",
        "entry.py": base / "terra_container_entry.py",
        "instructions.txt": base / "terra_container_instructions.txt",
        "audit": DATA / "context/terra_container.json",
    }
    for key, path in source_paths.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == protocol["source_hashes"][key], key
    check_sha256_sidecar(base / "terra_container_continuation.sha256", base / "terra_container_continuation.json")
    continuation = json.loads((base / "terra_container_continuation.json").read_text())
    assert continuation["prior_completed"] == 37 and continuation["remaining_attempts"] == 13
    assert hashlib.sha256((ROOT / "analysis/continue_terra_container.py").read_bytes()).hexdigest() == continuation["continuation_runner_sha256"]
    raw_bytes = (base / "terra_container_raw.jsonl").read_bytes()
    assert hashlib.sha256(raw_bytes[:continuation["prior_raw_bytes"]]).hexdigest() == continuation["prior_raw_sha256"]
    records = [json.loads(line) for line in raw_bytes.decode().splitlines()]
    exported = csv_rows(base / "terra_container.csv")
    assert len(records) == len(exported) == 50
    totals = collections.Counter()
    previous_end = None
    for index, (record, row) in enumerate(zip(records, exported), 1):
        assert int(row["sample"]) == record["attempt"] == index
        assert record["status"] == "completed" and record["returncode"] == 0
        assert row["prompt"] == record["prompt"] == PROMPT
        assert row["session_id"] == record["session_id"] and row["raw_answer"] == record["raw_answer"]
        start, end = dt.datetime.fromisoformat(row["started_utc"]), dt.datetime.fromisoformat(row["completed_utc"])
        assert end >= start
        if previous_end:
            assert (start - previous_end).total_seconds() >= protocol["minimum_completion_to_next_launch_gap_seconds"]
        previous_end = end
        assert not record["stderr"].strip()
        events = [json.loads(line) for line in record["stdout"].splitlines() if line.strip()]
        assert [event["thread_id"] for event in events if event["type"] == "thread.started"] == [row["session_id"]]
        assert [event["item"]["text"] for event in events if event["type"] == "item.completed" and event["item"]["type"] == "agent_message"] == [row["raw_answer"]]
        for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
            assert int(row[key]) == record["usage"][key]
        totals.update(record["usage"])
    return totals


def load_metadata() -> list[dict[str, str]]:
    metadata = csv_rows(MODELS / "metadata.csv")
    assert len(metadata) == len({row["condition_id"] for row in metadata})
    return metadata


def load_comparisons(metadata: list[dict[str, str]]) -> list[dict]:
    results = []
    for item in metadata:
        if item["evidence_tier"] == "PRIMARY / AUDITED":
            continue
        path = MODELS / item["file"]
        if path.suffix == ".csv":
            records = csv_rows(path)
            assert all(row["prompt"] == PROMPT for row in records)
            assert len(records) == len({row["session_id"] for row in records})
            raw = [row["raw_answer"] for row in records]
            session_ids = [row["session_id"] for row in records]
        else:
            raw = [line for line in path.read_text().splitlines() if line.strip()]
            if item["condition_id"] == "work_luna_light":
                for index, line in enumerate(raw, 1):
                    assert re.match(rf"^{index}\.\s+", line)
                raw = [re.sub(r"^\d+\.\s+", "", line) for line in raw]
            session_ids = []
        assert len(raw) == int(item["n"]), item["condition_id"]
        result = summarize(item["condition_id"], item["label"], item["evidence_tier"], raw)
        result["session_ids"] = session_ids
        result["file"] = item["file"]
        results.append(result)
    return results


def exact_overlaps(results: list[dict]) -> list[tuple[str, list[tuple[str, int]]]]:
    appearances = collections.defaultdict(list)
    for result in results:
        for title, count in result["counts"].items():
            appearances[title].append((result["id"], count))
    overlaps = [(title, groups) for title, groups in appearances.items() if len(groups) > 1]
    return sorted(overlaps, key=lambda item: (-len(item[1]), -sum(count for _, count in item[1]), item[0]))


def head_overlaps(results: list[dict]) -> list[tuple[str, list[tuple[str, int]]]]:
    appearances = collections.defaultdict(list)
    for result in results:
        for head, count in result["heads"].items():
            appearances[head].append((result["id"], count))
    overlaps = [(head, groups) for head, groups in appearances.items() if len(groups) > 1]
    return sorted(overlaps, key=lambda item: (-len(item[1]), -sum(count for _, count in item[1]), item[0]))


def family_label(result: dict) -> str:
    return f"{result['dominant_family']} ({result['dominant_family_count']}/{result['n']})"


FIGURE_LABELS = {
    "luna_codex": "GPT-5.6 Luna / original Codex",
    "luna_container": "GPT-5.6 Luna / reduced local context",
    "terra_container": "GPT-5.6 Terra / reduced-context container",
    "sol_codex": "GPT-5.6 Sol / Codex",
    "astra_codex": "GPT-6 Astra / Codex",
    "work_luna_light": "GPT-5.6 Luna Light / ChatGPT Work",
    "claude_sonnet_5_high": "Claude Sonnet 5 High",
    "gemini_3_5_flash_lite": "Gemini 3.5 Flash-Lite",
}
INK, MUTED, TEAL, RUST = "#192d35", "#53666d", "#167a72", "#b54435"


def svg_text(x, y, content, size=20, weight=400, color=INK, extra=""):
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'fill="{color}" {extra}>{html.escape(str(content))}</text>')


def svg_frame(width, height, title, body, results):
    values = {key: {"n": r["n"], "hits": r["hits"], "unique": r["unique"],
                    "heads": dict(r["heads"]), "modes": r["modes"],
                    "mode_count": r["mode_count"]} for key, r in results.items()}
    metadata = html.escape(json.dumps(values, sort_keys=True))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">\n'
        f'<title id="title">{html.escape(title)}</title>\n'
        '<desc id="desc">Two separate audited GPT-5.6 Luna cohorts compared with '
        'logged and manual Web observations. Non-cartograph families are post-hoc literal descriptions.</desc>\n'
        f'<metadata id="study-values">{metadata}</metadata>\n'
        '<style>text{font-family:Inter,Arial,sans-serif} .mono{font-family:ui-monospace,monospace}</style>\n'
        f'<rect width="{width}" height="{height}" fill="#fcfbf8"/>\n'
        + "\n".join(body) + "\n</svg>\n"
    )


def response_grid(x, y, result, pitch=12, cell=9):
    """One square per valid response; misses are outlined and crossed."""
    marks = []
    for index, value in enumerate(result["values"]):
        px, py = x + (index % 40) * pitch, y + (index // 40) * pitch
        hit = bool(CARTOGRAPH.search(value))
        if hit:
            marks.append(f'<rect x="{px}" y="{py}" width="{cell}" height="{cell}" fill="{TEAL}"/>')
        else:
            marks.append(f'<rect x="{px}" y="{py}" width="{cell}" height="{cell}" fill="#fff" stroke="{RUST}" stroke-width="1.5"/>')
            marks.append(f'<path d="M{px+2},{py+2}l{cell-4},{cell-4}m0,-{cell-4}l-{cell-4},{cell-4}" stroke="{RUST}"/>')
    return marks


def comparison_lines(identifier, result):
    fraction = f"{result['hits']}/{result['n']}"
    if identifier == "terra_container":
        return [f"The Orchard of …  {result['heads']['Orchard']}/{result['n']}",
                f"cartograph*  {fraction}"]
    if identifier == "claude_sonnet_5_high":
        return [f"The Weight of …  {result['heads']['Weight']}/{result['n']}",
                f"cartograph*  {fraction}"]
    if identifier == "gemini_3_5_flash_lite":
        h, n = result["heads"], result["n"]
        return [f"Architecture {h['Architecture']}/{n} · Geography {h['Geography']}/{n}",
                f"Geometry {h['Geometry']}/{n} · Weight {h['Weight']}/{n}",
                f"Cartography {h['Cartography']}/{n} · other {n-sum(h.values())}/{n}"]
    if identifier == "astra_codex":
        return [f"cartograph*  {fraction}", "No broad dominant literal family"]
    return [f"cartograph*  {fraction}"]


def svg_a(results: dict[str, dict]) -> str:
    original, reduced = results["luna_codex"], results["luna_container"]
    body = [
        svg_text(48, 59, "The Cartographer Attractor", 36, 700),
        svg_text(48, 108, PROMPT, 25, 500, TEAL, 'class="mono"'),
        svg_text(48, 137, "Adaptively selected extreme case—not an estimate for typical creative prompts.", 16, 400, MUTED),
        '<line x1="800" y1="155" x2="800" y2="825" stroke="#ccd5d6"/>',
        svg_text(48, 171, "PRIMARY / AUDITED", 17, 700, MUTED),
        svg_text(48, 199, "Separate collections · low reasoning · fresh sessions", 18, 400, MUTED),
    ]
    for x, key, context in ((48, "luna_codex", "Original Codex"),
                             (425, "luna_container", "Reduced local context")):
        r = results[key]
        misses = r["n"] - r["hits"]
        body += [
            svg_text(x, 246, "GPT-5.6 Luna", 25, 600),
            svg_text(x, 278, context, 22, 400),
            svg_text(x, 351, f"{r['hits']} / {r['n']}", 60, 700, TEAL),
            svg_text(x, 384, "cartograph*", 23, 600),
        ]
        body += response_grid(x, 409, r, pitch=8, cell=6)
        body += [
            svg_text(x, 481, f"{misses} {'miss' if misses == 1 else 'misses'} ×", 20, 600, RUST),
            svg_text(x, 516, f"{r['unique']} distinct exact titles", 21, 600),
        ]
    body += [
        svg_text(48, 549, "Each square = one response; crosses mark misses.", 17, 400, MUTED),
        '<line x1="48" y1="571" x2="752" y2="571" stroke="#ccd5d6"/>',
        svg_text(48, 610, "MODE SHIFT", 16, 700, MUTED),
        svg_text(48, 641, "The Cartographer of …", 23, 500),
        svg_text(503, 641, "Original", 18, 400, MUTED, 'text-anchor="end"'),
        svg_text(721, 641, "Reduced context", 18, 400, MUTED, 'text-anchor="end"'),
    ]
    for y, ending in ((682, "Vanishing Hours"), (729, "Vanishing Roads")):
        title = f"The Cartographer of {ending}"
        body += [
            svg_text(48, y, ending, 24, 600),
            svg_text(503, y, original["counts"][title], 28, 700, TEAL, 'text-anchor="end"'),
            svg_text(581, y, "→", 25, 400, MUTED),
            svg_text(721, y, reduced["counts"][title], 28, 700, TEAL, 'text-anchor="end"'),
        ]
    body += [
        svg_text(48, 792, "Exact titles moved.", 29, 700),
        svg_text(48, 826, "cartograph* barely did.", 29, 700, TEAL),
        svg_text(838, 171, "COMPARISON PROFILES", 17, 700, MUTED),
        svg_text(838, 199, "Observed literal patterns; conditions differ", 18, 400, MUTED),
    ]
    positions = [("work_luna_light", 238), ("sol_codex", 330),
                 ("terra_container", 422), ("claude_sonnet_5_high", 514),
                 ("gemini_3_5_flash_lite", 606), ("astra_codex", 758)]
    for key, y in positions:
        r = results[key]
        tier = "LOGGED COMPARISON" if r["tier"] == "LOGGED COMPARISON" else "MANUAL WEB"
        body += [
            svg_text(838, y, FIGURE_LABELS[key], 22, 600),
            svg_text(838, y+25, tier, 14, 700, "#77558b" if tier == "MANUAL WEB" else "#35647e"),
        ]
        if key == "terra_container":
            lines = [f"Orchard {r['heads']['Orchard']}/{r['n']}  ·  cartograph* {r['hits']}/{r['n']}"]
        elif key == "claude_sonnet_5_high":
            lines = [f"The Weight of …  {r['heads']['Weight']}/{r['n']}"]
        else:
            lines = comparison_lines(key, r)
        body += [svg_text(838, y+54+i*25, line, 20, 500) for i, line in enumerate(lines)]
        if key not in ("gemini_3_5_flash_lite", "astra_codex"):
            body.append(f'<line x1="838" y1="{y+73}" x2="1552" y2="{y+73}" stroke="#e0e5e5"/>')
    body += [
        svg_text(48, 874, "Non-cartograph families are post-hoc literal descriptions. Manual Web evidence is descriptive; conditions are not pooled.", 18, 400, MUTED),
    ]
    return svg_frame(1600, 900, "The Cartographer Attractor — research overview", body, results)


def svg_b(results: dict[str, dict]) -> str:
    paper, pale, accent = "#f4f0e5", "#c4d3ce", "#edc17b"
    body = [
        '<rect width="1080" height="1080" fill="#163a3c"/>',
        svg_text(60, 66, "THE CARTOGRAPHER ATTRACTOR", 34, 700, paper),
        svg_text(60, 119, PROMPT, 25, 400, accent, 'class="mono"'),
        '<line x1="60" y1="149" x2="1020" y2="149" stroke="#547172"/>',
        svg_text(60, 187, "SELECTED EXTREME CASE · PRIMARY / AUDITED · LOW REASONING", 16, 600, pale),
    ]
    for y, key, context in ((299, "luna_codex", "Original Codex"),
                             (447, "luna_container", "Reduced local context")):
        r = results[key]
        body += [
            svg_text(60, y, f"{r['hits']} / {r['n']}", 108, 700, paper),
            svg_text(679, y-61, "GPT-5.6 Luna", 27, 600, paper),
            svg_text(679, y-26, context, 24, 400, pale),
            svg_text(679, y+6, f"{r['n']-r['hits']} {'miss' if r['n']-r['hits']==1 else 'misses'}", 20, 400, accent),
        ]
    body += [
        svg_text(60, 504, "cartograph*", 40, 600, accent, 'class="mono"'),
        svg_text(60, 554, f"{results['luna_codex']['unique']} different exact titles in each set.", 29, 500, paper),
    ]
    # Four deliberately small contrast cards; no attempt to rank unlike conditions.
    cards = [
        (60, 592, "claude_sonnet_5_high", ["Claude Sonnet 5 High"]),
        (557, 592, "work_luna_light", ["GPT-5.6 Luna Light", "/ ChatGPT Work"]),
        (60, 759, "terra_container", ["GPT-5.6 Terra", "/ reduced-context container"]),
        (557, 759, "gemini_3_5_flash_lite", ["Gemini 3.5 Flash-Lite"]),
    ]
    for x, y, key, label in cards:
        r = results[key]
        body.append(f'<g aria-label="{html.escape(FIGURE_LABELS[key], quote=True)}">')
        body.append(f'<rect x="{x}" y="{y}" width="463" height="148" fill="none" stroke="#7c9490" rx="2"/>')
        tier = "MANUAL WEB" if r["tier"] == "MANUAL WEB" else "LOGGED COMPARISON"
        body.append(svg_text(x+18, y+25, tier, 13, 700, pale))
        for i, line in enumerate(label):
            body.append(svg_text(x+18, y+53+i*25, line, 22, 600, paper))
        if key == "claude_sonnet_5_high":
            lines = [f"{r['heads']['Weight']}/{r['n']} → The Weight of …"]
        elif key == "work_luna_light":
            lines = [f"{r['hits']}/{r['n']} → cartograph*"]
        elif key == "terra_container":
            lines = [f"Orchard {r['heads']['Orchard']}/{r['n']} · cartograph* {r['hits']}/{r['n']}"]
        else:
            selected = ("Architecture", "Geography", "Geometry", "Weight")
            total = sum(r["heads"][head] for head in selected)
            lines = ["Architecture / Geography", f"Geometry / Weight · {total}/{r['n']}"]
        for i, line in enumerate(lines):
            body.append(svg_text(x+18, y+108+i*25, line, 22, 500, accent))
        body.append('</g>')
    body += [
        svg_text(60, 955, "Why can an open-ended request produce", 28, 500, paper),
        svg_text(60, 991, "such narrow—and different—defaults?", 28, 500, paper),
        svg_text(60, 1033, "Observed black-box outputs. Serving conditions differ; manual Web samples are descriptive.", 16, 400, pale),
        svg_text(60, 1059, "cartograph* is the fixed endpoint. Other families are post-hoc literal descriptions.", 16, 400, pale),
    ]
    return svg_frame(1080, 1080, "The Cartographer Attractor — social poster", body, results)


def verify_readme(results: dict[str, dict]) -> None:
    text = (ROOT / "README.md").read_text()
    assert text.count("](" + "data/luna_reduced_context_200.csv" + ")") >= 3
    assert "GPT-5.6 Luna Light / ChatGPT Work" in text
    checks = {
        "luna_codex": "| **199/200** | 157 | 42 | 28 | 201 |",
        "luna_container": "| **198/200** | 154 | 44 | 28 | 202 |",
        "terra_container": "| 50 | 18/50 | 19 | `The Orchard of …` 26/50 |",
        "sol_codex": "| 20 | 18/20 | 10 | `cartograph*` 18/20 |",
        "astra_codex": "| 20 | 0/20 | 11 | top extracted heads tied · 3 each |",
        "work_luna_light": "| 20 | 19/20 | 5 | `cartograph*` 19/20 |",
        "claude_haiku_4_5": "| 60 | 49/60 | 24 | `cartograph*` 49/60 |",
        "claude_sonnet_5_high": "| 60 | 0/60 | 17 | `The Weight of …` 60/60 |",
        "deepseek_instant": "| 62 | 49/62 | 21 | `cartograph*` 49/62 |",
        "grok_fast": "| 51 | 28/51 | 34 | `cartograph*` 28/51 |",
        "gemini_3_5_flash_lite": "| 60 | 1/60 | 33 | `The Architecture of …` 22/60 |",
        "gpt_5_6_terra_light": "| 20 | 3/20 | 12 | `The Orchard of …` 12/20 |",
    }
    for identifier, snippet in checks.items():
        assert snippet in text, f"README count is missing or stale: {identifier}"
    assert "823 responses from 12 observed conditions" in text
    assert "202 normalized\ndistinct exact titles" in text
    assert "29 appeared in more than one condition" in text
    assert "97.2%–99.9% for original GPT-5.6 Luna" in text
    assert "0.0%–16.1% for GPT-6 Astra" in text
    for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
        if "://" in target or target.startswith("#"):
            continue
        local = ROOT / unquote(target.split("#", 1)[0])
        assert local.exists(), f"broken README link: {target}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-figures", action="store_true", help="regenerate both SVGs")
    parser.add_argument("--write-ledger", action="store_true", help="rebuild the derived reduced-context ledger")
    args = parser.parse_args()
    primary = load_primary(write_ledger=args.write_ledger)
    terra_usage = verify_terra()
    metadata = load_metadata()
    assert {row["evidence_tier"] for row in metadata} == {
        "PRIMARY / AUDITED", "LOGGED COMPARISON", "MANUAL WEB"}
    comparison_meta = [row for row in metadata if row["evidence_tier"] != "PRIMARY / AUDITED"]
    referenced_web = {row["file"] for row in comparison_meta if row["file"].startswith("web/")}
    referenced_logged_csv = {row["file"] for row in comparison_meta if row["file"].startswith("logged/")}
    assert referenced_web == {f"web/{path.name}" for path in (MODELS / "web").glob("*.txt")}
    assert referenced_logged_csv == {f"logged/{path.name}" for path in (MODELS / "logged").glob("*.csv")}
    comparisons = load_comparisons(metadata)
    results = primary + comparisons
    by_id = {result["id"]: result for result in results}
    assert set(by_id) == {row["condition_id"] for row in metadata}
    for item in metadata:
        by_id[item["condition_id"]]["label"] = item["label"]

    all_sessions = [session for result in results for session in result.get("session_ids", [])]
    assert len(all_sessions) == len(set(all_sessions)) == 493
    assert by_id["luna_codex"]["halves"] == [100, 99]
    assert by_id["luna_container"]["halves"] == [100, 98]
    assert len(set(by_id["luna_codex"]["counts"]) & set(by_id["luna_container"]["counts"])) == 14
    assert (by_id["terra_container"]["hits"], by_id["terra_container"]["n"]) == (18, 50)
    assert terra_usage["input_tokens"] == 164850
    expected_n = {"work_luna_light": 20, "claude_haiku_4_5": 60, "claude_sonnet_5_high": 60,
                  "deepseek_instant": 62, "grok_fast": 51, "gemini_3_5_flash_lite": 60,
                  "gpt_5_6_terra_light": 20}
    assert {key: by_id[key]["n"] for key in expected_n} == expected_n
    assert sum(value.startswith("The Weight of ") for value in by_id["claude_sonnet_5_high"]["values"]) == 60

    usage = {row["condition"]: row for row in csv_rows(DATA / "reported_usage.csv")}
    assert int(usage["Luna / original Codex"]["input_tokens"]) == 1_107_200
    assert sum(int(usage[key]["input_tokens"]) for key in (
        "Luna / container initial", "Luna / container prospective extension 1",
        "Luna / container prospective extension 2", "Luna / container slow completion")) == 356_400

    figure_a, figure_b = svg_a(by_id), svg_b(by_id)
    figure_paths = [(ROOT / "figures/research-overview.svg", figure_a),
                    (ROOT / "figures/shareable-overview.svg", figure_b)]
    if args.write_figures:
        for path, content in figure_paths:
            path.write_text(content)
    for path, content in figure_paths:
        assert path.read_text() == content, f"stale figure: run {Path(__file__).name} --write-figures"
        assert "GPT-5.6 Luna Light / ChatGPT Work" in content
        if path.name == "research-overview.svg":
            assert "GPT-6 Astra / Codex" in content
    verify_readme(by_id)

    print("| Condition | Tier | n | cartograph* | Nominal 95% Wilson CI | Distinct | Modal title(s) | Mode | Collision | Dominant literal family |")
    print("|---|---|---:|---:|---:|---:|---|---:|---:|---|")
    for result in results:
        interval = f"{result['wilson_low']:.1%}–{result['wilson_high']:.1%}"
        print(f"| {result['label']} | {result['tier']} | {result['n']} | {result['hits']}/{result['n']} | {interval} | {result['unique']} | {'; '.join(result['modes'])} | {result['mode_count']}/{result['n']} | {result['collision_rate']:.3f} | {family_label(result)} |")

    print("\nPrimary GPT-5.6 Luna details:")
    for result in primary:
        print(f"- {result['label']}: attempts={result['attempts']}, halves={result['halves']}, Cartographer={result['cartographer']}, Cartography={result['cartography']}")
        for title, count in result["counts"].most_common(5):
            print(f"    {count:>3}  {title}")

    print("\nMechanically extracted The [HEAD] of … distributions:")
    for result in results:
        if result["heads"]:
            heads = ", ".join(f"{head}={count}" for head, count in result["heads"].most_common())
            print(f"- {result['label']}: {heads}")

    print("\nExact normalized titles appearing in multiple conditions:")
    overlaps = exact_overlaps(results)
    title_conditions = collections.Counter()
    for title, groups in overlaps:
        title_conditions[len(groups)] += 1
        print(f"- {title}: " + ", ".join(f"{by_id[identifier]['label']}={count}" for identifier, count in groups))
    distinct_union = set().union(*(set(result["counts"]) for result in results))
    # Both the union and overlap counts use the exact same normalized Counter keys.
    overlap_scale = (sum(result["n"] for result in results), len(results),
                     len(distinct_union), len(overlaps),
                     *(sum(len(groups) >= minimum for _, groups in overlaps)
                       for minimum in (3, 4, 5)))
    assert overlap_scale == (823, 12, 202, 29, 7, 2, 2), overlap_scale
    print(f"\nOverlap denominator: {sum(result['n'] for result in results)} responses; {len(results)} conditions; {len(distinct_union)} normalized distinct exact titles; {len(overlaps)} titles in 2+ conditions; {sum(count for size, count in title_conditions.items() if size >= 3)} in 3+; {sum(count for size, count in title_conditions.items() if size >= 4)} in 4+; {sum(count for size, count in title_conditions.items() if size >= 5)} in 5+.")

    print("\nMechanically extracted heads appearing in multiple conditions:")
    for head, groups in head_overlaps(results):
        print(f"- {head}: " + ", ".join(f"{by_id[identifier]['label']}={count}" for identifier, count in groups))

    print("\nChecks passed: consolidated 200-row ledger matches all source rows; raw counts, primary protocols, context exports, GPT-5.6 Terra event streams, session uniqueness, reported usage, metadata coverage, README values/links, and both generated figures.")


if __name__ == "__main__":
    main()
