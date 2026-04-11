import os

def replace_in_file(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # screenshot
    content = content.replace('"screenshot", "static"', '"screenshot", "capture"')
    content = content.replace('"screenshot", "dynamic"', '"screenshot", "capture-sequence"')

    # project -> asset
    content = content.replace('"project", "content"', '"asset", "list"')
    content = content.replace('"project", "asset-exists"', '"asset", "exists"')
    content = content.replace('"project", "asset-delete"', '"asset", "delete"')
    content = content.replace('"project", "asset-refs"', '"asset", "refs"')
    content = content.replace('"project", "asset-duplicate"', '"asset", "duplicate"')
    content = content.replace('"project", "asset-rename"', '"asset", "rename"')
    content = content.replace('"project", "asset-describe"', '"asset", "info"')

    # Fix asset-property (split into get/set). If there's a --set flag, it's set-property, else get-property.
    # In tests, they might be written as `["project", "asset-property", "Asset", "Prop"]` vs `["project", "asset-property", "Asset", "Prop", "--set", "Val"]`
    content = content.replace('"project", "asset-property",\n                "/Game/Map:Actor_0", "bHidden", "--set", "True"', '"asset", "set-property",\n                "/Game/Map:Actor_0", "bHidden", "True"')
    # Just in case the above doesn't catch it:
    content = content.replace('"project", "asset-property"', '"asset", "get-property"')
    
    # scene
    content = content.replace('"scene", "actors"', '"scene", "list"')
    content = content.replace('"scene", "components"', '"scene", "list-components"')
    content = content.replace('"scene", "describe"', '"scene", "info"')
    content = content.replace('"scene", "material"', '"scene", "get-material"')
    content = content.replace('"scene", "transform"', '"scene", "get-transform"')
    
    # Scene property: if it has "--set", we replace it differently
    content = content.replace('"scene", "property",\n                "/Game/Map:Actor_0", "bHidden", "--set", "True"', '"scene", "set-property",\n                "/Game/Map:Actor_0", "bHidden", "True"')
    content = content.replace('"scene", "property",\n                "/Game/Map:Actor_0", "RelativeLocation", "--set"', '"scene", "set-property",\n                "/Game/Map:Actor_0", "RelativeLocation"')
    content = content.replace('"scene", "property"', '"scene", "get-property"')

    # material
    content = content.replace('"material", "stats"', '"material", "get-stats"')
    content = content.replace('"material", "errors"', '"material", "get-errors"')
    content = content.replace('"material", "textures"', '"material", "list-textures"')
    content = content.replace('"material", "connections"', '"material", "get-connections"')
    content = content.replace('"material", "hlsl"', '"material", "dump-hlsl"')

    # blueprint
    content = content.replace('"blueprint", "remove-function"', '"blueprint", "delete-function"')
    content = content.replace('"blueprint", "remove-unused-variables"', '"blueprint", "delete-unused-variables"')
    
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


test_dir = r"F:\workspace\CLI-Anything\unreal\agent-harness\cli_anything\unreal\tests"
for file in os.listdir(test_dir):
    if file.endswith(".py"):
        replace_in_file(os.path.join(test_dir, file))

print("done")
