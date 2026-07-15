# Test Guide

## Unit Tests

```bash
cd F:\workspace\CLI-Anything\unreal\agent-harness
pip install -e ".[dev]"
python -m pytest cli_anything/unreal/tests/ -q
```

## Bounded E2E Smoke

Default project: `F:\Test574`. Requires JSON protocol. Verifies existing editor or auto-launches with hard timeout.

```bash
set UE_TEST_PROJECT=F:\Test574\Test574.uproject
python -m pytest cli_anything/unreal/tests/test_full_e2e.py -q --e2e --e2e-smoke --e2e-auto-launch --e2e-launch-timeout 180
```

Behavior:
- Reachable editor -> tests run.
- Not reachable + no `--e2e-auto-launch` -> fail fast.
- `--e2e-auto-launch` -> run `editor launch --timeout <N>`, fail clearly on launch error/timeout.

## Full E2E

Suite stays bounded smoke until legacy E2E migrates to `--output json` protocol + explicit launch gating.

Current machine note:
- `F:\Test574\Test574.uproject` preflight passes.
- Auto-launch currently times out: editor starts but Remote Control API not exposed on port 30010.
- Smoke E2E cannot be called passing here until project-side startup fixed.
