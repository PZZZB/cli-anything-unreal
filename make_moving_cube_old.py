import unreal

EAL = unreal.EditorAssetLibrary
ELL = unreal.EditorLevelLibrary
SL = unreal.SystemLibrary

MAP_PATH = "/Game/TestBlind_Old"

# Step 1: Clean up any existing asset at the target path to avoid overwrite dialog
can_create = True
if EAL.does_asset_exist(MAP_PATH):
    if EAL.delete_asset(MAP_PATH):
        SL.collect_garbage()
    else:
        can_create = False
        unreal.log_error(f"Failed to delete existing asset at {MAP_PATH}")

# Step 2: Create a new level
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
if can_create:
    les.new_level(MAP_PATH)
    unreal.log(f"Created new level: {MAP_PATH}")

# Step 3: Spawn the cube actor at (0, 0, 100)
cube_actor = ELL.spawn_actor_from_class(
    unreal.StaticMeshActor,
    unreal.Vector(0, 0, 100),
    unreal.Rotator(0, 0, 0)
)
unreal.log("Spawned StaticMeshActor")

# Step 4: Set the StaticMesh to Cube
smc = cube_actor.get_components_by_class(unreal.StaticMeshComponent)[0]
cube_mesh = unreal.load_asset("/Engine/BasicShapes/Cube")
if cube_mesh:
    smc.set_static_mesh(cube_mesh)
    unreal.log("Set StaticMesh to Cube")

# Step 5: Enable physics simulation
smc.set_mobility(unreal.ComponentMobility.MOVABLE)
smc.set_simulate_physics(True)
unreal.log("Enabled physics simulation")

# Step 6: Verify location
loc = cube_actor.get_actor_location()
unreal.log(f"Actor location: ({loc.x}, {loc.y}, {loc.z})")

# Step 7: Save the current level
save_ok = les.save_current_level()
if save_ok:
    unreal.log(f"Successfully saved level to {MAP_PATH}")
else:
    unreal.log_error(f"Failed to save level")

result = {
    "cube_actor": cube_actor.get_name(),
    "mesh": smc.static_mesh.get_name() if smc.static_mesh else "None",
    "simulates_physics": smc.is_simulating_physics(),
    "mobility": str(smc.mobility),
    "location": {
        "x": loc.x,
        "y": loc.y,
        "z": loc.z
    },
    "level_saved": save_ok,
    "saved_to": MAP_PATH
}
