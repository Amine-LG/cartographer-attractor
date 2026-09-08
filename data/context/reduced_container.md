# Reduced container condition: saved local context

These are the saved September 6 local preview and neutral launcher configuration
for the reduced-context condition. They complement the
[frozen extension protocol](../luna_container_extension_protocol.json), which
records the image and launcher hashes. The container was not instruction-free.
It replaced the long local Codex base template with one short instruction and
still supplied permissions and environment metadata.

The full text of the preview is below, with role order and content boundaries
preserved. Message IDs and internal metadata values are omitted. Code fences add
a display newline where needed. The container paths and UTC timezone are neutral
values from the record, not personal host paths. Checksums and source provenance
are in [manifest.json](manifest.json).

## What changed—and what remained

- CLI: `codex-cli 0.153.4`; model `gpt-5.6-luna`; reasoning `low`; personality `none`.
- Fixed image: `sha256:a1fad9a7cb0d451c39c6c9110053cfcb8441f65a154ab8908db6d3bdc88b5f68`.
- Fresh container, temporary neutral home, empty `/w`, and ephemeral subject
  session. The research tree and previous results were not mounted.
- Local base instruction replaced; project-document budget zero; host skill
  discovery skipped and the five installed system skills explicitly disabled.
- Search and the listed tool/memory features disabled. No tool use was observed.
  The saved preview does not expose the complete outbound tool-schema array.
- Existing account authentication was shared for access. Credentials, auth
  paths, mount dumps, and unrelated account/catalog data are not included here.
  This did not isolate account effects or establish a different backend.
- The preview contains `/w`, bash, `2026-09-06`, and `Etc/UTC`. It contains no
  project path/name, personal username, skill catalog, AGENTS.md body, or previous
  title. Neutral runtime `USER=u` is configuration, not a username in its text.
- A September 7 saved preview has identical role/content text after replacing
  only the calendar date. Dates therefore changed; do not claim one identical
  context hash for all 200 calls. Later extensions pinned image/launcher/
  instruction hashes, not captured per-request server inputs.
- Average reported input usage was 1,782 tokens per valid response. Neither this
  counter nor the text size below reveals hidden instructions or token accounting.

## Local base instruction

Exactly 27 UTF-8 bytes, including its trailing newline:

````text
Follow the user's request.
````

## Ordered local preview

### Message 1: `developer`

Content block 1:

````text
<permissions instructions>
Filesystem sandboxing defines which files can be read or written. `sandbox_mode` is `read-only`: The sandbox only permits reading files. Network access is restricted.
Approval policy is currently never. Do not provide the `sandbox_permissions` for any reason, commands will be rejected.
</permissions instructions>
````

### Message 2: `user`

Content block 1:

````text
<environment_context>
  <cwd>/w</cwd>
  <shell>bash</shell>
  <current_date>2026-09-06</current_date>
  <timezone>Etc/UTC</timezone>
  <filesystem><workspace_roots><root>/w</root></workspace_roots><permission_profile type="managed"><file_system type="restricted"><entry access="read"><special>:root</special></entry></file_system></permission_profile></filesystem>
</environment_context>
````

### Message 3: `user`

Content block 1:

````text
Invent a literary novel title. Title only.
````


## Subject launch configuration

This command is reconstructed from the saved `entry.py` subject branch and its
overrides, corroborated by the recorded debug command. It is not a new run. The
prompt was supplied on standard input, exactly 42 bytes with no trailing newline.
Settings and disabled skill paths below are launcher configuration, not evidence
that their literal strings appeared in the model's messages.

````sh
codex --ask-for-approval never --sandbox read-only exec --skip-git-repo-check --ephemeral --ignore-user-config --ignore-rules --strict-config --model gpt-5.6-luna -c 'model="gpt-5.6-luna"' -c 'model_reasoning_effort="low"' -c 'personality="none"' -c 'web_search="disabled"' -c 'model_instructions_file="/opt/instructions.txt"' -c project_doc_max_bytes=0 -c features.skip_host_skill_discovery=true -c features.shell_tool=false -c features.view_image=false -c features.apps=false -c features.plugins=false -c features.remote_plugin=false -c features.skill_search=false -c features.tool_suggest=false -c features.image_generation=false -c features.browser_use=false -c features.computer_use=false -c features.multi_agent=false -c features.goals=false -c features.sleep_tool=false -c features.hooks=false -c features.workspace_dependencies=false -c features.shell_snapshot=false -c features.memories=false -c features.external_agent_memory_import=false -c features.unbounded_connection_retries=false -c 'skills.config=[{path="/home/u/.codex/skills/.system/imagegen/SKILL.md",enabled=false},{path="/home/u/.codex/skills/.system/openai-docs/SKILL.md",enabled=false},{path="/home/u/.codex/skills/.system/plugin-creator/SKILL.md",enabled=false},{path="/home/u/.codex/skills/.system/skill-creator/SKILL.md",enabled=false},{path="/home/u/.codex/skills/.system/skill-installer/SKILL.md",enabled=false}]' --json -
````

The launcher's explicit environment allowlist was:

````json
{
  "PATH": "/usr/local/bin:/usr/bin:/bin",
  "USER": "u",
  "LOGNAME": "u",
  "SHELL": "/bin/bash",
  "LANG": "C.UTF-8",
  "LC_ALL": "C.UTF-8",
  "TZ": "UTC",
  "PWD": "/w",
  "HOME": "/home/u"
}
````

The launcher checked that `/w` was empty before execution. The saved audit lists
no workspace entries and only `.codex` in the temporary home before inspection.
The home existed for runtime/auth state; it was not the investigator's home.

## Startup warnings and inspection limits

The controller accepted two known startup warnings: the under-development
`skip_host_skill_discovery` feature, and an unavailable `codex-code-mode-host`
executable. The operational amendment changed warning handling, not the image,
instructions, or subject flags. Those warning strings were absent from the saved
model-input preview; their absence from every actual server request is not
verifiable. Later account/catalog failures remain recorded in the response data.

The preview was made using `codex debug prompt-input` with the configuration
overrides above, rather than by intercepting the subject request. The debug path
did not expose `exec`'s `--ignore-user-config` flag. Its three messages therefore
show what the local preview constructed, not all system/developer instructions,
tools, routing, or metadata that the server may have supplied. Fresh/ephemeral
execution removes the need to resume a previous conversation; it does not remove
all wrapper context or prove statistical independence.

The [original Codex snapshot](original_codex.md) documents the larger context.
Persistence in the reduced condition weakens the necessity of those removed
local cues. It does not identify why the lexical concentration occurred.
