# CLI Command Reference

Complete `ue-cli` command reference. Non-TTY output defaults JSON; terminal can force with `--output json`.

Workflow examples live in sibling workflow docs.

## editor - Editor Control

| Command | Description | Requires Editor |
|---------|-------------|:-:|
| `editor status [--all] [--scan-range START-END] [TASK_ID]` | No TASK_ID: list Unreal Editor processes/result array. With `--project`, filters to that project unless `--all` is set. Online entries include bridge plugin version fields; mismatch entries include `next_command` when project is known. Offline entries include recovery hints. With TASK_ID: async progress | - |
| `editor preflight` | Check engine/project build compatibility | No |
| `editor launch [--map MAP] [--no-wait] [--timeout N]` | Launch editor; waits until ready; kills zombies | No |
| `editor close` | Gracefully close editor | No |
| `editor new-level PATH [--template PATH]` | Safely create/open new level | Yes |
| `editor save-level` | Safely save current level | Yes |
| `editor exec [--timeout SEC] [--log-wait SEC] COMMAND` | Run UE console command and return captured Output Log text when available (`stat unit`, `r.DumpRenderTargetPoolMemory`, `renderdoc.captureframe`) | Yes |
| `editor viewport bookmark jump --index N [--timeout SEC]` | Jump Level Viewport bookmark 0-9; Windows only | Yes |
| `editor run-script [PATH|-] [-c CODE] [--timeout N] [--no-save]` | Execute Python file, stdin (`-`), or short inline code with result capture | Yes |
| `editor cvar get NAME` / `editor cvar set NAME VALUE` | Get/set console variable; `get` errors on missing/unverified empty CVars, negative values are supported (`... set r.X -4` or `... set r.X -- -4`) | Yes |
| `editor enable-remote` | Enable Remote Control config | No |
| `editor api-discover TARGET [-q QUERY] [-d NAMES] [--timeout N]` | Discover UE class/API. TARGET: class, asset path, actor path | Yes |
| `editor cancel TASK_ID` | Cancel async editor launch | - |
| `editor plugin-version` | Compare bundled vs loaded plugin | Yes (loaded) |
| `editor plugin-upgrade` | Deploy -> compile -> restart plugin upgrade | No |

### api-discover Usage

`api-discover` belongs under `editor`, not top-level.

**TARGET auto-detection**: class name, asset path, actor path:

```bash
# Class name - direct lookup:
ue-cli editor api-discover DirectionalLight
ue-cli editor api-discover unreal.MaterialEditingLibrary -q connect

# Asset path (/Game/...) - auto-detects class from the live asset:
ue-cli editor api-discover /Game/Materials/M_Water

# Actor path (contains PersistentLevel) - auto-detects class from scene actor:
ue-cli editor api-discover /Game/Maps/L.L:PersistentLevel.Light_0

# Drill into details with -d:
ue-cli editor api-discover DirectionalLight -d bHidden,Intensity
ue-cli editor api-discover /Game/Materials/M_Water -d BlendMode,ShadingModel

# WRONG - these will fail:
ue-cli api-discover DirectionalLight   # not top-level, needs 'editor' prefix
```

**Progressive disclosure**: Details panel style.

1. **Overview** (default): property/function **names** only.
   ```json
   {"properties": ["Constant", "Desc"], "functions": ["ConnectMaterialProperty"]}
   ```

2. **Detail** (`-d NAMES`): full info for named items: tooltips, categories, params, returns, read/write.
   ```bash
   editor api-discover unreal.MaterialEditingLibrary -d ConnectMaterialProperty
   ```
   ```json
   {"items": [{"kind": "function", "name": "ConnectMaterialProperty",
     "detail": {"tooltip": "Connect a material expression output to...",
       "return_type": "bool",
       "params": [{"name": "FromExpression", "type": "UMaterialExpression*"}, ...]}}]}
   ```

**Data source**: C++ reflection via `CliAnythingBridgeLibrary.get_class_info()`, same `TFieldIterator` system as UE Details panel.

## project - Project Management

| Command | Description |
|---------|-------------|
| `project info [--project PATH]` | Show `.uproject` info |
| `project config list` | List config files |
| `project config get CONFIG_NAME [--section SEC]` | Read config |
| `project config set CONFIG_NAME SECTION KEY VALUE` | Set config value |
| `project generate` | Generate Visual Studio project files |

## asset - Asset Operations

All asset commands require editor.

| Command | Description |
|---------|-------------|
| `asset list [-q QUERY] [--class CLASS] [--path PATH] [--limit N]` | Search assets via Asset Registry |
| `asset exists ASSET_PATH` | Check existence |
| `asset property ASSET_PATH PROP[=VALUE]` | Get/set property |
| `asset delete ASSET_PATH [--force]` | Delete with ref detection |
| `asset refs ASSET_PATH` | List referencers |
| `asset duplicate SRC DEST [--force]` | Duplicate asset |
| `asset rename SRC DEST` | Rename/move asset |

## build - Build System

Build commands do not require editor.

Synchronous `build compile` / `build cook` / `build package` stream the live UAT/UBT log to stderr while waiting, similar to UE `Build.bat`. JSON stdout stays one final payload with `log_file`.

| Command | Description |
|---------|-------------|
| `build compile [--project PATH] [--config C] [--platform P] [--no-wait] [--timeout N]` | Compile C++ |
| `build cook [--project PATH] [--platform P] [--no-wait] [--timeout N]` | Cook content |
| `build package [--project PATH] [--platform P] [--config C] [--output-dir DIR] [--no-wait] [--timeout N]` | Full package pipeline |
| `build stop [--project PATH]` | Kill MSBuild/UBT tree |
| `build is-building [--project PATH]` | Check compile/build running |
| `build status [--project PATH] [TASK_ID]` | Check artifacts/logs or async progress |
| `build cancel TASK_ID` | Cancel async build |

## scene - Scene/Level Queries

All scene commands require editor.

| Command | Description |
|---------|-------------|
| `scene list [--class CLASS] [-q QUERY] [--field name\|label\|path\|all] [--exact]` | List actors in current level; outputs `name`, World Outliner `label`, `path`, `class`; `-q` searches name/label/path by default |
| `scene property ACTOR_PATH PROP[=VALUE]` | Get/set property |
| `scene get-transform ACTOR_PATH` | Get transform |
| `scene list-components ACTOR_PATH` | List actor components |
| `scene get-material ACTOR_PATH [--index N]` | Get material from actor mesh |

## material - Material Viewing & Editing

All material commands require editor.

### Viewing
| Command | Description |
|---------|-------------|
| `material list [--path /Game/]` | List materials |
| `material info MATERIAL_PATH` | Nodes, params, textures, connections, Custom node code |
| `material get-graph MATERIAL_PATH` | Mermaid topology + orphan detection |
| `material get-stats MATERIAL_PATH` | Compilation stats |
| `material get-errors MATERIAL_PATH` | Compilation errors |
| `material list-textures MATERIAL_PATH` | Referenced textures |
| `material analyze MATERIAL_PATH` | Common issue detector |
| `material dump-hlsl MATERIAL_PATH --output PATH [--platform P] [--shader-type T] [--full]` | Compiled HLSL via `r.DumpShaderDebugInfo` |
| `material hlsl-code MATERIAL_PATH` | Material HLSL expression source |
| `material shader-source MATERIAL_PATH` | Compiled `.usf` sources with cbuffers/structs |

### Editing
| Command | Description |
|---------|-------------|
| `material add-node PATH --type CLASS [--pos-x X] [--pos-y Y] [--set KEY=VALUE] [--add-input NAME] [--code-file PATH]` | Add expression node |
| `material delete-node PATH --node NAME` | Delete expression node |
| `material connect PATH --from NODE [--from-output PIN] --to NODE --to-input PIN` | Connect nodes |
| `material disconnect PATH --from NODE [--from-output PIN] --to NODE --to-input PIN` | Disconnect nodes |
| `material set-param PATH --name N --value V --type scalar\|vector\|texture` | Set MaterialInstance param |
| `material get-param PATH --name N` | Get MaterialInstance param |
| `material recompile PATH` | Force shader recompile |

## blueprint - Blueprint Viewing & Editing

All blueprint commands require editor.

| Command | Description |
|---------|-------------|
| `blueprint list [--path /Game/]` | List blueprints |
| `blueprint info BLUEPRINT_PATH` | Graphs, nodes, variables |
| `blueprint add-function PATH --name NAME` | Add function graph |
| `blueprint delete-function PATH --name NAME` | Remove function graph |
| `blueprint add-variable PATH --name NAME --type TYPE` | Add member variable |
| `blueprint delete-variable PATH --name NAME` | Delete member variable |
| `blueprint delete-unused-variables PATH` | Remove unused variables |
| `blueprint rename-graph PATH --old OLD --new NEW` | Rename graph |
| `blueprint compile PATH` | Compile blueprint |

## umg - Widget Blueprint Authoring

All UMG commands require editor and the CliAnythingBridge plugin.

| Command | Description |
|---------|-------------|
| `umg create WIDGET_PATH [--root-class CLASS] [--root-name NAME] [--force] [--variable]` | Create a Widget Blueprint with a root widget; default root is `CanvasPanel` |
| `umg add-widget WIDGET_PATH --type CLASS --name NAME [--parent CANVAS] [--text TEXT] [--x X] [--y Y] [--w W] [--h H] [--z Z] [--variable]` | Add a child widget to a CanvasPanel and set its Canvas slot |
| `umg tree WIDGET_PATH` | Inspect the design-time WidgetTree, including root, child widgets, slots, and TextBlock text |

## screenshot - Screenshot

All screenshot commands require editor.

| Command | Description |
|---------|-------------|
| `screenshot capture [--path PATH] [--filename NAME] [--no-compress]` | Capture main editor window. `--path` is a full output path; `.png` writes the raw PNG there, `.jpg/.jpeg` writes the compressed image there and keeps raw PNG beside it |
| `screenshot capture-sequence [-n N] [-i SEC] [--no-compress]` | Capture sequence with bounded per-frame waits |

## session - Undo/Redo

| Command | Description |
|---------|-------------|
| `session status` | Current session info |
| `session undo` | Undo last change |
| `session redo` | Redo last undone change |
| `session history` | Show undo history |

## task - Background Task Management

Generic async task polling/cancel.

| Command | Description |
|---------|-------------|
| `task status TASK_ID` | Check progress/result |
| `task cancel TASK_ID` | Cancel pending/running task |

## install-skills - IDE Skill Installation

| Command | Description |
|---------|-------------|
| `install-skills [--target PATH]` | Install skill docs into IDE dirs or custom path |

## Multi-Instance Support

Multiple editors: discover with `editor status --all`, target with `--port`.

```bash
ue-cli editor status --all
ue-cli --port 30010 editor status
ue-cli --port 30011 material list
```

Online bridge mismatch and offline result items have `next_command`. For stale editor process:

```bash
ue-cli --project "F:\MyGame\MyGame.uproject" editor launch
```

For online bridge mismatch:

```bash
ue-cli --project "F:\MyGame\MyGame.uproject" editor plugin-upgrade
```

`editor launch` kills stale matching editors and starts reachable editor.
