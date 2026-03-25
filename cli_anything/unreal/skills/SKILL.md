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

3. **Specify `--project` on the first command** (or set the env var). The CLI has no way to auto-discover which .uproject you mean.

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

- **Connection refused** → editor not running. Use `editor launch` first.
- **Timeout** → editor is busy (compiling shaders, loading a level). Wait 10-15 seconds and retry.
- **Asset not found** → path is wrong. Use `material list`, `blueprint list`, or `project content` to find the correct path.
- **"modules built with different engine version"** → Run `editor preflight` → `build compile` → `editor launch`.
- **Material `expressions` is protected** → Do not access `Material.expressions` directly. Use `material info` to read, CLI edit commands to modify.
- **Screenshot fails** → editor window must be visible (the CLI auto-brings it to foreground).
- **HLSL dump empty** → shader may need recompilation first; run `material recompile`.

## Command Overview

The CLI is organized into command groups. For the full command reference with all flags and details, read `references/commands.md`.

| Group | What it does | Requires Editor? |
|-------|-------------|:-:|
| `editor` | Launch, close, status, exec Python, run scripts, console vars | Mixed |
| `project` | Project info, content listing, config read/write | No |
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
# 1. Inspect current state
cli-anything-unreal --json material info /Game/M_Water

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

Multiple editors can run simultaneously. Use `--port` to target a specific instance. Use `editor list` to discover all running instances.

```bash
cli-anything-unreal --json editor list
cli-anything-unreal --json --port 30010 editor status
cli-anything-unreal --json --port 30011 material list
```
