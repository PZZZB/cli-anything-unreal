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

### 3. Material disconnect through Python/bridge can corrupt later edits

- **Modules:** `PythonScriptPlugin` / `MaterialEditor`
- **Issue:** On UE 5.7.4, disconnecting either a material output or an
  expression input through the injected Python/bridge path can return success,
  save the asset, and then crash inside Python/MaterialEditor during a later
  material edit.
- **CLI safety behavior:** bridge 1.27 refuses these two disconnect operations
  before mutation and returns `MATERIAL_DISCONNECT_UNSAFE_ENGINE`. Use the
  Material Editor UI, or an engine version where this workflow has been
  validated.

### 4. `scene transform` (Remote Control API 400 Error)

- **Module:** `RemoteControl`
- **Issue:** raw Remote Control reads of intrinsic transform props (`RelativeLocation`, `RelativeRotation`) can return `400 Client Error` from reflection parsing.
- **Workaround (CLI):** `ue-cli` already routes transform reads through `editor run-script` + `actor.get_actor_transform()`. User/agent no action.
