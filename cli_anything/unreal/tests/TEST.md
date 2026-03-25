# Test Guide

## Unit Tests (test_core.py)

Run without any external dependencies:

```bash
cd F:\workspace\CLI-Anything\unreal\agent-harness
pip install -e ".[dev]"
pytest cli_anything/unreal/tests/test_core.py -v
```

Tests cover:
- Project parsing (.uproject, .ini configs, content listing)
- Engine discovery (engine root, editor exe, UAT/Build.bat)
- Session management (undo/redo, save/load, history)
- Build status checking
- HTTP API (mocked)
- Material analysis (mocked)
- CLI interface (Click test runner)

## E2E Tests (test_full_e2e.py)

Require a running UE editor with AutomationTestAPI plugin:

```bash
# Set environment
set UE_TEST_PROJECT=F:\Test_RXEngine_5_7\Test_RXEngine_5_7.uproject
set UE_TEST_PORT=30020

# Run E2E tests
pytest cli_anything/unreal/tests/test_full_e2e.py -v --e2e
```

E2E tests cover:
- Editor connection
- Project info queries
- Material listing and analysis
- Screenshot capture
- Console command execution

## Multi-Instance Testing

To test with multiple editors, start editors on different ports and run:

```bash
set UE_TEST_PORT=30021
pytest cli_anything/unreal/tests/test_full_e2e.py -v --e2e
```
