# CLI Command Reference

Complete command reference for `cli-anything-unreal`. All commands support `--json` for structured output.

For workflows and examples, see the workflow files in this directory.

## editor — Editor Control

| Command | Description | Requires Editor |
|---------|-------------|:-:|
| `editor status` | Check if editor is running and reachable | - |
| `editor list [--scan-range START-END]` | Discover all running editor instances | - |
| `editor preflight` | Check engine/project build compatibility | No |
| `editor launch [--map MAP] [--wait/--no-wait]` | Launch editor with preflight check | No |
| `editor close` | Gracefully close the editor | Yes |
| `editor new-level PATH [--template PATH]` | Create and open a new level safely | Yes |
| `editor save-level` | Save the current level safely | Yes |
| `editor exec COMMAND [--timeout N]` | Execute console command (py prefix = Python mode) | Yes |
| `editor run-script PATH [--timeout N] [--no-save]` | Execute .py script with result capture | Yes |
| `editor cvar get NAME` / `editor cvar set NAME VALUE` | Get/set console variable | Yes |
| `editor enable-remote` | Enable Remote Control in project config | No |
| `editor api-discover TARGET [-m FILTER] [-d NAMES]` | Discover API surface of a UE class. TARGET can be class name, asset path (/Game/...), or actor path (auto-detects class) | Yes |
| `editor plugin-version` | Check bundled vs loaded plugin version | Yes (for loaded) |
| `editor plugin-upgrade` | Upgrade plugin: deploy → compile → restart | No |

### api-discover Usage

`api-discover` is a subcommand of `editor`, not a top-level command.

**TARGET auto-detection**: The TARGET argument is smart — pass a class name, asset path, or actor path:

```bash
# Class name — direct lookup:
cli-anything-unreal --json editor api-discover DirectionalLight
cli-anything-unreal --json editor api-discover unreal.MaterialEditingLibrary -m connect

# Asset path (/Game/...) — auto-detects class from the live asset:
cli-anything-unreal --json editor api-discover /Game/Materials/M_Water

# Actor path (contains PersistentLevel) — auto-detects class from scene actor:
cli-anything-unreal --json editor api-discover /Game/Maps/L.L:PersistentLevel.Light_0

# Drill into details with -d:
cli-anything-unreal --json editor api-discover DirectionalLight -d bHidden,Intensity
cli-anything-unreal --json editor api-discover /Game/Materials/M_Water -d BlendMode,ShadingModel

# WRONG — these will fail:
cli-anything-unreal api-discover DirectionalLight   # not top-level, needs 'editor' prefix
```

**Progressive disclosure** (like the Details panel — glance, then hover):

1. **Overview** (default): Returns property/function **names** only.
   Quick scan of what's available. Example:
   ```json
   {"properties": ["Constant", "Desc"], "functions": ["ConnectMaterialProperty"]}
   ```

2. **Detail** (`-d NAMES`): Returns full info for the **specific** items you name
   (comma-separated). Includes tooltips, categories, parameter types, return types,
   read/write flags. Example:
   ```bash
   editor api-discover unreal.MaterialEditingLibrary -d ConnectMaterialProperty
   ```
   Returns:
   ```json
   {"items": [{"kind": "function", "name": "ConnectMaterialProperty",
     "detail": {"tooltip": "Connect a material expression output to...",
       "return_type": "bool",
       "params": [{"name": "FromExpression", "type": "UMaterialExpression*"}, ...]}}]}
   ```

**Data source**: Uses C++ reflection via `CliAnythingBridgeLibrary.get_class_info()`
— the same `TFieldIterator` system the UE Details panel uses.

## project — Project Management

| Command | Description |
|---------|-------------|
| `project info` | Display project information (.uproject) |
| `project config list` | List all configuration files |
| `project config get CONFIG_NAME [--section SEC]` | Read a configuration file |
| `project config set CONFIG_NAME SECTION KEY VALUE` | Set a configuration value |
| `project generate` | Generate Visual Studio project files |

## asset — Asset Operations

All asset commands require the editor.

| Command | Description |
|---------|-------------|
| `asset list [-q QUERY] [--class CLASS] [--path PATH] [--limit N]` | Search assets via Asset Registry (like Content Browser) |
| `asset exists ASSET_PATH` | Check if asset exists |
| `asset property ASSET_PATH PROP[=VALUE]` | Get or set a property (`Prop` to read, `Prop=Value` to write) |
| `asset delete ASSET_PATH [--force]` | Delete with reference detection |
| `asset refs ASSET_PATH` | List all referencers |
| `asset duplicate SRC DEST [--force]` | Duplicate asset (--force to overwrite) |
| `asset rename SRC DEST` | Rename/move asset |

## build — Build System

None of the build commands require the editor.

| Command | Description |
|---------|-------------|
| `build compile` | Compile C++ code |
| `build cook [--platform P]` | Cook content assets |
| `build package [--platform P] [--config C]` | Full package pipeline |
| `build status` | Check build status (binaries, logs) |

## scene — Scene/Level Queries

All scene commands require the editor.

| Command | Description |
|---------|-------------|
| `scene list [--class CLASS] [-q QUERY]` | List actors in current level (like World Outliner) |
| `scene property ACTOR_PATH PROP[=VALUE]` | Get or set a property (`Prop` to read, `Prop=Value` to write) |
| `scene get-transform ACTOR_PATH` | Get actor transform (location, rotation, scale) |
| `scene list-components ACTOR_PATH` | List components on an actor |
| `scene get-material ACTOR_PATH` | Get material assigned to actor's mesh |

## material — Material Viewing & Editing

All material commands require the editor.

### Viewing
| Command | Description |
|---------|-------------|
| `material list [--path /Game/]` | List all materials |
| `material info MATERIAL_PATH` | Nodes, parameters, textures, connections, Custom node code |
| `material get-graph MATERIAL_PATH` | Connection graph: Mermaid topology, orphan detection |
| `material get-stats MATERIAL_PATH` | Compilation stats (instruction counts) |
| `material get-errors MATERIAL_PATH` | Check for compilation errors |
| `material list-textures MATERIAL_PATH` | List referenced textures |
| `material analyze MATERIAL_PATH` | Auto-detect common issues |
| `material dump-hlsl MATERIAL_PATH [--platform P] [--shader-type T]` | Compiled HLSL (legacy, r.DumpShaderDebugInfo) |
| `material hlsl-code MATERIAL_PATH` | Material HLSL expression source (Material.ush) |
| `material shader-source MATERIAL_PATH` | All compiled shader source (.usf) with cbuffer/struct defs |

### Editing
| Command | Description |
|---------|-------------|
| `material add-node PATH --type CLASS [--pos-x X] [--pos-y Y]` | Add expression node |
| `material delete-node PATH --node NAME` | Delete expression node |
| `material connect PATH --from NODE --to NODE --to-input PIN` | Connect two nodes |
| `material disconnect PATH --from NODE --to NODE --to-input PIN` | Disconnect nodes |
| `material set-param PATH --name N --value V --type scalar\|vector\|texture` | Set MaterialInstance parameter |
| `material get-param PATH --name N` | Get MaterialInstance parameter |
| `material recompile PATH` | Force shader recompilation |

## blueprint — Blueprint Viewing & Editing

All blueprint commands require the editor.

| Command | Description |
|---------|-------------|
| `blueprint list [--path /Game/]` | List all blueprints |
| `blueprint info BLUEPRINT_PATH` | Graphs, nodes, variables |
| `blueprint add-function PATH --name NAME` | Add function graph |
| `blueprint delete-function PATH --name NAME` | Remove function graph |
| `blueprint add-variable PATH --name NAME --type TYPE` | Add member variable |
| `blueprint delete-variable PATH --name NAME` | Delete member variable |
| `blueprint delete-unused-variables PATH` | Remove all unused variables |
| `blueprint rename-graph PATH --old OLD --new NEW` | Rename a graph |
| `blueprint compile PATH` | Compile blueprint |

## screenshot — Screenshot

All screenshot commands require the editor.

| Command | Description |
|---------|-------------|
| `screenshot capture [--filename NAME]` | Capture main editor window |
| `screenshot capture-sequence [-n N] [-i SEC] [--no-compress]` | Capture N screenshots at interval |

## session — Undo/Redo

| Command | Description |
|---------|-------------|
| `session status` | Current session info |
| `session undo` | Undo last change |
| `session redo` | Redo last undone change |
| `session history` | Show undo history |

## Multi-Instance Support

Multiple editors can run simultaneously on different ports. Use `editor list` to discover instances, then `--port` to target one:

```bash
cli-anything-unreal --json editor list
cli-anything-unreal --json --port 30010 editor status
cli-anything-unreal --json --port 30011 material list
```
