---
name: unreal-engine-cli
description: |
  Control Unreal Engine 5 editor via the cli-anything-unreal CLI tool.
  Use this skill whenever the user wants to interact with UE5 — launching the editor,
  editing materials, querying scenes/actors, managing blueprints, taking screenshots,
  capturing GPU frames with RenderDoc, building/cooking/packaging, or running Python
  scripts inside the editor.
  TRIGGER on any mention of Unreal Engine, UE5, UE editor, materials, blueprints,
  levels, actors, meshes, shaders, HLSL, RenderDoc, GPU frame capture, .rdc files,
  or game development workflows involving an Unreal project — even if the user
  doesn't explicitly mention "CLI" or "cli-anything".
  Also trigger on Chinese equivalents: 虚幻引擎, 材质, 蓝图, 关卡, 场景, 编译, 打包,
  截图, 截帧, actor, .uproject files, cook, compile, or any UE5 asset path like /Game/...
---

# Unreal Engine CLI Skill

You are an AI agent with access to `cli-anything-unreal`, a CLI tool that controls Unreal Engine 5 editor. Your users are UE5 game developers.

Before running any commands, verify the CLI is installed: `cli-anything-unreal --version`.

## Core Principles

**Query First, Then Set.** Before modifying any UE object property, always query its reflection info with `editor api-discover` to discover the correct property names and types. Never guess property names or types — UE's Python API requires exact types (e.g., `unreal.LinearColor`, not a tuple string). This applies to all operations: material nodes, actor properties, blueprint variables, etc. Use two-step discovery — glance first, then hover for details:
1. **Overview** (default): `editor api-discover ClassName` — returns property/function **names** only.
2. **Detail** (on demand): `editor api-discover ClassName -d Prop1,Func2` — returns full info (tooltips, categories, parameter types, return types, read/write) for the items you name.

**CLI is the interface to UE5.** All engine operations go through the `cli-anything-unreal` tool (dedicated subcommands *or* `editor run-script`) — direct file manipulation bypasses engine locks and reference tracking, causing corruption. Read `references/safety.md` before any destructive operation.

**Prefer CLI subcommands; fall back to `editor run-script` immediately.** `references/commands.md` is the complete subcommand list — if the operation you need is not there, don't spend turns verifying the command's absence (e.g., searching the CLI source code or trying name variations). Write a Python script and run it with `editor run-script` instead; this is the designed escape hatch and the fastest path forward.

**UE asset boundary — two hard rules:**
1. `.uasset` is a proprietary binary format. Writing text to a `.uasset` file with generic file-write tools will corrupt it instantly. Create assets via `editor run-script` + UE Python API.
2. Scripts with `import unreal` require the engine runtime. Run them via `editor run-script`, not OS `python` (which lacks the `unreal` module).

## Usage Conventions

- **JSON by default.** CLI output defaults to JSON for non-TTY callers (AI agents). If you ever need to force it explicitly, `--output json` is a top-level flag and must appear BEFORE the subcommand:
  - ✅ `cli-anything-unreal --output json editor launch`
  - ❌ `cli-anything-unreal editor launch --output json`
- **Runner output contract.** In JSON mode, stdout is one final machine-readable payload. Progress/heartbeats belong on stderr. If your command runner streams stdout live, do not replay captured stdout at completion or the final JSON will appear twice.
- **Discover running editors with `editor status`.** It returns a result array; each item has `status`, `pid`, `port`, and `project_path`. Use `--port` from an online item to target a specific running editor. If an item is `offline`, follow its `next_command`. Offline build commands still need `--project`.
- **Use UE virtual paths** (`/Game/MyAsset`) when interacting with engine assets, not OS filesystem paths with `.uasset` extensions.
- **Use `editor launch` for normal startup.** It blocks until the editor API is online (or timeout). For async launch, use `--no-wait` and poll with `editor status <task_id>` or generic `task status <task_id>`.
- **`editor launch` auto-handles zombie processes.** Stale `UnrealEditor.exe` processes (no API response) are killed automatically. Only `ALREADY_RUNNING` (API alive) blocks the launch.
- **Clean up temp files.** After executing a temporary Python script or writing output to a temp file, delete it to keep the workspace clean.
- **Protect your context window.** Commands like `blueprint info` or `editor api-discover` can return large outputs. If you only need a single field, either redirect to a temp JSON file and parse it, or use targeted commands like `scene property`.

## Decision Flow

When the user asks you to do something in Unreal:

1. **Is the editor running?** Run `editor status`. If the matching result item is not `online`, read `references/workflows-editor.md` and follow the Editor Lifecycle flow.
2. **Do you know the asset path?** If not, discover it with `material list`, `blueprint list`, `scene list`, or `asset list`. These return class names too.
3. **Do you know what properties/functions this object has?** Use `editor api-discover <target>` for an overview, then `-d Name1,Name2` for details. TARGET can be a class name, asset path, actor path, or component subobject path. For actors, the response includes a `components` tree; drill into `components[].path` when the functional property lives on a component (e.g. `DirectionalLight.Intensity` is on `LightComponent0`). **Don't know which class to query?** See "UE Python API — Class Lookup" in `references/workflows-editor.md`.
4. **Does a CLI subcommand exist for this?** Check `references/commands.md`. If not listed, go to step 5.
5. **No subcommand?** Write a Python script and run it with `editor run-script`. Use the reflection data from step 3 for correct property names and types. See `references/workflows-editor.md` for scripting patterns. Delete the script afterwards.
6. **Need visual verification?** Use `screenshot capture` and review the image.
7. **Need GPU-level debugging?** Use `editor exec "renderdoc.captureframe"` to capture a GPU frame, then analyze the `.rdc` file. See `references/workflows-editor.md` § "RenderDoc Frame Capture".

If a command fails, check the JSON `error` field. Common causes: connection refused (editor not running), timeout (editor busy — retry after 10-15s), asset not found (wrong path — use list commands to discover).

## Reference Files — Load on Demand

| When you need to... | Read this file |
|------|------|
| Find the right CLI command or its arguments | `references/commands.md` |
| Launch, close, or troubleshoot the editor; write Python scripts | `references/workflows-editor.md` |
| Jump Level Viewport bookmarks or verify viewport camera | `references/workflows-editor.md` § "Viewport Bookmarks" |
| Find which UE class has the function you need (API lookup) | `references/workflows-editor.md` § "UE Python API — Class Lookup" |
| Capture a RenderDoc GPU frame, debug shaders or draw calls | `references/workflows-editor.md` § "RenderDoc Frame Capture" |
| Edit materials, write HLSL, inspect shaders | `references/workflows-materials.md` |
| Manipulate assets, query scenes, edit blueprints | `references/workflows-assets-scenes.md` |
| Delete/overwrite assets, or before any destructive operation | `references/safety.md` |

Read the relevant file before attempting the operation. Do not guess commands or workflows from memory.
