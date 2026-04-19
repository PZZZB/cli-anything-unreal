---
name: unreal-engine-cli
description: |
  Control Unreal Engine 5 editor via the cli-anything-unreal CLI tool.
  Use this skill whenever the user wants to interact with UE5 — launching the editor,
  editing materials, querying scenes/actors, managing blueprints, taking screenshots,
  building/cooking/packaging, or running Python scripts inside the editor.
  TRIGGER on any mention of Unreal Engine, UE5, UE editor, materials, blueprints,
  levels, actors, meshes, shaders, HLSL, or game development workflows involving
  an Unreal project — even if the user doesn't explicitly mention "CLI" or "cli-anything".
  Also trigger on Chinese equivalents: 虚幻引擎, 材质, 蓝图, 关卡, 场景, 编译, 打包,
  截图, actor, .uproject files, cook, compile, or any UE5 asset path like /Game/...
---

# Unreal Engine CLI Skill

You are an AI agent with access to `cli-anything-unreal`, a CLI tool that controls Unreal Engine 5 editor. Your users are UE5 game developers.

Before running any commands, verify the CLI is installed: `cli-anything-unreal --version`.

## Core Principles

**Query First, Then Set.** Before modifying any UE object property, always query its reflection info with `editor api-discover` to discover the correct property names and types. Never guess property names or types — UE's Python API requires exact types (e.g., `unreal.LinearColor`, not a tuple string). This applies to all operations: material nodes, actor properties, blueprint variables, etc.

**Two-step discovery.** `editor api-discover` mirrors how people use the Details panel — glance first, then hover for details:
1. **Overview** (default): `editor api-discover ClassName` — returns property/function **names** only. Quick scan of what's available.
2. **Detail** (on demand): `editor api-discover ClassName -d Prop1,Func2` — returns full info (tooltips, categories, parameter types, return types, read/write) for the **specific** items you care about. Comma-separated names let you get multiple details in one call.

**CLI is the interface to UE5.** All engine operations go through CLI commands — direct file manipulation bypasses engine locks and reference tracking, causing corruption. Read `references/safety.md` before any destructive operation.

**Prefer `cli-anything-unreal ... editor launch --wait` for normal startup.** `editor launch` and `editor status` both return `startup_precheck` in JSON for startup blockers (BuildId/module mismatch). If a workflow must launch the editor externally (e.g., RenderDoc/frame-capture injection), that is allowed; when startup appears stuck, use `cli-anything-unreal ... editor status` (with the intended `--port`) plus `editor list` to diagnose runtime API/dialog blocking.

**Always pass `--json`.** Parse the structured JSON block in output. UE warning logs may appear before the JSON — extract the JSON block, not the raw stdout.

**Specify `--project` on the first command.** Subsequent commands in the same shell session inherit it automatically.

**Prefer CLI commands over Python scripts.** Most operations already have dedicated commands. Check `references/commands.md` first. Only fall back to `editor run-script` when no CLI command covers the operation.

**UE asset boundary — two hard rules:**
1. `.uasset` is a proprietary binary format. Writing text to a `.uasset` file with generic file-write tools will corrupt it instantly. Create assets via `editor run-script` + UE Python API.
2. Scripts with `import unreal` require the engine runtime. Run them via `editor run-script`, not OS `python` (which lacks the `unreal` module).

**Use UE virtual paths** (`/Game/MyAsset`) when interacting with engine assets, not OS filesystem paths with `.uasset` extensions.

**Clean up temp files.** After executing a temporary Python script or writing output to a temp file, delete it to keep the workspace clean.

**Protect your context window.** Commands like `blueprint info` or `editor api-discover` can return large outputs. If you only need a single field, either redirect to a temp JSON file and parse it, or use targeted commands like `scene property`.

## Decision Flow

When the user asks you to do something in Unreal:

1. **Is the editor running?** Run `editor status`. If not reachable, read `references/workflows-editor.md` and follow the Editor Lifecycle flow.
2. **Do you know the asset path?** If not, discover it with `material list`, `blueprint list`, `scene list`, or `asset list`. These return class names too.
3. **Do you know what properties/functions this object has?** Use `editor api-discover <path-or-class>` for an overview (names only), then `-d Name1,Name2` for details (types, tooltips, params). You can pass a class name, an asset path (`/Game/...`), or an actor path — it auto-detects the type.
4. **Does a CLI command exist for this?** Read `references/commands.md` to find the right command.
5. **No CLI command covers it?** Write and run a Python script with `editor run-script`, using the reflection data from step 3 to get correct property names and types. Delete the script afterwards.
6. **Need visual verification?** Use `screenshot capture` and review the image.

If a command fails, check the JSON `error` field. Common causes: connection refused (editor not running), timeout (editor busy — retry after 10-15s), asset not found (wrong path — use list commands to discover).

## Reference Files — Load on Demand

| When you need to... | Read this file |
|------|------|
| Find the right CLI command or its arguments | `references/commands.md` |
| Launch, close, or troubleshoot the editor; write Python scripts | `references/workflows-editor.md` |
| Edit materials, write HLSL, inspect shaders | `references/workflows-materials.md` |
| Manipulate assets, query scenes, edit blueprints | `references/workflows-assets-scenes.md` |
| Delete/overwrite assets, or before any destructive operation | `references/safety.md` |

Read the relevant file before attempting the operation. Do not guess commands or workflows from memory.
