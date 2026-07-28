# ue-cli

AI-agent CLI harness for Unreal Engine 5. Agents control UE editor from shell: material analysis, Blueprint edits, screenshots, build/cook/package, JSON results.

### CLI vs Raw API

For coding agents, CLI beats raw UE Remote Control:

* **Token-efficient**: short commands, no giant schemas/raw JSON/engine internals in context.
* **Workflow-safe**: wraps UE traps: references, dirty-package saves, modal avoidance, MSYS2 path fix.
* **Agent-shaped output**: errors/crashes/results become JSON or concise text agents can parse.

### Runner Output Contract

JSON mode emits one final machine-readable payload on stdout. Progress, heartbeats, diagnostics go stderr.

Runners: stream stderr live. For stdout, either stream live or replay captured stdout once, not both, or final JSON duplicates.

### Requirements

* Python 3.10+
* Unreal Engine 5.x with Remote Control API plugin
* Cursor, Claude Code, GitHub Copilot, or any coding agent

## Getting Started

### Installation

```bash
# Install the package
pip install ue-cli
# (Or for local development: pip install -e .)
```

### Installing Skills

Install agent skill docs:

```bash
ue-cli install-skills
```

## How to Prompt Your Agent (Demo)

Agent runs commands behind scenes:

```text
> Use ue-cli skills to analyze the material /Game/MyMaterial.
  Fix any issues found and take a screenshot before and after.
```

### Skills-less operation

Without installed skills, point agent at built-in help:

```text
> Use ue-cli to check the project status.
  Check ue-cli --help for available commands.
```

## Features

- **Project Management**: parse `.uproject`, read/write `.ini`, list content assets
- **Build System**: compile, cook, package via UAT/UBT
- **Material Analysis**: list/inspect/analyze/edit materials
- **Blueprint Management**: view graphs, edit variables/functions, compile
- **Screenshot**: capture viewport, compare screenshots, CVar A/B
- **Editor Control**: console commands, CVars, Python scripts, status

## Architecture

Two backends:
- **UAT/UBT** subprocess: build/cook/package, no editor needed
- **HTTP API** localhost:30010: materials, blueprints, screenshots, console, Python, editor required

## Multi-Instance Support

Multiple UE editors can run on different ports:

```bash
ue-cli --port 30010 editor status
ue-cli --port 30011 material list
```

Use `editor status` to discover running instances.

## Quick Start (Manual Usage)

```bash
# Check CLI
ue-cli --help

# Project info (no editor needed)
ue-cli --project F:\path\to\MyProject.uproject project info

# Check editor status
ue-cli editor status

# Material analysis workflow
ue-cli --output json material list
ue-cli --output json material analyze /Game/MyMaterial
ue-cli --output json screenshot capture --filename material_check
ue-cli --output json screenshot capture --filename stat_evidence --include-ui
```

## Known Engine Bugs

UE Remote Control + Python have UE 5.7 automation bugs. See [ENGINE_BUGS.md](ENGINE_BUGS.md) for issues, workarounds, engine-source fixes.

## Agent Workflow

```
list materials -> analyze -> fix -> screenshot verify
```
