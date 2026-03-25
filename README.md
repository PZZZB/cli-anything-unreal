# cli-anything-unreal

AI Agent CLI harness for Unreal Engine 5.7. Enables AI agents to control UE editor via command-line for material analysis, Blueprint editing, screenshot verification, and build automation.

## Features

- **Project Management**: Parse `.uproject`, read/write `.ini` configs, list content assets
- **Build System**: Compile, cook, and package via UAT/UBT subprocess calls
- **Material Analysis**: List materials, inspect nodes/parameters/textures, auto-detect issues, dump HLSL
- **Blueprint Editing**: List/inspect blueprints, add functions/variables, compile
- **Scene Queries**: List actors, find by name, get/set properties, inspect transforms
- **Screenshot**: Capture viewport, compare screenshots, CVar A/B testing
- **Editor Control**: Execute console commands, run Python scripts, get/set CVars

## Architecture

Two backends:

- **UAT/UBT** (subprocess): build, cook, package — no editor needed
- **HTTP Remote Control API** (localhost): materials, blueprints, scenes, screenshots — requires running editor

See [UNREAL.md](UNREAL.md) for detailed architecture documentation.

## Installation

```bash
pip install git+https://github.com/PZZZB/cli-anything-unreal.git
```

Update to latest version:

```bash
pip install --upgrade git+https://github.com/PZZZB/cli-anything-unreal.git
```

## Quick Start

```bash
# Check CLI
cli-anything-unreal --help

# Project info (no editor needed)
cli-anything-unreal project info --project F:\path\to\MyProject.uproject

# Build (no editor needed)
cli-anything-unreal build compile --project F:\path\to\MyProject.uproject

# Check editor status
cli-anything-unreal editor status

# Material analysis workflow
cli-anything-unreal --json material list
cli-anything-unreal --json material analyze /Game/MyMaterial
cli-anything-unreal --json screenshot take --filename material_check

# Interactive mode
cli-anything-unreal repl
```

## Multi-Instance Support

Multiple UE editors can run simultaneously. Use `--port` to target a specific instance:

```bash
cli-anything-unreal --port 30020 editor status
cli-anything-unreal --port 30021 material list
```

Use `editor list` to discover all running instances.

## Agent Workflow

```
查材质 → 发现问题 → 改材质 → 截图验证
list materials → analyze → fix → screenshot verify
```

## Requirements

- Python >= 3.10
- Unreal Engine 5 (for build operations)
- Running UE editor with Remote Control plugin enabled (for editor operations)

## Issues & Feedback

Please open an issue at [GitHub Issues](https://github.com/PZZZB/cli-anything-unreal/issues).
