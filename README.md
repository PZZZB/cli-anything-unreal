# ue-cli

`ue-cli` controls Unreal Engine 4.26 and Unreal Engine 5.x editors from a shell. It provides structured commands for project inspection, editor lifecycle, materials, Blueprints, scenes, screenshots, CVars, Python, and UAT/UBT builds.

## Requirements

- Python 3.10+
- Git, required by the GitHub install command below
- Unreal Engine 4.26 or 5.x and a `.uproject`
- Loadable Epic `RemoteControl`, `PythonScriptPlugin`, and `EditorScriptingUtilities` engine plugins; `editor launch` enables and configures them for the selected project
- Windows for the supported end-to-end workflow; editor discovery, launch, and UAT/UBT integration currently use Windows-specific paths and tools

A coding agent is optional. Every command can also be run manually.

## Install

The package is not currently published on PyPI. `pip install ue-cli` will fail. Install the current source from GitHub:

```powershell
python -m pip install "git+https://github.com/PZZZB/ue-cli.git"
ue-cli --version
```

For local development:

```powershell
git clone https://github.com/PZZZB/ue-cli.git
Set-Location ue-cli
python -m pip install -e ".[dev]"
ue-cli --version
```

If `ue-cli` is not found after installation, run it as:

```powershell
python -m cli_anything.unreal --version
```

## First Run

Use forward slashes in Windows paths. Quote paths so projects under directories containing spaces also work:

```powershell
$Project = "F:/path/to/MyProject.uproject"

# Read project metadata. Unreal Editor is not required.
ue-cli --output json --project "$Project" project info

# Read-only startup checks. This does not modify project files.
ue-cli --output json --project "$Project" preflight
```

If engine discovery fails for a custom source build, set its root and rerun `preflight`:

```powershell
$env:UE_ENGINE_ROOT = "F:/path/to/UnrealEngine"
```

Start the controlled editor:

```powershell
ue-cli --output json --project "$Project" editor launch
```

First launch may:

- enable `RemoteControl`, `PythonScriptPlugin`, `EditorScriptingUtilities`, and `CliAnythingBridge` in the `.uproject`;
- create or update `Config/DefaultRemoteControl.ini`;
- deploy `Plugins/CliAnythingBridge`;
- compile only the `CliAnythingBridge` Editor module when its binary is missing or stale, then repair and validate its `UnrealEditor.modules` metadata. Bridge upgrades preserve the previous plugin until that validation passes and restore it with structured rollback details if deployment or compilation fails. If the remaining Editor target output is incomplete, launch stops with a structured full-build reason and recovery command instead of starting a full project build automatically.

Commit or back up the project before first launch if these project-file changes need review.

`editor launch` returns `online` when ready. Slow startup may return a `launching` payload with a `task_id`; poll that task:

```powershell
ue-cli --output json --project "$Project" editor status <task_id>
```

Or block until any asynchronous task finishes, with an optional caller-side timeout:

```powershell
ue-cli --output json task wait <task_id> --timeout 300
```

`task wait` exits 0 for a completed task, 3 for a failed/task-timeout result, and 4 for cancellation or caller wait timeout. A caller timeout never cancels the task; output keeps the current task status and adds `wait.status=timeout` plus a follow-up command.
Task records keep lifecycle `status` separate from the current `phase` (for example, `running` plus `waiting_remote_control`). Terminal states are monotonic: a late worker result cannot replace cancellation or another final outcome. A timed-out editor launch can become completed only after `editor status` verifies the recorded process identity and port owner.

If crash recovery blocks startup, the launch task returns `EDITOR_LAUNCH_BLOCKED_BY_RESTORE_PACKAGES` with the matching UnrealEditor PID and window title. Choose **Restore Selected** or **Skip Restore** in that existing editor, then run `editor status`; do not launch a second editor for the project.

Controlled launch requires WebRemoteControl, which Unreal does not start under `-NullRHI`. `editor launch` rejects that extra argument before creating a task or starting UnrealEditor. When launch receives `--extra-arg=-abslog=PATH`, task status and startup diagnostics report and inspect that explicit log file.

After status becomes `online`, run a read-only editor query:

```powershell
ue-cli --output json --project "$Project" material list
```

Each shell invocation is a new process. Repeat `--project` on project-scoped commands when running outside the project tree. Commands that talk to an editor infer the nearest unique `.uproject` from the current directory or its parents, so they cannot silently fall through to another project's editor. An explicit `--project` wins; `--port` selects the port but keeps the inferred project identity check. Use `editor status --all` to inspect every project. Project selection remains sticky inside the interactive `ue-cli` REPL.

If an already-running editor was started without Remote Control preparation, run this command, close that editor, then launch it again:

```powershell
ue-cli --output json --project "$Project" editor enable-remote
```

## Install Agent Skills

Skill installation is optional. By default, this command detects installed clients and writes only their matching global targets:

```powershell
ue-cli install-skills
```

| Target | Installed when detected |
| --- | --- |
| `%USERPROFILE%\.agents\skills\ue-cli` | Codex, Cursor, GitHub Copilot, Windsurf, or OpenCode |
| `%USERPROFILE%\.claude\skills\ue-cli` | Claude Code |
| `%USERPROFILE%\.codebuddy\agents\ue-cli` | CodeBuddy |
| `%USERPROFILE%\.gemini\skills\ue-cli` | Gemini CLI |

The shared `.agents` location follows the Agent Skills convention. If no supported client or initialized skill directory is detected, the command reports every target as `skipped` and creates no skill target. Run a newly installed client once so its profile directory exists, or explicitly install every built-in target:

```powershell
ue-cli install-skills --all-targets
```

Existing `ue-cli` target directories are replaced, including custom `--target` directories. Other skills beside the `ue-cli` directory are not changed.

For an agent with a different skill-directory convention, install directly to its exact `ue-cli` directory. The final directory name must be `ue-cli`; this prevents accidentally replacing an entire skills root:

```powershell
ue-cli install-skills --target "C:/path/expected/by/your-agent/ue-cli"
```

`--target` is repeatable. Restart or reload the agent after installation.

## Prompt an Agent

With the skill installed:

```text
Use the ue-cli skill with project F:/path/to/MyProject.uproject.
Analyze /Game/MyMaterial, fix confirmed issues, then capture before/after screenshots.
```

Without the skill:

```text
Use ue-cli with project F:/path/to/MyProject.uproject.
Run ue-cli --help and command-specific --help before choosing commands.
```

## Common Commands

Global options such as `--output`, `--project`, and `--port` must appear before the subcommand.

```powershell
$Project = "F:/path/to/MyProject.uproject"

ue-cli --help
ue-cli --list-commands
ue-cli --output json --project "$Project" editor status
ue-cli --output json --project "$Project" material analyze /Game/MyMaterial
ue-cli --output json --project "$Project" material get-param /Game/MyMaterialInstance --name Roughness
ue-cli --output json --project "$Project" material shader-source /Game/MyMaterial
ue-cli --output json --project "$Project" screenshot capture --path "F:/output/material_check.png"
ue-cli --output json --project "$Project" screenshot capture --path "F:/output/stat_evidence.png" --include-ui
ue-cli --output json --project "$Project" editor run-script --no-save -c 'result={"label":"quoted value"}'
ue-cli --output json --project "$Project" editor cvar get r.VSync --timeout 10
```

Use Unreal virtual paths such as `/Game/MyMaterial` for assets, not filesystem paths to `.uasset` files.
`material get-param` returns the effective scalar, vector, texture, or static-switch value, including values inherited from parent material instances or materials.
`material info` supports Material, MaterialFunction, and MaterialInstanceConstant assets. Bridge 1.29 reads these assets directly through Remote Control, including graph edges, outputs, textures, and instance parameters, without creating Python expression wrappers. A stale bridge returns `MATERIAL_INFO_BRIDGE_REQUIRED` with an upgrade command.
`material get-stats` rejects MaterialInstanceConstant assets with `MATERIAL_STATS_UNSUPPORTED_CLASS`; parent-graph counts are not reported as effective compiled-instance statistics.
Material inspection commands never save packages. Bridge 1.30 runs graph mutations in native C++ and saves only their explicitly targeted package, leaving unrelated dirty work untouched. Material expression UObjects never cross into Python.
`material info`, `material analyze`, and `material get-graph` recognize Material Attributes connections as material outputs and trace their upstream graph.
`material shader-source` refreshes changed engine `.usf`/`.ush` files before synchronous extraction. Success reports `shader_cache_refresh=changed`; an empty extraction returns `MATERIAL_SHADER_SOURCE_FAILED` instead of stale success.
`material dump-hlsl` rejects an inactive requested shader platform before recompiling, preserves the material package's original dirty flag, and returns a nonzero structured error when no dump or matching shader stage is available.
On Windows PowerShell, `editor run-script -c` preserves double-quoted Python string literals that native argument parsing would otherwise strip. Use stdin (`editor run-script -`) or a `.py` file for multiline code.
A `.py` file passed to `editor run-script` executes with `__name__ == "__main__"` and an absolute `__file__`, so guarded script entrypoints run normally.
Each `editor run-script` invocation receives fresh globals. Deferred Unreal callbacks retain that invocation's globals after the command returns; store their handles and unregister them when finished because later callback failures appear only in the editor log.
`editor cvar get` confirms the selected editor's TCP listener, then uses the remaining timeout for the requested CVar. It does not spend the budget on a duplicate functional readiness call. Query timeouts report the actual request stage; verified missing CVars return `CVAR_NOT_FOUND`.
`editor exec --timeout` never redispatches a command after an ambiguous transport failure. A timeout returns nonzero `EDITOR_EXEC_DELIVERY_UNKNOWN`; inspect editor state and logs before retrying because a non-idempotent command may already have run. Inline command logs are bounded; `omitted_line_count` reports omitted lines and `log_file` retains complete diagnostics. Automation commands lower Unreal's runtime-only interactive-FPS gate to 1 FPS without saving project configuration, so background agent runs do not require human window focus.

## Multiple Editors

Discover all running instances:

```powershell
ue-cli --output json editor status --all
```

Select one editor by project or port:

```powershell
ue-cli --output json --project "F:/ProjectA/ProjectA.uproject" editor status
ue-cli --output json --port 30011 material list
```

When `--port` is omitted, ue-cli uses the selected project's `DefaultRemoteControl.ini` or one unambiguous live editor. Multiple matching editors produce a structured ambiguity error instead of choosing silently. A directory containing multiple `.uproject` files also requires explicit `--project`. For every project-bound editor request on Windows, the listening-port PID must be known and its process command line must match that project; unknown or mismatched ownership fails before sending the request.

`editor status` applies a 15-second discovery deadline by default. Use `editor status --timeout <seconds>` when a slow machine needs more time. An exhausted deadline returns `EDITOR_STATUS_TIMEOUT` with the `blocking_phase`; a blocked task read also includes its `task_id`.

`editor close` targets the verified editor for the selected project. Without `--project`, it captures the process owning the selected Remote Control port. By default it reads dirty map/content packages, moves dirty `/Temp/` maps to deterministic `/Game/__UeCliAutoSave_<name>` assets, saves everything else, requires Unreal to confirm the save, then closes. It never asks the caller to classify who changed a package or choose a save path. Unknown/offline state and same-project stale peers are preserved as machine-readable failures because they cannot be saved safely. The single escape hatch, `--force`, allows data loss and offline/stale process termination and should be used only when the request already authorizes that outcome.

## Output Contract

Non-interactive callers receive JSON by default. `--output json` forces it. JSON mode writes one final machine-readable payload to stdout; progress, heartbeats, and diagnostics go to stderr.

Runners should either stream stdout live or replay captured stdout once, never both.

Failed cook/package results prioritize terminal plugin-load failures over compiler-like lines from earlier phases. These failures return `code=BUILD_PLUGIN_LOAD_FAILED`, `failure_kind=plugin_load_failure`, the primary `diagnostic`, plugin/module names when available, and `phase=cook` when the UAT log identifies Cook as the failing phase.

`build compile --module NAME` is a focused project or engine-core module build. If the current Editor target receipt identifies `NAME` as an Engine plugin module, ue-cli rejects the command before UBT with `ENGINE_PLUGIN_MODULE_UNSUPPORTED` and provides a full `build compile` recovery command. Project-targeted UBT can omit Engine plugin output actions and otherwise fail with `Unable to find output items for module`.

## Features

- **Project management:** parse `.uproject`, inspect `.ini`, list content assets
- **Build system:** compile, cook, and package through UAT/UBT
- **Material analysis:** list, inspect, analyze, and edit materials
- **Blueprint and scene tools:** inspect and edit Blueprints, actors, and components
- **Screenshots:** capture the viewport, include UI overlays, compare images, run CVar A/B checks
- **Editor control:** launch, status, console commands, CVars, and Python scripts

## Architecture

Three communication tiers:

1. **UAT/UBT subprocess:** build, cook, and package without a running editor.
2. **Remote Control HTTP:** query and edit editor state through the selected HTTP port.
3. **Editor Python injection:** execute Unreal Python through Remote Control when no dedicated subcommand exists.

## Known Engine Bugs

UE Remote Control and Python have version-specific automation bugs. See [ENGINE_BUGS.md](ENGINE_BUGS.md) for known issues, workarounds, and engine-source fixes.

## Problems and Support

Report reproducible ue-cli problems at [PZZZB/ue-cli issues](https://github.com/PZZZB/ue-cli/issues). Include ue-cli version, Unreal version, exact command, expected behavior, actual behavior, minimal reproduction, and sanitized logs.
