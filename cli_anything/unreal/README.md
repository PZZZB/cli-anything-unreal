# cli-anything-unreal

AI Agent CLI harness for Unreal Engine 5. Enables AI agents to control UE editor via command-line for material analysis, blueprint editing, screenshot verification, and build automation.

### CLI vs Raw API

Why use a CLI instead of giving the Agent direct access to the UE HTTP Remote Control API? If you are using **coding agents**, CLI is the best fit:

* **Token-efficient**: CLI invocations are significantly more token-efficient. They avoid loading verbose API schemas, massive raw JSON responses, and complex engine internals into the model context. This allows agents to act through concise, purpose-built commands.
* **Handling Common Stuck Points**: The CLI encapsulates multi-step workflows into robust single commands. It handles UE-specific nuances automatically (such as resolving references, auto-saving dirty packages, bypassing modal dialog blocks, and normalizing path mangling from terminals like MSYS2).
* **Agent-Optimized Outputs**: Errors, engine crashes, and query results are specifically formatted as structured JSON or concise text for agents to easily parse and act upon.

### Requirements

* Python 3.10 or newer
* Unreal Engine 5.x (with Remote Control API plugin enabled)
* Cursor, Claude Code, GitHub Copilot, or any other coding agent.

## Getting Started

### Installation

```bash
# Install the package
pip install cli-anything-unreal
# (Or for local development: pip install -e .)
```

### Installing Skills

Cursor, Claude Code, and other coding agents can automatically use locally installed skills to understand how to interact with the project:

```bash
cli-anything-unreal install-skills
```

## How to Prompt Your Agent (Demo)

Your coding agent will be running the commands behind the scenes. Point your agent at the CLI and let it work:

```text
> Use cli-anything-unreal skills to analyze the material /Game/MyMaterial.
  Fix any issues found and take a screenshot before and after.
```

### Skills-less operation

Even if you don't install the skills explicitly, you can just tell your agent to figure it out using the built-in help:

```text
> Use cli-anything-unreal to check the project status. 
  Check cli-anything-unreal --help for available commands.
```

## Features

- **Project Management**: Parse `.uproject`, read/write `.ini` configs, list content assets
- **Build System**: Compile, cook, and package via UAT/UBT subprocess calls
- **Material Analysis**: List materials, inspect nodes/parameters/textures, auto-detect issues (requires running editor)
- **Blueprint Management**: View graphs, edit variables/functions, recompile (requires running editor)
- **Screenshot**: Capture viewport, compare screenshots, CVar A/B testing (requires running editor)
- **Editor Control**: Execute console commands, get/set CVars, run Python scripts, check editor status

## Architecture

Two backends:
- **UAT/UBT** (subprocess): build, cook, package — no editor needed
- **HTTP API** (localhost:30020): materials, blueprints, screenshots, console commands — requires running editor with AutomationTestAPI plugin

## Multi-Instance Support

Multiple UE editors can run simultaneously. Use `--port` to target a specific instance:

```bash
cli-anything-unreal --port 30020 editor status
cli-anything-unreal --port 30021 material list
```

Use `editor list` to discover all running instances.

## Quick Start (Manual Usage)

You can still use the CLI manually to inspect and control the editor:

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