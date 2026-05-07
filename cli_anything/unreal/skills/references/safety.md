# Safety Patterns & Destructive Operation Guards

Read this file before deleting assets, overwriting files, creating new `.uasset` assets, or performing any operation that modifies engine state irreversibly.

## Forbidden Patterns

These patterns were all observed in benchmark testing and caused catastrophic failures — file locks, data corruption, modal dialogs, or wasted agent turns.

| Forbidden | Use Instead | Why |
|-----------|-------------|-----|
| `rm /path/to/DLL` or `del *.dll` | `build compile` or `editor close` | DLL files are locked by the running editor; deleting them corrupts the build |
| `rm /path/to/Asset.uasset` | `asset delete --force` | Bypasses engine reference tracking; corrupts Content Browser cache |
| `sleep 60 && editor status` | `editor launch` | Blind polling wastes agent turns; `editor launch` blocks until the API is ready by default |
| `os.remove()` for .uasset in Python | `EditorAssetLibrary.delete_asset()` | Direct file deletion corrupts the engine's in-memory asset registry |
| `taskkill` / `kill` editor process | `editor close` | Unclean shutdown leaves lock files and corrupts saved state |
| Editing `.ini` config files directly | `project config set` | Manual edits may not be picked up; CLI ensures proper formatting |
| `LevelEditorSubsystem.new_level` or `save_current_level` in Python | `editor new-level` or `editor save-level` CLI | These UE5 APIs trigger engine teardown in the HTTP tick thread, causing a C++ Access Violation crash |

**General rule:** All UE operations go through CLI commands. Direct file manipulation bypasses engine locks and reference tracking, causing corruption.

## Modal Dialogs Block CLI Execution

Any modal dialog blocks CLI execution indefinitely — not just asset overwrite dialogs. The editor is waiting for a button click that will never come in a headless CLI environment.

**Common triggers and how to avoid them:**

| Trigger | Prevention |
|---------|------------|
| `new_level(path)` when level already exists | Delete + `collect_garbage()` first |
| `save_asset()` with dirty referencers | Use `--no-save` and handle saves explicitly |
| `import_asset()` with naming conflict | Delete existing + `collect_garbage()` first |
| `create_asset()` / `duplicate_asset()` when target exists | See "Asset Overwrite Avoidance" below |
| Any `unreal.EditorDialog` call | Never use in headless scripts |

## Asset Overwrite Avoidance

`create_asset` / `duplicate_asset` will pop a modal "Overwrite Existing Object" dialog if the target path already has an asset loaded in memory.

The fix: check for existing asset, delete it, then flush the old UObject from memory before creating:

```python
import unreal
EAL = unreal.EditorAssetLibrary
target = "/Game/MyAsset"
can_create = True
if EAL.does_asset_exist(target):
    if EAL.delete_asset(target):           # Returns True if fully deleted
        unreal.SystemLibrary.collect_garbage()  # Flush old UObject from memory
    else:
        can_create = False                 # Delete failed — do NOT create

if can_create:
    ATH = unreal.AssetToolsHelpers.get_asset_tools()
    new_asset = ATH.create_asset(...)
```

## Silent Failures — C++ Errors Without Python Exceptions

Some UE operations fail at the C++ level without raising a Python exception. If a script completes "successfully" but the result is wrong, check recent engine errors:

```bash
cli-anything-unreal editor run-script -c "import unreal; result = list(unreal.CliAnythingBridgeLibrary.get_recent_engine_errors(10))"
```

## Test Agent — Asset Validation Requirements

If you are a Test agent verifying assets after a Dev agent has created or modified them, simply checking if the `.uasset` file exists on disk is not enough — a corrupted file will still appear on disk.

**First step of any asset test:** Load the asset through the engine API:

```python
import unreal
path = "/Game/MyNewAsset"
asset = unreal.EditorAssetLibrary.load_asset(path)
if not asset:
    unreal.log_error(f"Asset at {path} exists on disk but FAILED to load. It may be corrupted.")
else:
    unreal.log(f"Successfully loaded asset: {asset.get_name()}")
```

If `load_asset` returns `None`, the test must fail, and the corruption should be reported back to the Dev agent.
