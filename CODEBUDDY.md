# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

## What this repository is

`cli-anything-unreal` is a Python CLI harness for AI agents controlling Unreal Engine 5 editors. It wraps two UE interaction modes:

- UAT/UBT subprocess calls for compile, cook, and package operations that do not require a running editor.
- Unreal Remote Control HTTP API plus editor-side Python execution for editor automation such as materials, blueprints, scene queries, screenshots, CVars, and asset operations.

## Commands

### Install and setup

```bash
pip install -e .
pip install -e ".[dev]"
```

Requirements from the README: Python 3.10+ and Unreal Engine 5.x with Remote Control API available for editor-backed commands.

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

Current collection is 406 tests. The custom `tmp_path` fixture writes under `.tmp_pytest/` for easier debugging.

### Packaging/building this Python package

```bash
python -m build
```

No repository-level lint command or lint configuration was found.

### Running the CLI locally

```bash
cli-anything-unreal --help
python -m cli_anything.unreal --help
cli-anything-unreal --list-commands
cli-anything-unreal --output json editor status
cli-anything-unreal --project F:/path/to/Project.uproject editor launch
cli-anything-unreal --project F:/path/to/Project.uproject --output json project info
```

Important CLI behavior:

- Global options such as `--output`, `--project`, and `--port` belong before subcommands.
- Default output is text for TTY stdout and JSON for non-TTY stdout.
- `--project` is sticky through the session state once loaded.
- If `--port` is omitted and a project is loaded, the CLI tries to read the Remote Control port from `Config/DefaultRemoteControl.ini`; otherwise the default is 30010.
- On Git Bash/MSYS2, `/Game/...` paths may be mangled by the shell; `unreal_cli.py` has `_fix_argv_msys2()` to repair this before Click parses args.

### Common UE workflow commands

```bash
# Discover editors and ports
cli-anything-unreal editor list
cli-anything-unreal --project F:/path/to/Project.uproject editor status

# Enable Remote Control settings in the project; restart editor afterward
cli-anything-unreal --project F:/path/to/Project.uproject editor enable-remote

# Launch editor asynchronously and poll task status
cli-anything-unreal --project F:/path/to/Project.uproject editor launch --no-wait
cli-anything-unreal --project F:/path/to/Project.uproject editor status <task_id>

# Run Python in the editor. Assign a result dict to return structured JSON.
cli-anything-unreal --project F:/path/to/Project.uproject --output json editor run-script -c "result = {'status': 'ok'}"

# UAT/UBT-backed operations; use --no-wait for long-running tasks and poll with build status <task_id>
cli-anything-unreal --project F:/path/to/Project.uproject build compile --config Development --platform Win64
cli-anything-unreal --project F:/path/to/Project.uproject build cook --platform Win64
cli-anything-unreal --project F:/path/to/Project.uproject build package --config Development --platform Win64 --output-dir F:/path/to/out
cli-anything-unreal --project F:/path/to/Project.uproject build status <task_id>
cli-anything-unreal --project F:/path/to/Project.uproject build cancel <task_id>

# Bridge plugin maintenance
cli-anything-unreal --project F:/path/to/Project.uproject editor plugin-version
cli-anything-unreal --project F:/path/to/Project.uproject editor plugin-upgrade

# Install bundled AI-agent skills
cli-anything-unreal install-skills
```

## Architecture

### Main package layout

- `cli_anything/unreal/unreal_cli.py` is the Click root command. It defines global options, machine-readable command specs, output-mode defaults, MSYS2 path repair, and hidden task-worker entrypoints.
- `cli_anything/unreal/commands/` is the thin CLI layer. Command modules parse arguments, call `require_project()`/`require_editor()` as needed, delegate to `core/`, and emit via `output()` or JSON helpers.
- `cli_anything/unreal/core/` contains feature logic for project metadata, builds, editor script execution, materials, blueprints, assets, scenes, screenshots, Android/RenderDoc, session state, plugin bridge deployment, and background tasks.
- `cli_anything/unreal/utils/ue_http_api.py` contains `UEEditorAPI`, the single Remote Control HTTP client used by core modules.
- `cli_anything/unreal/utils/ue_backend.py` handles Unreal Engine discovery, editor process management, preflight checks, Remote Control config, and UAT/UBT subprocess support.
- `cli_anything/unreal/bridge_plugin/CliAnythingBridge/` is a bundled C++ UE plugin auto-deployed into target projects when needed.
- `cli_anything/unreal/skills/` contains agent skill docs copied by `install-skills` into Claude, CodeBuddy, and Gemini locations.
- `cli_anything/unreal/tests/` contains unit and E2E tests.

### Communication tiers

1. Subprocess tier: `core/build.py` and `utils/ue_backend.py` call UAT/UBT for compile/cook/package without requiring a running editor.
2. HTTP REST tier: `UEEditorAPI` calls Unreal Remote Control endpoints such as `/remote/info`, `/remote/object/call`, `/remote/object/property`, `/remote/object/describe`, and `/remote/search/assets`.
3. Python script injection: `core/script_runner.py` executes Python through `PythonScriptLibrary.ExecutePythonCommandEx` for API surfaces not practical through raw HTTP.

### Script runner pattern

`run_python_code()` and `run_python_script()` wrap user code in `_WRAPPER_TEMPLATE`, execute it in an isolated `_cli_user_ns`, capture stdout, catch exceptions with tracebacks, optionally auto-save dirty `/Game/` packages, and emit a marked log line prefixed with `__cli_result__:`. CLI-side parsing scans `LogOutput` for that marker and returns the parsed dict. User scripts should assign `result`; dict results are merged into the top-level response, non-dicts become `{"value": ...}`, and missing `result` returns `{"status": "ok"}`.

Use `save=False` / `--no-save` only when deliberately avoiding the default dirty-package auto-save after script execution.

### Background task system

Long-running operations such as build compile/cook/package and editor launch use `core/tasks.py`:

- Task JSON files are stored in `CLI_ANYTHING_UNREAL_TASK_DIR` or the system temp directory under `cli_anything_unreal_tasks`.
- `submit_task()` creates a task and spawns `python -m cli_anything.unreal --output json _task-worker run <task_id>` detached from the caller.
- Poll via `task status <task_id>`, `editor status <task_id>`, or `build status <task_id>` depending on context.
- Final statuses are `completed`, `failed`, `timeout`, and `cancelled`.

### Bridge plugin

`core/plugin_bridge.py` manages `CliAnythingBridge`, a C++ plugin bundled with the package and deployed to `<Project>/Plugins/CliAnythingBridge`. The plugin exposes UE APIs that Python/Blueprint cannot access directly, including class reflection, actor component trees, material compile errors, HLSL/shader source extraction, and viewport bounds for screenshots.

Plugin version checks compare the bundled `.uplugin` version with `unreal.CliAnythingBridgeLibrary.get_plugin_version()` in the running editor. `editor plugin-upgrade` deploys source, compiles, restarts if needed, and verifies the loaded version.

### Testing conventions

- Unit tests use synthetic data and mocks; they should not require a real UE editor.
- Editor-dependent tests are marked `e2e` and skipped unless `--e2e` is provided.
- `--e2e-smoke` skips non-smoke E2E tests.
- The `temp_project` fixture creates a fake UE project with `.uproject`, `Config`, `Content`, `Source`, and `Binaries` structure.
- When testing Click commands, use `click.testing.CliRunner` and pass global CLI flags before the command group.

### Known UE-specific behavior

- `ENGINE_BUGS.md` documents UE 5.7 issues affecting automation. Notably, `DeleteAllMaterialExpressions` may only delete half the nodes per call; loop until expressions are gone. Raw Remote Control reads of intrinsic transform properties can return 400; this CLI routes scene transform work through editor Python instead.
- If Remote Control console/Python execution is disabled, `editor exec`, CVar writes, or script execution may fail. Use `editor enable-remote`, then restart the editor.
- `editor status` can report `not_running`, `starting`, `zombie`, or `online`; it also includes startup precheck summaries and fatal log hints when available.
