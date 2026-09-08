#!/usr/bin/env python3
"""Complete the 13 unlaunched attempts after the host controller interruption."""
import argparse
import csv
import datetime as dt
import json
import os
import subprocess
import time
from pathlib import Path

import run_terra_container as engine

PROTOCOL = engine.MODEL_DATA / 'terra_container_continuation.json'
HASH = engine.MODEL_DATA / 'terra_container_continuation.sha256'
PRIOR = 37


def prepare():
    assert not PROTOCOL.exists() and not HASH.exists()
    blob = engine.RAW.read_bytes()
    records = [json.loads(line) for line in blob.splitlines()]
    assert len(records) == PRIOR and all(r['status'] == 'completed' for r in records)
    until = dt.datetime.now(dt.timezone.utc).isoformat()
    command = ['docker', 'events', '--since', records[0]['started_utc'], '--until', until,
               '--filter', 'type=container', '--filter', 'image=' + engine.IMAGE,
               '--format', '{{json .}}']
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    starts = [{'time': e['time'], 'name': e['Actor']['Attributes']['name']}
              for e in events if e['Action'] == 'start']
    assert len(starts) == PRIOR
    assert len({e['name'] for e in starts}) == PRIOR
    for event, record in zip(starts, records):
        start = dt.datetime.fromisoformat(record['started_utc']).timestamp()
        end = dt.datetime.fromisoformat(record['completed_utc']).timestamp()
        assert start - 1 <= event['time'] <= end
    content = json.dumps({
        'created_utc': until,
        'reason': 'Host controller stopped between completed attempt 37 and unlaunched attempt 38. User requested continuation. Retained Docker lifecycle events account for 37 starts; no failed or unfinished subject attempt is replaced.',
        'prior_completed': PRIOR,
        'remaining_attempts': 13,
        'cumulative_attempt_ceiling': 50,
        'model': engine.MODEL,
        'prompt': engine.PROMPT,
        'image': engine.IMAGE,
        'gap_seconds': engine.GAP_SECONDS,
        'retry_count': 0,
        'context_or_subject_configuration_changes': 'None; import and use the frozen original runner, launcher, instruction file, Docker image, and parser.',
        'stop_rule': 'Stop at first failure or limit; never retry or replace an attempt.',
        'original_protocol_sha256': engine.sha(engine.PROTOCOL.read_bytes()),
        'original_runner_sha256': engine.sha(Path(engine.__file__).read_bytes()),
        'continuation_runner_sha256': engine.sha(Path(__file__).read_bytes()),
        'prior_raw_bytes': len(blob),
        'prior_raw_sha256': engine.sha(blob),
        'retained_docker_starts': starts,
    }, indent=2) + '\n'
    engine.write_atomic(PROTOCOL, content)
    engine.write_atomic(HASH, engine.sha(content) + '  data/models/' + PROTOCOL.name + '\n')
    print('Continuation frozen: 37 preserved, exactly 13 remaining attempts.', flush=True)


def run(auth):
    assert not engine.CSV.exists()
    p = json.loads(PROTOCOL.read_text())
    assert engine.sha(PROTOCOL.read_bytes()) == HASH.read_text().split()[0]
    assert engine.sha(Path(__file__).read_bytes()) == p['continuation_runner_sha256']
    assert engine.sha(Path(engine.__file__).read_bytes()) == p['original_runner_sha256']
    assert engine.sha(engine.PROTOCOL.read_bytes()) == p['original_protocol_sha256']
    original = json.loads(engine.PROTOCOL.read_text())
    for key, file in [('entry.py', engine.MODEL_DATA/'terra_container_entry.py'),
                      ('instructions.txt', engine.MODEL_DATA/'terra_container_instructions.txt'),
                      ('audit', engine.AUDIT)]:
        assert engine.sha(file.read_bytes()) == original['source_hashes'][key]
    blob = engine.RAW.read_bytes()
    assert engine.sha(blob) == p['prior_raw_sha256']
    records = [json.loads(line) for line in blob.splitlines()]
    assert len(records) == PRIOR
    seen = {r['session_id'] for r in records}
    auth_hash = engine.sha(auth.read_bytes())
    try:
        for attempt in range(PRIOR + 1, engine.TARGET + 1):
            # Also exceeds the minimum gap before the first continuation call.
            time.sleep(engine.GAP_SECONDS)
            result = engine.invoke(engine.IMAGE, 'subject', auth, engine.MODEL_DATA/'terra_container_instructions.txt')
            record = dict(result, attempt=attempt, prompt=engine.PROMPT, model=engine.MODEL, reasoning_effort='low')
            failure = None
            try:
                sid, answer, usage = engine.parse_subject(result, seen)
                seen.add(sid)
                record.update(status='completed', session_id=sid, raw_answer=answer, usage=usage)
            except Exception as exc:
                failure = str(exc)
                record.update(status='failed', failure=failure)
            with engine.RAW.open('a') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
                f.flush()
                os.fsync(f.fileno())
            if failure:
                raise RuntimeError('Stopped without retry: ' + failure)
            records.append(record)
            print(f'{attempt}/50 complete', flush=True)
    finally:
        assert engine.sha(auth.read_bytes()) == auth_hash, 'Credential file changed'
    assert len(records) == 50 and len(seen) == 50
    with engine.CSV.open('x', newline='') as f:
        fields = ['sample', 'session_id', 'started_utc', 'completed_utc', 'prompt', 'raw_answer',
                  'cartograph', 'input_tokens', 'cached_input_tokens', 'output_tokens']
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in records:
            row = {k: r[k] for k in fields if k in r}
            row.update(sample=r['attempt'], cartograph=bool(engine.RX_CARTOGRAPH.search(r['raw_answer'])))
            row.update({k: r['usage'][k] for k in ['input_tokens', 'cached_input_tokens', 'output_tokens']})
            writer.writerow(row)
    print('50/50 completed; results frozen.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'run'])
    parser.add_argument('--auth-file', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare()
    else:
        assert args.auth_file is not None
        run(args.auth_file)
