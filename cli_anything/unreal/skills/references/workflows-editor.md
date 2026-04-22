# Editor Lifecycle

## Launch

```bash
# Sync (blocks until editor API is online or timeout)
cli-anything-unreal editor launch --timeout 600

# Async (returns immediately, poll for progress)
cli-anything-unreal editor launch --no-wait
# → {"task_id": "t-abc123", "status": "submitted", "suggested_poll_interval_seconds": 5}

# Check launch progress
cli-anything-unreal editor status <task_id>
```

Zombie processes (UnrealEditor.exe running but API unreachable) are auto-killed on launch. Only a truly running editor (API alive) blocks with `ALREADY_RUNNING`.

## Status

`editor status` returns one of:
- `online` — API reachable, editor fully running
- `starting` — process exists, modal dialogs detected (startup in progress)
- `zombie` — process exists but API unreachable, no dialogs (stale/hung process)
- `not_running` — no editor process found

## Close

```bash
cli-anything-unreal editor close
```
