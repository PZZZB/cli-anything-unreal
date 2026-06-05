# CODEBUDDY.md

CodeBuddy repo guide.

## What this repository is

`ue-cli` = Python CLI harness for AI agents controlling Unreal Engine 5 editors.

Two UE modes:
- UAT/UBT subprocess for compile/cook/package. No editor needed.
- Remote Control HTTP + editor Python for materials, blueprints, scenes, screenshots, CVars, assets.

## Commands

### Install and setup

```bash
pip install -e .
pip install -e ".[dev]"
```

Requirements: Python 3.10+, Unreal Engine 5.x, Remote Control API for editor commands.

### Tests

```bash
# Unit tests; no UE editor required. E2E tests are collected but skipped unless --e2e is passed.
python -m pytest cli_anything/unreal/tests/ -v

# Single test file
python -m pytest cli_anything/unreal/tests/test_material.py -v

# Single test
python -m pytest cli_anything/unreal/tests/test_material.py::TestMaterial::test_list -v

# Collect tests without running them
python -m pytest --collect-only -q cli_anything/unreal/tests/

# E2E tests; requires a real .uproject and running/reachable UE editor unless auto-launch is used
UE_TEST_PROJECT=F:/path/to/Project.uproject python -m pytest cli_anything/unreal/tests/test_full_e2e.py -v --e2e

# E2E with auto-launch
python -m pytest cli_anything/unreal/tests/test_full_e2e.py -v --e2e --e2e-auto-launch --e2e-launch-timeout 300

# Bounded E2E smoke subset
python -m pytest cli_anything/unreal/tests/ -v --e2e --e2e-smoke
```

Current collection: 406 tests. `tmp_path` writes under `.tmp_pytest/`.

### Packaging/building this Python package

```bash
python -m build
```

No repo lint command/config found.

### Running the CLI locally

```bash
ue-cli --help
python -m cli_anything.unreal --help
ue-cli --list-commands
ue-cli --output json editor status
ue-cli --project F:/path/to/Project.uproject editor launch
ue-cli --project F:/path/to/Project.uproject --output json project info
```

Important CLI behavior:
- Global flags (`--output`, `--project`, `--port`) go before subcommands.
- TTY stdout defaults text; non-TTY stdout defaults JSON.
- `--project` sticks in session state.
- Missing `--port` + loaded project -> read `Config/DefaultRemoteControl.ini`; fallback 30010.
- Git Bash/MSYS2 may mangle `/Game/...`; `_fix_argv_msys2()` repairs before Click parsing.

### Common UE workflow commands

```bash
# Discover editors and ports
ue-cli editor status
ue-cli --project F:/path/to/Project.uproject editor status

# Enable Remote Control settings in the project; restart editor afterward
ue-cli --project F:/path/to/Project.uproject editor enable-remote

# Launch editor asynchronously and poll task status
ue-cli --project F:/path/to/Project.uproject editor launch --no-wait
ue-cli --project F:/path/to/Project.uproject editor status <task_id>

# Run Python in the editor. Assign a result dict to return structured JSON.
ue-cli --project F:/path/to/Project.uproject --output json editor run-script -c "result = {'status': 'ok'}"

# UAT/UBT-backed operations; use --no-wait for long-running tasks and poll with build status <task_id>
ue-cli --project F:/path/to/Project.uproject build compile --config Development --platform Win64
ue-cli --project F:/path/to/Project.uproject build cook --platform Win64
ue-cli --project F:/path/to/Project.uproject build package --config Development --platform Win64 --output-dir F:/path/to/out
ue-cli --project F:/path/to/Project.uproject build status <task_id>
ue-cli --project F:/path/to/Project.uproject build cancel <task_id>

# Bridge plugin maintenance
ue-cli --project F:/path/to/Project.uproject editor plugin-version
ue-cli --project F:/path/to/Project.uproject editor plugin-upgrade

# Install bundled AI-agent skills
ue-cli install-skills
```

## Architecture

### Main package layout

- `cli_anything/unreal/unreal_cli.py`: Click root, global flags, command specs, output defaults, MSYS2 fix, hidden task worker.
- `cli_anything/unreal/commands/`: thin CLI layer. Parse args, require project/editor, delegate to `core/`, emit output.
- `cli_anything/unreal/core/`: project/build/editor/material/blueprint/asset/scene/screenshot/Android/RenderDoc/session/plugin/task logic.
- `cli_anything/unreal/utils/ue_http_api.py`: `UEEditorAPI`, single Remote Control HTTP client.
- `cli_anything/unreal/utils/ue_backend.py`: engine discovery, editor process/preflight, Remote Control config, UAT/UBT.
- `cli_anything/unreal/bridge_plugin/CliAnythingBridge/`: bundled C++ UE plugin.
- `cli_anything/unreal/skills/`: skill docs installed by `install-skills`.
- `cli_anything/unreal/tests/`: unit + E2E tests.

### Communication tiers

1. Subprocess tier: `core/build.py` + `utils/ue_backend.py` call UAT/UBT without editor.
2. HTTP REST tier: `UEEditorAPI` calls `/remote/info`, `/remote/object/call`, `/remote/object/property`, `/remote/object/describe`, `/remote/search/assets`.
3. Python script injection: `core/script_runner.py` executes through `PythonScriptLibrary.ExecutePythonCommandEx` for HTTP gaps.

### Script runner pattern

`run_python_code()` / `run_python_script()` wrap user code in `_WRAPPER_TEMPLATE`, run isolated `_cli_user_ns`, capture stdout/exceptions, optionally auto-save dirty `/Game/` packages, emit `__cli_result__:` marker. CLI parses `LogOutput`, returns dict. Set `result`; dict merges top-level, non-dict -> `{"value": ...}`, missing -> `{"status": "ok"}`. Use `--no-save` only deliberately.

### Background task system

Long ops use `core/tasks.py`:
- Task JSON in `UE_CLI_TASK_DIR` or system temp under `ue_cli_tasks`.
- `submit_task()` spawns `python -m cli_anything.unreal --output json _task-worker run <task_id>`.
- Poll via `task status <task_id>`, `editor status <task_id>`, or `build status <task_id>`.
- Final: `completed`, `failed`, `timeout`, `cancelled`.

### Bridge plugin

`core/plugin_bridge.py` manages bundled `CliAnythingBridge` deployed to `<Project>/Plugins/CliAnythingBridge`. Exposes class reflection, actor component trees, material compile errors, HLSL/shader source, viewport bounds. `editor plugin-upgrade` deploys, compiles, restarts if needed, verifies loaded version.

### Testing conventions

- Unit tests use synthetic data/mocks; no real editor.
- Editor tests marked `e2e`, skipped unless `--e2e`.
- `--e2e-smoke` skips non-smoke E2E.
- `temp_project` creates fake `.uproject`, `Config`, `Content`, `Source`, `Binaries`.
- Click tests use `click.testing.CliRunner`; pass global CLI flags before command group.

### Known UE-specific behavior

- `ENGINE_BUGS.md`: UE 5.7 automation issues. `DeleteAllMaterialExpressions` deletes half per call; loop until empty. Raw Remote Control transform reads can 400; CLI uses editor Python.
- Disabled Remote Control console/Python causes `editor exec`, CVar writes, scripts to fail. Run `editor enable-remote`, restart editor.
- `editor status` reports `not_running`, `starting`, `zombie`, `online`, plus precheck/fatal-log hints.
