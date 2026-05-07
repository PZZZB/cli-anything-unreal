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
cli-anything-unreal editor exec "renderdoc.captureframe"
```

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

## Editor-Specific Error Patterns

| Error | Cause | Fix |
|-------|-------|-----|
| Connection refused | Editor not running | Follow the Lifecycle flow above |
| Timeout | Editor is busy (compiling shaders, loading level) | Run `editor status` to check; if reachable, wait 10-15s and retry |
| "modules built with different engine version" | Binary/engine mismatch | `editor preflight` → `build compile` → `editor launch` |
| Screenshot fails | Editor window not visible or minimized | Ensure editor is in foreground, retry |
