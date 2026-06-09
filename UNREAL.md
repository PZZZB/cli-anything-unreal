# Unreal Engine 5.7 - ue-cli Architecture & SOP

## Architecture Summary

UE5 has GUI editor, UObject reflection, Blueprint/material systems, Remote Control HTTP, and editor-only Python. No Blender-style single headless `--python` entry. `ue-cli` uses dual backend:

```text
Agent -> ue-cli
  -> UAT/UBT subprocess: compile, cook, package, generate project files
  -> Running Unreal Editor:
       Remote Control HTTP localhost:30010
       PythonScriptPlugin execution
       CliAnythingBridge C++ reflection/helpers
```

## CLI Strategy: Dual-Backend

### Why Two Backends?

1. **Build-time ops**: compile C++, cook, package, generate project files. Use UAT/UBT subprocess. No editor.
2. **Editor-time ops**: query scene, edit materials/Blueprints/assets, screenshots. Need live editor. Use Remote Control + Python.

### Why Not a Single Backend?

- UAT/UBT cannot query live scene/material data.
- HTTP API cannot compile C++ or package.
- Both together cover CI/offline tasks + live editor automation.

## Backend A: UAT / UBT (Subprocess)

Invokes `RunUAT.bat` / `Build.bat`.

| Operation | Tool | Example |
|-----------|------|---------|
| Compile C++ | UAT `BuildCookRun -build` | `build compile --config Development` |
| Cook content | UAT `BuildCookRun -cook` | `build cook --platform Win64` |
| Package | UAT `BuildCookRun -build -cook -stage -package -archive` | `build package` |
| Stop build | `taskkill /F /T` process tree | `build stop` |
| Check building | Process scan | `build is-building` |
| Generate VS files | `GenerateProjectFiles.bat` | `project generate` |
| Build status | Filesystem scan | `build status` |

Engine discovery order:
1. `.uproject` `EngineAssociation`
2. `UE_ENGINE_ROOT`
3. default installs (`C:\Program Files\Epic Games\UE_*`)
4. Windows registry / Epic Launcher

## Backend B: HTTP Remote Control API

Built-in Remote Control plugin. HTTP REST to `localhost:<port>`; default 30010.

### Core Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/remote/info` | GET | Routes |
| `/remote/object/call` | PUT | Call UObject function |
| `/remote/object/property` | PUT | Get/set UObject property |
| `/remote/object/describe` | PUT | Introspect UObject |
| `/remote/search/assets` | PUT | Search assets |

### Python Script Injection Pattern

For multi-step operations beyond one HTTP call:

1. Generate Python script from template/params.
2. Write temp `.py`.
3. Execute in editor via Remote Control.
4. Script emits structured JSON/result marker.
5. CLI reads result.
6. Temp files cleaned.

```python
# Example: generated script to query material info
import unreal, json, tempfile

result = {}
mat = unreal.EditorAssetLibrary.load_asset("{material_path}")
result["blend_mode"] = str(mat.get_editor_property("blend_mode"))
result["shading_model"] = str(mat.get_editor_property("shading_model"))
# ... more queries ...

output_path = tempfile.gettempdir() + "/cli_anything_result.json"
with open(output_path, "w") as f:
    json.dump(result, f)
```

## Multi-Instance Support

Multiple UE editors can run, each on separate port.

| Feature | Detail |
|---------|--------|
| Default port | 30010 |
| Port range | 30010-30030 configurable |
| Discovery | `editor status` scans |
| Targeting | `--port` |
| Process enum | Windows process listing |

## Data Model

### Project (.uproject)

`.uproject` is JSON manifest:

```json
{
    "FileVersion": 3,
    "EngineAssociation": "{GUID-or-version}",
    "Category": "Game",
    "Description": "",
    "Modules": [
        {
            "Name": "MyGame",
            "Type": "Runtime",
            "LoadingPhase": "Default"
        }
    ],
    "Plugins": [
        {"Name": "PythonScriptPlugin", "Enabled": true},
        {"Name": "RemoteControl", "Enabled": true}
    ]
}
```

Parsed directly; no binary format.

### Config (.ini)

UE INI quirks:
- array keys: `+Key=Value`, `-Key=Value`
- duplicate keys
- layered overrides: `Base*.ini` -> `Default*.ini` -> `Saved/*.ini`

Parser handles read/write.

### Materials & Blueprints

Binary `.uasset`; never parse/write directly. Use editor via HTTP + Python.

## Core Modules

| Module | Editor Required | Purpose |
|--------|-----------------|---------|
| `unreal_cli.py` | No | Click root, global flags, command specs |
| `core/project.py` | No | `.uproject`, config I/O, content list |
| `core/build.py` | No | compile/cook/package/stop/is-building |
| `core/session.py` | No | session state, undo/redo |
| `core/scene.py` | Yes | actors, properties, transforms |
| `core/materials.py` | Yes | material inspect/edit/HLSL |
| `core/blueprint.py` | Yes | Blueprint graphs/vars/compile |
| `core/screenshot.py` | Yes | capture/compare/compress |
| `core/script_runner.py` | Yes | Python in editor |
| `utils/ue_http_api.py` | Yes | Remote Control client |
| `utils/ue_backend.py` | Mixed | engine discovery, editor/UAT/UBT |

## Command Map: GUI Action -> CLI Command

| UE Editor Action | CLI Command |
|-----------------|-------------|
| Open project | `project info --project path/to.uproject` |
| Browse content | `asset list [--path /Game/Maps]` |
| Edit config | `project config get DefaultEngine` / `project config set ...` |
| Generate VS solution | `project generate` |
| Build Development | `build compile --config Development` |
| Cook Windows | `build cook --platform Win64` |
| Package | `build package --platform Win64 --config Shipping` |
| Stop build | `build stop` |
| Check building | `build is-building` |
| Check artifacts | `build status` |
| Check editor | `editor status` |
| Run console | `editor exec "stat fps"`; returns `log_text` for captured Output Log lines |
| Run Python | `editor run-script script.py` |
| Get/set CVar | `editor cvar get r.ScreenPercentage` / `editor cvar set r.Shadow.Virtual.ResolutionLodBiasDirectional -4`; missing or unverified empty CVars return an error |
| List actors | `scene list [--class StaticMeshActor]` |
| Find actor | `scene list -q "PlayerStart"` searches UObject name, Outliner label, and path; use `--field name --exact` for precise name match |
| Inspect actor API | `editor api-discover /Game/Maps/Level.Level:PersistentLevel.MyActor` |
| Get actor prop | `scene property <path> <property>` |
| List materials | `material list [--path /Game/Materials]` |
| Inspect material | `material info /Game/Materials/M_Base` |
| Analyze material | `material analyze /Game/Materials/M_Base` |
| Dump HLSL/source | `material hlsl-code /Game/Materials/M_Base` |
| Add material node | `material add-node <path> --type MaterialExpressionTextureSample` |
| Wire nodes | `material connect <path> --from Node_A --to Node_B --to-input Pin` |
| Recompile material | `material recompile <path>` |
| List blueprints | `blueprint list` |
| Inspect blueprint | `blueprint info /Game/BP/BP_Player` |
| Add BP function | `blueprint add-function <path> --name MyNewFunction` |
| Add BP variable | `blueprint add-variable <path> --name Health --type float` |
| Compile blueprint | `blueprint compile <path>` |
| Screenshot | `screenshot capture --filename test_shot` |
| Undo/redo | `session undo` / `session redo` |

## Session & Undo/Redo

Session tracks active project, engine root, editor port, undo/redo snapshots (max 50), dirty flag. Can persist/restore JSON.

## Test Coverage Plan

1. **Unit tests**: no editor/engine. Cover project/config/session/build status/HTTP client/material/Blueprint/CLI with mocks.
2. **E2E tests**: require UE editor. Cover connection, scene, material edit, screenshot, console, Blueprint.

## Rendering Gap Assessment: Low

CLI delegates to engine; not reimplementation. Gaps:
- **No offline `.uasset` parsing/writing**. By design. Never create/write `.uasset` from text/code; use `editor run-script` + UE Python.
- **Windows-focused**. Linux/Mac need path/discovery changes.
- **Plugin dependency**. Remote Control + Python Script Plugin required; bridge plugin for advanced reflection/shader/viewport helpers.

## Known Engine Bugs

UE5 automation bugs exist (`delete_all_material_expressions` modify-while-iterating, transform Remote Control 400). See [ENGINE_BUGS.md](ENGINE_BUGS.md).
