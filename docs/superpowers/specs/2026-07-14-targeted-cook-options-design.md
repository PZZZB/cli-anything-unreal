# Targeted Cook Options Design

## Goal

Expose the three Unreal cook inputs required by current workflows without
adding a second cooker implementation or a general-purpose argument surface:

- one or more packages
- a cooker output directory
- one or more per-run ini overrides

The existing `RunUAT.bat BuildCookRun -cook` path remains the only execution
path.

## CLI

`build cook` gains three options:

```text
--package PACKAGE     Package to cook; repeat for multiple packages.
--output-dir DIR      Root directory for cooked output.
--ini OVERRIDE        Per-run UE ini override; repeat for multiple overrides.
```

Example:

```powershell
ue-cli --project F:\Game\Game.uproject build cook --platform Android `
  --package /Game/Maps/Oregon_Main `
  --output-dir F:\Cooked\Oregon `
  --ini "Engine:[/Script/Engine.RendererSettings]:r.SDOC.Enable=1"
```

The `--ini` value omits the native `-ini:` prefix because the option already
identifies its type.

## Native UE Mapping

- Packages become one UAT argument:
  `-AdditionalCookerOptions=-Package=/Game/A+/Game/B`. UE's CookCommandlet
  accepts `+`-separated `PACKAGE` values.
- Output becomes `-CookOutputDir=<DIR>`. AutomationTool converts it to the
  CookCommandlet's safely quoted `-outputdir=<DIR>` form.
- Each ini override becomes a UAT argument `-ini:<OVERRIDE>`. AutomationTool
  already collects and forwards these overrides to the cooker.
- Existing default behavior remains `-allmaps` when no package is supplied.
  Supplying at least one package removes `-allmaps`, so a targeted cook cannot
  silently expand into a full-map cook.

No direct `UnrealEditor-Cmd.exe` invocation is added.

## Data Flow

The Click command validates values and puts `packages`, `output_dir`, and
`ini_overrides` into the existing build-task payload. Both synchronous waits
and `--no-wait` therefore execute the same task worker path. The worker passes
the fields to `cook_content`, which builds the native UAT argv. The existing
result normalization continues to return `uat_command` and `log_file`.

## Validation And Errors

The existing Windows UAT value validation is reused. Literal quotes, shell
control characters, NUL, CR, and LF are rejected before task submission.
Package and ini values remain otherwise opaque to ue-cli; Unreal owns their
semantics and diagnostics.

## Tests

- Core argv tests for default all-map and targeted package cooks.
- Core argv tests for output directory and repeated ini forwarding.
- CLI payload tests covering synchronous and async-shared parameters.
- Task-worker forwarding tests.
- CLI validation tests for unsafe values.
- Help and skill command-reference updates.
- Full unit suite and the full `F:\Test574` E2E suite before release.

## Non-Goals

- A generic `--cook-arg` or `--uat-arg` option for `build cook`.
- Reimplementing cook behavior in Python.
- Replacing source-code search or IDE workflows.
- Changing the current default all-map cook when no target is provided.
