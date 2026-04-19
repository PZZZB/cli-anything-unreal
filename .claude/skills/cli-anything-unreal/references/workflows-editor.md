# Editor Lifecycle & Python Scripting

## Editor Lifecycle — Required Flow

When you need the editor running, follow this sequence. Do not skip steps or improvise alternatives.

```
Step 1: editor status
  → Online? Proceed to your task.
  → Offline? Continue to Step 2.

Step 2: editor preflight
  → Ready? editor launch --wait
  → BuildId mismatch? Continue to Step 3.

Step 3: editor close (if running) → build compile → editor launch --wait
  This is the ONLY correct way to fix module version mismatches.

Step 4: editor status (verify)
  → Online? Proceed.
  → Still offline? Report the error to the user.
```

Key points:
- `editor launch --wait` handles waiting for the editor to become ready. Do not use `sleep` commands.
- If `build compile` fails because DLLs are locked, close the editor first with `editor close`.
- If the user says the editor is already running, start at Step 1 to verify.

### Example

```bash
# 1. Preflight — catches build mismatches before they cause hangs
cli-anything-unreal --json --project F:\MyGame\MyGame.uproject editor preflight

# 2. If BuildId mismatch, compile first
cli-anything-unreal --json --project F:\MyGame\MyGame.uproject build compile

# 3. Launch editor (--wait blocks until ready)
cli-anything-unreal --json --project F:\MyGame\MyGame.uproject editor launch --map /Game/Maps/MyMap

# 4. Verify
cli-anything-unreal --json editor status
```

## Python Scripting Patterns

Use `editor run-script` for operations not covered by CLI commands. Use `editor exec "py ..."` for quick one-liners.

### Result Convention

Set a `result` dict variable to return structured data. If not set, returns `{"status": "ok"}`. If the script raises an exception, returns `{"error": "...", "error_type": "...", "traceback": "..."}`.

```bash
# Inline Python — result variable is captured
cli-anything-unreal --json editor exec "py result = {'actors': 42}"

# Script file — same result capture, auto-save
cli-anything-unreal --json editor run-script build_scene.py --timeout 60

# Read-only script — skip auto-save
cli-anything-unreal --json editor run-script query.py --no-save
```

### Synchronous Execution — No Tick Callbacks

`editor run-script` is synchronous: the CLI waits for the Python main thread to finish, then returns the result and disconnects.

1. **No tick-based async callbacks.** By the time they trigger, the CLI connection is gone and the return value is lost.
2. **Multi-frame operations must be split into separate scripts.** Call `editor run-script` once per frame-bound step.
3. **All work must complete in the main thread before the script returns.**

### Inline Python Auto-Mode

When `editor exec` command starts with `py `, it automatically switches to reliable script mode:
- Code is written to a temp file, executed via `exec_python_file`, result captured as JSON.
- Dirty packages are auto-saved after execution (use `--no-save` to skip).
- If the script errors, the error message and traceback are returned (not a silent timeout).

## Editor-Specific Error Patterns

| Error | Cause | Fix |
|-------|-------|-----|
| Connection refused | Editor not running | Follow the Lifecycle flow above |
| Timeout | Editor is busy (compiling shaders, loading level) | Run `editor status` to check; if reachable, wait 10-15s and retry |
| "modules built with different engine version" | Binary/engine mismatch | `editor preflight` → `build compile` → `editor launch` |
| Screenshot fails | Editor window not visible or minimized | Ensure editor is in foreground, retry |
