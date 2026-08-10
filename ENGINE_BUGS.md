# Known Engine Bugs

Known Unreal Engine bugs that affect `ue-cli` automation + Python APIs.

## UE 5.7

### 1. `DeleteAllMaterialExpressions` (Modify-While-Iterating Bug)

- **Module:** `EditorScriptingUtilities`
- **Location:** `Engine/Plugins/Editor/EditorScriptingUtilities/Source/EditorScriptingUtilities/Private/MaterialEditingLibrary.cpp`
- **Issue:** `UMaterialEditingLibrary::DeleteAllMaterialExpressions` iterates forward while removing expressions. Index shift skips nodes; one call deletes only half.
- **Workaround (Python):**
  ```python
  import unreal
  mel = unreal.MaterialEditingLibrary
  # Loop until no expressions remain
  while len(mat.get_editor_property("expressions")) > 0:
      mel.delete_all_material_expressions(mat)
  ```
- **Engine Fix (C++):** iterate copy:
  ```cpp
  TArray<TObjectPtr<UMaterialExpression>> ExpressionsCopy = Material->GetExpressions();
  for (UMaterialExpression* Expression : ExpressionsCopy)
  {
      DeleteMaterialExpression(Material, Expression);
  }
  ```

### 2. Do not force GC after deleting material expressions from Python

- **Module:** `PythonScriptPlugin` / `MaterialEditor`
- **Issue:** `delete_material_expression()` marks the expression UObject as
  garbage. A `collect_garbage()` call in the same injected Python workflow can
  crash the editor inside Python wrapper destruction, even after obvious local
  lists are cleared.
- **Workaround:** release local wrappers, return from the Python request, and
  let the editor collect later. Test fixtures should prefer a stable dedicated
  material instead of clearing its graph between tests:
  ```python
  expressions = [
      expression
      for expression in unreal.ObjectIterator(unreal.MaterialExpression)
      if expression.get_outer() == material
  ]
  for expression in expressions:
      unreal.MaterialEditingLibrary.delete_material_expression(material, expression)
  expression = None
  expressions.clear()
  # Do not call unreal.SystemLibrary.collect_garbage() here.
  ```

### 3. Python material graph UObject wrappers can crash later work

- **Modules:** `PythonScriptPlugin` / `MaterialEditor`
- **Issue:** On UE 5.7.4, repeated Python inspection and edit calls can retain
  `MaterialExpression` wrappers. A command may return success, then the editor
  crashes later in Python/MaterialEditor.
- **CLI behavior:** bridge 1.30 performs material graph reads and edits directly
  through Remote Control and C++. No material expression crosses into Python;
  mutations then save only the target asset.

### 4. `SetMaterialAttributes.AttributeSetTypes` direct writes can assert

- **Modules:** `Engine` / `PythonScriptPlugin`
- **Issue:** `UMaterialExpressionSetMaterialAttributes` stores attribute IDs in
  `AttributeSetTypes` and matching pins in `Inputs`. Writing only
  `attribute_set_types` through Python property reflection can leave those
  arrays out of sync. UE 5.5 and 5.7 then assert while updating cached material
  expression data (`Array index out of bounds: 1 into an array of size 1`).
- **CLI behavior:** bridge 1.32 makes `material connect --to-input <attribute>`
  call the native `CreateOrGetInputAttribute` path on UE 5.5+ before
  connecting. Earlier supported engines receive the equivalent paired-array
  mutation because they lack that engine helper. `material add-node --set`
  rejects direct `AttributeSetTypes` and `Inputs` writes with
  `MATERIAL_SET_ATTRIBUTES_UNSAFE_PROPERTY`.
- **Do not use:** `node.set_editor_property("attribute_set_types", [...])`.
  `editor run-script --no-save` disables autosave; it does not sandbox unsafe
  Unreal API calls.

### 5. `scene transform` (Remote Control API 400 Error)

- **Module:** `RemoteControl`
- **Issue:** raw Remote Control reads of intrinsic transform props (`RelativeLocation`, `RelativeRotation`) can return `400 Client Error` from reflection parsing.
- **Workaround (CLI):** `ue-cli` already routes transform reads through `editor run-script` + `actor.get_actor_transform()`. User/agent no action.
