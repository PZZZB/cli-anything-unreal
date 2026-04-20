# Material Editing & Shader Workflows

## AI Progressive Material Editing Workflow

When editing a material, follow this progressive workflow to avoid context overflow and work in your comfort zone (HLSL).

### 1. Locate or Create

Find an existing material or create a new one:
```bash
cli-anything-unreal --json material list --path /Game/Materials/
# Or create via Python script:
cli-anything-unreal --json editor run-script create_mat.py
```

### 2. Inspect Properties & Topology

Check material outputs and node connection graph before editing:
```bash
# Full info: nodes, parameters, textures, connections, Custom node code
cli-anything-unreal --json material info /Game/M_Water

# Lightweight connection graph with orphan detection
cli-anything-unreal --json material get-graph /Game/M_Water
```

### 3. HLSL Custom Node (Preferred Approach)

The visual node graph is difficult for AI to manipulate. Writing HLSL in a Custom node is easier and more robust:

```bash
# Add a Custom node with HLSL from a file
cli-anything-unreal --json material add-node /Game/M_Water \
    --type MaterialExpressionCustom --code-file my_shader.hlsl

# Connect to an output pin
cli-anything-unreal --json material connect /Game/M_Water \
    --from MaterialExpressionCustom_0 --to __material_output__ --to-input BaseColor

# Recompile → {"status":"ok"} or {"status":"error","compile_errors":[...]}
cli-anything-unreal --json material recompile /Game/M_Water
```

To update HLSL code on an existing Custom node, use `editor run-script`:
```python
import unreal
mat = unreal.load_asset("/Game/M_Water")
node = unreal.MaterialEditingLibrary.get_material_property_input_node(
    mat, unreal.MaterialProperty.MP_BASE_COLOR)
if node:
    with open("my_shader.hlsl") as f:
        node.set_editor_property("code", f.read())
```

Then recompile and verify via CLI (do NOT use `MEL.recompile_material()` — it's void and cannot detect failures):
```bash
cli-anything-unreal --json material recompile /Game/M_Water
```

### 4. Alternative: Standard Nodes

For simpler changes, use standard expression nodes:

```bash
# Add a Constant3Vector node
cli-anything-unreal --json material add-node /Game/M_Water \
    --type MaterialExpressionConstant3Vector --pos-x -200 --pos-y 0

# Connect to BaseColor
cli-anything-unreal --json material connect /Game/M_Water \
    --from Constant3Vector_0 --to __material_output__ --to-input BaseColor

# Set a scalar parameter on a MaterialInstance
cli-anything-unreal --json material set-param /Game/MI_Water \
    --name Roughness --value 0.5 --type scalar

# Recompile → check status field
cli-anything-unreal --json material recompile /Game/M_Water
```

**Connect to material output:** Use `--to __material_output__` with `--to-input` being the material property name: `BaseColor`, `Metallic`, `Roughness`, `Normal`, `Emissive`, `Opacity`, `WorldPositionOffset`, etc.

### 5. Setting Node Properties

Per the "Query First, Then Set" core principle, always use `editor api-discover` to check the node's property types before setting them:

```bash
# Step 1: Discover what properties the node type has
cli-anything-unreal --json editor api-discover unreal.MaterialExpressionConstant3Vector
# → Shows: constant (LinearColor), desc (str), etc.

# Step 2: Use editor run-script with the correct type
```

**For simple properties (int, float, str, enum)** on newly added nodes, `add-node --set` works:
```bash
cli-anything-unreal --json material add-node /Game/M \
    --type MaterialExpressionPanner --set speed_x=0.15
```

**For any property on an existing node**, use `editor run-script` with `get_material_property_input_node`:
```python
import unreal
mat = unreal.load_asset("/Game/M_Water")
node = unreal.MaterialEditingLibrary.get_material_property_input_node(
    mat, unreal.MaterialProperty.MP_BASE_COLOR)
if node:
    node.set_editor_property("constant", unreal.LinearColor(0.9, 0.3, 0.1, 1.0))
```

**When creating a node with complex properties**, combine creation + setting in one script:
```python
import unreal
mat = unreal.load_asset("/Game/M_Water")
expr = unreal.MaterialEditingLibrary.create_material_expression(
    mat, unreal.MaterialExpressionConstant3Vector, -200, 0)
expr.set_editor_property("constant", unreal.LinearColor(0.2, 0.5, 0.8, 1.0))
unreal.MaterialEditingLibrary.connect_material_property(
    expr, "", unreal.MaterialProperty.MP_BASE_COLOR)
```

**Progressive Node Discovery:** There are 400+ `MaterialExpression` classes — do not try to list them all. Use a targeted Python search:
```python
import unreal
# Search for nodes related to "Noise"
print([cls for cls in dir(unreal) if "Noise" in cls and cls.startswith("MaterialExpression")])
```
Then use `editor api-discover unreal.MaterialExpressionNoise` to see the node's properties before setting them.

## HLSL / Shader Source Discovery

When writing Custom HLSL for UE5 materials, you need to know what cbuffer/struct resources are available (`cbuffer View`, `FPrimitiveConstants`, `FMaterialPixelParameters`, etc.). These vary by engine version and material configuration.

**Two complementary commands:**

### `material hlsl-code` — Lightweight, No Recompile
Returns `/Engine/Generated/Material.ush` with `FMaterialPixelParameters` and material-specific structs. Does not include `cbuffer View`.

```bash
cli-anything-unreal --json material hlsl-code /Game/M_Custom
# → {"source": "plugin", "lines": 5250, "file": "F:/Project/Saved/CliAnything/M_Custom.ush"}
```

### `material shader-source` — Full Source with cbuffers
Triggers synchronous recompile, returns all compiled `.usf` files with complete cbuffer/struct definitions including `cbuffer View`, `FPrimitiveConstants`, etc.

```bash
cli-anything-unreal --json material shader-source /Game/M_Custom
# → {"source": "plugin", "shader_count": 12, "shaders": [...], "output_dir": "..."}
```

### Typical Shader Development Workflow

```bash
# 1. Get lightweight HLSL context (fast)
cli-anything-unreal --json material hlsl-code /Game/M_Custom

# 2. Get full shader source with cbuffers (triggers recompile)
cli-anything-unreal --json material shader-source /Game/M_Custom

# 3. Read shader files to discover available resources (cbuffer View members, etc.)

# 4. Write Custom HLSL code using discovered resources

# 5. Recompile and verify
cli-anything-unreal --json material recompile /Game/M_Custom
```

## Actor → Material → Shader Investigation

When you need to trace from a visible actor back to its shader code:

```bash
cli-anything-unreal --json scene list -q "MyActor"
cli-anything-unreal --json scene get-material "<actor_path>"
cli-anything-unreal --json material info /Game/SomeMaterial
cli-anything-unreal --json material hlsl-code /Game/SomeMaterial
```

## Diagnostics

To check an existing material for compile errors or common issues:
```bash
cli-anything-unreal --json material get-errors /Game/M_Water
cli-anything-unreal --json material analyze /Game/M_Water
```

Full command reference: see `commands.md` → `material` section.

## Material-Specific Notes

- **`MEL.recompile_material()` is void** — cannot detect compile failures. Always verify with CLI `material recompile` (`{"status":"ok"}` or `{"status":"error","compile_errors":[...]}`) or `material get-errors` (checks without recompiling). Never assume success just because no exception was raised.
- `Material.expressions` is protected in UE5.7+ — use `material info` to read nodes, and CLI commands (`add-node`, `connect`, `delete-node`) to edit them. Do not access `expressions` directly in Python.
- To find existing nodes for property modification, use `MaterialEditingLibrary.get_material_property_input_node()` — do not try `find_object` (unreliable) or access `expressions` (protected).
- `material shader-source` always recompiles synchronously to guarantee the latest source. It may take a moment for complex materials.
