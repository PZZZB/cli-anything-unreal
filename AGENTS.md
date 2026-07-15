# AGENTS.md

Codex repo guide.

## What This Is

`ue-cli` = Python CLI for AI agents controlling Unreal Engine 5 editors. Wraps UE Remote Control HTTP API + UAT/UBT behind structured, token-light JSON commands.

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
ue-cli --help
ue-cli --output json editor status
ue-cli --project F:\path\to\Project.uproject editor launch
```

## Architecture

### Three Communication Tiers

1. **Subprocess tier** (`core/build.py`): UAT/UBT compile/cook/package. No editor.
2. **HTTP REST tier** (`utils/ue_http_api.py`): Remote Control API, default port 30010. Query props, search assets, call UObject funcs.
3. **Python script injection** (`core/script_runner.py`): escape hatch for HTTP gaps. Runs via `PythonScriptLibrary.ExecutePythonCommandEx`, captures `unreal.log("__cli_result__:" + json.dumps(...))`.

### Code Layers

- **`commands/`** - thin Click layer: parse args, call core, emit `output()`/`emit_json()`.
- **`core/`** - business logic: materials, blueprint, scene, build, script runner.
- **`utils/ue_http_api.py`** - single HTTP client: `UEEditorAPI`.
- **`utils/ue_backend.py`** - editor exe/process/preflight/port/zombie management.

### Script Runner Pattern

`core/script_runner.py` wraps user code in `_WRAPPER_TEMPLATE`: isolated `_cli_user_ns`, stdout capture, traceback capture, dirty-package auto-save. CLI parses `LogOutput`, finds `__cli_result__:`, returns dict. `result` dict merges into response; no `result` -> `{"status": "ok"}`.

### Bridge Plugin (`bridge_plugin/CliAnythingBridge/`)

Bundled C++ UE plugin auto-deployed to project `Plugins/`. Exposes:
- `GetClassInfo` - `TFieldIterator` reflection, Details-panel parity
- `GetActorComponentTree` - actor component hierarchy
- `GetMaterialCompileErrors` - direct `FMaterialResource`
- `GetMaterialHLSLCode` / `GetMaterialShaderSource` - shader source
- `GetActiveViewportScreenBounds` - viewport crop bounds

### Async Task System (`core/tasks.py`)

Long ops (compile/cook/package/editor launch) use file task queue. `submit_task()` writes task JSON in temp, spawns detached worker: `ue-cli _task-worker run <task_id>`. Poll `task status <task_id>`. Final: `completed`, `failed`, `timeout`, `cancelled`.

### Skill System (`skills/`)

`SKILL.md` tells agents how to use CLI. `references/` holds load-on-demand domain docs. `install-skills` copies docs into agent settings.

## Key Design Decisions

- JSON default when stdout non-TTY. `--output json` must appear before subcommands.
- `--project` sticky for session.
- Port auto-detect from `Config/DefaultRemoteControl.ini` if not specified.
- `_fix_argv_msys2()` repairs Git Bash `/Game/...` path mangling.
- `script_runner` auto-saves dirty packages after each script run unless `save=False`.
- Fresh `_cli_user_ns` per `run_python_code`; no variable leak.

## Testing Conventions

- Unit tests mock `UEEditorAPI`; never require real editor.
- `tmp_path` fixture writes under `.tmp_pytest/`.
- `temp_project` builds fake UE project tree.
- E2E gated behind `--e2e` + `UE_TEST_PROJECT`.
