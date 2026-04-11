import unreal

actor_path = '/Game/NewMap.NewMap:PersistentLevel.PostProcessVolume_0'

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = eas.get_all_level_actors()
target = None
for a in actors:
    if a.get_name() == 'PostProcessVolume_0':
        target = a
        break

result = {}
if target:
    # Try using the remote object describe API via Python
    # Or use unreal.SystemLibrary / EditorDialog approaches

    # Approach: Use the Remote Control API to describe the object
    # The /remote/object/describe endpoint returns property metadata including tooltips

    # Let's try using unreal.ReflectionHelpers or similar
    # Check if there's a way to get metadata from the class

    # Try to find Priority and BlendRadius in the class hierarchy
    # using get_class and iterating

    cls = target.get_class()
    class_name = cls.get_name()
    result['class_name'] = class_name

    # Check super classes
    supers = []
    current = cls
    while current:
        supers.append(current.get_name())
        current = current.get_super_class() if hasattr(current, 'get_super_class') else None
    result['class_hierarchy'] = supers

    # Check if we can access C++ property metadata through any API
    # Try the describe function via remote control
    import json
    import urllib.request

    # Use the remote control API directly
    url = "http://localhost:30010/remote/object/describe"
    payload = {
        "objectPath": actor_path
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), method='PUT',
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            # Find Priority and BlendRadius in the description
            result['describe_keys'] = list(data.keys()) if isinstance(data, dict) else type(data).__name__
    except Exception as e:
        result['describe_error'] = str(e)
else:
    result['error'] = 'Actor not found'
