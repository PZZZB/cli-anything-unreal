# Editor Lifecycle & Python Scripting

## Editor Lifecycle - Required Flow

When editor needed, follow exact sequence:

```
Step 1: editor status
  Matching instance online? Proceed to your task.
  No matching online instance? Continue to Step 2.

Step 2: preflight (or editor preflight)
  Ready? editor launch
  BuildId mismatch? Continue to Step 3.

Step 3: editor close (if running) -> build compile -> editor launch
  This is the ONLY correct way to fix module version mismatches.

Step 4: editor status (verify)
  Matching instance online? Proceed.
  `launching`/`unreachable`? Poll the reported status command and wait.
  Still `offline` after the stale grace? Report the error to the user.
```

Key points:
- `preflight` (`editor preflight` also works) verifies Remote Control config and enables the `RemoteControl` plugin only when loadable module binaries exist. UE4/custom engines with source-only RemoteControl are reported as unavailable and are not modified.
- `editor launch` waits until API online or timeout. Without `--timeout`, foreground wait is bounded; slow launches return `launching` with a task id instead of hanging until the shell kills ue-cli. Do not use `sleep`.
- Async: `--no-wait`, then `editor status <task_id>` or `task status <task_id>`.
- DLL locked build fail -> `editor close`, then compile. If `editor plugin-upgrade` reports `LNK1104` with `locked_file`, close/kill all UnrealEditor processes for that project and retry the reported command. `plugin-upgrade` waits for matching editor processes to exit before compiling, but another stale process can still hold third-party plugin DLLs.
- `build compile --platform Win64` fails fast with `EDITOR_RUNNING_LOCKS_DLLS` when the same project editor is running. This avoids wasting minutes before UBT reaches a locked `UnrealEditor-*.dll` link step.
- CliAnythingBridge missing/stale module -> keep plugin enabled; `editor launch` deploys/enables it and precompiles before starting UE. Do not disable it to bypass startup.
- Do not create or load maps at module top level inside `editor run-script` with `EditorLoadingAndSavingUtils.new_blank_map` or `load_map`; ue-cli blocks these known-crashy world teardown paths. Reusable helper functions may contain offline/commandlet map-load branches as long as they are not called at top level. Use `editor new-level /Game/Path/Level` or `editor open-level /Game/Path/Level`, then run a separate actor/content setup script, then `editor save-level`. `editor launch --map` and `editor open-level` inputs must include their Unreal mount root (`/Game/...`); bare names are ambiguous and rejected. Level commands verify the active editor world after transition and try to recover if the HTTP bridge resets.
- User says editor running -> still verify with Step 1.
- `unreachable` means the editor process is alive but Remote Control may be busy during PIE/loading/startup. Retry the reported `editor status` command; do not relaunch or kill yet.
- `launching` means an active `editor.launch` task owns the process. Poll `editor status <task_id>`.
- `offline` with `next_command` means the process stayed unreachable past the stale grace or has a clearer failure; use its `next_command`.
- `editor launch` kills zombie `UnrealEditor.exe` (no API). API-alive `ALREADY_RUNNING` blocks.

### Example

```bash
# 1. Preflight - catches build mismatches before they cause hangs
ue-cli --project F:\MyGame\MyGame.uproject preflight

# 2. If BuildId mismatch, compile first
ue-cli --project F:\MyGame\MyGame.uproject build compile

# 3. Launch editor (blocks until ready)
ue-cli --project F:\MyGame\MyGame.uproject editor launch --map /Game/Maps/MyMap

# 4. Verify
ue-cli editor status
```

### Async Launch

```bash
# Async (returns immediately, poll for progress)
ue-cli editor launch --no-wait
# -> {"task_id": "t-abc123", "status": "submitted", "suggested_poll_interval_seconds": 5}

# Check launch progress
ue-cli editor status <task_id>
# Or use generic task commands:
ue-cli task status <task_id>
ue-cli task cancel <task_id>
```

### Status Values

`editor status` without task id returns result array. Each item has:
- `status`: `online` if Remote Control reachable; `launching` when an active launch task owns an unreachable process; `unreachable` for temporary Remote Control loss while the process is alive; `offline` only after stale grace or clear failure
- `pid`: UnrealEditor pid
- `port`: Remote Control port
- `project_path`: uproject path
- `bridge_version` / `bundled_version` / `plugin_match`: online bridge plugin health. `plugin_match` can be `null` if the version probe timed out or the editor is busy.
- `message` / `suggestion` / `next_command`: recovery hints. For `unreachable`, retry status; for `launching`, poll the task; for stale `offline`, relaunch/close guidance may be provided; for online bridge mismatches, run plugin-upgrade when shown

With top-level `--project`, `editor status` filters to that project by default. Use `editor status --all` only when you need to inspect editors for other projects too.

If an online item has `plugin_match: false` and `next_command`, run it (`editor plugin-upgrade`). Do not force recompile before every launch; `editor launch` deploys bridge source and recompiles only when plugin load failure requires it.

`editor status <task_id>` returns async task progress.

## Close

```bash
ue-cli editor close
```

`editor close` does not report `closed` only because the Remote Control API stopped responding. On Windows it also waits for matching same-project `UnrealEditor.exe` processes to exit, and terminates a stale lock holder when needed so immediate `build compile` does not hit locked editor/plugin DLLs.

## Python Scripting Patterns

Use `editor run-script` when no CLI command covers operation. Use `-c` only for short one-liners; for multiline Python, especially in PowerShell, pipe code to `editor run-script -` or pass a `.py` file so shell argv splitting cannot corrupt code or indentation.

### Result Convention

Set `result` dict to return structured data. Missing -> `{"status": "ok"}`. Exception -> `{"error": "...", "error_type": "...", "traceback": "..."}`.

```bash
# Inline Python via -c - result variable is captured
ue-cli editor run-script -c "result = {'actors': 42}"

# Multiline Python via stdin - avoids PowerShell argv splitting
@'
value = 41
result = {'actors': value + 1}
'@ | ue-cli editor run-script -

# Script file - same result capture, auto-save
ue-cli editor run-script build_scene.py --timeout 60

# Read-only script - skip auto-save
ue-cli editor run-script query.py --no-save
```

For long scripts that save or modify many assets, pass a larger `--timeout`
(for example `--timeout 300`). `EDITOR_SCRIPT_TIMEOUT` means the CLI stopped
waiting for the HTTP response; the editor completion state is unknown, so run
`editor status` and inspect the project Output Log before retrying.

### Console Commands

Use `editor exec` for UE console commands:

```bash
ue-cli editor exec "stat unit"
ue-cli editor exec "r.DumpRenderTargetPoolMemory"
```

`editor exec` returns captured log text in `log_text` when Remote Control/Python can observe it. Some diagnostics, including render-target pool dumps, write to the project Output Log instead of the immediate Remote Control response; `ue-cli` reads the current editor log delta and returns it as `log_file_text`/`log_text`.

Negative CVar values are valid:

```bash
ue-cli editor cvar set r.Shadow.Virtual.ResolutionLodBiasDirectional -4
ue-cli editor cvar set r.Shadow.Virtual.ResolutionLodBiasDirectional -- -4
```

`editor cvar get NAME` fails instead of returning a misleading success when UE returns an empty value for a missing or unverified CVar. If the bridge plugin is old and the value is empty, upgrade it:

```bash
ue-cli editor plugin-upgrade
```

## Viewport Bookmarks

Console attempts have executed without moving camera:

```bash
ue-cli editor exec "BOOKMARK JUMPTO=1"
ue-cli editor exec "JumpToBookmark1"
```

Read active Level Viewport camera with the CLI command. UE Python differs by engine branch; do not call `LevelEditorSubsystem.get_level_viewport_camera_info()` directly.

```bash
ue-cli --output json --project "F:/path/to/Project.uproject" editor viewport camera
```

Use dedicated Windows-only bookmark command. It finds UE main window, foregrounds it, focuses viewport, sends numeric key `0`-`9`, then compares active viewport camera before/after.

```bash
ue-cli --output json --project "F:/path/to/Project.uproject" editor viewport bookmark jump --index 1
```

Success returns index, window, before/after camera. `BOOKMARK_JUMP_UNCHANGED` means likely focus fail, missing bookmark, changed shortcut, or wrong window.

## Viewport Game View

`editor exec ToggleGameView` can report command execution without changing the Level Viewport. Use the dedicated state API instead:

```bash
# Query current state
ue-cli --output json --project "F:/path/to/Project.uproject" editor viewport game-view

# Set or toggle, with verified before/after state
ue-cli --output json --project "F:/path/to/Project.uproject" editor viewport game-view on
ue-cli --output json --project "F:/path/to/Project.uproject" editor viewport game-view off
ue-cli --output json --project "F:/path/to/Project.uproject" editor viewport game-view toggle
```

## RenderDoc Frame Capture

Capture GPU frame for offline shader/draw-call analysis.

### Prerequisites

1. **RenderDoc plugin loaded.** Project `DefaultEngine.ini`:
   ```ini
   [Plugins]
   +EnabledPlugins=RenderDoc
   ```
   Or enable via UE Editor -> Edit -> Plugins -> RenderDoc. Verify:
   ```bash
   ue-cli editor exec "renderdoc.captureframe"
   # If the plugin is missing, the command silently does nothing.
   ```

2. **Windowed editor required.** Not `-nullrhi`; RenderDoc needs real RHI.

### Capture a Frame

```bash
# 1. Ensure editor is online
ue-cli editor status

# 2. Capture the next frame
ue-cli editor exec "renderdoc.captureframe"
```

Capture saves `.rdc` under `<ProjectDir>/Saved/RenderDocCaptures/` (example `F:\MyProject\Saved\RenderDocCaptures\2026.05.11-11.01.53_capture.rdc`). RenderDoc UI may open if installed.

### Typical Workflow

```bash
# 1. Open the target map
ue-cli editor launch --map /Game/Maps/MyMap

# 2. (Optional) Tweak rendering settings before capture
ue-cli editor cvar set r.ShadowQuality 3
ue-cli editor cvar set r.AntiAliasingMethod 2
ue-cli editor cvar set r.Shadow.Virtual.ResolutionLodBiasDirectional -4

# 3. Capture a GPU frame
ue-cli editor exec "renderdoc.captureframe"

# 4. (Optional) Take a viewport screenshot for visual reference alongside the .rdc
ue-cli screenshot capture --filename before_capture
```

### Analyzing the Capture

Use `rdc-cli` skill if available, or RenderDoc app. Common tasks:
- **Shader debugging**: step pixel/vertex shaders.
- **Draw call inspection**: expensive draws, overdraw, redundant state.
- **Texture/RT verification**: inspect intermediate render targets.
- **Performance profiling**: GPU timings per draw/pass.

### Android Packaged Apps

For UE Android packaged captures, use `rdc-cli` Android loader workflow, not editor-only `renderdoc.captureframe`.

Known UE issue: Adreno + RenderDoc Android loader + `VK_KHR_buffer_device_address` can fail `vkAllocateMemory` with `VK_ERROR_INVALID_OPAQUE_CAPTURE_ADDRESS`. Workaround: comment user-identified `ADD_CUSTOM_EXTENSION` block in `Engine/Source/Runtime/VulkanRHI/Private/VulkanExtensions.cpp` (`FVulkanKHRBufferDeviceAddressExtension` through related ray-tracing/vendor diagnostic extensions), then rebuild/package Development. Keep evidence + cleanup in `rdc-cli` `references/android-loader-and-ue5.md`.

### Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Command executes but no capture | RenderDoc plugin not loaded | Check `DefaultEngine.ini` has `+EnabledPlugins=RenderDoc`; restart editor |
| Capture fails with D3D error | `-nullrhi` or headless mode | Remove `-nullrhi`; use windowed mode |
| Can't find `.rdc` | Unknown capture dir | Check `<ProjectDir>/Saved/RenderDocCaptures/` |
| RenderDoc UI doesn't open | RenderDoc not installed | Install from [renderdoc.org](https://renderdoc.org) |

### Synchronous Execution - No Tick Callbacks

`editor run-script` is synchronous: CLI waits for Python main thread, returns result, disconnects.

1. **No tick-based async callbacks.** By trigger time, CLI connection gone.
2. **Multi-frame ops split into scripts.** One `editor run-script` per frame-bound step.
3. **Finish all work on main thread before return.**

### Inline Python Auto-Mode

`editor run-script -c` executes inline Python with full result capture:
- Uses `exec_python_file`, captures result as JSON.
- Auto-saves dirty packages unless `--no-save`.
- Errors return message + traceback, not silent timeout.

## UE Python API - Class Lookup

UE Python functions live on Library/Subsystem helpers, not usually objects themselves. Start here, then `editor api-discover ClassName -q keyword`.

| I want to... | Start with |
|--------------|-----------|
| Spawn/delete/duplicate actors | `EditorActorSubsystem` |
| Move/rotate/scale actors | `EditorLevelLibrary` |
| Save packages | `EditorLoadingAndSavingUtils` |
| Open/create levels | `editor open-level` / `editor new-level` (`LevelEditorSubsystem`) |
| Load/save/delete/rename assets | `EditorAssetLibrary` |
| Create material nodes, connect pins | `MaterialEditingLibrary` |
| Create new asset | `AssetToolsHelpers.get_asset_tools()` -> `create_asset()` |
| Render targets, draw to texture | `KismetRenderingLibrary` |
| Mesh LODs, collision | `StaticMeshEditorSubsystem` |
| Viewport camera | `LevelEditorSubsystem` |
| Sub-levels, streaming | `EditorLevelUtils` |
| Sequencer playback/keys | `LevelSequenceEditorBlueprintLibrary` |

**Pitfalls** - wrong guesses:
- `spawn_actor` -> `EditorActorSubsystem.spawn_actor_from_class`, not `EditorLevelLibrary`
- `create_material` -> `get_asset_tools().create_asset()`, not `MaterialEditingLibrary`
- `set_material(slot, mat)` -> call on `MeshComponent`, not `StaticMesh` asset
- `set_location` -> `Actor.set_actor_location(vector)`; UE uses `set_actor_*`
- viewport realtime -> not exposed to Python; use CVars via `editor exec`

**When you can't find the class**: pass live actor/asset path:
```bash
ue-cli editor api-discover "/Game/Maps/L.L:PersistentLevel.MyActor_0"
```

## Editor-Specific Error Patterns

| Error | Cause | Fix |
|-------|-------|-----|
| Connection refused | Editor not running | Follow lifecycle above |
| Timeout | Editor busy: shaders/loading | Run `editor status`; if reachable, wait 10-15s and retry |
| "modules built with different engine version" | Binary/engine mismatch | `editor preflight` -> `build compile` -> `editor launch` |
| Screenshot fails | Editor window not visible/minimized | Foreground editor, retry |


## Bridge Version Mismatch

If `editor status` reports `plugin_match=false`, the editor has already loaded an older or missing `CliAnythingBridge` DLL. UE cannot safely hot-reload that C++ bridge. Run the reported `editor plugin-upgrade` command so ue-cli can deploy, recompile, restart the editor, then retry bridge-backed commands.
