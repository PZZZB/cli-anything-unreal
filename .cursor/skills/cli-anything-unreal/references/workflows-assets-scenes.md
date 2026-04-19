# Asset, Scene & Blueprint Workflows

## Universal Workflow: Query First, Then Set

All UE object operations follow the same progressive disclosure pattern:

```
1. Find the object      → scene list / asset list / material list (returns paths + class names)
2. Discover its API     → editor api-discover <path-or-class> (property/function names)
3. Drill into details   → editor api-discover <path-or-class> -d Prop1,Func2 (types, tooltips)
4. Read runtime values  → scene property / asset property
5. Modify values        → scene property Prop=Value / asset property Prop=Value
```

`api-discover` accepts a class name, asset path, or actor path — it auto-detects the type:

```bash
# Example: working with a DirectionalLight actor
cli-anything-unreal --json scene list                                            # 1. Find it (get actor path + class)
cli-anything-unreal --json editor api-discover /Temp/L.L:PersistentLevel.Light_0 # 2. Overview from actor path
cli-anything-unreal --json editor api-discover DirectionalLight -d bHidden       # 3. Detail (class name also works)
cli-anything-unreal --json scene property <actor_path> Intensity                 # 4. Read value
cli-anything-unreal --json scene property <actor_path> Intensity=5.0             # 5. Modify

# Example: working with a material asset
cli-anything-unreal --json asset list --class Material                           # 1. Find it
cli-anything-unreal --json editor api-discover /Game/Materials/M_Water           # 2. Overview from asset path
cli-anything-unreal --json editor api-discover /Game/Materials/M_Water -d BlendMode  # 3. Detail
```

## Asset Manipulation

```bash
# Discover asset class and properties (auto-detects class from asset path)
cli-anything-unreal --json editor api-discover /Game/MyAsset
cli-anything-unreal --json editor api-discover /Game/MyAsset -d BlendMode,ShadingModel

# Or use class name directly if you already know it
cli-anything-unreal --json editor api-discover Material -d BlendMode,ShadingModel

# Get/Set property values
cli-anything-unreal --json asset property /Game/MyAsset BlendMode
cli-anything-unreal --json asset property /Game/MyAsset BlendMode=Translucent

# Rename and duplicate
cli-anything-unreal --json asset rename /Game/Old /Game/New
cli-anything-unreal --json asset duplicate /Game/Old /Game/New --force

# Check references before deleting (avoids breaking other assets)
cli-anything-unreal --json asset refs /Game/MyAsset
cli-anything-unreal --json asset delete /Game/MyAsset
```

### Asset Deletion — Safe Workflow

`asset delete` checks references before deleting, avoiding modal dialogs:

```bash
# 1. Check what references the asset
cli-anything-unreal --json asset refs /Game/M_Old
# → {"asset": "/Game/M_Old", "referencers": ["/Game/Maps/Level1"], "count": 1}

# 2. Delete without --force — blocked because of references
cli-anything-unreal --json asset delete /Game/M_Old
# → {"status": "has_references", "deleted": false, "hint": "Use --force to delete anyway"}

# 3. Force delete (referencers will have broken references)
cli-anything-unreal --json asset delete /Game/M_Old --force
# → {"status": "ok", "deleted": true, "had_references": true}
```

`asset duplicate --force` pre-deletes the destination before duplicating, avoiding the "overwrite?" dialog entirely.

## Scene Manipulation

```bash
# Discover actor class and properties (auto-detects class from actor path)
cli-anything-unreal --json editor api-discover <actor_path>
cli-anything-unreal --json editor api-discover <actor_path> -d Intensity,bVisible

# Search actors by name
cli-anything-unreal --json scene list -q "DirectionalLight"

# Get/Set property
cli-anything-unreal --json scene property <actor_path> Intensity
cli-anything-unreal --json scene property <actor_path> Intensity=5.0

# Check transform
cli-anything-unreal --json scene get-transform <actor_path>

# List components
cli-anything-unreal --json scene list-components <actor_path>

# Find which material an actor uses
cli-anything-unreal --json scene get-material <actor_path>
```

## Blueprint Editing

```bash
# 1. Find the blueprint
cli-anything-unreal --json blueprint list --path /Game/Blueprints/

# 2. Inspect current state (graphs, nodes, variables)
cli-anything-unreal --json blueprint info /Game/BP_Enemy

# 3. Add a variable
cli-anything-unreal --json blueprint add-variable /Game/BP_Enemy --name Health --type Float

# 4. Add a function
cli-anything-unreal --json blueprint add-function /Game/BP_Enemy --name TakeDamage

# 5. Clean up unused variables
cli-anything-unreal --json blueprint delete-unused-variables /Game/BP_Enemy

# 6. Compile and verify
cli-anything-unreal --json blueprint compile /Game/BP_Enemy
```

## Level Management

```bash
# Create and open a new level
cli-anything-unreal --json editor new-level /Game/Maps/NewLevel

# Save the current level
cli-anything-unreal --json editor save-level
```

If the level path already exists, the command refuses to avoid modal dialogs — use `asset delete` first or pick a different path.

**Known limitation:** If Python-based commands (scene list, api-discover with actor paths, run-script, etc.) were executed in this session, `new-level` may crash the editor due to a UE PythonScriptPlugin bug (retained UObject references cause `World Memory Leaks` assert). Workaround: relaunch the editor with `editor launch` before creating a new level, or create levels early before running queries.
