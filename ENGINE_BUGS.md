# Known Engine Bugs

This document tracks known bugs in Unreal Engine that affect the CLI-Anything automation tools and their Python APIs.

## UE 5.7

### 1. `DeleteAllMaterialExpressions` (Modify-While-Iterating Bug)
- **Module:** `EditorScriptingUtilities`
- **Location:** `Engine/Plugins/Editor/EditorScriptingUtilities/Source/EditorScriptingUtilities/Private/MaterialEditingLibrary.cpp`
- **Issue:** The underlying C++ function `UMaterialEditingLibrary::DeleteAllMaterialExpressions` iterates forward through the material expressions array while removing items. This shifts array indices during the loop, causing it to skip elements and only delete exactly half of the nodes per call.
- **Workaround (Python):** 
  ```python
  import unreal
  mel = unreal.MaterialEditingLibrary
  # Loop until no expressions remain
  while len(mat.get_editor_property("expressions")) > 0:
      mel.delete_all_material_expressions(mat)
  ```
- **Engine Fix (C++):** Change the `for` loop in `DeleteAllMaterialExpressions` to iterate over a copy of the array:
  ```cpp
  TArray<TObjectPtr<UMaterialExpression>> ExpressionsCopy = Material->GetExpressions(); 
  for (UMaterialExpression* Expression : ExpressionsCopy) 
  { 
      DeleteMaterialExpression(Material, Expression); 
  }
  ```

### 2. `scene transform` (Remote Control API 400 Error)
- **Module:** `RemoteControl`
- **Issue:** Using the raw HTTP Remote Control API to directly read intrinsic transform properties like `RelativeLocation` or `RelativeRotation` on some actors causes the engine to return a `400 Client Error` due to reflection parsing issues.
- **Workaround (CLI):** `cli-anything-unreal` already handles this internally by using the `editor run-script` execution model to retrieve transforms via the Python API `actor.get_actor_transform()` instead of the raw property endpoints. No further action is required for users or agents.