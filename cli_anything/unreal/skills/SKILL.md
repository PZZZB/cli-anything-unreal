---
name: unreal-engine-cli
description: |
  Control Unreal Engine 5 editor via the cli-anything-unreal CLI tool.
  Use this skill whenever the user wants to interact with UE5 — launching the editor,
  editing materials, querying scenes/actors, managing blueprints, taking screenshots,
  building/cooking/packaging, or running Python scripts inside the editor.
  TRIGGER on any mention of Unreal Engine, UE5, UE editor, materials, blueprints,
  levels, actors, meshes, shaders, HLSL, or game development workflows involving
  an Unreal project — even if the user doesn't explicitly mention "CLI" or "cli-anything".
---

# Unreal Engine CLI Skill

You are an AI Agent with access to `cli-anything-unreal`, a CLI tool that controls Unreal Engine 5 editor. Your users are UE5 game developers.

## Step 0: Verify Installation
Before running any commands, verify that the CLI is installed and available in your environment:
Run `cli-anything-unreal --version` to ensure the tool is available in your PATH. Do not assume it is installed without checking.

## Core Principles & Hard Constraints

1. **Use `editor launch` to open the editor, not UnrealEditor.exe directly.** The `editor launch` command runs a preflight build compatibility check before opening — without this, a version mismatch between engine and project binaries causes the editor to hang silently with no error message.
2. **Always pass `--json`.** When parsing `--json` outputs, always look for the structured JSON block, as it may occasionally be preceded by Unreal Engine warning logs in stdout.
3. **Specify `--project` on the first command** (or set the env var). Subsequent commands in the same shell session inherit it.
4. **Prefer CLI commands over writing Python scripts.** Most operations (material editing, blueprint editing, scene queries) already have dedicated commands. Check `references/commands.md` first.
5. **UE5 Python API restriction:** `Material.expressions` is protected in UE5.7+ — use `material info` to read nodes, and CLI commands (`add-node`, `connect`, `delete-node`) to edit them.
6. **HARD CONSTRAINT for `.uasset` Creation:** When creating UE `.uasset` files, you MUST use `cli-anything-unreal editor run-script` combined with the UE Python API. **NEVER** use generic Write tools to directly write text to a file and rename it to `.uasset`. `.uasset` is a proprietary binary format; writing plain text to it will instantly corrupt it.
7. **HARD CONSTRAINT for Script Execution:** **NEVER** run scripts containing `import unreal` using the local OS `python` command (e.g., `python script.py`). This will fail with `ModuleNotFoundError`. They MUST be executed via `cli-anything-unreal editor run-script script.py`.
8. **HARD CONSTRAINT for Asset Paths:** Always use UE virtual paths (e.g., `/Game/MyAsset`) when interacting with engine assets. **NEVER** use OS file system paths with `.uasset` extensions (e.g., `C:/Project/Content/MyAsset.uasset`) unless specifically dealing with build/cook artifacts.
9. **HARD CONSTRAINT for Temp Files:** After executing a temporary Python script or writing output to a temp file, you MUST proactively delete the file to keep the user's workspace clean.
10. **Context Window Protection:** For commands that yield massive outputs (like `scene info` or `blueprint info`), **DO NOT** run them directly into your context window if you only need a single field. Either redirect the output to a temporary JSON file (`> temp.json`) and parse specific lines with the Read tool, or pipe the output through `jq` or `grep`.

## Test Phase Requirements (Test Agent)

If you are a Test agent verifying Unreal assets (e.g. after a Dev agent has created or modified them), you MUST explicitly verify that the asset is valid and can be successfully loaded by the engine API. Simply checking if the `.uasset` file exists on disk is **NOT** enough.

**First step of ANY asset test:**
Run `editor run-script` with a script that calls `unreal.EditorAssetLibrary.load_asset()`.
Example:
```python
import unreal
path = "/Game/MyNewAsset"
asset = unreal.EditorAssetLibrary.load_asset(path)
if not asset:
    unreal.log_error(f"Asset at {path} exists on disk but FAILED to load in engine. It may be corrupted.")
else:
    unreal.log(f"Successfully loaded asset: {asset.get_name()}")
```
If `load_asset` returns `None`, the test MUST fail, and you must report the corruption back to the Dev agent.

## Decision Flow

When the user asks you to do something in Unreal, follow this sequence:

1. **Verify Installation:** Run `cli-anything-unreal --version`.
2. **Is the editor running?** Run `editor status`. If not reachable, use `editor launch`.
3. **Do you know the asset path?** If not, discover it with `material list`, `blueprint list`, `scene list`, or `asset list`.
4. **Does a CLI command exist for this?** Check the command reference located in the same directory as this SKILL.md file (`references/commands.md`). Use CLI commands first.
5. **No CLI command covers it?** Write a Python script and run it with `editor run-script`. (Remember to delete it afterwards!)
6. **Need visual verification?** Use `screenshot capture` and review the image.

## Handling Errors

CLI commands return JSON with an `error` field when something goes wrong. Common patterns:
- **Connection refused** → editor not running. Run `editor launch`.
- **Timeout** → editor is busy. Run `editor status` to check; if reachable, wait 10-15 seconds and retry.
- **Asset not found** → path is wrong. Run `material list` or `asset list` to discover it.
- **"modules built with different engine version"** → Run `editor preflight` → `build compile` → `editor launch`.
- **Material `expressions` is protected** → Do not access `Material.expressions` directly in Python. Use CLI commands.
- **Engine bugs** → Read `ENGINE_BUGS.md` in the project root.
- **Screenshot fails** → editor window must be visible. Retry.
- **Asset overwrite dialog blocks script** → see "Avoiding Asset Overwrite Dialogs" below.
- **Silent Failures (C++ Errors without Python Exceptions)** → Check recent engine errors: `cli-anything-unreal --json editor exec "py import unreal; result = list(unreal.CliAnythingBridgeLibrary.get_recent_engine_errors(10))"`
- **JSON Parsing Errors** → The output may contain UE warnings before the JSON. Extract the JSON block.

## No Modal Dialogs in CLI Environment

> **Any modal dialog blocks CLI execution indefinitely.** This is not limited to asset overwrite dialogs — it applies to *all* UI-blocking operations in the UE editor.

**Common triggers:**
- `new_level(path)`: Delete + GC first if level exists.
- `save_asset()` with dirty referencers: Use `--no-save` and handle saves explicitly.
- `import_asset()` with naming conflict: Delete existing + GC first.
- Any `unreal.EditorDialog` call: Never use in scripts.

## Avoiding Asset Overwrite Dialogs

`create_asset` / `duplicate_asset` will pop a modal "Overwrite Existing Object" dialog if the target path already has an asset loaded in memory, blocking CLI execution indefinitely.

**Fix**: check `delete_asset` return value, then call `collect_garbage()` before creating.

```python
import unreal
EAL = unreal.EditorAssetLibrary
target = "/Game/MyAsset"
can_create = True
if EAL.does_asset_exist(target):
    if EAL.delete_asset(target):           # Returns True if fully deleted
        unreal.SystemLibrary.collect_garbage()  # Flush the old UObject from memory
    else:
        can_create = False                 # Delete failed — do NOT create

if can_create:
    ATH = unreal.AssetToolsHelpers.get_asset_tools()
    new_asset = ATH.create_asset(...)
```

## Command Index & Workflows

To keep this prompt concise, all specific CLI commands, arguments, and detailed workflow examples have been moved to `references/commands.md`. 

**Whenever you need to perform a specific action, read `references/commands.md` in this directory to find the right syntax.**

Key topics covered in `references/commands.md`:
* **Editor Control & Python Execution** (`editor status`, `editor run-script`, etc.)
* **Project Management** (`project info`, `asset delete`, etc.)
* **Build System** (`build compile`, `build cook`)
* **Scene Queries** (`scene list`, `scene info`, transform, materials)
* **Material Viewing & Editing** (Add nodes, connect, recompile, dump HLSL)
* **Blueprint Editing** (Add variables/functions, compile)
* **Screenshots** (`screenshot capture`)
* **Multi-Instance Support** (Targeting specific editors via `--port`)
* **Advanced Workflows & Examples** (Step-by-step examples for Editor Lifecycle, Scripting, and Actor->Material Investigation)
