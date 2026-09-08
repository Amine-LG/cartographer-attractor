#!/usr/bin/env python3
"""Audit, preregister, and run the 50-call Terra container condition."""

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MODEL_DATA = DATA / "models"
CONTEXT_DATA = DATA / "context"
PROMPT = "Invent a literary novel title. Title only."
MODEL = "gpt-5.6-terra"
IMAGE = "sha256:a1fad9a7cb0d451c39c6c9110053cfcb8441f65a154ab8908db6d3bdc88b5f68"
TARGET = 50
GAP_SECONDS = 12.0
INSTRUCTIONS = "Follow the user's request.\n"
ALPINE = "alpine@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce"
RX_SECRET = re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{20,}\.")
RX_LIMIT = re.compile(r"rate.?limit|usage.?limit|account.?limit|quota", re.I)
RX_CARTOGRAPH = re.compile(r"\bcartograph\w*", re.I)

KNOWN_WARNINGS = ['Under-development features enabled: skip_host_skill_discovery. Under-development features are incomplete and may behave unpredictably. To suppress this warning, set `suppress_unstable_features_warning = true` in /home/u/.codex/config.toml.', 'Code Mode is unavailable because failed to spawn code-mode host /usr/local/bin/codex-code-mode-host: host executable was not found. Code mode will fail closed; enable `features.code_mode_host` and install `codex-code-mode-host`.']

DISABLED = (
    "shell_tool view_image apps plugins remote_plugin skill_search tool_suggest "
    "image_generation browser_use computer_use multi_agent goals sleep_tool hooks "
    "workspace_dependencies shell_snapshot memories external_agent_memory_import "
    "unbounded_connection_retries"
).split()

ENTRY = r'''"""Neutral container launcher; never reads or prints credential contents."""
import json
import os
import subprocess
import sys
from pathlib import Path

ENV = dict(PATH='/usr/local/bin:/usr/bin:/bin', USER='u', LOGNAME='u',
           SHELL='/bin/bash', LANG='C.UTF-8', LC_ALL='C.UTF-8', TZ='UTC',
           PWD='/w')
# These are the standard, image-owned home path; no host state roots are reused.
ENV.update({k: v for k, v in os.environ.items() if k == 'HOME'})
assert ENV.get('HOME') == '/home/u'
KNOWN_WARNINGS = ['Under-development features enabled: skip_host_skill_discovery. Under-development features are incomplete and may behave unpredictably. To suppress this warning, set `suppress_unstable_features_warning = true` in /home/u/.codex/config.toml.', 'Code Mode is unavailable because failed to spawn code-mode host /usr/local/bin/codex-code-mode-host: host executable was not found. Code mode will fail closed; enable `features.code_mode_host` and install `codex-code-mode-host`.']

DISABLED = ('shell_tool view_image apps plugins remote_plugin skill_search '
            'tool_suggest image_generation browser_use computer_use multi_agent '
            'goals sleep_tool hooks workspace_dependencies shell_snapshot '
            'memories external_agent_memory_import unbounded_connection_retries').split()
CONFIG = ['model="gpt-5.6-terra"', 'model_reasoning_effort="low"',
          'personality="none"', 'web_search="disabled"',
          'model_instructions_file="/opt/instructions.txt"',
          'project_doc_max_bytes=0', 'features.skip_host_skill_discovery=true']
CONFIG += ['features.' + key + '=false' for key in DISABLED]
CONFIG += ['skills.config=[' + ','.join(
    '{path="/home/u/.codex/skills/.system/' + skill + '/SKILL.md",enabled=false}'
    for skill in ['imagegen', 'openai-docs', 'plugin-creator', 'skill-creator', 'skill-installer']) + ']']
OVERRIDES = [part for option in CONFIG for part in ('-c', option)]
BASE = ['codex', '--ask-for-approval', 'never', '--sandbox', 'read-only']


def call(args):
    p = subprocess.run(args, env=ENV, cwd='/w', text=True,
                       capture_output=True, timeout=90)
    return dict(command=args, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)


def main():
    mode = sys.argv[1]
    assert not list(Path('/w').iterdir())
    if mode == 'audit':
        prompt = sys.stdin.read()
        data = {'environment': ENV, 'workspace_entries': [],
                'visible_home_entries_before': sorted(p.name for p in Path('/home/u').iterdir()),
                'instructions': Path('/opt/instructions.txt').read_text(),
                'version': call(['codex', '--version']),
                'exec_help': call(['codex', 'exec', '--help']),
                'features': call(['codex', 'features', 'list'] + OVERRIDES),
                'catalog': call(['codex', 'debug', 'models', '--bundled'] + OVERRIDES),
                'login_status': call(['codex', 'login', 'status']),
                'prompt_input': call(BASE + ['debug', 'prompt-input'] + OVERRIDES + [prompt]),
                'mountinfo': Path('/proc/self/mountinfo').read_text()}
        print(json.dumps(data))
        return
    assert mode == 'subject'
    command = BASE + ['exec', '--skip-git-repo-check', '--ephemeral',
                      '--ignore-user-config', '--ignore-rules', '--strict-config',
                      '--model', 'gpt-5.6-terra'] + OVERRIDES + ['--json', '-']
    os.execvpe(command[0], command, ENV)


if __name__ == '__main__':
    main()
'''

PROTOCOL = MODEL_DATA / "terra_container_protocol.json"
PROTOCOL_HASH = MODEL_DATA / "terra_container_protocol.sha256"
AUDIT = CONTEXT_DATA / "terra_container.json"
RAW = MODEL_DATA / "terra_container_raw.jsonl"
CSV = MODEL_DATA / "terra_container.csv"


def sha(data):
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def write_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(value)
    temp.replace(path)


def container_command(image_id, mode, auth_file, instruction_file, name):
    return [
        "docker", "run", "--rm", "--interactive", "--name", name,
        "--hostname", "q", "--read-only", "--user", "1000:1000",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--memory", "1g", "--cpus", "1", "--pids-limit", "128",
        "--network", "bridge", "--log-driver", "none",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m,mode=1777",
        "--tmpfs", "/home/u:rw,nosuid,nodev,size=128m,uid=1000,gid=1000,mode=0700",
        "--tmpfs", "/home/u/.codex:rw,nosuid,nodev,size=128m,uid=1000,gid=1000,mode=0700",
        "--env", "HOME=/home/u",
        "--mount", f"type=bind,src={instruction_file},dst=/opt/instructions.txt,readonly",
        "--mount", f"type=bind,src={auth_file},dst=/home/u/.codex/auth.json,readonly",
        "--mount", f"type=bind,src={MODEL_DATA / 'terra_container_entry.py'},dst=/opt/entry.py,readonly",
        image_id, mode,
    ]


def invoke(image_id, mode, auth_file, instruction_file, timeout=180):
    name = "terra-" + uuid.uuid4().hex[:12]
    command = container_command(image_id, mode, auth_file, instruction_file, name)
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        p = subprocess.run(command, input=PROMPT, capture_output=True, text=True, timeout=timeout)
        result = {"returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
    except subprocess.TimeoutExpired as exc:
        subprocess.run(["docker", "stop", "--timeout", "1", name], capture_output=True)
        out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
        err = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
        result = {"returncode": -1, "stdout": out, "stderr": err + "\nTimed out; no retry."}
    result.update(started_utc=started, completed_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    if RX_SECRET.search(result["stdout"] + result["stderr"]):
        raise RuntimeError("Credential-like output detected; not persisted")
    return result


def compact_audit(payload, image_id):
    for key in ["version", "features", "catalog", "login_status", "prompt_input"]:
        assert payload[key]["returncode"] == 0, key
    preview = json.loads(payload["prompt_input"]["stdout"])
    messages = [
        {"role": message["role"], "content": [block["text"] for block in message["content"]]}
        for message in preview
    ]
    date = dt.datetime.now(dt.timezone.utc).date().isoformat()
    expected = [
        {"role": "developer", "content": [
            "<permissions instructions>\nFilesystem sandboxing defines which files can be read or written. "
            "`sandbox_mode` is `read-only`: The sandbox only permits reading files. Network access is restricted.\n"
            "Approval policy is currently never. Do not provide the `sandbox_permissions` for any reason, commands will be rejected.\n"
            "</permissions instructions>"
        ]},
        {"role": "user", "content": [
            "<environment_context>\n  <cwd>/w</cwd>\n  <shell>bash</shell>\n"
            f"  <current_date>{date}</current_date>\n  <timezone>Etc/UTC</timezone>\n"
            "  <filesystem><workspace_roots><root>/w</root></workspace_roots><permission_profile type=\"managed\">"
            "<file_system type=\"restricted\"><entry access=\"read\"><special>:root</special></entry>"
            "</file_system></permission_profile></filesystem>\n</environment_context>"
        ]},
        {"role": "user", "content": [PROMPT]},
    ]
    kinds = [message.get("internal_chat_message_metadata_passthrough", {}).get("content_item_kinds", []) for message in preview]
    extra_indices = [i for i, kind in enumerate(kinds) if kind in
                     [["multi_agent.usage_hint"], ["multi_agent.mode_instructions"]]]
    assert [message for i, message in enumerate(messages) if i not in extra_indices] == expected, "Unexpected model-input preview"
    assert len(extra_indices) in (0, 2)
    catalog = json.loads(payload["catalog"]["stdout"])
    entry = next(model for model in catalog["models"] if model.get("slug") == MODEL)
    assert payload["instructions"] == INSTRUCTIONS
    assert payload["workspace_entries"] == []
    assert payload["visible_home_entries_before"] == [".codex"]
    assert payload["version"]["stdout"].strip() == "codex-cli 0.153.4"
    assert "Logged in using ChatGPT" in (payload["login_status"]["stdout"] + payload["login_status"]["stderr"])
    feature_lines = payload["features"]["stdout"].splitlines()
    selected = {}
    for key in DISABLED + ["skip_host_skill_discovery"]:
        line = next(line for line in feature_lines if line.split()[0] == key)
        selected[key] = line.split()[-1] == "true"
    assert all(not selected[key] for key in DISABLED)
    assert selected["skip_host_skill_discovery"]
    return {
        "captured_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope": "Sanitized local codex debug prompt-input preview; not a full outbound request or server-side context capture.",
        "model": MODEL,
        "reasoning_effort": "low",
        "personality": "none",
        "web_search": "disabled",
        "cli_version": payload["version"]["stdout"].strip(),
        "authentication_mode": "ChatGPT login (credential content and host path omitted)",
        "image_id": image_id,
        "model_catalog_entry": {key: entry[key] for key in ("slug", "display_name", "default_reasoning_level", "supported_reasoning_levels") if key in entry},
        "environment": payload["environment"],
        "workspace_entries": payload["workspace_entries"],
        "local_instruction": payload["instructions"],
        "local_instruction_sha256": sha(payload["instructions"]),
        "prompt_preview_messages": messages,
        "prompt_preview_text_characters": sum(len(text) for m in messages for text in m["content"]),
        "selected_features": selected,
        "extra_developer_messages_vs_historical_preview": [messages[i] for i in extra_indices],
        "context_note": "Terra's local preview includes two generic collaboration messages; a non-generative Luna preview using the same Docker setup has the original three messages. This difference accompanies model selection despite multi_agent=false. All current messages are preserved here; model-specific wrapper equivalence is not assumed.",
        "audit_stderr": {
            key: payload[key]["stderr"] for key in ("version", "features", "login_status", "prompt_input")
        },
        "limitations": [
            "The preview is a debug path, not a captured subject request.",
            "Server-side instructions, routing, sampling details, and a complete tool schema remain unknown.",
            "Fresh ephemeral sessions do not prove statistical independence.",
        ],
    }


def prepare(args):
    for path in (PROTOCOL, PROTOCOL_HASH, AUDIT, RAW, CSV):
        if path.exists():
            raise RuntimeError(f"Refusing to overwrite {path}")
    binary = Path(args.codex_binary).resolve()
    auth_file = Path(args.auth_file).resolve()
    assert binary.is_file() and auth_file.is_file()
    assert sha(binary.read_bytes()) == "56ef98ab4032d317ab26e9b5e5a175650717351edb16ed9cde0cb6d1734d62da"
    write_atomic(MODEL_DATA / "terra_container_instructions.txt", INSTRUCTIONS)
    write_atomic(MODEL_DATA / "terra_container_entry.py", ENTRY)
    image_id = IMAGE
    check = subprocess.run(["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"], capture_output=True, text=True, check=True)
    assert check.stdout.strip() == IMAGE
    audit_result = invoke(image_id, "audit", auth_file, MODEL_DATA / "terra_container_instructions.txt")
    if audit_result["returncode"]:
        raise RuntimeError("Pre-run audit failed")
    payload = json.loads(audit_result["stdout"])
    audit = compact_audit(payload, image_id)
    write_atomic(AUDIT, json.dumps(audit, indent=2) + "\n")
    protocol = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "purpose": "Prospective 50-session Terra comparison under the reduced-context container protocol.",
        "prompt": PROMPT,
        "prompt_utf8_bytes": len(PROMPT.encode()),
        "prompt_sha256": sha(PROMPT),
        "model": MODEL,
        "reasoning_effort": "low",
        "personality": "none",
        "target_completed_responses": TARGET,
        "hard_attempt_ceiling": TARGET,
        "sequential": True,
        "fresh_ephemeral_session_per_attempt": True,
        "minimum_completion_to_next_launch_gap_seconds": GAP_SECONDS,
        "retries": 0,
        "allowed_pre_turn_warnings": KNOWN_WARNINGS,
        "stop_rule": "Stop at the first failed/invalid call, account/rate/usage limit, unexpected event, or duplicate session. Failed attempts are retained and not replaced.",
        "endpoint": "Case-insensitive literal cartograph* lexical root in the complete final answer.",
        "secondary": ["Cartographer count", "Cartography count", "unique and modal exact title"],
        "workspace": "Empty /w in a fresh read-only non-root container; research files are not mounted.",
        "authentication": "Existing ChatGPT login mounted read-only; credential content and host path are never logged.",
        "container_image_id": image_id,
        "base_image": ALPINE,
        "source_hashes": {
            "runner": sha(Path(__file__).read_bytes()),
            "entry.py": sha(ENTRY),
            "instructions.txt": sha(INSTRUCTIONS),
            "codex_binary": sha(binary.read_bytes()),
            "audit": sha(AUDIT.read_bytes()),
        },
        "comparison_note": "Same Docker image, resource limits, tmpfs ownership/modes, read-only original auth mount, environment and subject flags as reduced-context Luna. The original entry.py is mounted at the same container path with only two model identifiers changed from gpt-5.6-luna to gpt-5.6-terra. Date may differ; the local preview is checked against the original shape.",
        "context_drift": audit["context_note"],
    }
    content = json.dumps(protocol, indent=2) + "\n"
    write_atomic(PROTOCOL, content)
    write_atomic(PROTOCOL_HASH, f"{sha(content)}  data/models/{PROTOCOL.name}\n")
    print("Protocol and audit frozen; zero subject calls.", flush=True)


def parse_subject(result, seen):
    joined = result["stdout"] + result["stderr"]
    if RX_LIMIT.search(joined):
        raise RuntimeError("Account, usage, quota, or rate-limit condition")
    if result["returncode"] != 0:
        raise RuntimeError(f"Nonzero exit {result['returncode']}")
    events = [json.loads(line) for line in result["stdout"].splitlines() if line.strip()]
    if any(event.get("type") in {"error", "turn.failed"} for event in events):
        raise RuntimeError("Error event")
    if result["stderr"].strip():
        raise RuntimeError("Unexpected stderr")
    started = False
    for event in events:
        if event.get("type") == "turn.started":
            started = True
        item = event.get("item", {})
        kind = item.get("type")
        if kind == "error":
            if started or item.get("message") not in KNOWN_WARNINGS:
                raise RuntimeError("Unrecognized diagnostic or in-turn error")
        elif kind and kind not in {"agent_message", "reasoning"}:
            raise RuntimeError("Unexpected tool item")
    sessions = [event["thread_id"] for event in events if event.get("type") == "thread.started"]
    answers = [event["item"]["text"] for event in events if event.get("type") == "item.completed" and event.get("item", {}).get("type") == "agent_message"]
    turns = [event for event in events if event.get("type") == "turn.completed"]
    if len(sessions) != 1 or sessions[0] in seen:
        raise RuntimeError("Missing or duplicate session ID")
    if len(answers) != 1 or len(turns) != 1:
        raise RuntimeError("Incomplete or multiple-answer response")
    if not answers[0].strip():
        raise RuntimeError("Empty answer")
    return sessions[0], answers[0], turns[0].get("usage", {})


def run(args):
    if RAW.exists() or CSV.exists():
        raise RuntimeError("Refusing to resume, retry, or overwrite an existing run")
    protocol_text = PROTOCOL.read_text()
    expected, relative = PROTOCOL_HASH.read_text().split(maxsplit=1)
    assert relative.strip() == f"data/models/{PROTOCOL.name}"
    assert sha(protocol_text) == expected
    protocol = json.loads(protocol_text)
    assert protocol["model"] == MODEL and protocol["hard_attempt_ceiling"] == TARGET
    assert sha(Path(__file__).read_bytes()) == protocol["source_hashes"]["runner"]
    assert sha(AUDIT.read_bytes()) == protocol["source_hashes"]["audit"]
    assert sha((MODEL_DATA / "terra_container_entry.py").read_bytes()) == protocol["source_hashes"]["entry.py"]
    assert sha((MODEL_DATA / "terra_container_instructions.txt").read_bytes()) == protocol["source_hashes"]["instructions.txt"]
    image_id = protocol["container_image_id"]
    auth_file = Path(args.auth_file).resolve()
    assert auth_file.is_file()
    auth_hash = sha(auth_file.read_bytes())
    rows = []
    seen = set()
    last_completed = None
    failure = None
    for attempt in range(1, TARGET + 1):
        if last_completed is not None:
            time.sleep(max(0.0, GAP_SECONDS - (time.monotonic() - last_completed)))
        result = invoke(image_id, "subject", auth_file, MODEL_DATA / "terra_container_instructions.txt")
        last_completed = time.monotonic()
        record = {
            "attempt": attempt,
            "prompt": PROMPT,
            "model": MODEL,
            "reasoning_effort": "low",
            "started_utc": result["started_utc"],
            "completed_utc": result["completed_utc"],
            "returncode": result["returncode"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
        }
        try:
            session_id, answer, usage = parse_subject(result, seen)
            seen.add(session_id)
            record.update(status="completed", session_id=session_id, raw_answer=answer, usage=usage)
            rows.append(record)
        except Exception as exc:
            record.update(status="failed", failure=str(exc))
            failure = str(exc)
        with RAW.open("a") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        print(f"{attempt}/{TARGET} complete", flush=True)
        if failure:
            break
    if sha(auth_file.read_bytes()) != auth_hash:
        raise RuntimeError("Host credential file changed during execution")
    if failure or len(rows) != TARGET:
        raise RuntimeError(f"Stopped after {len(rows)} completed responses: {failure}")
    with CSV.open("w", newline="") as stream:
        fields = ["sample", "session_id", "started_utc", "completed_utc", "prompt", "raw_answer",
                  "cartograph", "input_tokens", "cached_input_tokens", "output_tokens"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            usage = row["usage"]
            writer.writerow({
                "sample": row["attempt"], "session_id": row["session_id"],
                "started_utc": row["started_utc"], "completed_utc": row["completed_utc"],
                "prompt": PROMPT, "raw_answer": row["raw_answer"],
                "cartograph": str(bool(RX_CARTOGRAPH.search(row["raw_answer"]))),
                "input_tokens": usage.get("input_tokens", ""),
                "cached_input_tokens": usage.get("cached_input_tokens", ""),
                "output_tokens": usage.get("output_tokens", ""),
            })
    print("50/50 completed; results frozen.", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "run"])
    parser.add_argument("--auth-file", required=True)
    parser.add_argument("--codex-binary", default=shutil.which("codex"))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
