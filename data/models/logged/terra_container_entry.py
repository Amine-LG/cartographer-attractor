"""Neutral container launcher; never reads or prints credential contents."""
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
