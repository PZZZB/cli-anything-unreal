# CLI Command Reference

Complete command reference for `cli-anything-unreal`. All commands support `--json` for structured output.

## editor — Editor Control

| Command | Description | Requires Editor |
|---------|-------------|:-:|
| `editor status` | Check if editor is running and reachable | - |
| `editor list [--scan-range START-END]` | Discover all running editor instances | - |
| `editor preflight` | Check engine/project build compatibility | No |
| `editor launch [--map MAP] [--wait/--no-wait]` | Launch editor with preflight check | No |
| `editor close` | Gracefully close the editor | Yes |
| `editor exec COMMAND [--timeout N]` | Execute console command (see Python mode below) | Yes |
| `editor run-script PATH [--timeout N] [--no-save]` | Execute .py script with result capture | Yes |
| `editor cvar get NAME` | Get a console variable value | Yes |
| `editor cvar set NAME VALUE` | Set a console variable value | Yes |
| `editor enable-remote` | Enable Remote Control in project config | No |

### Python Execution (editor exec / editor run-script)

When `editor exec` command starts with `py `, it automatically switches to reliable script mode:
- Code is written to temp file, executed via `exec_python_file`, result captured as JSON.
- Dirty packages are auto-saved after execution (use `--no-save` to skip).
- If the script errors, the error message and traceback are returned (not a silent timeout).

```bash
# Inline Python — result variable is captured
cli-anything-unreal --json editor exec "py result = {'actors': 42}"

# Script file — same result capture, auto-save
cli-anything-unreal --json editor run-script build_scene.py --timeout 60

# Read-only script — skip auto-save
cli-anything-unreal --json editor run-script query.py --no-save
```

**Script convention:** Set a `result` dict variable to return structured data. If not set, returns `{"status": "ok"}`. If script raises an exception, returns `{"error": "...", "error_type": "...", "traceback": "..."}`.

## project — Project Management

| Command | Description |
|---------|-------------|
| `project info` | Display project information (.uproject) |
| `project content` | List content assets in the project |
| `project config read SECTION FILE` | Read a .ini config section |
| `project config write SECTION KEY VALUE FILE` | Write a .ini config value |
| `project generate` | Generate Visual Studio project files |

## build — Build System

| Command | Description |
|---------|-------------|
| `build compile` | Compile C++ code |
| `build cook [--platform P]` | Cook content assets |
| `build package [--platform P] [--config C]` | Full package pipeline |
| `build status` | Check build status (binaries, logs) |

None of the build commands require the editor to be running.

## scene — Scene/Level Queries

All scene commands require the editor to be running.

| Command | Description |
|---------|-------------|
| `scene actors` | List all actors in current level |
| `scene find NAME` | Find actors by name (substring match) |
| `scene describe ACTOR_PATH` | List all properties and functions on an actor |
| `scene property ACTOR_PATH PROP [--set VALUE]` | Get or set a property on an actor |
| `scene transform ACTOR_PATH` | Get actor transform (location, rotation, scale) |
| `scene components ACTOR_PATH` | List components on an actor |
| `scene material ACTOR_PATH` | Get material assigned to actor's mesh |

## material — Material Viewing, Editing & Analysis

All material commands require the editor to be running.

### Viewing
| Command | Description |
|---------|-------------|
| `material list [--path /Game/]` | List all materials |
| `material info MATERIAL_PATH` | Detailed info: nodes, parameters, textures |
| `material stats MATERIAL_PATH` | Compilation stats (instruction counts) |
| `material errors MATERIAL_PATH` | Check for compilation errors |
| `material textures MATERIAL_PATH` | List referenced textures |
| `material analyze MATERIAL_PATH` | Auto-detect common issues |
| `material hlsl MATERIAL_PATH [--platform sm6] [--shader-type pixel]` | Get compiled HLSL shader code |

### Editing
| Command | Description |
|---------|-------------|
| `material add-node PATH --type CLASS [--pos-x X] [--pos-y Y]` | Add expression node |
| `material delete-node PATH --node NAME` | Delete expression node by name |
| `material connect PATH --from NODE --to NODE --to-input PIN` | Connect two nodes |
| `material disconnect PATH --from NODE --to NODE --to-input PIN` | Disconnect nodes |
| `material set-param PATH --name N --value V --type scalar\|vector\|texture` | Set parameter on MaterialInstance |
| `material recompile PATH` | Force shader recompilation |

### Material Editing Examples
```bash
# Add a Constant3Vector node
cli-anything-unreal --json material add-node /Game/M_Water \
    --type MaterialExpressionConstant3Vector --pos-x -200 --pos-y 0

# Connect it to BaseColor
cli-anything-unreal --json material connect /Game/M_Water \
    --from Constant3Vector_0 --to __material_output__ --to-input BaseColor

# Set a scalar parameter on a MaterialInstance
cli-anything-unreal --json material set-param /Game/MI_Water \
    --name Roughness --value 0.5 --type scalar

# Recompile after editing
cli-anything-unreal --json material recompile /Game/M_Water
```

**Connect to material output:** Use `--to __material_output__` with `--to-input` being the material property name: `BaseColor`, `Metallic`, `Roughness`, `Normal`, `Emissive`, `Opacity`, `WorldPositionOffset`, etc.

## blueprint — Blueprint Viewing & Editing

All blueprint commands require the editor to be running.

| Command | Description |
|---------|-------------|
| `blueprint list [--path /Game/]` | List all blueprints |
| `blueprint info BLUEPRINT_PATH` | Detailed info: graphs, nodes, variables |
| `blueprint add-function PATH --name FUNC_NAME` | Add a function graph |
| `blueprint remove-function PATH --name FUNC_NAME` | Remove a function graph |
| `blueprint add-variable PATH --name VAR --type TYPE` | Add a member variable |
| `blueprint remove-unused-variables PATH` | Remove all unused variables |
| `blueprint rename-graph PATH --old OLD --new NEW` | Rename a graph |
| `blueprint compile PATH` | Compile blueprint |

## screenshot — Screenshot & Comparison

All screenshot commands require the editor to be running.

| Command | Description |
|---------|-------------|
| `screenshot take [--filename NAME]` | Capture viewport screenshot |
| `screenshot compare FILE_A FILE_B` | Compare two screenshots |
| `screenshot compress FILE [--max-size N]` | Compress for Agent vision analysis |
| `screenshot cvar-test --cvar NAME --values V1,V2 [--labels L1,L2]` | A/B comparison with different CVar values |

## session — Undo/Redo

| Command | Description |
|---------|-------------|
| `session status` | Current session info |
| `session undo` | Undo last change |
| `session redo` | Redo last undone change |
| `session history` | Show undo history |
