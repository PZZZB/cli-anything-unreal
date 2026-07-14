# Targeted Cook Options Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `ue-cli build cook` pass package seeds, a cook output directory, and repeated ini overrides through the existing Unreal AutomationTool cook path.

**Architecture:** Extend the current Click command and file-task payload with three typed fields. `cook_content` remains the only argv builder and maps those fields to `AdditionalCookerOptions`, `CookOutputDir`, and native `-ini:` arguments before calling `RunUAT.bat BuildCookRun`.

**Tech Stack:** Python 3, Click, pytest, Unreal AutomationTool `BuildCookRun`.

## Global Constraints

- Keep `RunUAT.bat BuildCookRun -cook` as the only cook execution path.
- Do not add generic `--cook-arg` or `--uat-arg` options to `build cook`.
- Preserve default `-allmaps` argv when no package is supplied; omit it for targeted package cooks.
- Package values are seeds; Unreal may also cook dependencies and configured roots.
- Synchronous and `--no-wait` calls must use the same task payload and worker.
- Reuse existing unsafe-value validation and reject `+` inside one package value.

---

### Task 1: Native Cook Argument Mapping

**Files:**
- Modify: `cli_anything/unreal/core/build.py:16-47,316-347`
- Test: `cli_anything/unreal/tests/test_build.py:420-434`

**Interfaces:**
- Produces: `validate_cook_package(value: str) -> str`
- Produces: `cook_content(..., *, packages=None, output_dir=None, ini_overrides=None) -> dict`
- Consumes: existing `validate_package_uat_value` and `run_uat`

- [x] **Step 1: Write failing core argv tests**

Add tests that call the desired API and inspect `run_uat` argv:

```python
result = cook_content(
    temp_project["uproject"],
    platform="Android",
    packages=["/Game/Foo/A", "/Game/Foo/B"],
    output_dir=r"F:\Cook Output",
    ini_overrides=[
        "Engine:[Section]:Key=Value",
        "Game:[Other]:Flag=True",
    ],
)
args = mock_run.call_args.args[2]
assert "-allmaps" not in args
assert "-AdditionalCookerOptions=-Package=/Game/Foo/A+/Game/Foo/B" in args
assert r"-CookOutputDir=F:\Cook Output" in args
assert "-ini:Engine:[Section]:Key=Value" in args
assert "-ini:Game:[Other]:Flag=True" in args
assert result["uat_command"] == mock_run.return_value["command"]
```

Also assert an argument-less cook still contains `-allmaps`, and that
`validate_cook_package("/Game/A+/Game/B")` raises `ValueError`.

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest cli_anything/unreal/tests/test_build.py -k "cook_native_options or cook_rejects_embedded_plus or cook_success" -v
```

Expected: new tests fail because `cook_content` lacks the keyword arguments and `validate_cook_package` does not exist.

- [x] **Step 3: Implement minimal validation and argv mapping**

Add:

```python
def validate_cook_package(value: str) -> str:
    value = validate_package_uat_value(value, label="cook package")
    if "+" in value:
        raise ValueError("Cook package must not contain '+'")
    return value
```

Extend `cook_content` with keyword-only `packages`, `output_dir`, and
`ini_overrides`. Validate all values, build the existing base argv, append
`-allmaps` only when `packages` is empty, and otherwise append one combined
`-AdditionalCookerOptions=-Package=...` argument. Map output and ini values to
`-CookOutputDir=` and repeated `-ini:` arguments.

- [x] **Step 4: Run the focused tests and verify GREEN**

Run the command from Step 2. Expected: all selected tests pass.

### Task 2: CLI And Async Worker Plumbing

**Files:**
- Modify: `cli_anything/unreal/commands/build.py:12-56,261-276`
- Modify: `cli_anything/unreal/core/tasks.py:640-652`
- Test: `cli_anything/unreal/tests/test_build.py:1329-1369,2368-2380`

**Interfaces:**
- Consumes: `validate_cook_package` and extended `cook_content`
- Produces task payload keys: `packages`, `output_dir`, `ini_overrides`

- [x] **Step 1: Write failing CLI payload and worker tests**

Invoke:

```python
result = CliRunner().invoke(cli, [
    "--output", "json",
    "--project", temp_project["uproject"],
    "build", "cook",
    "--platform", "Android",
    "--package", "/Game/Foo/A",
    "--package", "/Game/Foo/B",
    "--output-dir", r"F:\Cook Output",
    "--ini", "Engine:[Section]:Key=Value",
    "--no-wait",
])
```

Assert successful parsing and exact task payload tuples. Add a
`_run_build_task(..., "cook_content", ...)` test asserting the worker passes
all three fields as keyword arguments. Extend the help test to require all
three option names, and parameterize unsafe-value tests for package, output,
and ini values.

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest cli_anything/unreal/tests/test_build.py -k "build_cook" -v
```

Expected: Click reports unknown options and the worker omits the new kwargs.

- [x] **Step 3: Implement Click options and task forwarding**

Add repeatable `--package`, optional `--output-dir`, and repeatable `--ini` to
`build_cook`. Reuse `_validate_package_value`, adding labels for `packages`,
`output_dir`, and `ini_overrides`, and call `validate_cook_package` for package
values. Put the normalized values into `_build_payload`. In `_run_build_task`,
forward the same three keys to `cook_content`.

- [x] **Step 4: Run the focused tests and verify GREEN**

Run the command from Step 2. Expected: all selected tests pass.

### Task 3: Documentation And Release Verification

**Files:**
- Modify: `cli_anything/unreal/skills/references/commands.md:103-133`
- Modify: `docs/superpowers/specs/2026-07-14-targeted-cook-options-design.md`
- Create: `docs/superpowers/plans/2026-07-14-targeted-cook-options-plan.md`

**Interfaces:**
- Documents the exact CLI syntax and native UAT mapping implemented by Tasks 1-2.

- [x] **Step 1: Update command reference**

Document:

```powershell
ue-cli --project F:\Game\Game.uproject build cook --platform Android `
  --package /Game/Foo/A --package /Game/Foo/B `
  --output-dir "F:\Cook Output" `
  --ini "Engine:[Section]:Key=Value"
```

State that packages seed a cook rather than excluding dependencies/configured
roots. Clarify that `build package --output-dir` remains the archive directory.

- [x] **Step 2: Run focused and full unit verification**

Run:

```powershell
python -m pytest cli_anything/unreal/tests/test_build.py -v
python -m pytest cli_anything/unreal/tests/ -v
```

Expected: zero failures; E2E-gated tests may remain skipped by design.

- [x] **Step 3: Run full real-project E2E**

Run:

```powershell
$env:UE_TEST_PROJECT='F:\Test574\Test574.uproject'
python -m pytest cli_anything/unreal/tests/test_full_e2e.py -v --e2e --e2e-auto-launch --e2e-launch-timeout 300
```

Expected: all runnable E2E tests pass. Record any intentional skips exactly.

- [x] **Step 4: Inspect diff and commit implementation**

Run:

```powershell
git diff --check
git status --short
git diff --stat
git add cli_anything/unreal/core/build.py cli_anything/unreal/commands/build.py `
  cli_anything/unreal/core/tasks.py cli_anything/unreal/tests/test_build.py `
  cli_anything/unreal/skills/references/commands.md `
  docs/superpowers/specs/2026-07-14-targeted-cook-options-design.md `
  docs/superpowers/plans/2026-07-14-targeted-cook-options-plan.md
git commit -m "feat(build): expose targeted cook options"
```

- [ ] **Step 5: Push both configured remotes**

Run:

```powershell
git push origin main
git push gongfeng main
```

Expected: both pushes update `main` to the implementation commit.
