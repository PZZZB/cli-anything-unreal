# cli-anything-unreal

AI Agent CLI harness for Unreal Engine 5.7. Enables AI agents to control UE editor via command-line for material analysis, screenshot verification, and build automation.

## Features

- **Project Management**: Parse `.uproject`, read/write `.ini` configs, list content assets
- **Build System**: Compile, cook, and package via UAT/UBT subprocess calls
- **Material Analysis**: List materials, inspect nodes/parameters/textures, auto-detect issues (requires running editor)
- **Screenshot**: Capture viewport, compare screenshots, CVar A/B testing (requires running editor)
- **Editor Control**: Execute console commands, get/set CVars, check editor status

## Architecture

Two backends:
- **UAT/UBT** (subprocess): build, cook, package — no editor needed
- **HTTP API** (localhost:30020): materials, screenshots, console commands — requires running editor with AutomationTestAPI plugin

## Multi-Instance Support

Multiple UE editors can run simultaneously. Use `--port` to target a specific instance:

```bash
cli-anything-unreal --port 30020 editor status
cli-anything-unreal --port 30021 material list
```

Use `editor list` to discover all running instances.

## Installation

```bash
pip install -e .
```

## Quick Start

```bash
# Check CLI
cli-anything-unreal --help

# Project info (no editor needed)
cli-anything-unreal project info --project F:\path\to\MyProject.uproject

# Check editor status
cli-anything-unreal editor status

# Material analysis workflow
cli-anything-unreal --json material list
cli-anything-unreal --json material analyze /Game/MyMaterial
cli-anything-unreal --json screenshot take --filename material_check

# Interactive mode
cli-anything-unreal repl
```

## Agent Workflow

```
查材质 → 发现问题 → 改材质 → 截图验证
list materials → analyze → fix → screenshot verify
```
