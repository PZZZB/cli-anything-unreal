# Editor Lifecycle & Python Scripting

## Editor Lifecycle — Required Flow

When you need the editor running, follow this sequence. Do not skip steps or improvise alternatives.

```
Step 1: editor status
  → Online? Proceed to your task.
  → Offline? Continue to Step 2.

Step 2: editor preflight
  → Ready? editor launch
  → BuildId mismatch? Continue to Step 3.

Step 3: editor close (if running) → build compile → editor launch
  This is the ONLY correct way to fix module version mismatches.

Step 4: editor status (verify)
  → Online? Proceed.
  → Still offline? Report the error to the user.
```

Key points:
- `editor launch` blocks until the editor API is online (or timeout). Do not use `sleep` commands.
- For async launch, use `--no-wait` and poll with `editor status <task_id>` or generic `task status <task_id>`.
- If `build compile` fails because DLLs are locked, close the editor first with `editor close`.
- If the user says the editor is already running, start at Step 1 to verify.
- `editor launch` auto-handles zombie processes (stale `UnrealEditor.exe` with no API response) — it kills them and proceeds. Only `ALREADY_RUNNING` (API alive) blocks the launch.

### Example

```bash
# 1. Preflight — catches build mismatches before they cause hangs
cli-anything-unreal --project F:\MyGame\MyGame.uproject editor preflight

# 2. If BuildId mismatch, compile first
cli-anything-unreal --project F:\MyGame\MyGame.uproject build compile

# 3. Launch editor (blocks until ready)
cli-anything-unreal --project F:\MyGame\MyGame.uproject editor launch --map /Game/Maps/MyMap

# 4. Verify
cli-anything-unreal editor status
```

### Async Launch

```bash
# Async (returns immediately, poll for progress)
cli-anything-unreal editor launch --no-wait
# → {"task_id": "t-abc123", "status": "submitted", "suggested_poll_interval_seconds": 5}

# Check launch progress
cli-anything-unreal editor status <task_id>
# Or use generic task commands:
cli-anything-unreal task status <task_id>
cli-anything-unreal task cancel <task_id>
```

### Status Values

`editor status` returns one of:
- `online` — API reachable, editor fully running
- `starting` — process exists, modal dialogs detected (startup in progress)
- `zombie` — process exists but API unreachable, no dialogs (stale/hung process)
- `not_running` — no editor process found

## Close

```bash
cli-anything-unreal editor close
```

## Python Scripting Patterns

Use `editor run-script` for operations not covered by CLI commands. Use `-c` for quick inline code, or pass a file path for larger scripts.

### Result Convention

Set a `result` dict variable to return structured data. If not set, returns `{"status": "ok"}`. If the script raises an exception, returns `{"error": "...", "error_type": "...", "traceback": "..."}`.

```bash
# Inline Python via -c — result variable is captured
cli-anything-unreal editor run-script -c "result = {'actors': 42}"

# Script file — same result capture, auto-save
cli-anything-unreal editor run-script build_scene.py --timeout 60

# Read-only script — skip auto-save
cli-anything-unreal editor run-script query.py --no-save
```

### Console Commands

Use `editor exec` for UE console commands (stat, renderdoc, cvars, etc.):

```bash
cli-anything-unreal editor exec "stat unit"
```

## Viewport Bookmarks

Jumping Level Viewport bookmarks is not reliably exposed through `editor exec`. These console-command attempts have been observed to execute without changing the viewport camera:

```bash
cli-anything-unreal editor exec "BOOKMARK JUMPTO=1"
cli-anything-unreal editor exec "JumpToBookmark1"
```

Use the dedicated CLI command. It is Windows-only because it uses host-side WinAPI input simulation: locate the UE main window for the project, restore/foreground it, click the window center so the Level Viewport receives focus, send the numeric shortcut key (`0`-`9`), then compare `get_level_viewport_camera_info()` before/after.

```bash
cli-anything-unreal --output json --project "F:/path/to/Project.uproject" editor viewport bookmark jump --index 1
```

On success it returns the bookmark index, matched window info, and before/after viewport camera. If the camera does not change, the command returns `BOOKMARK_JUMP_UNCHANGED`; likely causes are: viewport not focused, bookmark does not exist, shortcut was changed, or the wrong editor window was activated.

## RenderDoc Frame Capture

Capture a GPU frame for offline analysis (shader debugging, draw call inspection, etc.).

### Prerequisites

1. **RenderDoc plugin must be loaded in UE.** The project's `DefaultEngine.ini` must include:
   ```ini
   [Plugins]
   +EnabledPlugins=RenderDoc
   ```
   Or enable it manually via the UE editor → Edit → Plugins → RenderDoc. Verify it's active:
   ```bash
   cli-anything-unreal editor exec "renderdoc.captureframe"
   # If the plugin is missing, the command silently does nothing.
   ```

2. **Editor must be running in windowed mode** (not `-nullrhi`). RenderDoc requires a real RHI backend.

### Capture a Frame

```bash
# 1. Ensure editor is online
cli-anything-unreal editor status

# 2. Capture the next frame
cli-anything-unreal editor exec "renderdoc.captureframe"
```

After execution, RenderDoc captures the next frame and saves it as a `.rdc` file. The capture is saved to `<ProjectDir>/Saved/RenderDocCaptures/` (e.g. `F:\MyProject\Saved\RenderDocCaptures\2026.05.11-11.01.53_capture.rdc`). If RenderDoc is installed, the UI may auto-launch to display the capture.

### Typical Workflow

```bash
# 1. Open the target map
cli-anything-unreal editor launch --map /Game/Maps/MyMap

# 2. (Optional) Tweak rendering settings before capture
cli-anything-unreal editor cvar set r.ShadowQuality 3
cli-anything-unreal editor cvar set r.AntiAliasingMethod 2

# 3. Capture a GPU frame
cli-anything-unreal editor exec "renderdoc.captureframe"

# 4. (Optional) Take a viewport screenshot for visual reference alongside the .rdc
cli-anything-unreal screenshot capture --filename before_capture
```

### Analyzing the Capture

The `.rdc` file can be analyzed with the `rdc-cli` skill if available, or opened manually in the RenderDoc application. Common analysis tasks:

- **Shader debugging**: Inspect pixel/vertex shader execution step by step.
- **Draw call inspection**: Identify expensive draw calls, overdraw, or redundant state changes.
- **Texture/RT verification**: Check intermediate render targets to diagnose visual artifacts.
- **Performance profiling**: Review GPU timings per draw call or pass.

### Android Packaged Apps

For UE Android packaged-app captures, use the `rdc-cli` skill's Android loader workflow instead of editor-only `renderdoc.captureframe`.

Known UE-specific failure: Adreno + RenderDoc Android loader + `VK_KHR_buffer_device_address` can fail at `vkAllocateMemory` with `VK_ERROR_INVALID_OPAQUE_CAPTURE_ADDRESS`. This is not an RDG/subpass crash. The verified UE-side workaround is to comment out the user-identified `ADD_CUSTOM_EXTENSION` block in `Engine/Source/Runtime/VulkanRHI/Private/VulkanExtensions.cpp` (`FVulkanKHRBufferDeviceAddressExtension` through the related ray-tracing/vendor diagnostic extensions), then rebuild/package Development. Keep the full capture flow, evidence, and Android GPU debug cleanup in `rdc-cli`'s `references/android-loader-and-ue5.md`.

### Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Command executes but no capture | RenderDoc plugin not loaded | Check `DefaultEngine.ini` has `+EnabledPlugins=RenderDoc`; restart editor |
| Capture fails with D3D error | `-nullrhi` or headless mode | Remove `-nullrhi` from launch args; use windowed mode |
| Can't find the .rdc file | Unknown capture directory | Check `<ProjectDir>/Saved/RenderDocCaptures/` — that's the default save location |
| RenderDoc UI doesn't open | RenderDoc not installed | Install RenderDoc from [renderdoc.org](https://renderdoc.org) |

### Synchronous Execution — No Tick Callbacks

`editor run-script` is synchronous: the CLI waits for the Python main thread to finish, then returns the result and disconnects.

1. **No tick-based async callbacks.** By the time they trigger, the CLI connection is gone and the return value is lost.
2. **Multi-frame operations must be split into separate scripts.** Call `editor run-script` once per frame-bound step.
3. **All work must complete in the main thread before the script returns.**

### Inline Python Auto-Mode

`editor run-script -c` executes inline Python with full result capture:
- Code is executed via `exec_python_file`, result captured as JSON.
- Dirty packages are auto-saved after execution (use `--no-save` to skip).
- If the script errors, the error message and traceback are returned (not a silent timeout).

## UE Python API — Class Lookup

UE's Python API is split across Library/Subsystem classes — functions live on static helpers, not the objects themselves. Use this table to find the right class, then `editor api-discover ClassName -q keyword` to locate the exact function.

| I want to... | Start with |
|--------------|-----------|
| Spawn/delete/duplicate actors | `EditorActorSubsystem` |
| Move/rotate/scale actors | `EditorLevelLibrary` |
| Save packages, load maps | `EditorLoadingAndSavingUtils` |
| Load/save/delete/rename assets | `EditorAssetLibrary` |
| Create material nodes, connect pins | `MaterialEditingLibrary` |
| Create a new asset from scratch | `AssetToolsHelpers.get_asset_tools()` → `create_asset()` |
| Render targets, draw to texture | `KismetRenderingLibrary` |
| Mesh LODs, collision | `StaticMeshEditorSubsystem` |
| Viewport camera | `LevelEditorSubsystem` |
| Sub-levels, streaming | `EditorLevelUtils` |
| Sequencer playback/keys | `LevelSequenceEditorBlueprintLibrary` |

**Pitfalls** — these don't exist where you'd guess:

- `spawn_actor` → `EditorActorSubsystem.spawn_actor_from_class` (not `EditorLevelLibrary`)
- `create_material` → `get_asset_tools().create_asset()` (not `MaterialEditingLibrary`)
- `set_material(slot, mat)` → call on `MeshComponent`, not the `StaticMesh` asset
- `set_location` → `Actor.set_actor_location(vector)` (UE uses `set_actor_*` prefix)
- viewport realtime → not exposed to Python; use console CVars via `editor exec`

**When you can't find the class**: pass a live actor/asset path to api-discover and it auto-detects:
```bash
cli-anything-unreal editor api-discover "/Game/Maps/L.L:PersistentLevel.MyActor_0"
```

## Editor-Specific Error Patterns

| Error | Cause | Fix |
|-------|-------|-----|
| Connection refused | Editor not running | Follow the Lifecycle flow above |
| Timeout | Editor is busy (compiling shaders, loading level) | Run `editor status` to check; if reachable, wait 10-15s and retry |
| "modules built with different engine version" | Binary/engine mismatch | `editor preflight` → `build compile` → `editor launch` |
| Screenshot fails | Editor window not visible or minimized | Ensure editor is in foreground, retry |
