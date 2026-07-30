# ue-cli

`ue-cli` controls Unreal Engine 5 editors from a shell. It provides structured commands for project inspection, editor lifecycle, materials, Blueprints, scenes, screenshots, CVars, Python, and UAT/UBT builds.

## Requirements

- Python 3.10+
- Git, required by the GitHub install command below
- Unreal Engine 5.x and a `.uproject`
- A loadable Epic `RemoteControl` engine plugin; `editor launch` enables and configures it for the selected project
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

- enable `RemoteControl` and `CliAnythingBridge` in the `.uproject`;
- create or update `Config/DefaultRemoteControl.ini`;
- deploy `Plugins/CliAnythingBridge`;
- compile the bridge when its binary is missing or stale.

Commit or back up the project before first launch if these project-file changes need review.

`editor launch` returns `online` when ready. Slow startup may return a `launching` payload with a `task_id`; poll that task:

```powershell
ue-cli --output json --project "$Project" editor status <task_id>
```

After status becomes `online`, run a read-only editor query:

```powershell
ue-cli --output json --project "$Project" material list
```

Each shell invocation is a new process. Repeat `--project` on every project-scoped command. Project selection remains sticky only inside the interactive `ue-cli` REPL.

If an already-running editor was started without Remote Control preparation, run this command, close that editor, then launch it again:

```powershell
ue-cli --output json --project "$Project" editor enable-remote
```

## Install Agent Skills

Skill installation is optional. With no `--target`, this command installs to exactly three locations:

```powershell
ue-cli install-skills
```

- `%USERPROFILE%\.claude\skills\ue-cli`
- `%USERPROFILE%\.codebuddy\agents\ue-cli`
- `%USERPROFILE%\.gemini\skills\ue-cli`

Existing target directories are replaced, including custom `--target` directories. Cursor, Codex, and GitHub Copilot are not default targets.

For another agent, first confirm that agent's skill-directory convention, then install only to that directory:

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
ue-cli --output json --project "$Project" screenshot capture --path "F:/output/material_check.png"
ue-cli --output json --project "$Project" screenshot capture --path "F:/output/stat_evidence.png" --include-ui
```

Use Unreal virtual paths such as `/Game/MyMaterial` for assets, not filesystem paths to `.uasset` files.

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

When `--port` is omitted, ue-cli uses the selected project's `DefaultRemoteControl.ini` or one unambiguous live editor. Multiple matching editors produce a structured ambiguity error instead of choosing silently.

## Output Contract

Non-interactive callers receive JSON by default. `--output json` forces it. JSON mode writes one final machine-readable payload to stdout; progress, heartbeats, and diagnostics go to stderr.

Runners should either stream stdout live or replay captured stdout once, never both.

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
