import unreal
EAL = unreal.EditorAssetLibrary
path = '/Game/M_BlackHole'
if EAL.does_asset_exist(path):
    ok = EAL.delete_asset(path)
    unreal.SystemLibrary.collect_garbage()
    result = {'deleted': ok, 'exists_after': EAL.does_asset_exist(path)}
else:
    result = {'exists': False}
