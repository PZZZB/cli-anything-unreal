import os
import re

def replace_in_doc(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # screenshot
    content = content.replace('screenshot static', 'screenshot capture')
    content = content.replace('screenshot dynamic', 'screenshot capture-sequence')

    # project -> asset
    content = content.replace('project content', 'asset list')
    content = content.replace('project asset-exists', 'asset exists')
    content = content.replace('project asset-delete', 'asset delete')
    content = content.replace('project asset-refs', 'asset refs')
    content = content.replace('project asset-duplicate', 'asset duplicate')
    content = content.replace('project asset-rename', 'asset rename')
    content = content.replace('project asset-describe', 'asset info')
    
    # We must be careful with asset-property because it splits to get-property and set-property
    # In markdown docs, we can manually replace it with get-property | set-property
    # Example: project asset-property <path> <property> [--set <value>] -> asset get-property <path> <property> / asset set-property <path> <property> <value>
    content = content.replace('project asset-property', 'asset get-property / asset set-property')
    
    # scene
    content = content.replace('scene actors', 'scene list')
    content = content.replace('scene components', 'scene list-components')
    content = content.replace('scene describe', 'scene info')
    content = content.replace('scene material', 'scene get-material')
    content = content.replace('scene transform', 'scene get-transform')
    
    # scene property
    content = content.replace('scene property', 'scene get-property / scene set-property')

    # material
    content = content.replace('material stats', 'material get-stats')
    content = content.replace('material errors', 'material get-errors')
    content = content.replace('material textures', 'material list-textures')
    content = content.replace('material connections', 'material get-connections')
    content = content.replace('material hlsl', 'material dump-hlsl')
    
    # material set-param (should mention get-param too)
    # We'll just manually fix this since there isn't a direct conflict, just text replacement.

    # blueprint
    content = content.replace('blueprint remove-function', 'blueprint delete-function')
    content = content.replace('blueprint remove-unused-variables', 'blueprint delete-unused-variables')
    content = content.replace('bp remove-function', 'bp delete-function')
    content = content.replace('bp remove-unused-variables', 'bp delete-unused-variables')

    # Clean up awkward slashes caused by generic replacement
    content = content.replace('scene get-property / scene set-property <path> <prop> [--set <value>]', 'scene get-property <path> <prop> \\n scene set-property <path> <prop> <value>')
    content = content.replace('asset get-property / asset set-property <path> <property> [--set <value>]', 'asset get-property <path> <property> \\n asset set-property <path> <property> <value>')
    
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

docs = [
    r"F:\workspace\CLI-Anything\unreal\agent-harness\cli_anything\unreal\skills\SKILL.md",
    r"F:\workspace\CLI-Anything\unreal\agent-harness\cli_anything\unreal\skills\references\commands.md",
    r"F:\workspace\CLI-Anything\unreal\README.md"
]

for doc in docs:
    replace_in_doc(doc)

print("done")