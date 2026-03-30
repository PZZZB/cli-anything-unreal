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

## Core Principles

1. **Use `editor launch` to open the editor, not UnrealEditor.exe directly.** The `editor launch` command runs a preflight build compatibility check before opening — without this, a version mismatch between engine and project binaries causes the editor to hang silently with no error message. It also provides timeout handling and progress feedback.

   ```bash
   # Correct
   cli-anything-unreal --json --project F:\path\to.uproject editor launch

   # Wrong — bypasses build check, hangs on version mismatch
   "F:/ENGINE/UnrealEditor.exe" "F:/path/to.uproject"
   ```

2. **Always pass `--json`** so you get structured output you can parse and act on programmatically. Without it, you get human-readable text that's harder to reason about.

3. **Specify `--project` on the first command** (or set the env var). The CLI has no way to auto-discover which .uproject you mean. Once provided, subsequent commands in the same shell session inherit it — you don't need to repeat `--project` every time.

4. **Prefer CLI commands over writing Python scripts.** Most operations (material editing, blueprint editing, scene queries) already have dedicated commands — they're faster and less error-prone than scripts. Check `<group> --help` first. Only write scripts via `editor run-script` for operations not covered by existing commands.

5. **UE5 Python API restriction:** `Material.expressions` is protected in UE5.7+ — you cannot read or write it directly. Use `material info` to read nodes, and `material add-node` / `material connect` / `material delete-node` to edit them.

## Decision Flow

When the user asks you to do something in Unreal, follow this sequence:

1. **Is the editor running?** Run `editor status`. If not reachable, go through the Editor Lifecycle workflow below.
2. **Do you know the asset path?** If not, discover it with `material list`, `blueprint list`, `scene actors`, or `project content`.
3. **Does a CLI command exist for this?** Check the command reference in `references/commands.md`. Use CLI commands first.
4. **No CLI command covers it?** Write a Python script and run it with `editor run-script`.
5. **Need visual verification?** Use `screenshot take` and review the image.

## Handling Errors

CLI commands return JSON with an `error` field when something goes wrong. Common patterns:

- **Connection refused** → editor not running. Run `editor launch` to start it, then `editor status` to confirm it's reachable.
- **Timeout** → editor is busy (compiling shaders, loading a level). Run `editor status` to check; if reachable, wait 10-15 seconds and retry the original command.
- **Asset not found** → path is wrong. Run `material list`, `blueprint list`, or `project content` to discover the correct path, then retry.
- **"modules built with different engine version"** → Run `editor preflight` to diagnose → `build compile` to rebuild → `editor launch` to start fresh.
- **Material `expressions` is protected** → Do not access `Material.expressions` directly. Use `material info` to read, CLI edit commands (`add-node`, `connect`, `delete-node`) to modify.
- **Screenshot fails** → editor window must be visible. Retry — the CLI auto-brings it to foreground on the attempt.
- **HLSL dump empty** → shader may need recompilation first. Run `material recompile`, then retry `material hlsl`.
- **Asset overwrite dialog blocks script** → see "Avoiding Asset Overwrite Dialogs" below.

## Avoiding Asset Overwrite Dialogs

> **CLI commands handle this automatically.** `project asset-delete` and `project asset-duplicate --force` already include reference checking and GC. This section only matters when writing Python scripts via `editor run-script`.

`create_asset` / `duplicate_asset` will pop a modal "Overwrite Existing Object" dialog if the target path already has an asset loaded in memory, blocking CLI execution indefinitely.

**Root cause**: `EAL.delete_asset()` removes the on-disk package but the UObject stays in memory until the next GC. `create_asset` sees the in-memory object and asks to overwrite.

**Fix**: check `delete_asset` return value, then call `collect_garbage()` before creating.

### Safe asset replacement pattern (in Python scripts)

```python
import unreal
EAL = unreal.EditorAssetLibrary

target = "/Game/MyAsset"
can_create = True
if EAL.does_asset_exist(target):
    if EAL.delete_asset(target):           # Returns True if fully deleted
        unreal.SystemLibrary.collect_garbage()  # Flush the old UObject from memory
    else:
        can_create = False                 # Delete failed — do NOT create (would trigger dialog)

if can_create:
    ATH = unreal.AssetToolsHelpers.get_asset_tools()
    new_asset = ATH.create_asset(...)
```

Key points:
- `delete_asset(path)` and `delete_loaded_asset(obj)` are both force-deletes — no dialog, even with referencers
- **Always check `delete_asset` return value** — if it returns `False`, do not call `create_asset` (would trigger overwrite dialog)
- **`collect_garbage()` after successful delete is mandatory** — without it the old UObject lingers and `create_asset`/`duplicate_asset` triggers an overwrite dialog
- **Never call `duplicate_asset` when the destination already exists** — always delete + GC first
- Use `--no-save` on `editor run-script` if you handle saves explicitly, to avoid the auto-save path

## Command Overview

The CLI is organized into command groups. For the full command reference with all flags and details, read `references/commands.md`.

| Group | What it does | Requires Editor? |
|-------|-------------|:-:|
| `editor` | Launch, close, status, exec Python, run scripts, console vars | Mixed |
| `project` | Project info, content listing, config, asset ops (delete/duplicate/rename/refs) | Mixed |
| `build` | Compile C++, cook content, package, check build status | No |
| `scene` | List actors, find by name, get/set properties, transforms, components | Yes |
| `material` | List, inspect, edit nodes, connect, set params, recompile, HLSL dump | Yes |
| `blueprint` | List, inspect, add/remove functions & variables, compile | Yes |
| `screenshot` | Take screenshots, compare, compress, CVar A/B test | Yes |
| `session` | Undo, redo, history | Yes |

## Key Workflows

### Editor Lifecycle
```bash
# 1. Preflight check — catches build mismatches before they cause hangs
cli-anything-unreal --json --project F:\RXGame\RXGame.uproject editor preflight

# 2. If BuildId mismatch, compile first
cli-anything-unreal --json --project F:\RXGame\RXGame.uproject build compile

# 3. Launch editor
cli-anything-unreal --json --project F:\RXGame\RXGame.uproject editor launch --map /Game/Maps/MyMap

# 4. Verify it's reachable
cli-anything-unreal --json editor status
```

### Material Editing
```bash
# 1. Inspect current state (includes connection graph + Custom HLSL code)
cli-anything-unreal --json material info /Game/M_Water
# Returns: nodes[] with code_preview for Custom nodes,
#          material_outputs{} showing which node feeds each output pin

# 1b. Connection graph only (lightweight)
cli-anything-unreal --json material connections /Game/M_Water

# 2. Add nodes
cli-anything-unreal --json material add-node /Game/M_Water --type MaterialExpressionPanner
cli-anything-unreal --json material add-node /Game/M_Water --type MaterialExpressionTextureSample

# 3. Connect nodes
cli-anything-unreal --json material connect /Game/M_Water \
    --from Panner_0 --to TextureSample_0 --to-input UVs
cli-anything-unreal --json material connect /Game/M_Water \
    --from TextureSample_0 --to __material_output__ --to-input BaseColor

# 4. Recompile and verify
cli-anything-unreal --json material recompile /Game/M_Water
cli-anything-unreal --json material errors /Game/M_Water

# 5. Visual check
cli-anything-unreal --json screenshot take --filename material_check
```

**Connect to material output:** Use `--to __material_output__` with `--to-input` being the property name: `BaseColor`, `Metallic`, `Roughness`, `Normal`, `Emissive`, `Opacity`, `WorldPositionOffset`, etc.

### Python Scripting (for operations not covered by CLI commands)

Use `editor run-script` for complex operations. Set a `result` dict variable to return structured data.

```bash
# Write the script using the Write tool (not cat/heredoc — this is Windows)
# Then execute it:
cli-anything-unreal --json editor run-script setup_scene.py --timeout 60

# Read-only script — skip auto-save
cli-anything-unreal --json editor run-script query.py --no-save
```

Inline Python also works for quick one-liners:
```bash
cli-anything-unreal --json editor exec "py result = {'actors': 42}"
```

Script return conventions:
- Set `result = {...}` → returned as JSON
- No `result` variable → returns `{"status": "ok"}`
- Exception → returns `{"error": "...", "error_type": "...", "traceback": "..."}`

Dirty packages are auto-saved after script execution. Use `--no-save` for read-only scripts.

### Blueprint Editing
```bash
# 1. Find the blueprint
cli-anything-unreal --json blueprint list --path /Game/Blueprints/

# 2. Inspect current state (graphs, nodes, variables)
cli-anything-unreal --json blueprint info /Game/BP_Enemy

# 3. Add a variable
cli-anything-unreal --json blueprint add-variable /Game/BP_Enemy \
    --name Health --type Float

# 4. Add a function
cli-anything-unreal --json blueprint add-function /Game/BP_Enemy \
    --name TakeDamage

# 5. Clean up unused variables
cli-anything-unreal --json blueprint remove-unused-variables /Game/BP_Enemy

# 6. Compile and verify
cli-anything-unreal --json blueprint compile /Game/BP_Enemy
```

### Scene Manipulation
```bash
# 1. Find actors by name
cli-anything-unreal --json scene find "DirectionalLight"

# 2. Inspect all properties and functions on an actor
cli-anything-unreal --json scene describe <actor_path>

# 3. Read a property
cli-anything-unreal --json scene property <actor_path> Intensity

# 4. Modify a property
cli-anything-unreal --json scene property <actor_path> Intensity --set 5.0

# 5. Check transform (location, rotation, scale)
cli-anything-unreal --json scene transform <actor_path>

# 6. List components
cli-anything-unreal --json scene components <actor_path>

# 7. Find which material an actor uses
cli-anything-unreal --json scene material <actor_path>
```

Use `scene actors` to list everything in the current level when you don't know the actor name.

### Build & Package
```bash
# 1. Compile C++ (editor does NOT need to be running)
cli-anything-unreal --json --project F:\RXGame\RXGame.uproject build compile

# 2. Cook content for target platform
cli-anything-unreal --json --project F:\RXGame\RXGame.uproject build cook --platform Win64

# 3. Full package (compile + cook + stage)
cli-anything-unreal --json --project F:\RXGame\RXGame.uproject build package \
    --platform Win64 --config Shipping

# 4. Check build status (binary info, last build logs)
cli-anything-unreal --json --project F:\RXGame\RXGame.uproject build status
```

### Actor → Material → Shader Investigation
```bash
cli-anything-unreal --json scene find "PostProcessVolume"
cli-anything-unreal --json scene material "<actor_path>"
cli-anything-unreal --json material info /Game/SomeMaterial
cli-anything-unreal --json material hlsl /Game/SomeMaterial
```

### CVar A/B Comparison
```bash
cli-anything-unreal --json screenshot cvar-test \
    --cvar "r.Shadow.Virtual.Enable" \
    --values "0,1" \
    --labels "NoVSM,WithVSM"
```

## Multi-Instance

Multiple editors can run simultaneously — useful when working on different maps or comparing changes across project copies. Each instance listens on a different port. Use `editor list` to discover all running instances, then `--port` to target one.

```bash
# Discover all running editors (port, project, pid)
cli-anything-unreal --json editor list

# Target a specific instance by port
cli-anything-unreal --json --port 30010 editor status
cli-anything-unreal --json --port 30011 material list
```

Without `--port`, commands target the default port (30010). If `editor list` returns multiple instances, always confirm which port you need before running commands.
