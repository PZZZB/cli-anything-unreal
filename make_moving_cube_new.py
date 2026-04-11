"""
make_moving_cube_new.py
Creates a physically-simulated cube at (0,0,100) and saves the level as /Game/TestBlind_New.
Run via: cli-anything-unreal --json editor run-script make_moving_cube_new.py
"""

import unreal

EAL = unreal.EditorAssetLibrary
ELL = unreal.EditorLevelLibrary
EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
ELS = unreal.EditorLoadingAndSavingUtils

target_level_path = "/Game/TestBlind_New"

# Step 1: Spawn a StaticMeshActor at (0, 0, 100)
cube_mesh_path = "/Engine/BasicShapes/Cube.Cube"
location = unreal.Vector(0.0, 0.0, 100.0)
rotation = unreal.Rotator(0.0, 0.0, 0.0)

actor = EAS.spawn_actor_from_class(
    unreal.StaticMeshActor,
    location,
    rotation
)

if not actor:
    result = {"error": "Failed to spawn StaticMeshActor"}
    result

# Step 2: Set the StaticMesh to Cube
comp = actor.get_components_by_class(unreal.StaticMeshComponent)[0]
cube_mesh = EAL.load_asset(cube_mesh_path)
comp.set_static_mesh(cube_mesh)

# Step 3: Enable physics simulation
# Must set mobility to MOVABLE first — physics won't work on STATIC actors
comp.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)

# Set simulate_physics via body_instance
body_instance = comp.get_editor_property("body_instance")
body_instance.set_editor_property("simulate_physics", True)
comp.set_editor_property("body_instance", body_instance)

# Verify physics settings
body_instance_check = comp.get_editor_property("body_instance")
sim_phys = body_instance_check.get_editor_property("simulate_physics")
mobility = comp.get_editor_property("mobility")

# Step 4: Save the current level as /Game/TestBlind_New
# Use the deprecated but working get_editor_world — LevelEditorSubsystem.get_world() returns None
world = ELL.get_editor_world()
save_success = ELS.save_map(world, target_level_path)

# Verify the asset was saved
asset_exists = EAL.does_asset_exist(target_level_path)

result = {
    "actor_name": actor.get_name(),
    "mesh_set": comp.static_mesh.get_path_name() if comp.static_mesh else "None",
    "mobility": str(mobility),
    "simulate_physics": str(sim_phys),
    "level_saved_to": target_level_path,
    "save_success": save_success,
    "asset_exists_after_save": asset_exists,
}
