# Unreal Engine 5.7 — CLI-Anything Architecture & SOP

## Architecture Summary

Unreal Engine 5 is a C++ game engine with a modular editor built on Slate UI,
a Blueprints visual scripting system, and a powerful material graph compiler.
Unlike Blender (which offers `--background --python` headless mode), UE has no
single headless scripting entry point. We therefore adopt a **dual-backend**
strategy that routes each operation through the most suitable channel.

```
┌───────────────────────────────────────────────────────────────────┐
│                     Unreal Editor (GUI)                          │
│  ┌────────────┐ ┌────────────┐ ┌──────────┐ ┌───────────────┐   │
│  │  Viewport  │ │  Material  │ │Blueprint │ │  World        │   │
│  │  (Slate)   │ │  Editor    │ │  Editor  │ │  Outliner     │   │
│  └─────┬──────┘ └─────┬──────┘ └────┬─────┘ └───────┬───────┘   │
│        │              │             │               │            │
│  ┌─────┴──────────────┴─────────────┴───────────────┴─────────┐  │
│  │              UObject / Reflection System                   │  │
│  │   All engine objects: Actors, Materials, Blueprints, ...   │  │
│  └────────────────────────┬───────────────────────────────────┘  │
│                           │                                      │
│  ┌────────────────────────┴───────────────────────────────────┐  │
│  │              Remote Control API Plugin                     │  │
│  │   HTTP REST server exposing UObject call/property/search   │  │
│  │   Default port: 30010                                      │  │
│  └────────────────────────┬───────────────────────────────────┘  │
│                           │                                      │
│  ┌────────────────────────┴───────────────────────────────────┐  │
│  │              Python Script Execution                       │  │
│  │   PythonScriptPlugin + EditorScriptingUtilities            │  │
│  │   Execute .py files inside the running editor              │  │
│  └────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────┘
                            │
              ┌─────────────┴──────────────┐
              │                            │
  ┌───────────▼───────────┐   ┌────────────▼────────────┐
  │  Backend A: UAT/UBT   │   │  Backend B: HTTP API    │
  │  (subprocess)         │   │  (localhost REST)       │
  │                       │   │                         │
  │  • Compile C++        │   │  • Actor queries        │
  │  • Cook content       │   │  • Material editing     │
  │  • Package project    │   │  • Blueprint editing    │
  │  • Generate VS files  │   │  • Screenshots          │
  │  • No editor needed   │   │  • Console commands     │
  │                       │   │  • Python script exec   │
  │  RunUAT.bat           │   │  • Requires running     │
  │  Build.bat            │   │    editor               │
  └───────────────────────┘   └─────────────────────────┘
```

## CLI Strategy: Dual-Backend

### Why Two Backends?

UE5's architecture splits cleanly into two categories of operations:

1. **Build-time operations** — Compiling C++ code, cooking assets, packaging
   builds, generating project files. These are handled by UAT (Unreal
   Automation Tool) and UBT (Unreal Build Tool), invoked as subprocesses.
   They do not require a running editor.

2. **Editor-time operations** — Querying scenes, editing materials, modifying
   Blueprints, taking screenshots. These require a live editor instance and
   are performed via the **Remote Control API** (HTTP REST on localhost).

### Why Not a Single Backend?

- UAT/UBT cannot query live scene data or manipulate materials in real-time.
- The HTTP API cannot compile C++ or package builds.
- Combining both gives full engine coverage without requiring the editor for
  offline tasks (CI pipelines, batch builds).

## Backend A: UAT / UBT (Subprocess)

Invoked via `RunUAT.bat` and `Build.bat` in the engine install directory.

| Operation | Tool | Example |
|-----------|------|---------|
| Compile C++ | UAT `BuildCookRun -build` | `build compile --config Development` |
| Cook content | UAT `BuildCookRun -cook` | `build cook --platform Win64` |
| Package | UAT `BuildCookRun -build -cook -stage -package -archive` | `build package` |
| Generate VS files | `GenerateProjectFiles.bat` | `project generate` |
| Build status | Filesystem scan of Binaries/ and Intermediate/ | `build status` |

**Engine discovery** is multi-strategy:
1. Parse `EngineAssociation` from `.uproject` JSON
2. `UE_ENGINE_ROOT` environment variable
3. Default install paths (`C:\Program Files\Epic Games\UE_*`, etc.)
4. Windows registry (Epic Games Launcher)

## Backend B: HTTP Remote Control API

Uses the built-in **Remote Control** plugin (enabled by default in UE5).
All requests are HTTP REST to `localhost:<port>`.

### Core Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/remote/info` | GET | List available routes |
| `/remote/object/call` | PUT | Call function on a UObject |
| `/remote/object/property` | PUT | Get/set property on a UObject |
| `/remote/object/describe` | PUT | Introspect a UObject |
| `/remote/search/assets` | PUT | Search assets by class/path |

### Python Script Injection Pattern

For complex operations (materials, Blueprints) that require multi-step logic
beyond what a single API call can express, we use an embedded script pattern:

1. Generate a Python script from a template with parameter substitution
2. Write it to a temporary `.py` file
3. Execute it in-editor via the Remote Control API (`exec_python_file`)
4. The script writes structured results to a temp JSON file
5. CLI polls for and reads the JSON output
6. Temp files are cleaned up

This avoids the limitations of single-line console commands and gives us
full access to `unreal` Python API inside the editor.

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

Multiple UE editors can run simultaneously, each on a different HTTP port.

| Feature | Detail |
|---------|--------|
| Default port | 30010 |
| Port range | 30010 – 30030 (configurable) |
| Discovery | `editor list` scans the port range |
| Targeting | `--port` flag on any command |
| Process enum | WMIC-based process listing (Windows) |

## Data Model

### Project (.uproject)

The `.uproject` file is a JSON manifest at the project root:

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

We parse this directly — no binary formats involved.

### Config (.ini)

UE config files use an extended INI format with:
- Array-style keys: `+Key=Value` (append), `-Key=Value` (remove)
- Duplicate key support (multiple values per key)
- Hierarchical overrides: `Base*.ini` → `Default*.ini` → `Saved/*.ini`

Our parser handles all these quirks for read/write operations.

### Materials & Blueprints

These are binary `.uasset` files — we do NOT parse them directly.
Instead, all material/Blueprint operations go through the running editor
via the HTTP API + Python script injection.

## Core Modules

| Module | Lines | Editor Required | Purpose |
|--------|-------|-----------------|---------|
| `unreal_cli.py` | 1,822 | — | Click CLI entry point, all commands |
| `core/project.py` | 320 | No | .uproject parsing, config I/O, content listing |
| `core/build.py` | 270 | No | Compile, cook, package via UAT/UBT |
| `core/session.py` | 204 | No | Session state, undo/redo (50 entries max) |
| `core/scene.py` | 252 | Yes | Actor queries, property get/set, transforms |
| `core/materials.py` | 1,293 | Yes | Material inspection, node editing, HLSL dump |
| `core/blueprint.py` | 599 | Yes | Blueprint graphs, variables, compilation |
| `core/screenshot.py` | 393 | Yes | Viewport capture, comparison, compression |
| `core/script_runner.py` | 228 | Yes | Generic Python script execution in editor |
| `utils/ue_http_api.py` | 552 | — | HTTP client for Remote Control API |
| `utils/ue_backend.py` | 785 | — | Engine discovery, UAT/UBT invocation |

**Total: ~7,100 lines of Python**

## Command Map: GUI Action → CLI Command

| UE Editor Action | CLI Command |
|-----------------|-------------|
| Open project | `project info --project path/to.uproject` |
| Browse content | `project content [--ext .uasset] [--path /Game/Maps]` |
| Edit config | `project config read DefaultEngine` / `project config write ...` |
| Generate VS solution | `project generate` |
| Build (Development) | `build compile --config Development` |
| Cook for Windows | `build cook --platform Win64` |
| Package project | `build package --platform Win64 --config Shipping` |
| Check build artifacts | `build status` |
| Check editor status | `editor status` |
| Discover editors | `editor list` |
| Run console command | `editor exec "stat fps"` |
| Run Python in editor | `editor exec py "print('hello')"` |
| Run .py script | `editor run-script myscript.py` |
| Get/set CVar | `editor cvar get r.ScreenPercentage` / `editor cvar set ...` |
| List scene actors | `scene actors [--class StaticMeshActor]` |
| Find actor by name | `scene find "PlayerStart"` |
| Inspect actor | `scene describe /Game/Maps/Level.Level:PersistentLevel.MyActor` |
| Get actor property | `scene property get <path> <property>` |
| List materials | `material list [--path /Game/Materials]` |
| Inspect material | `material info /Game/Materials/M_Base` |
| Analyze material | `material analyze /Game/Materials/M_Base` |
| Dump HLSL | `material hlsl /Game/Materials/M_Base --platform sm6` |
| Add material node | `material add-node <path> MaterialExpressionTextureSample` |
| Wire nodes | `material connect <path> --from Node_A --from-output 0 ...` |
| Recompile material | `material recompile <path>` |
| List blueprints | `blueprint list` |
| Inspect blueprint | `blueprint info /Game/BP/BP_Player` |
| Add BP function | `blueprint add-function <path> MyNewFunction` |
| Add BP variable | `blueprint add-variable <path> Health float` |
| Compile blueprint | `blueprint compile <path>` |
| Take screenshot | `screenshot take --filename test_shot` |
| Compare screenshots | `screenshot compare imageA.png imageB.png` |
| Undo/redo | `session undo` / `session redo` |

## Session & Undo/Redo

The session module tracks:
- Active project path, directory, and name
- Auto-discovered engine root
- Current editor HTTP port
- State snapshots for undo/redo (max 50 entries)
- Modified flag

Session state can be persisted to and restored from JSON files.

## Test Coverage Plan

1. **Unit tests** (`test_core.py`): 112 tests, no editor or engine required
   - Project parsing (.uproject JSON, .ini configs, content enumeration)
   - Engine discovery logic (mock filesystem)
   - Session management (undo/redo, snapshots, persistence)
   - Build status parsing (filesystem scan)
   - HTTP API client (mocked requests)
   - Material/Blueprint operations (mocked API responses)
   - CLI interface via Click test runner

2. **E2E tests** (`test_full_e2e.py`): Requires running UE editor
   - Editor connection and status
   - Scene actor queries
   - Material inspection and editing
   - Screenshot capture and comparison
   - Console command execution
   - Blueprint operations

## Rendering Gap Assessment: Low

Most UE operations are delegated to the engine itself — we are a **thin CLI
wrapper**, not a reimplementation. The main gaps are:

- **No offline .uasset parsing** — Material/Blueprint operations require a
  running editor. This is by design; UE's binary asset format is proprietary
  and version-dependent.
- **Windows-only** — UAT/UBT and editor discovery are Windows-focused.
  Linux/Mac support would require path adjustments.
- **Plugin dependency** — Remote Control plugin must be enabled; Python
  Script Plugin needed for advanced operations.
