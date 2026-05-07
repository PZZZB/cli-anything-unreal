# CLI Command Reference

Complete command reference for `cli-anything-unreal`. Output defaults to JSON for non-TTY callers; use `--output json` explicitly to force it in a terminal.

For workflows and examples, see the workflow files in this directory.

## editor — Editor Control

| Command | Description | Requires Editor |
|---------|-------------|:-:|
| `editor status [TASK_ID]` | Check editor state or async task progress. Returns `online`/`starting`/`zombie`/`not_running` | - |
| `editor list [--scan-range START-END]` | Discover all running editor instances | - |
| `editor preflight` | Check engine/project build compatibility | No |
| `editor launch [--map MAP] [--no-wait] [--timeout N]` | Launch editor (blocks until ready; auto-kills zombie processes) | No |
| `editor close` | Gracefully close the editor | No |
| `editor new-level PATH [--template PATH]` | Create and open a new level safely | Yes |
| `editor save-level` | Save the current level safely | Yes |
| `editor exec COMMAND` | Execute a UE console command (e.g. `stat unit`, `renderdoc.captureframe`) | Yes |
| `editor run-script [PATH] [-c CODE] [--timeout N] [--no-save]` | Execute Python (file or inline -c) with result capture | Yes |
| `editor cvar get NAME` / `editor cvar set NAME VALUE` | Get/set console variable | Yes |
| `editor enable-remote` | Enable Remote Control in project config | No |
| `editor api-discover TARGET [-q QUERY] [-d NAMES] [--timeout N]` | Discover API surface of a UE class. TARGET can be class name, asset path (/Game/...), or actor path (auto-detects class) | Yes |
| `editor cancel TASK_ID` | Cancel an async editor launch task | - |
| `editor plugin-version` | Check bundled vs loaded plugin version | Yes (for loaded) |
| `editor plugin-upgrade` | Upgrade plugin: deploy → compile → restart | No |

### api-discover Usage

`api-discover` is a subcommand of `editor`, not a top-level command.

**TARGET auto-detection**: The TARGET argument is smart — pass a class name, asset path, or actor path:

```bash
# Class name — direct lookup:
cli-anything-unreal editor api-discover DirectionalLight
cli-anything-unreal editor api-discover unreal.MaterialEditingLibrary -q connect

# Asset path (/Game/...) — auto-detects class from the live asset:
cli-anything-unreal editor api-discover /Game/Materials/M_Water

# Actor path (contains PersistentLevel) — auto-detects class from scene actor:
cli-anything-unreal editor api-discover /Game/Maps/L.L:PersistentLevel.Light_0

# Drill into details with -d:
cli-anything-unreal editor api-discover DirectionalLight -d bHidden,Intensity
cli-anything-unreal editor api-discover /Game/Materials/M_Water -d BlendMode,ShadingModel

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
| `project info [--project PATH]` | Display project information (.uproject) |
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
| `build compile [--config C] [--platform P] [--no-wait] [--timeout N]` | Compile C++ code |
| `build cook [--platform P] [--no-wait] [--timeout N]` | Cook content assets |
| `build package [--platform P] [--config C] [--output-dir DIR] [--no-wait] [--timeout N]` | Full package pipeline |
| `build stop` | Stop a running build (kills MSBuild/UBT process tree) |
| `build is-building` | Check if the project is currently being compiled |
| `build status [TASK_ID]` | Check build status (binaries, logs) or async task progress |
| `build cancel TASK_ID` | Cancel an async build task |

## scene — Scene/Level Queries

All scene commands require the editor.

| Command | Description |
|---------|-------------|
| `scene list [--class CLASS] [-q QUERY]` | List actors in current level (like World Outliner) |
| `scene property ACTOR_PATH PROP[=VALUE]` | Get or set a property (`Prop` to read, `Prop=Value` to write) |
| `scene get-transform ACTOR_PATH` | Get actor transform (location, rotation, scale) |
| `scene list-components ACTOR_PATH` | List components on an actor |
| `scene get-material ACTOR_PATH [--index N]` | Get material assigned to actor's mesh |

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
| `material dump-hlsl MATERIAL_PATH --output PATH [--platform P] [--shader-type T] [--full]` | Compiled HLSL (legacy, r.DumpShaderDebugInfo) |
| `material hlsl-code MATERIAL_PATH` | Material HLSL expression source (Material.ush) |
| `material shader-source MATERIAL_PATH` | All compiled shader source (.usf) with cbuffer/struct defs |

### Editing
| Command | Description |
|---------|-------------|
| `material add-node PATH --type CLASS [--pos-x X] [--pos-y Y] [--set KEY=VALUE] [--add-input NAME] [--code-file PATH]` | Add expression node |
| `material delete-node PATH --node NAME` | Delete expression node |
| `material connect PATH --from NODE [--from-output PIN] --to NODE --to-input PIN` | Connect two nodes |
| `material disconnect PATH --from NODE [--from-output PIN] --to NODE --to-input PIN` | Disconnect nodes |
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
| `screenshot capture [--path PATH] [--filename NAME] [--no-compress]` | Capture main editor window |
| `screenshot capture-sequence [-n N] [-i SEC] [--no-compress]` | Capture N screenshots at interval |

## session — Undo/Redo

| Command | Description |
|---------|-------------|
| `session status` | Current session info |
| `session undo` | Undo last change |
| `session redo` | Redo last undone change |
| `session history` | Show undo history |

## task — Background Task Management

Generic commands for polling or canceling any async task (build, editor launch, etc.).

| Command | Description |
|---------|-------------|
| `task status TASK_ID` | Check task progress and result |
| `task cancel TASK_ID` | Cancel a running or pending task |

## install-skills — IDE Skill Installation

| Command | Description |
|---------|-------------|
| `install-skills [--target PATH]` | Install skill docs into IDE directories (Claude, CodeBuddy, Gemini) or a custom path |

## Multi-Instance Support

Multiple editors can run simultaneously on different ports. Use `editor list` to discover instances, then `--port` to target one:

```bash
cli-anything-unreal editor list
cli-anything-unreal --port 30010 editor status
cli-anything-unreal --port 30011 material list
```
