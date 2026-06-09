# Asset, Scene & Blueprint Workflows

## Universal Workflow: Query First, Then Set

All UE object ops use progressive disclosure, same as editor UI:

```
1. Find the object     -> scene list / asset list / material list (returns paths + class names)
2. Discover its API    -> editor api-discover <path-or-class> (property/function names)
3. Drill into details  -> editor api-discover <path-or-class> -d Prop1,Func2 (types, tooltips)
4. Read runtime values -> scene property / asset property
5. Modify values       -> scene property Prop=Value / asset property Prop=Value
```

`api-discover` accepts class name, asset path, actor path, or **component subobject path**. It auto-detects type.

## Scene Workflow: Actor -> Component -> Property

Commands map 1:1 to Actor -> Component -> field. Lights/cameras/many built-ins store functional props on native components, not actor. Check component tree first.

```bash
# 1. Find actor
ue-cli scene list --class DirectionalLight

# 2. api-discover <actor> - returns components tree (matches Details panel)
ue-cli editor api-discover ".../DirectionalLight_0"
# -> components: [{ path: ".../DirectionalLight_0.LightComponent0",
#                  class: "DirectionalLightComponent", is_root: true }]

# 3. api-discover <component.path> - drill into it
ue-cli editor api-discover ".../DirectionalLight_0.LightComponent0" -d Intensity

# 4. scene property - accepts actor OR component path
ue-cli scene property ".../DirectionalLight_0.LightComponent0" Intensity=50.0
```

Editor-only visualizers (gizmos/billboards) filtered by default to match Details panel.

## Asset Manipulation

```bash
# Discover asset class and properties (auto-detects class from asset path)
ue-cli editor api-discover /Game/MyAsset
ue-cli editor api-discover /Game/MyAsset -d BlendMode,ShadingModel

# Or use class name directly if you already know it
ue-cli editor api-discover Material -d BlendMode,ShadingModel

# Get/Set property values
ue-cli asset property /Game/MyAsset BlendMode
ue-cli asset property /Game/MyAsset BlendMode=Translucent

# Rename and duplicate
ue-cli asset rename /Game/Old /Game/New
ue-cli asset duplicate /Game/Old /Game/New --force
```

See [Asset Deletion - Safe Workflow](#asset-deletion--safe-workflow) for reference checks.

`asset delete` checks references before deleting, avoiding modals:

```bash
# 1. Check what references the asset
ue-cli asset refs /Game/M_Old
# -> {"asset": "/Game/M_Old", "referencers": ["/Game/Maps/Level1"], "count": 1}

# 2. Delete without --force - blocked because of references
ue-cli asset delete /Game/M_Old
# -> {"status": "has_references", "deleted": false, "hint": "Use --force to delete anyway"}

# 3. Force delete (referencers will have broken references)
ue-cli asset delete /Game/M_Old --force
# -> {"status": "ok", "deleted": true, "had_references": true}
```

`asset duplicate --force` pre-deletes destination, avoiding overwrite dialog.

## Scene Manipulation

```bash
# Discover actor class and properties (auto-detects class from actor path)
ue-cli editor api-discover <actor_path>
ue-cli editor api-discover <actor_path> -d Intensity,bVisible

# Search actors by UObject name, World Outliner label, or path
ue-cli scene list -q "DirectionalLight"
ue-cli scene list -q "SM_Env_FmlBush17" --field label
ue-cli scene list -q "StaticMeshActor_27" --field name --exact

# Get/Set property
ue-cli scene property <actor_path> Intensity
ue-cli scene property <actor_path> Intensity=5.0

# Check transform
ue-cli scene get-transform <actor_path>

# List components
ue-cli scene list-components <actor_path>

# Find which material an actor uses
ue-cli scene get-material <actor_path>
```

## Blueprint Editing

```bash
# 1. Find the blueprint
ue-cli blueprint list --path /Game/Blueprints/

# 2. Inspect current state (graphs, nodes, variables)
ue-cli blueprint info /Game/BP_Enemy

# 3. Add a variable
ue-cli blueprint add-variable /Game/BP_Enemy --name Health --type float

# 4. Add a function
ue-cli blueprint add-function /Game/BP_Enemy --name TakeDamage

# 5. Clean up unused variables
ue-cli blueprint delete-unused-variables /Game/BP_Enemy

# 6. Compile and verify
ue-cli blueprint compile /Game/BP_Enemy
```

## Operations Without Dedicated Subcommands

For adding Blueprint components, spawning actors, setting component defaults, etc., use `editor run-script`. Do not hunt for absent subcommands.

**Add a component to a Blueprint:**
```python
import unreal

bp_path = "/Game/Blueprints/BP_Enemy"
bp = unreal.load_asset(bp_path)
subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)

# Gather existing subobject handles - first one is the root
handles = subsystem.k2_gather_subobject_data_for_blueprint(bp)

# Add a StaticMeshComponent under the root
params = unreal.AddNewSubobjectParams()
params.parent_handle = handles[0]
params.new_class = unreal.StaticMeshComponent
params.blueprint_context = bp
new_handle, fail_reason = subsystem.add_new_subobject(params)

# Compile so the CDO picks up the new component
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
unreal.EditorAssetLibrary.save_asset(bp_path)
result = {"status": "ok", "component": "StaticMeshComponent"}
```

**Spawn an actor in the current level:**
```python
import unreal

actor_class = unreal.StaticMeshActor
location = unreal.Vector(0, 0, 100)
rotation = unreal.Rotator(0, 0, 0)

actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
    actor_class, location, rotation
)
actor.set_actor_label("MyNewActor")

result = {"status": "ok", "actor": actor.get_path_name()}
```

## Level Management

```bash
# Create and open a new level
ue-cli editor new-level /Game/Maps/NewLevel

# Save the current level
ue-cli editor save-level
```

Existing level path -> command refuses to avoid modal. Use `asset delete` first or choose different path.

**Known limitation:** after Python-based commands in same session (`scene list`, actor-path `api-discover`, `run-script`), `new-level` may crash editor due UE PythonScriptPlugin retained UObject refs (`World Memory Leaks` assert). Workaround: relaunch editor before creating level, or create levels early.
