# AGENTS.md

Canonical repository guide for Codex, Claude Code, and CodeBuddy. `CLAUDE.md`
and `CODEBUDDY.md` import this file. Keep shared guidance here; do not duplicate
it into the compatibility entrypoints.

## Repository Purpose

`ue-cli` is a Python CLI for AI agents controlling Unreal Engine 5 editors. It
wraps UAT/UBT subprocesses, the UE Remote Control HTTP API, and editor Python
behind structured, token-light commands.

Requirements:

- Python 3.10+
- Unreal Engine 5.x for editor and build operations
- Remote Control enabled for commands that talk to a running editor

## Setup

```bash
pip install -e .
pip install -e ".[dev]"
```

The `dev` extra installs pytest tooling. Packaging uses `python -m build`, which
requires the separate `build` package.

## Validation

Unit tests use mocks or synthetic projects and do not require Unreal Editor:

```bash
# Full unit suite
python -m pytest cli_anything/unreal/tests/ -v

# One file
python -m pytest cli_anything/unreal/tests/test_material.py -v

# One test
python -m pytest cli_anything/unreal/tests/test_material.py::TestMaterial::test_list -v

# Collection only
python -m pytest --collect-only -q cli_anything/unreal/tests/
```

E2E tests require a real `.uproject`. PowerShell:

```powershell
$env:UE_TEST_PROJECT = "F:/path/to/Project.uproject"

# Existing reachable editor
python -m pytest cli_anything/unreal/tests/test_full_e2e.py -v --e2e

# Auto-launch editor
python -m pytest cli_anything/unreal/tests/test_full_e2e.py -v --e2e --e2e-auto-launch --e2e-launch-timeout 300

# Bounded smoke subset
python -m pytest cli_anything/unreal/tests/ -v --e2e --e2e-smoke
```

Do not hard-code a collected-test count in this guide; it changes frequently.
`tmp_path` writes under `.tmp_pytest/`. E2E tests remain skipped unless
`--e2e` is passed.

## CLI Contract

```bash
ue-cli --help
python -m cli_anything.unreal --help
ue-cli --list-commands
ue-cli --output json editor status
ue-cli --project F:/path/to/Project.uproject editor launch
ue-cli --project F:/path/to/Project.uproject --output json project info
```

- Global flags such as `--output`, `--project`, and `--port` go before
  subcommands.
- TTY stdout defaults to text; non-TTY stdout defaults to JSON.
- `--project` sets project context for the current CLI or REPL session.
- Port starts at 30010 and, unless explicitly set, can be replaced by project
  `Config/DefaultRemoteControl.ini` or one unambiguous live editor.
- `_fix_argv_msys2()` repairs Git Bash/MSYS2 mangling of Unreal paths such as
  `/Game/...`.
- Use root and command-specific `--help` or `--list-commands` instead of
  guessing command syntax.

## Common Workflows

```bash
# Discover editor instances and ports
ue-cli editor status
ue-cli --project F:/path/to/Project.uproject editor status

# Check launch prerequisites
ue-cli --project F:/path/to/Project.uproject preflight

# Enable Remote Control; restart the editor afterward
ue-cli --project F:/path/to/Project.uproject editor enable-remote

# Launch asynchronously, then poll
ue-cli --project F:/path/to/Project.uproject editor launch --no-wait
ue-cli task status <task_id>

# Execute editor Python; assign result for structured output
ue-cli --project F:/path/to/Project.uproject --output json editor run-script -c "result = {'status': 'ok'}"

# UAT/UBT operations; --no-wait returns a task ID
ue-cli --project F:/path/to/Project.uproject build compile --config Development --platform Win64 --no-wait
ue-cli --project F:/path/to/Project.uproject build cook --platform Win64 --no-wait
ue-cli --project F:/path/to/Project.uproject build package --config Development --platform Win64 --output-dir F:/path/to/out --no-wait
ue-cli --project F:/path/to/Project.uproject build status <task_id>
ue-cli build cancel <task_id>

# Bridge maintenance
ue-cli --project F:/path/to/Project.uproject editor plugin-version
ue-cli --project F:/path/to/Project.uproject editor plugin-upgrade
```

## Architecture

### Communication Tiers

1. **Subprocess:** `core/build.py` and `utils/ue_backend.py` call UAT/UBT for
   compile, cook, and package operations. No editor required.
2. **HTTP REST:** `utils/ue_http_api.py` provides the single `UEEditorAPI`
   client for Remote Control properties, searches, and UObject calls.
3. **Python injection:** `core/script_runner.py` executes editor Python through
   `PythonScriptLibrary.ExecutePythonCommandEx` when HTTP cannot express an
   operation.

### Package Layers

- `unreal_cli.py`: Click root, global flags, output defaults, command metadata,
  MSYS2 repair, and hidden task worker.
- `commands/`: thin Click layer; parse input, require project/editor, call
  `core/`, emit output.
- `core/`: project, build, editor-domain, session, plugin, and task logic.
- `utils/ue_http_api.py`: Remote Control HTTP client.
- `utils/ue_backend.py`: engine discovery, process/preflight handling, Remote
  Control configuration, and UAT/UBT helpers.
- `bridge_plugin/CliAnythingBridge/`: bundled C++ Unreal plugin.
- `skills/`: packaged agent skill and load-on-demand references.
- `tests/`: unit and E2E tests.

### Script Runner

`run_python_code()` and `run_python_script()` use a fresh `_cli_user_ns`,
capture stdout and exceptions, parse the `__cli_result__:` marker, and
auto-save dirty `/Game/` packages unless saving is disabled. A `result` dict
merges into the response; a non-dict becomes `{"value": ...}`; no result
becomes `{"status": "ok"}`. Use `--no-save` deliberately.

### Background Tasks

Long operations use `core/tasks.py`. `submit_task()` writes task JSON, starts a
detached `_task-worker`, and returns a task ID. Poll with `task status`,
`editor status <task_id>`, or `build status <task_id>`. Final states include
`completed`, `failed`, `timeout`, and `cancelled`.

### Bridge Plugin

The bundled `CliAnythingBridge` exposes class reflection, actor component
trees, material compile errors, material HLSL/shader source, and active
viewport bounds. `editor plugin-upgrade` deploys and compiles it, restarts the
editor when needed, then verifies the loaded version.

## Change Rules

- Keep `commands/` thin; put business logic in `core/`.
- Preserve structured failures and explicit unknown states. Never report
  success from empty or unverified output.
- Use `UEEditorAPI` rather than adding separate Remote Control clients.
- Keep editor-free unit tests mocked or synthetic.
- Add focused tests for a change, then run the full unit suite.
- Keep global CLI flags before command groups in docs and tests.
- Update `README.md` for user-facing behavior changes.
- Keep volatile values such as test counts out of persistent guidance.

## Agent Skill System

`cli_anything/unreal/skills/SKILL.md` is the packaged `ue-cli` skill;
`references/` contains domain guides loaded on demand.

`ue-cli install-skills` detects installed clients and writes only matching
targets. `--all-targets` explicitly installs every built-in target. A custom
`--target` must name the exact `ue-cli` leaf directory; existing target content
is replaced while sibling skills remain untouched.

## Known Unreal Behavior

- `editor enable-remote` edits project settings; restart the editor before
  expecting Remote Control console or Python calls to work.
- Raw Remote Control reads of intrinsic transforms can fail; scene transform
  reads already use editor Python.
- UE 5.7 `DeleteAllMaterialExpressions` can skip expressions while deleting.
  Follow the workaround in `ENGINE_BUGS.md`.
