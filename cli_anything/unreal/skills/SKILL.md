Always use `--output json` for AI callers. **Important: `--output json` is a top-level flag and must appear BEFORE the subcommand:**
- ✅ `cli-anything-unreal --output json editor launch`
- ❌ `cli-anything-unreal editor launch --output json`

Long-running commands use `--no-wait` plus task polling:
- `build compile --no-wait` → poll `build status <task_id>`
- `editor launch --no-wait` → poll `editor status <task_id>`
- Or use generic `task status <task_id>` / `task cancel <task_id>`

`editor launch` auto-handles zombie processes (stale UnrealEditor.exe with no API response) — it kills them and proceeds. Only `ALREADY_RUNNING` (API alive) blocks the launch.
