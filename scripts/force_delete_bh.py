import unreal
EAL = unreal.EditorAssetLibrary
path = '/Game/M_BlackHole'

# Try to force delete using different approaches
asset = EAL.load_asset(path)
result = {"loaded": asset is not None}

if asset:
    # Try delete_loaded_asset
    try:
        EAL.delete_loaded_asset(asset)
        unreal.SystemLibrary.collect_garbage()
        result["delete_loaded"] = True
    except Exception as e:
        result["delete_loaded_error"] = str(e)
    
    # Check if still exists
    result["exists_after_loaded_delete"] = EAL.does_asset_exist(path)
    
    if EAL.does_asset_exist(path):
        # Try saving all packages first then deleting
        try:
            unreal.EditorLoadingAndSavingUtils.save_packages([asset.get_outer()], only_dirty=False)
            EAL.delete_asset(path)
            unreal.SystemLibrary.collect_garbage()
            result["delete_after_save"] = True
        except Exception as e:
            result["delete_after_save_error"] = str(e)
        
        result["exists_final"] = EAL.does_asset_exist(path)

if not EAL.does_asset_exist(path):
    result["final_status"] = "deleted"
else:
    result["final_status"] = "still_exists"
