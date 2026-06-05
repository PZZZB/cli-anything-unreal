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

### 2. `scene transform` (Remote Control API 400 Error)

- **Module:** `RemoteControl`
- **Issue:** raw Remote Control reads of intrinsic transform props (`RelativeLocation`, `RelativeRotation`) can return `400 Client Error` from reflection parsing.
- **Workaround (CLI):** `ue-cli` already routes transform reads through `editor run-script` + `actor.get_actor_transform()`. User/agent no action.
