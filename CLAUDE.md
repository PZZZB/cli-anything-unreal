# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

`cli-anything-unreal` is a Python CLI tool that lets AI coding agents control Unreal Engine 5 editors. It wraps UE's Remote Control HTTP API and UAT/UBT build tools behind structured, token-efficient CLI commands with JSON output.

## Commands

### Install & Setup
```bash
pip install -e .                    # Dev install
pip install -e ".[dev]"             # With pytest
```

### Running Tests
```bash
# Unit tests (no UE editor needed, ~358 tests)
python -m pytest cli_anything/unreal/tests/ -v

# Single test file
python -m pytest cli_anything/unreal/tests/test_material.py -v

# Single test
python -m pytest cli_anything/unreal/tests/test_material.py::TestMaterial::test_list -v

# E2E tests (requires running UE editor + UE_TEST_PROJECT env var)
UE_TEST_PROJECT=F:\path\to\Project.uproject python -m pytest cli_anything/unreal/tests/test_full_e2e.py -v --e2e

# E2E with auto-launch
python -m pytest cli_anything/unreal/tests/test_full_e2e.py -v --e2e --e2e-auto-launch --e2e-launch-timeout 300

# E2E smoke subset only
python -m pytest cli_anything/unreal/tests/ -v --e2e --e2e-smoke
```

### Running the CLI
```bash
cli-anything-unreal --help
cli-anything-unreal --output json editor status
cli-anything-unreal --project F:\path\to\Project.uproject editor launch
```

## Architecture

### Three Communication Tiers

1. **Subprocess tier** (`core/build.py`): UAT/UBT for compile/cook/package. No editor needed.
2. **HTTP REST tier** (`utils/ue_http_api.py`): Remote Control API on port 30010. Queries properties, searches assets, calls UObject functions.
3. **Python script injection** (`core/script_runner.py`): For anything the HTTP API can't do. Wraps user code in a try/except template, executes via `PythonScriptLibrary.ExecutePythonCommandEx`, captures result via `unreal.log()` with a marker prefix (`__cli_result__:`).

### Code Layers

- **`commands/`** — Click CLI layer. Thin: parses args, calls core, calls `output()` or `emit_json()`.
- **`core/`** — Business logic. Each module (materials, blueprint, scene, etc.) orchestrates HTTP calls and script execution.
- **`utils/ue_http_api.py`** — `UEEditorAPI` class: the single HTTP client all core modules use. Default port 30010.
- **`utils/ue_backend.py`** — Editor process management (find exe, preflight checks, port resolution, kill zombies).

### Script Runner Pattern

The central execution pattern (`core/script_runner.py`):
- User code is wrapped in `_WRAPPER_TEMPLATE` which isolates it in a dedicated namespace (`_cli_user_ns`), captures stdout, catches exceptions with full tracebacks, and auto-saves dirty packages.
- The wrapper emits result as `unreal.log("__cli_result__:" + json.dumps(...))`.
- The CLI-side parses `LogOutput` from `ExecutePythonCommandEx` response, finds the marker, returns structured dict.
- Scripts that assign a `result` variable get it merged into the response. No `result` → `{"status": "ok"}`.

### Bridge Plugin (`bridge_plugin/CliAnythingBridge/`)

A C++ UE plugin that ships with the CLI package and is auto-deployed to the project's `Plugins/` directory. Exposes functions that Python/Blueprint can't access directly:
- `GetClassInfo` — TFieldIterator-based reflection (same as Details panel)
- `GetActorComponentTree` — Actor component hierarchy
- `GetMaterialCompileErrors` — Direct FMaterialResource access
- `GetMaterialHLSLCode` / `GetMaterialShaderSource` — Shader source extraction
- `GetActiveViewportScreenBounds` — Viewport pixel coordinates for screenshot cropping

### Async Task System (`core/tasks.py`)

Long-running ops (compile, cook, package, editor launch) use a file-based task queue:
- `submit_task()` creates a JSON file in temp dir and spawns a detached worker process.
- Worker runs `cli-anything-unreal _task-worker run <task_id>` (hidden Click command).
- CLI caller polls with `task status <task_id>`. Final statuses: `completed`, `failed`, `timeout`, `cancelled`.

### Skill System (`skills/`)

`SKILL.md` is the Claude Code skill definition — it tells the AI agent how to use the CLI. The `references/` directory contains per-domain docs loaded on demand to save context window. The `install-skills` command copies these into the user's Claude Code settings.

## Key Design Decisions

- **JSON output by default** when stdout is not a TTY (i.e., when called by an agent). The `--output json` flag must come BEFORE subcommands.
- **`--project` is sticky**: once passed, the session remembers it for subsequent commands.
- **Port auto-detection**: reads from project's `Config/DefaultRemoteControl.ini` if `--port` is not specified.
- **MSYS2 path fix**: `_fix_argv_msys2()` in `unreal_cli.py` handles Git Bash mangling `/Game/...` paths into Windows paths.
- **Auto-save on script execution**: `script_runner` saves all dirty packages after each script run (disable with `save=False`).
- **Namespace isolation**: Each `run_python_code` call executes in a fresh `_cli_user_ns` dict so variables don't leak between calls.

## Testing Conventions

- Unit tests mock `UEEditorAPI` — they never hit a real editor. Use `unittest.mock.patch` on the HTTP methods or `require_editor`.
- The custom `tmp_path` fixture in `conftest.py` creates directories under `.tmp_pytest/` (not system temp) for easier debugging.
- The `temp_project` fixture creates a full fake UE project structure (`.uproject`, Config, Content, Source, Binaries).
- E2E tests are gated behind `--e2e` flag and require `UE_TEST_PROJECT` env var pointing to a real `.uproject`.
