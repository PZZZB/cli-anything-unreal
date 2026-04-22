# Test Guide

## Unit Tests

```bash
cd F:\workspace\CLI-Anything\unreal\agent-harness
pip install -e ".[dev]"
python -m pytest cli_anything/unreal/tests/test_core.py cli_anything/unreal/tests/test_editor_startup_precheck.py -q
```

## Bounded E2E Smoke

Use the F:\Test574 project by default, require JSON protocol, and either verify an already-running editor or auto-launch it with a hard timeout.

```bash
set UE_TEST_PROJECT=F:\Test574\Test574.uproject
python -m pytest cli_anything/unreal/tests/test_full_e2e.py -q --e2e --e2e-smoke --e2e-auto-launch --e2e-launch-timeout 180
```

Behavior:
- If the editor is already reachable, tests proceed immediately.
- If it is not reachable and `--e2e-auto-launch` is absent, tests fail fast instead of hanging.
- If `--e2e-auto-launch` is present, the suite runs `editor launch --timeout <N>` and fails clearly on launch error or timeout.

## Full E2E

The current suite is intentionally reduced to a bounded smoke subset until the rest of the legacy E2E cases are migrated to the new `--output json` protocol and explicit launch gating.


Current environment note:
- F:\Test574\Test574.uproject preflight passes, but auto-launch currently times out because the editor process starts without exposing the Remote Control API on port 30010. Smoke E2E therefore cannot be marked passing on this machine until that project-side startup issue is fixed.

