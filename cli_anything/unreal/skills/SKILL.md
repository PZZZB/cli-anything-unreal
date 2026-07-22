---
name: ue-cli
description: |
  Control Unreal Engine 5 editor via `ue-cli`.
  Use whenever user wants UE5 work: launch editor, materials, scenes/actors,
  blueprints, screenshots, RenderDoc GPU frames, build/cook/package, or run
  Python inside editor.
  TRIGGER on Unreal Engine, UE5, UE editor, materials, blueprints, levels,
  actors, meshes, shaders, HLSL, RenderDoc, GPU frame capture, .rdc, .uproject,
  cook, compile, /Game/... asset paths, or Chinese: 虚幻引擎, 材质, 蓝图, 关卡,
  场景, 编译, 打包, 截图, 截帧.
---

# Unreal Engine CLI Skill

You have `ue-cli`, a CLI controlling Unreal Engine 5 editor. Users are UE5 developers.

Verify install first: `ue-cli --version`.

## Core Principles

**Query First, Then Set.** Before changing any UE object property, query reflection with `editor api-discover`. Never guess names/types. UE Python needs exact types (`unreal.LinearColor`, not tuple string). Use:
1. **Overview**: `editor api-discover ClassName` -> property/function names.
2. **Detail**: `editor api-discover ClassName -d Prop1,Func2` -> tooltips, categories, param/return types, read/write.

**CLI is the interface to UE5.** All engine ops go through `ue-cli` subcommands or `editor run-script`. Direct file writes bypass locks/ref tracking and corrupt assets. Read `references/safety.md` before destructive work.

**Prefer subcommands; fall back fast to `editor run-script`.** `references/commands.md` is complete. If command not listed, stop searching variants; write UE Python and run it. That is intended escape hatch.

**UE asset boundary - hard rules:**
1. `.uasset` is proprietary binary. Generic text/file writes corrupt it. Create/edit assets through UE Python via `editor run-script`.
2. `import unreal` needs engine runtime. Run such scripts through `editor run-script`, not OS `python`.

## Usage Conventions

- **JSON by default.** Non-TTY callers get JSON. To force it, `--output json` is top-level and must appear before subcommand:
  - OK: `ue-cli --output json editor launch`
  - Bad: `ue-cli editor launch --output json`
- **Runner output contract.** JSON mode stdout = one final payload. Progress/heartbeats -> stderr. Do not stream stdout live then replay captured stdout, or JSON duplicates.
- **Long-running caller contract.** A tool result with `session_id` but no `exit_code` is a yield, not command completion; keep polling that session until process exit and the final JSON. Do not start status/stop recovery merely because a synchronous command yielded partial or empty output.
- **Build log visibility.** Synchronous `build compile` / `build cook` / `build package` stream live UAT/UBT log text to stderr while preserving final JSON on stdout. Repeated MSVC command-line warnings are folded in the live stream; `log_file` keeps every original line.
- **Discover editors with `editor status`.** Project-scoped status accepts either top-level `ue-cli --project PATH editor status` or subcommand `ue-cli editor status --project PATH`; use `editor status --all` to list other projects too. Result array items: `status`, `pid`, `port`, `project_path`. Online items include `bridge_version`, `bundled_version`, `plugin_match` (`true`/`false`/`null` when probe is busy). A mismatch enters `remote_control_only` mode: `editor run-script --no-save` remains available without restart, while `upgrade_command` is needed only for bridge-backed commands. `--no-save` disables ue-cli's automatic dirty-package save; it does not sandbox script side effects. `unreachable` means the editor process is alive but Remote Control may be temporarily busy during PIE/loading; retry the reported status command instead of relaunching. `offline` with `next_command` appears only after stale grace or clear failure. Build commands need a project.
- **Use UE virtual paths** (`/Game/MyAsset`) for engine assets, not OS `.uasset` paths.
- **Multiline Python.** Use `editor run-script -` with stdin for multiline snippets, especially in PowerShell; keep `-c` for one-liners and file paths for reusable scripts.
- **Use `editor launch` for normal startup.** It launches an interactive editor by default so UE confirmation dialogs remain usable. Pass `--unattended` only when dialogs must be suppressed; `--no-unattended` explicitly selects the interactive default. The command waits until the API is online, then returns a pollable `launching` task after a bounded foreground wait if startup is still in progress. `--timeout` controls the background startup deadline, not how long the caller must stay attached. For async: `--no-wait`, then poll `editor status <task_id>` or `task status <task_id>`.
- **Zombie handling.** `editor launch` kills stale `UnrealEditor.exe` only after status grace or when no active launch task owns it. Temporary `unreachable`/`launching` states should be polled, not killed. Only API-alive `ALREADY_RUNNING` blocks launch.
- **Clean temp files** after temporary Python scripts/output.
- **Protect context.** Large commands (`blueprint info`, `api-discover`) can flood. Redirect to temp JSON and parse, or use targeted commands (`scene property`).

## Decision Flow

When user asks UE work:

1. **Editor running?** Run `editor status`. If not online, read `references/workflows-editor.md` and follow lifecycle.
2. **Asset/actor path known?** If not, discover via `material list`, `blueprint list`, `scene list`, or `asset list`.
3. **Properties/functions known?** Use `editor api-discover <target>` overview, then `-d Name1,Name2`. Target can be class, asset path, actor path, component path. For actors, use `components[].path` when property lives on component (e.g. light intensity on `LightComponent0`). Unknown class? See `references/workflows-editor.md` "UE Python API - Class Lookup".
4. **Subcommand exists?** Check `references/commands.md`. If no, step 5.
5. **No subcommand?** Write Python, run `editor run-script`, using reflection data for exact names/types. Delete script after.
6. **Need visual proof?** `screenshot capture`, inspect image.
7. **Need GPU debug?** `editor exec "renderdoc.captureframe"`, analyze `.rdc`; see RenderDoc workflow.

Failures: inspect JSON `error`. Common causes: connection refused (editor down), timeout (editor busy, retry 10-15s), asset not found (wrong path, use list commands).

## Reporting ue-cli Problems

Treat every ue-cli tool or skill problem as improvement evidence. Submit it to the central GitHub Issues queue at https://github.com/PZZZB/cli-anything-unreal/issues. Prefer connected GitHub tooling when available; otherwise run `gh issue create --repo PZZZB/cli-anything-unreal`.

Include the ue-cli version, environment, exact command, expected behavior, actual behavior, a minimal reproduction, and sanitized logs. After submission, emit exactly `工具坑已提交：ue-cli -> {issue_url}`, replacing `{issue_url}` with the created Issue URL. Do not send ue-cli issues to a Codex conversation ID.

## Reference Files - Load on Demand

| When you need to... | Read this file |
|------|------|
| Find CLI command/args | `references/commands.md` |
| Launch/close/troubleshoot editor; write Python scripts | `references/workflows-editor.md` |
| Jump viewport bookmarks / verify viewport camera | `references/workflows-editor.md` "Viewport Bookmarks" |
| Find UE class/function for API lookup | `references/workflows-editor.md` "UE Python API - Class Lookup" |
| Capture RenderDoc frame, debug shaders/draw calls | `references/workflows-editor.md` "RenderDoc Frame Capture" |
| Edit materials, HLSL, shader inspection | `references/workflows-materials.md` |
| Manipulate assets, scenes, blueprints | `references/workflows-assets-scenes.md` |
| Delete/overwrite assets; destructive ops | `references/safety.md` |

Read relevant file before acting. Do not guess commands/workflows from memory.
