"""unreal_cli.py — Click CLI main entry point for cli-anything-unreal.

Provides commands for:
  - project: Project management (.uproject, configs, content)
  - build: Compile, cook, package via UAT/UBT
  - material: Material inspection and analysis (requires running editor)
  - blueprint: Blueprint viewing and editing (requires running editor)
  - screenshot: Viewport capture and comparison (requires running editor)
  - editor: Editor status, console commands, CVars
  - repl: Interactive REPL mode
"""

import io
import json
import shlex
import sys
from pathlib import Path
from typing import Optional

# ── Fix Windows GBK terminal encoding for Unicode output (✓✗⚠●◆) ────
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import click

from cli_anything.unreal.core.session import Session
from cli_anything.unreal.utils.repl_skin import ReplSkin

# ── Global state ────────────────────────────────────────────────────────

_json_output: bool = False
_session: Session = Session()
_skin = ReplSkin("unreal", version="0.1.1")
_in_repl: bool = False


def get_session() -> Session:
    return _session


def get_api():
    """Get a connected UEEditorAPI instance."""
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI
    return UEEditorAPI(port=_session.port)


# ── Path helpers ───────────────────────────────────────────────────────

def _fix_ue_path(path: str) -> str:
    """Normalize a UE content path — no-op for valid paths.

    Kept as a safety net at the command level, but the main fix
    is in main() which patches sys.argv before Click parses it.
    """
    return path


def _fix_argv_msys2():
    """Fix MSYS2 (Git Bash) path mangling in sys.argv BEFORE Click parses.

    MSYS2 auto-converts any argument starting with / to a Windows path
    when calling non-MSYS .exe programs:
        /Game/M_Test  ->  D:/Git/Game/M_Test
        /Engine/...   ->  D:/Git/Engine/...

    Detection: if an argv looks like a Windows absolute path (X:/...)
    but that path does NOT exist on disk, it was almost certainly mangled.
    Restore it to /remainder (strip the drive + MSYS prefix).

    This runs once at startup and is invisible to the user.
    """
    import os
    fixed = []
    for arg in sys.argv:
        if (
            len(arg) >= 3
            and arg[0].isalpha()
            and arg[1] == ":"
            and arg[2] in ("/", "\\")
            and not os.path.exists(arg)          # real disk path? leave it alone
            and not os.path.exists(arg.split("*")[0])  # glob pattern guard
        ):
            # Strip drive + leading prefix, restore as /...
            rest = arg[2:].replace("\\", "/")    # ":/Git/Game/M_Test" -> "/Git/Game/M_Test"
            # MSYS2 prepends its install dir, e.g. D:/Git -> /Git is the root
            # The original arg was just /Game/M_Test, which became D:/Git/Game/M_Test
            # We need to strip everything up to (but not including) the first path
            # component that the user actually typed.
            # Heuristic: the MSYS root is the part that exists on disk.
            # Walk from the left, find the longest prefix that is a real directory.
            parts = rest.strip("/").split("/")
            msys_prefix_len = 0
            for i in range(len(parts)):
                candidate = arg[0:3] + "/".join(parts[:i + 1])
                if os.path.isdir(candidate):
                    msys_prefix_len = i + 1
                else:
                    break
            # Restore: skip the MSYS prefix directories
            restored = "/" + "/".join(parts[msys_prefix_len:])
            fixed.append(restored)
        else:
            fixed.append(arg)
    sys.argv = fixed


# ── Output helpers ──────────────────────────────────────────────────────

def output(data):
    """Output data as JSON or pretty-printed."""
    if _json_output:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    elif isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                click.echo(f"  {k}: {json.dumps(v, indent=2, ensure_ascii=False, default=str)}")
            else:
                click.echo(f"  {k}: {v}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                click.echo(f"  {json.dumps(item, ensure_ascii=False, default=str)}")
            else:
                click.echo(f"  {item}")
    else:
        click.echo(str(data))


def handle_error(f):
    """Decorator for consistent error handling across commands."""
    import functools

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except FileNotFoundError as e:
            if _json_output:
                click.echo(json.dumps({"error": str(e)}))
            else:
                _skin.error(str(e))
            if not _in_repl:
                sys.exit(1)
        except ConnectionError as e:
            msg = f"Editor not reachable (port {_session.port}): {e}"
            if _json_output:
                click.echo(json.dumps({"error": msg}))
            else:
                _skin.error(msg)
                _skin.hint("Is the UE editor running with Remote Control plugin enabled?")
                _skin.hint(f"Try: cli-anything-unreal editor status --port {_session.port}")
            if not _in_repl:
                sys.exit(1)
        except Exception as e:
            if _json_output:
                click.echo(json.dumps({"error": str(e), "type": type(e).__name__}))
            else:
                _skin.error(f"{type(e).__name__}: {e}")
            if not _in_repl:
                sys.exit(1)

    return wrapper


def _require_project():
    """Ensure a project is loaded."""
    if not _session.is_loaded:
        raise click.UsageError(
            "No project loaded. Use --project or run: project info --project <path>"
        )


def _require_editor():
    """Ensure editor is reachable."""
    api = get_api()
    if not api.is_alive():
        raise ConnectionError(
            f"Editor HTTP API not responding on port {_session.port}"
        )
    return api


# ── Main CLI group ──────────────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.option("--json", "use_json", is_flag=True, help="Output in JSON format")
@click.option(
    "--project", "project_path", type=click.Path(),
    help="Path to .uproject file",
)
@click.option(
    "--port", type=int, default=30010,
    help="Editor Remote Control API port (default: 30010, for multi-instance support)",
)
@click.pass_context
def cli(ctx, use_json, project_path, port):
    """cli-anything-unreal — AI Agent CLI for Unreal Engine.

    Control UE editor via command-line: materials, screenshots, builds.

    Multi-instance: use --port to target a specific editor instance.
    """
    global _json_output
    _json_output = use_json
    _session.port = port

    if project_path:
        try:
            _session.load_project(project_path)
        except FileNotFoundError:
            if use_json:
                click.echo(json.dumps({"error": f"Project not found: {project_path}"}))
            else:
                _skin.error(f"Project not found: {project_path}")

    if ctx.invoked_subcommand is None:
        ctx.invoke(repl_cmd)


@cli.command("install-skills")
def install_skills():
    """Install AI agent skills for Cursor and Claude Code."""
    import os
    import shutil

    source_dir = Path(__file__).parent / "skills"
    if not source_dir.exists() or not source_dir.is_dir():
        _skin.error("Could not find skills directory in the package.")
        return

    # Install to current directory and global cursor
    targets = [
        Path.cwd() / ".cursor" / "skills" / "cli-anything-unreal",
        Path.cwd() / ".claude" / "skills" / "cli-anything-unreal",
        Path.home() / ".cursor" / "skills" / "cli-anything-unreal",
    ]

    installed = 0
    for target_dir in targets:
        try:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
            installed += 1
            if not _json_output:
                _skin.success(f"Installed skill to: {target_dir}")
        except Exception as e:
            if not _json_output:
                _skin.warning(f"Failed to install skill to {target_dir}: {e}")

    if _json_output:
        output({"status": "ok", "installed_count": installed})


# ══════════════════════════════════════════════════════════════════════
#  PROJECT commands
# ══════════════════════════════════════════════════════════════════════

@cli.group("project")
def project_group():
    """Project management — info, configs, content listing."""
    pass


@project_group.command("info")
@click.option("--project", "proj", type=click.Path(), help="Path to .uproject")
@handle_error
def project_info(proj):
    """Display project information."""
    from cli_anything.unreal.core.project import get_project_info

    path = proj or _session.project_path
    if not path:
        raise click.UsageError("No project specified. Use --project <path>")

    # If project was passed here, load it into session
    if proj and not _session.is_loaded:
        try:
            _session.load_project(proj)
        except Exception:
            pass

    info = get_project_info(path)
    output(info)


@project_group.group("config")
def config_group():
    """Read and modify project .ini configuration files."""
    pass


@config_group.command("list")
@handle_error
def config_list():
    """List all configuration files."""
    from cli_anything.unreal.core.project import list_configs

    _require_project()
    configs = list_configs(_session.project_dir)
    output(configs)


@config_group.command("get")
@click.argument("config_name")
@click.option("--section", help="Filter by section name")
@handle_error
def config_get(config_name, section):
    """Read a configuration file (e.g., DefaultEngine)."""
    from cli_anything.unreal.core.project import get_config

    _require_project()
    data = get_config(_session.project_dir, config_name)

    if section:
        data = {section: data.get(section, {})}

    output(data)


@config_group.command("set")
@click.argument("config_name")
@click.argument("section")
@click.argument("key")
@click.argument("value")
@handle_error
def config_set(config_name, section, key, value):
    """Set a configuration value."""
    from cli_anything.unreal.core.project import set_config

    _require_project()
    _session.snapshot(f"config set {config_name} [{section}] {key}")
    result = set_config(_session.project_dir, config_name, section, key, value)
    output(result)


@project_group.command("content")
@click.option("--ext", default="", help="Filter by extension (e.g., .uasset)")
@click.option("--filter", "path_filter", default="", help="Filter by path substring")
@click.option("--depth", default=5, help="Max directory depth")
@handle_error
def content_list(ext, path_filter, depth):
    """List content assets in the project."""
    from cli_anything.unreal.core.project import list_content

    _require_project()
    assets = list_content(_session.project_dir, filter_ext=ext, filter_path=path_filter, max_depth=depth)

    if _json_output:
        output({"assets": assets, "count": len(assets)})
    else:
        _skin.info(f"Found {len(assets)} assets")
        if assets:
            headers = ["Name", "Extension", "Content Path"]
            rows = [[a["name"], a["ext"], a.get("content_path", "")] for a in assets]
            _skin.table(headers, rows)


@project_group.command("generate")
@handle_error
def project_generate():
    """Generate Visual Studio project files."""
    from cli_anything.unreal.core.build import generate_project_files

    _require_project()
    result = generate_project_files(_session.project_path, _session.engine_root)
    output(result)


@project_group.command("asset-exists")
@click.argument("asset_path")
@handle_error
def project_asset_exists(asset_path):
    """Check if an asset exists at the given content path.

    Example: project asset-exists /Game/Materials/M_Water
    """
    from cli_anything.unreal.core.assets import asset_exists

    asset_path = _fix_ue_path(asset_path)
    api = _require_editor()
    result = asset_exists(api, asset_path, project_dir=_session.project_dir)
    output(result)


@project_group.command("asset-delete")
@click.argument("asset_path")
@click.option("--force", is_flag=True, default=False,
              help="Delete even if other assets reference it (they will have broken references).")
@handle_error
def project_asset_delete(asset_path, force):
    """Safely delete an asset with reference detection.

    Without --force: if other assets reference it, returns the list of
    referencers instead of deleting (avoids triggering modal dialogs).

    With --force: deletes regardless of references.

    Example: project asset-delete /Game/Materials/M_Old --force
    """
    from cli_anything.unreal.core.assets import asset_delete

    asset_path = _fix_ue_path(asset_path)
    api = _require_editor()
    result = asset_delete(api, asset_path, force=force, project_dir=_session.project_dir)
    output(result)


@project_group.command("asset-refs")
@click.argument("asset_path")
@handle_error
def project_asset_refs(asset_path):
    """List all assets that reference the given asset.

    Useful before deleting — shows what would break.

    Example: project asset-refs /Game/Materials/M_Water
    """
    from cli_anything.unreal.core.assets import asset_refs

    asset_path = _fix_ue_path(asset_path)
    api = _require_editor()
    result = asset_refs(api, asset_path, project_dir=_session.project_dir)
    output(result)


@project_group.command("asset-duplicate")
@click.argument("source_path")
@click.argument("dest_path")
@click.option("--force", is_flag=True, default=False,
              help="Overwrite destination if it already exists.")
@handle_error
def project_asset_duplicate(source_path, dest_path, force):
    """Duplicate an asset to a new path.

    With --force: if destination exists, deletes it first then duplicates.
    Without --force: fails if destination already exists.

    Example: project asset-duplicate /Game/M_Water /Game/M_Water_v2
    """
    from cli_anything.unreal.core.assets import asset_duplicate

    source_path = _fix_ue_path(source_path)
    dest_path = _fix_ue_path(dest_path)
    api = _require_editor()
    result = asset_duplicate(api, source_path, dest_path, force=force,
                             project_dir=_session.project_dir)
    output(result)


@project_group.command("asset-rename")
@click.argument("source_path")
@click.argument("dest_path")
@handle_error
def project_asset_rename(source_path, dest_path):
    """Rename/move an asset to a new path.

    Fails if destination already exists.

    Example: project asset-rename /Game/M_Old /Game/M_New
    """
    from cli_anything.unreal.core.assets import asset_rename

    source_path = _fix_ue_path(source_path)
    dest_path = _fix_ue_path(dest_path)
    api = _require_editor()
    result = asset_rename(api, source_path, dest_path,
                          project_dir=_session.project_dir)
    output(result)


# ══════════════════════════════════════════════════════════════════════
#  BUILD commands
# ══════════════════════════════════════════════════════════════════════

@cli.group("build")
def build_group():
    """Build system — compile, cook, package via UAT/UBT."""
    pass


@build_group.command("compile")
@click.option("--config", "build_config", default="Development",
              type=click.Choice(["Development", "Shipping", "DebugGame", "Test"]))
@click.option("--platform", default="Win64")
@click.option("--timeout", default=3600, help="Timeout in seconds")
@handle_error
def build_compile(build_config, platform, timeout):
    """Compile the project's C++ code."""
    from cli_anything.unreal.core.build import compile_project

    _require_project()
    _skin.info(f"Compiling {_session.project_name} ({build_config} / {platform})...")
    result = compile_project(
        _session.project_path, build_config, platform,
        _session.engine_root, timeout,
    )
    output(result)


@build_group.command("cook")
@click.option("--platform", default="Win64")
@click.option("--timeout", default=3600, help="Timeout in seconds")
@handle_error
def build_cook(platform, timeout):
    """Cook content assets for the target platform."""
    from cli_anything.unreal.core.build import cook_content

    _require_project()
    _skin.info(f"Cooking content for {platform}...")
    result = cook_content(_session.project_path, platform, _session.engine_root, timeout)
    output(result)


@build_group.command("package")
@click.option("--platform", default="Win64")
@click.option("--config", "build_config", default="Development",
              type=click.Choice(["Development", "Shipping", "DebugGame", "Test"]))
@click.option("--output", "output_dir", type=click.Path(), help="Archive output directory")
@click.option("--timeout", default=7200, help="Timeout in seconds")
@handle_error
def build_package(platform, build_config, output_dir, timeout):
    """Full package pipeline: build + cook + stage + package."""
    from cli_anything.unreal.core.build import package_project

    _require_project()
    _skin.info(f"Packaging {_session.project_name} ({build_config} / {platform})...")
    result = package_project(
        _session.project_path, platform, build_config,
        output_dir, _session.engine_root, timeout,
    )
    output(result)


@build_group.command("status")
@handle_error
def build_status_cmd():
    """Check build status (binaries, logs)."""
    from cli_anything.unreal.core.build import build_status

    _require_project()
    result = build_status(_session.project_path)
    output(result)


# ══════════════════════════════════════════════════════════════════════
#  SCENE commands
# ══════════════════════════════════════════════════════════════════════

@cli.group("scene")
def scene_group():
    """Scene/Level actor queries (requires running editor)."""
    pass


@scene_group.command("actors")
@click.option("--class", "actor_class", default=None, help="Filter by class (e.g., StaticMeshActor)")
@handle_error
def scene_actors(actor_class):
    """List all actors in the current level."""
    from cli_anything.unreal.core.scene import list_actors, list_actors_of_class

    api = _require_editor()
    if actor_class:
        result = list_actors_of_class(api, actor_class)
    else:
        result = list_actors(api)

    if not _json_output:
        actors = result.get("actors", [])
        _skin.info(f"Found {len(actors)} actors")
        if actors:
            headers = ["Name", "Path"]
            rows = [[a["name"], a.get("path", "")[:60]] for a in actors]
            _skin.table(headers, rows)
    else:
        output(result)


@scene_group.command("find")
@click.argument("name")
@handle_error
def scene_find(name):
    """Find actors by name (substring match)."""
    from cli_anything.unreal.core.scene import find_actor_by_name

    api = _require_editor()
    result = find_actor_by_name(api, name)
    output(result)


@scene_group.command("describe")
@click.argument("actor_path")
@handle_error
def scene_describe(actor_path):
    """Describe an actor — list properties and functions."""
    from cli_anything.unreal.core.scene import describe_actor

    api = _require_editor()
    result = describe_actor(api, actor_path)
    output(result)


@scene_group.command("property")
@click.argument("actor_path")
@click.argument("property_name")
@click.option("--set", "new_value", default=None, help="Set property to this value")
@handle_error
def scene_property(actor_path, property_name, new_value):
    """Get (or set) a property on an actor."""
    from cli_anything.unreal.core.scene import get_actor_property, set_actor_property

    api = _require_editor()
    if new_value is not None:
        result = set_actor_property(api, actor_path, property_name, new_value)
    else:
        result = get_actor_property(api, actor_path, property_name)
    output(result)


@scene_group.command("components")
@click.argument("actor_path")
@handle_error
def scene_components(actor_path):
    """List components on an actor."""
    from cli_anything.unreal.core.scene import get_actor_components

    api = _require_editor()
    result = get_actor_components(api, actor_path)
    output(result)


@scene_group.command("material")
@click.argument("actor_path")
@click.option("--index", default=0, help="Material slot index")
@handle_error
def scene_material(actor_path, index):
    """Get the material assigned to an actor's mesh."""
    from cli_anything.unreal.core.scene import get_actor_material

    api = _require_editor()
    result = get_actor_material(api, actor_path, index)
    output(result)


@scene_group.command("transform")
@click.argument("actor_path")
@handle_error
def scene_transform(actor_path):
    """Get an actor's transform (location, rotation, scale)."""
    from cli_anything.unreal.core.scene import get_actor_transform

    api = _require_editor()
    result = get_actor_transform(api, actor_path)
    output(result)


# ══════════════════════════════════════════════════════════════════════
#  MATERIAL commands
# ══════════════════════════════════════════════════════════════════════

@cli.group("material")
def material_group():
    """Material viewing, editing & analysis (add/connect/delete nodes, set params, recompile)."""
    pass


@material_group.command("list")
@click.option("--path", "content_path", default="/Game/", help="Content path to search")
@handle_error
def material_list(content_path):
    """List all materials in the project."""
    from cli_anything.unreal.core.materials import list_materials

    api = _require_editor()
    result = list_materials(api, content_path, _session.project_dir)
    output(result)


@material_group.command("info")
@click.argument("material_path")
@handle_error
def material_info(material_path):
    """Show detailed material information (nodes, parameters, textures)."""
    from cli_anything.unreal.core.materials import get_material_info

    material_path = _fix_ue_path(material_path)
    api = _require_editor()
    result = get_material_info(api, material_path, _session.project_dir)
    output(result)


@material_group.command("stats")
@click.argument("material_path")
@handle_error
def material_stats(material_path):
    """Show material compilation statistics (instruction counts)."""
    from cli_anything.unreal.core.materials import get_material_stats

    material_path = _fix_ue_path(material_path)
    api = _require_editor()
    result = get_material_stats(api, material_path, _session.project_dir)
    output(result)


@material_group.command("errors")
@click.argument("material_path")
@handle_error
def material_errors(material_path):
    """Check material for compilation errors."""
    from cli_anything.unreal.core.materials import get_material_errors

    material_path = _fix_ue_path(material_path)
    api = _require_editor()
    result = get_material_errors(api, material_path, _session.project_dir)
    output(result)


@material_group.command("textures")
@click.argument("material_path")
@handle_error
def material_textures(material_path):
    """List all textures referenced by a material."""
    from cli_anything.unreal.core.materials import get_material_texture_list

    material_path = _fix_ue_path(material_path)
    api = _require_editor()
    result = get_material_texture_list(api, material_path, _session.project_dir)
    output(result)


@material_group.command("connections")
@click.argument("material_path")
@handle_error
def material_connections(material_path):
    """Show material node connection graph.

    Lists which node feeds each material output pin (BaseColor, Normal,
    WorldPositionOffset, etc.) and identifies orphan nodes not connected
    to any output.  Custom nodes include HLSL code previews.

    Example: material connections /Game/M_Water
    """
    from cli_anything.unreal.core.materials import get_material_connections

    material_path = _fix_ue_path(material_path)
    api = _require_editor()
    result = get_material_connections(api, material_path, _session.project_dir)

    if not _json_output and "error" not in result:
        _skin.section(f"Connections: {material_path}")

        mat_outputs = result.get("material_outputs", {})
        if mat_outputs:
            _skin.info("Material Output Pins:")
            for pin, src in mat_outputs.items():
                if isinstance(src, dict):
                    _skin.status(f"  {pin}", f"{src['node']} ({src['node_type']})")
        else:
            _skin.warning("No material output connections found")

        orphans = result.get("orphan_nodes", [])
        if orphans:
            _skin.warning(f"{len(orphans)} orphan node(s) (not connected to output):")
            for name in orphans[:10]:
                _skin.hint(f"  {name}")
            if len(orphans) > 10:
                _skin.hint(f"  ... and {len(orphans) - 10} more")

        # Show Custom nodes with code
        nodes = result.get("nodes", [])
        customs = [n for n in nodes if n.get("type") == "MaterialExpressionCustom"]
        if customs:
            _skin.info(f"\nCustom HLSL Nodes ({len(customs)}):")
            for c in customs:
                preview = c.get("code_preview", "(no code)")
                lines = c.get("code_lines", "?")
                _skin.status(f"  {c['name']}", f"{lines} lines")
                if preview:
                    for line in preview.split("\n")[:3]:
                        click.echo(f"    {line}")

    output(result)


@material_group.command("analyze")
@click.argument("material_path")
@handle_error
def material_analyze(material_path):
    """Analyze material for common issues (Agent core feature)."""
    from cli_anything.unreal.core.materials import analyze_material

    material_path = _fix_ue_path(material_path)
    api = _require_editor()
    result = analyze_material(api, material_path, _session.project_dir)

    if not _json_output:
        _skin.section(f"Analysis: {material_path}")

        issues = result.get("issues", [])
        warnings = result.get("warnings", [])
        stats = result.get("stats", {})

        if issues:
            for issue in issues:
                _skin.error(f"ISSUE: {issue}")
        if warnings:
            for warning in warnings:
                _skin.warning(f"WARNING: {warning}")
        if not issues and not warnings:
            _skin.success("No issues found")

        if stats:
            _skin.status_block({
                "Texture Samples": str(stats.get("texture_sample_count", "?")),
                "Node Count": str(stats.get("node_count", "?")),
                "Textures": str(stats.get("texture_count", "?")),
            }, title="Statistics")
    else:
        output(result)


@material_group.command("hlsl")
@click.argument("material_path")
@click.option("--platform", default="sm6",
              help="Shader platform: sm6 (default), sm5, vulkan, vulkan_es31, opengl_es31, metal")
@click.option("--shader-type", default="pixel",
              type=click.Choice(["pixel", "vertex", "all"]),
              help="Which shader stage to return")
@click.option("--full", is_flag=True, help="Return full .usf file (not just material code)")
@handle_error
def material_hlsl(material_path, platform, shader_type, full):
    """Get compiled HLSL/USF shader code for a material.

    Triggers shader recompile with debug dump, reads the generated code.
    CVar r.DumpShaderDebugInfo is automatically saved and restored.

    Platforms: sm6 (DirectX SM6), sm5 (DirectX SM5), vulkan, opengl_es31, metal
    """
    from cli_anything.unreal.core.materials import get_material_hlsl

    material_path = _fix_ue_path(material_path)
    api = _require_editor()
    _require_project()

    if not _json_output:
        _skin.info(f"Dumping HLSL for {material_path} ({platform})...")
        _skin.hint("This triggers a shader recompile, may take a few seconds...")

    result = get_material_hlsl(
        api, material_path,
        project_dir=_session.project_dir,
        platform=platform,
        shader_type=shader_type,
    )

    if not _json_output and "error" not in result:
        _skin.success(f"Got {result.get('shader_count', 0)} shaders")
        _skin.status("Platform", result.get("platform", ""))
        _skin.status("Available", ", ".join(result.get("available_platforms", [])))

        mat_code = result.get("material_code", "")
        if mat_code:
            _skin.section("Material Code (CalcPixelMaterialInputs)")
            print(mat_code)
        elif full and result.get("shaders"):
            first = result["shaders"][0]
            _skin.section(f"Full shader: {first['pass']}")
            print(first.get("code", "No code"))

    if _json_output:
        # For JSON output, don't include full code by default (too large for token)
        if not full:
            for s in result.get("shaders", []):
                s.pop("code", None)
        output(result)
    elif "error" in result:
        output(result)


@material_group.command("add-node")
@click.argument("material_path")
@click.option("--type", "expression_class", required=True,
              help="UE expression class (e.g., MaterialExpressionConstant3Vector)")
@click.option("--pos-x", default=0, type=int, help="Node X position in graph")
@click.option("--pos-y", default=0, type=int, help="Node Y position in graph")
@handle_error
def material_add_node(material_path, expression_class, pos_x, pos_y):
    """Add a new material expression node.

    Requires MaterialEditingLibrary (Python Editor Scripting plugin).

    Example: material add-node /Game/M_Test --type MaterialExpressionConstant3Vector
    """
    from cli_anything.unreal.core.materials import add_material_node

    material_path = _fix_ue_path(material_path)
    api = _require_editor()
    result = add_material_node(api, material_path, expression_class,
                               pos_x=pos_x, pos_y=pos_y,
                               project_dir=_session.project_dir)
    output(result)


@material_group.command("delete-node")
@click.argument("material_path")
@click.option("--node", "node_name", required=True,
              help="Name of the expression node to delete")
@handle_error
def material_delete_node(material_path, node_name):
    """Delete a material expression node by name.

    Use 'material info' to find node names first.

    Example: material delete-node /Game/M_Test --node Constant3Vector_0
    """
    from cli_anything.unreal.core.materials import delete_material_node

    material_path = _fix_ue_path(material_path)
    api = _require_editor()
    result = delete_material_node(api, material_path, node_name,
                                  project_dir=_session.project_dir)
    output(result)


@material_group.command("connect")
@click.argument("material_path")
@click.option("--from", "from_node", required=True, help="Source node name")
@click.option("--from-output", default="", help="Source output pin name (empty for single-output)")
@click.option("--to", "to_node", required=True,
              help="Target node name, or '__material_output__' for material output pins")
@click.option("--to-input", required=True,
              help="Target input pin name, or material property (BaseColor, Normal, etc.)")
@handle_error
def material_connect(material_path, from_node, from_output, to_node, to_input):
    """Connect two material expression nodes.

    To connect to material output (BaseColor, Normal, etc.):
      --to __material_output__ --to-input BaseColor

    Example: material connect /Game/M_Test --from Constant3Vector_0 --to __material_output__ --to-input BaseColor
    """
    from cli_anything.unreal.core.materials import connect_material_nodes

    material_path = _fix_ue_path(material_path)
    api = _require_editor()
    result = connect_material_nodes(api, material_path,
                                    from_node, from_output, to_node, to_input,
                                    project_dir=_session.project_dir)
    output(result)


@material_group.command("disconnect")
@click.argument("material_path")
@click.option("--from", "from_node", required=True, help="Source node name")
@click.option("--from-output", default="", help="Source output pin name")
@click.option("--to", "to_node", required=True,
              help="Target node name, or '__material_output__'")
@click.option("--to-input", required=True,
              help="Target input pin name, or material property name")
@handle_error
def material_disconnect(material_path, from_node, from_output, to_node, to_input):
    """Disconnect material expression nodes.

    Example: material disconnect /Game/M_Test --from Constant3Vector_0 --to __material_output__ --to-input BaseColor
    """
    from cli_anything.unreal.core.materials import disconnect_material_nodes

    material_path = _fix_ue_path(material_path)
    api = _require_editor()
    result = disconnect_material_nodes(api, material_path,
                                       from_node, from_output, to_node, to_input,
                                       project_dir=_session.project_dir)
    output(result)


@material_group.command("set-param")
@click.argument("material_path")
@click.option("--name", "param_name", required=True, help="Parameter name")
@click.option("--value", "param_value", required=True,
              help='Value: scalar "0.5", vector \'{"r":1,"g":0,"b":0,"a":1}\', texture "/Game/T_Tex"')
@click.option("--type", "param_type", required=True,
              type=click.Choice(["scalar", "vector", "texture"]),
              help="Parameter type")
@handle_error
def material_set_param(material_path, param_name, param_value, param_type):
    """Set a parameter on a MaterialInstanceConstant.

    Example: material set-param /Game/MI_Test --name Roughness --value 0.5 --type scalar
    """
    from cli_anything.unreal.core.materials import set_material_param

    material_path = _fix_ue_path(material_path)
    api = _require_editor()
    result = set_material_param(api, material_path,
                                param_name, param_value, param_type,
                                project_dir=_session.project_dir)
    output(result)


@material_group.command("recompile")
@click.argument("material_path")
@handle_error
def material_recompile(material_path):
    """Recompile a material (force shader recompilation).

    Example: material recompile /Game/M_Test
    """
    from cli_anything.unreal.core.materials import recompile_material

    material_path = _fix_ue_path(material_path)
    api = _require_editor()
    result = recompile_material(api, material_path,
                                project_dir=_session.project_dir)
    output(result)


# ══════════════════════════════════════════════════════════════════════
#  BLUEPRINT commands
# ══════════════════════════════════════════════════════════════════════

@cli.group("blueprint")
def blueprint_group():
    """Blueprint viewing and editing (requires running editor)."""
    pass


@blueprint_group.command("list")
@click.option("--path", "content_path", default="/Game/", help="Content path to search")
@handle_error
def blueprint_list(content_path):
    """List all blueprints in the project."""
    from cli_anything.unreal.core.blueprint import list_blueprints

    api = _require_editor()
    result = list_blueprints(api, content_path, _session.project_dir)
    output(result)


@blueprint_group.command("info")
@click.argument("blueprint_path")
@handle_error
def blueprint_info(blueprint_path):
    """Show detailed blueprint information (graphs, nodes, variables)."""
    from cli_anything.unreal.core.blueprint import get_blueprint_info

    blueprint_path = _fix_ue_path(blueprint_path)
    api = _require_editor()
    result = get_blueprint_info(api, blueprint_path, _session.project_dir)
    output(result)


@blueprint_group.command("add-function")
@click.argument("blueprint_path")
@click.option("--name", "func_name", required=True, help="Name for the new function graph")
@handle_error
def blueprint_add_function(blueprint_path, func_name):
    """Add a function graph to a blueprint.

    Example: blueprint add-function /Game/BP_Test --name MyFunc
    """
    from cli_anything.unreal.core.blueprint import add_function

    blueprint_path = _fix_ue_path(blueprint_path)
    api = _require_editor()
    result = add_function(api, blueprint_path, func_name,
                          project_dir=_session.project_dir)
    output(result)


@blueprint_group.command("remove-function")
@click.argument("blueprint_path")
@click.option("--name", "func_name", required=True, help="Name of the function graph to remove")
@handle_error
def blueprint_remove_function(blueprint_path, func_name):
    """Remove a function graph from a blueprint.

    Example: blueprint remove-function /Game/BP_Test --name MyFunc
    """
    from cli_anything.unreal.core.blueprint import remove_function

    blueprint_path = _fix_ue_path(blueprint_path)
    api = _require_editor()
    result = remove_function(api, blueprint_path, func_name,
                             project_dir=_session.project_dir)
    output(result)


@blueprint_group.command("add-variable")
@click.argument("blueprint_path")
@click.option("--name", "var_name", required=True, help="Variable name")
@click.option("--type", "var_type", required=True,
              help="Variable type: bool, int, float, string, text, name, vector, rotator, transform")
@handle_error
def blueprint_add_variable(blueprint_path, var_name, var_type):
    """Add a member variable to a blueprint.

    Example: blueprint add-variable /Game/BP_Test --name Health --type float
    """
    from cli_anything.unreal.core.blueprint import add_variable

    blueprint_path = _fix_ue_path(blueprint_path)
    api = _require_editor()
    result = add_variable(api, blueprint_path, var_name, var_type,
                          project_dir=_session.project_dir)
    output(result)


@blueprint_group.command("remove-unused-variables")
@click.argument("blueprint_path")
@handle_error
def blueprint_remove_unused_variables(blueprint_path):
    """Remove all unused variables from a blueprint.

    Example: blueprint remove-unused-variables /Game/BP_Test
    """
    from cli_anything.unreal.core.blueprint import remove_unused_variables

    blueprint_path = _fix_ue_path(blueprint_path)
    api = _require_editor()
    result = remove_unused_variables(api, blueprint_path,
                                     project_dir=_session.project_dir)
    output(result)


@blueprint_group.command("compile")
@click.argument("blueprint_path")
@handle_error
def blueprint_compile(blueprint_path):
    """Compile a blueprint.

    Example: blueprint compile /Game/BP_Test
    """
    from cli_anything.unreal.core.blueprint import compile_blueprint

    blueprint_path = _fix_ue_path(blueprint_path)
    api = _require_editor()
    result = compile_blueprint(api, blueprint_path,
                               project_dir=_session.project_dir)
    output(result)


@blueprint_group.command("rename-graph")
@click.argument("blueprint_path")
@click.option("--old", "old_name", required=True, help="Current graph name")
@click.option("--new", "new_name", required=True, help="New graph name")
@handle_error
def blueprint_rename_graph(blueprint_path, old_name, new_name):
    """Rename a graph in a blueprint.

    Example: blueprint rename-graph /Game/BP_Test --old OldFunc --new NewFunc
    """
    from cli_anything.unreal.core.blueprint import rename_graph

    blueprint_path = _fix_ue_path(blueprint_path)
    api = _require_editor()
    result = rename_graph(api, blueprint_path, old_name, new_name,
                          project_dir=_session.project_dir)
    output(result)


# ══════════════════════════════════════════════════════════════════════
#  SCREENSHOT commands
# ══════════════════════════════════════════════════════════════════════

@cli.group("screenshot")
def screenshot_group():
    """Screenshot capture and comparison (requires running editor)."""
    pass


@screenshot_group.command("take")
@click.option("--filename", default="screenshot", help="Output filename (no extension)")
@click.option("--no-clean", is_flag=True, help="Don't disable noisy effects")
@click.option("--no-compress", is_flag=True, help="Return raw PNG instead of compressed JPG")
@handle_error
def screenshot_take(filename, no_clean, no_compress):
    """Take a viewport screenshot. Returns compressed JPG by default."""
    from cli_anything.unreal.core.screenshot import take_screenshot

    api = _require_editor()
    result = take_screenshot(
        api, filename,
        disable_noisy=not no_clean,
        project_dir=_session.project_dir,
    )

    # Default: same path agents read — JPG from compress_for_agent when not --no-compress
    if result.get("status") == "ok" or result.get("path_raw"):
        if no_compress:
            result["default_path"] = result.get("path_raw") or result.get("read_this")
        else:
            result["default_path"] = result.get("read_this") or result.get("path_raw")

    output(result)


def _exec_screenshot_sequence(frames, interval, no_compress):
    """Implementation for ``screenshot sequence``."""
    from cli_anything.unreal.core.screenshot import capture_screenshot_atlas

    api = _require_editor()
    result = capture_screenshot_atlas(
        api,
        frames,
        interval=interval,
        cols=None,
        filename_prefix="motion_seq",
        output_atlas=None,
        project_dir=_session.project_dir,
        disable_noisy=True,
        res_x=1920,
        res_y=1080,
        delay=1.0,
        wait_timeout=15.0,
        padding=6,
        label_frames=True,
        jpeg_for_llm=not no_compress,
        max_atlas_edge=1920,
        jpeg_quality=85,
    )
    if result.get("status") == "ok":
        if no_compress:
            result["default_path"] = result.get("atlas_path") or result.get("read_this")
        else:
            result["default_path"] = result.get("read_this") or result.get("atlas_path")
    output(result)


@screenshot_group.command(
    "sequence",
    help=(
        "Viewport frames over time merged into one atlas; "
        "default primary output is compressed JPG like screenshot take."
    ),
)
@click.option(
    "-n",
    "--frames",
    type=int,
    default=6,
    show_default=True,
    help="How many timed viewport captures to merge into one sheet",
)
@click.option(
    "-i",
    "--interval",
    type=float,
    default=0.5,
    show_default=True,
    help="Seconds to wait after each capture (scene time advances)",
)
@click.option(
    "--no-compress",
    is_flag=True,
    help="Return raw PNG atlas only (same as screenshot take --no-compress)",
)
@handle_error
def screenshot_sequence(frames, interval, no_compress):
    _exec_screenshot_sequence(frames, interval, no_compress)


@screenshot_group.command("compare")
@click.argument("image_a", type=click.Path(exists=True))
@click.argument("image_b", type=click.Path(exists=True))
@click.option("--tolerance", default="Low",
              type=click.Choice(["Zero", "Low", "Medium", "High"]))
@handle_error
def screenshot_compare(image_a, image_b, tolerance):
    """Compare two screenshots for differences."""
    from cli_anything.unreal.core.screenshot import compare_screenshots

    api = _require_editor()
    result = compare_screenshots(api, image_a, image_b, tolerance)
    output(result)


@screenshot_group.command("cvar-test")
@click.option("--cvar", required=True, help="CVar name to toggle")
@click.option("--values", required=True, help="Comma-separated values to test")
@click.option("--labels", default=None, help="Comma-separated labels")
@click.option("--prefix", default="cvar_test", help="Filename prefix")
@click.option("--settle", default=1.0, help="Seconds to wait after CVar change")
@handle_error
def screenshot_cvar_test(cvar, values, labels, prefix, settle):
    """Take screenshots with different CVar values for A/B comparison."""
    from cli_anything.unreal.core.screenshot import screenshot_with_cvar

    api = _require_editor()
    values_list = [v.strip() for v in values.split(",")]
    labels_list = [l.strip() for l in labels.split(",")] if labels else None

    result = screenshot_with_cvar(
        api, cvar, values_list, labels_list,
        filename_prefix=prefix,
        settle_time=settle,
        project_dir=_session.project_dir,
    )
    output(result)


@screenshot_group.command("compress")
@click.argument("image_path", type=click.Path(exists=True))
@click.option("--max-edge", default=1920, help="Max dimension")
@click.option("--quality", default=85, help="JPEG quality (1-100)")
@click.option("--output", "out_path", type=click.Path(), help="Output path")
@handle_error
def screenshot_compress(image_path, max_edge, quality, out_path):
    """Compress a screenshot for Agent vision analysis."""
    from cli_anything.unreal.core.screenshot import compress_for_agent

    result_path = compress_for_agent(image_path, max_edge, quality, out_path)
    if result_path:
        output({"path": result_path, "size": Path(result_path).stat().st_size})
    else:
        output({"error": "Compression failed (is Pillow installed?)"})


# ══════════════════════════════════════════════════════════════════════
#  EDITOR commands
# ══════════════════════════════════════════════════════════════════════

@cli.group("editor")
def editor_group():
    """Editor control — status, console commands, CVars."""
    pass


@editor_group.command("status")
@click.option("--port", type=int, help="Override port for this check")
@handle_error
def editor_status(port):
    """Check if the UE editor is running and reachable."""
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    check_port = port or _session.port
    api = UEEditorAPI(port=check_port)
    alive = api.is_alive()

    if alive:
        info = api.get_info()
        result = {
            "status": "online",
            "port": check_port,
            "info": info,
        }
        if not _json_output:
            _skin.success(f"Editor is online (port {check_port})")
    else:
        # API not responding — check if UE process is still alive
        # (may be blocked by a modal dialog)
        import sys as _sys
        result = {
            "status": "offline",
            "port": check_port,
        }
        if _sys.platform == "win32":
            try:
                from cli_anything.unreal.utils.ue_backend import (
                    find_running_editors, detect_ue_dialogs,
                )
                running = find_running_editors()
                if running:
                    result["status"] = "offline_api_blocked"
                    result["running_editors"] = [
                        {"pid": e["pid"], "project": e.get("project")} for e in running
                    ]
                    dialogs = detect_ue_dialogs()
                    if dialogs:
                        result["dialogs"] = [
                            {"title": d["title"]} for d in dialogs
                        ]
                    if not _json_output:
                        _skin.warning(
                            f"Editor process running but API not responding on port {check_port}"
                        )
                        if dialogs:
                            _skin.warning("Modal dialog(s) detected:")
                            for d in dialogs:
                                _skin.warning(f'  "{d["title"]}"')
                        _skin.hint("Editor may be blocked by a dialog. Check the editor window.")
                else:
                    if not _json_output:
                        _skin.error(f"Editor not reachable on port {check_port}")
            except Exception:
                if not _json_output:
                    _skin.error(f"Editor not reachable on port {check_port}")
        else:
            if not _json_output:
                _skin.error(f"Editor not reachable on port {check_port}")

    output(result)


@editor_group.command("list")
@click.option("--scan-range", default="30010-30020", help="Port range to scan")
@handle_error
def editor_list(scan_range):
    """Discover all running UE editor instances.

    Scans ports and checks for running editor processes.
    """
    from cli_anything.unreal.utils.ue_http_api import scan_editor_ports
    from cli_anything.unreal.utils.ue_backend import find_running_editors

    # Parse port range
    parts = scan_range.split("-")
    start = int(parts[0])
    end = int(parts[1]) if len(parts) > 1 else start

    # Scan HTTP ports
    instances = scan_editor_ports(port_range=(start, end))

    # Also find processes
    processes = find_running_editors()

    result = {
        "http_instances": [
            {"port": i["port"], "alive": i.get("alive", True)}
            for i in instances
        ],
        "processes": [
            {"pid": p["pid"], "project": p.get("project", "")}
            for p in processes
        ],
    }

    if not _json_output:
        if instances:
            _skin.section("Running Editor Instances (HTTP)")
            headers = ["Port", "Status"]
            rows = [[str(i["port"]), "Online"] for i in instances]
            _skin.table(headers, rows)
        else:
            _skin.warning(f"No editor HTTP API found on ports {start}-{end}")

        if processes:
            _skin.section("Editor Processes")
            headers = ["PID", "Project"]
            rows = [[str(p["pid"]), p.get("project", "unknown")] for p in processes]
            _skin.table(headers, rows)

    output(result)


@editor_group.command("preflight")
@handle_error
def editor_preflight():
    """Check if engine and project are compiled and ready to launch.

    Verifies:
    - Engine binaries exist (UnrealEditor.exe, .modules, .target)
    - Project C++ modules are compiled (UnrealEditor-{Module}.dll)
    - Binaries are not stale (newer than source code)
    """
    from cli_anything.unreal.utils.ue_backend import preflight_check

    _require_project()
    result = preflight_check(_session.project_path, _session.engine_root)

    if not _json_output:
        # Engine status
        eng = result["engine"]
        if eng["ready"]:
            _skin.success(f"Engine OK ({result.get('engine_root', '?')})")
        else:
            _skin.error("Engine NOT ready")
            for e in eng["errors"]:
                _skin.error(f"  {e}")
        for w in eng.get("warnings", []):
            _skin.warning(f"  {w}")

        # Project status
        proj = result["project"]
        if proj["ready"]:
            _skin.success(f"Project OK ({_session.project_name})")
        else:
            _skin.error(f"Project NOT ready ({_session.project_name})")
            for e in proj["errors"]:
                _skin.error(f"  {e}")
        for w in proj.get("warnings", []):
            _skin.warning(f"  {w}")

        if result["ready"]:
            _skin.success("Ready to launch editor")
        else:
            _skin.error("Cannot launch editor — fix errors above first")

    output(result)


@editor_group.command("launch")
@click.option("--map", "map_path", default=None, help="Level/map to open (.umap path)")
@click.option("--wait/--no-wait", default=True, help="Wait for API to come online")
@click.option("--timeout", default=300, help="Max seconds to wait for editor startup")
@handle_error
def editor_launch(map_path, wait, timeout):
    """Launch UE editor with preflight build check.

    Always runs preflight check first (BuildId match, DLL existence, etc.).
    If the check fails, returns an error with instructions to compile.
    Optionally waits for the Remote Control API to come online.
    """
    import subprocess as sp
    import time

    from cli_anything.unreal.utils.ue_backend import (
        preflight_check, find_editor_exe, read_rc_port,
    )
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    _require_project()

    # ── Determine poll port ─────────────────────────────────────────
    # If user explicitly passed --port, respect it.
    # Otherwise, read from project config (DefaultRemoteControl.ini).
    ctx = click.get_current_context()
    port_explicit = (
        ctx.parent
        and ctx.parent.get_parameter_source("port") == click.core.ParameterSource.COMMANDLINE
    )
    if port_explicit:
        poll_port = _session.port
    else:
        rc_port = read_rc_port(_session.project_dir)
        poll_port = rc_port if rc_port is not None else _session.port

    # ── Preflight check (always runs) ─────────────────────────────────
    if not _json_output:
        _skin.info("Running preflight check...")

    check = preflight_check(_session.project_path, _session.engine_root)

    if not check["ready"]:
        all_errors = check["engine"]["errors"] + check["project"]["errors"]
        if _json_output:
            output({
                "status": "preflight_failed",
                "errors": all_errors,
                "preflight": check,
            })
        else:
            _skin.error("Preflight check FAILED — cannot launch editor")
            for e in all_errors:
                _skin.error(f"  {e}")
            for w in check["engine"].get("warnings", []) + check["project"].get("warnings", []):
                _skin.warning(f"  {w}")
            _skin.hint("Fix the errors above, then try again.")
            _skin.hint(f"To compile: cli-anything-unreal --project {_session.project_path} build compile")
        return

    if not _json_output:
        _skin.success("Preflight OK")

    # ── Find editor exe ─────────────────────────────────────────────
    if not _session.engine_root:
        raise click.UsageError("Could not find engine root")

    editor_exe = find_editor_exe(_session.engine_root)
    if not editor_exe:
        raise FileNotFoundError(f"UnrealEditor.exe not found in {_session.engine_root}")

    # ── Check if editor is already running for this project ─────────
    from cli_anything.unreal.utils.ue_backend import find_running_editors

    # 1. Check by process — detect any UE instance with the same .uproject
    running = find_running_editors()
    project_path_norm = str(Path(_session.project_path).resolve()).lower()
    for editor_proc in running:
        proc_project = editor_proc.get("project", "")
        if proc_project and Path(proc_project).resolve().as_posix().lower() == Path(project_path_norm).as_posix().lower():
            output({
                "status": "already_running",
                "pid": editor_proc["pid"],
                "project": proc_project,
                "message": (
                    f"Editor is already running for this project (PID {editor_proc['pid']}). "
                    "Use 'editor close' to shut it down first, "
                    "or kill the process manually."
                ),
            })
            if not _json_output:
                _skin.error(f"Editor already running for {_session.project_name} (PID {editor_proc['pid']})")
                _skin.hint("Use: cli-anything-unreal editor close")
            return

    # 1b. Warn about any other UE instances (different projects)
    if running:
        other_projects = [
            p for p in running
            if p.get("project", "") and Path(p["project"]).resolve().as_posix().lower() != Path(project_path_norm).as_posix().lower()
        ]
        if other_projects:
            if _json_output:
                output({
                    "status": "warning",
                    "warning": "other_editors_running",
                    "running_editors": other_projects,
                    "message": (
                        f"{len(other_projects)} other UE editor(s) running. "
                        "Port conflicts may occur if they use the same Remote Control port."
                    ),
                })
            else:
                _skin.warning(f"{len(other_projects)} other UE editor(s) running:")
                for ep in other_projects:
                    _skin.warning(f"  PID {ep['pid']}: {ep.get('project', 'unknown')}")
                _skin.hint("Port conflicts may occur. Continue at your own risk.")

    # 2. Check by API port — detect any UE instance on the target port
    api_check = UEEditorAPI(port=poll_port)
    if api_check.is_alive():
        output({
            "status": "already_running",
            "port": poll_port,
            "message": (
                f"An editor is already responding on port {poll_port}. "
                "Use 'editor close' to shut it down, or use a different --port."
            ),
        })
        if not _json_output:
            _skin.error(f"Port {poll_port} is already in use by an editor")
            _skin.hint("Use: cli-anything-unreal editor close")
            _skin.hint(f"Or launch on another port: editor launch --port {poll_port + 10}")
        return

    # ── Auto-deploy bridge plugin before launch ────────────────────
    from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed
    deploy = ensure_plugin_deployed(_session.project_dir)
    if deploy["deployed"] and deploy["action"] != "already_up_to_date":
        if not _json_output:
            _skin.info(f"Bridge plugin {deploy['action']} → {deploy['plugin_dir']}")

    # ── Build command ───────────────────────────────────────────────
    cmd = [editor_exe, _session.project_path]
    if map_path:
        cmd.append(map_path)

    if not _json_output:
        _skin.info(f"Launching: {Path(editor_exe).name} {_session.project_name}")
        if map_path:
            _skin.info(f"Map: {map_path}")

    # ── Launch process ──────────────────────────────────────────────
    # Capture stderr to detect modal error dialogs (e.g., "modules missing").
    # On Windows, avoid shell=True so proc.pid is the actual UE process.
    try:
        proc = sp.Popen(
            cmd,
            stdout=sp.DEVNULL,
            stderr=sp.PIPE,
        )
    except Exception as e:
        output({"status": "error", "error": f"Failed to launch: {e}"})
        return

    result = {
        "status": "launched",
        "pid": proc.pid,
        "project": _session.project_name,
        "editor_exe": editor_exe,
    }

    if not _json_output:
        _skin.success(f"Editor launched (PID {proc.pid})")

    # ── Log file for early error detection ──────────────────────────
    log_file = Path(_session.project_dir) / "Saved" / "Logs" / f"{_session.project_name}.log"

    def _check_log_errors() -> str | None:
        """Scan the editor log for fatal/modal-dialog errors."""
        if not log_file.exists():
            return None
        try:
            text = log_file.read_text(encoding="utf-8", errors="replace")
            # Check for common fatal patterns that produce modal dialogs
            fatal_patterns = [
                "modules are missing or built with a different engine version",
                "Engine modules cannot be compiled at runtime",
                "Missing or incompatible modules",
                "Plugin .* failed to load",
                "Fatal Error:",
                "Assertion failed:",
            ]
            import re
            for pattern in fatal_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    # Extract context around the match
                    start = max(0, match.start() - 100)
                    end = min(len(text), match.end() + 300)
                    return text[start:end].strip()
        except Exception:
            pass
        return None

    # ── Wait for API ────────────────────────────────────────────────
    if wait:
        if not _json_output:
            _skin.info(f"Waiting for Remote Control API on port {poll_port} (timeout {timeout}s)...")

        api = UEEditorAPI(port=poll_port)
        start_time = time.time()
        deadline = start_time + timeout
        poll_interval = 5.0

        while time.time() < deadline:
            # Check if process died
            if proc.poll() is not None:
                stderr_out = ""
                try:
                    stderr_out = proc.stderr.read().decode("utf-8", errors="replace").strip()
                except Exception:
                    pass
                result["status"] = "crashed"
                result["returncode"] = proc.returncode
                error_msg = (
                    f"Editor process exited with code {proc.returncode} before API came online."
                )
                if stderr_out:
                    error_msg += f"\nStderr: {stderr_out}"
                log_error = _check_log_errors()
                if log_error:
                    error_msg += f"\nLog: {log_error}"
                result["error"] = error_msg
                if not _json_output:
                    _skin.error(f"Editor exited unexpectedly (code {proc.returncode})")
                    if stderr_out:
                        _skin.error(f"  {stderr_out[:500]}")
                    if log_error:
                        _skin.error(f"  {log_error[:500]}")
                    _skin.hint("Check Saved/Logs/ for full details")
                break

            if api.is_alive():
                result["status"] = "online"
                result["port"] = poll_port
                elapsed = int(time.time() - start_time)
                result["startup_time_seconds"] = elapsed
                if not _json_output:
                    _skin.success(f"Editor API online (took ~{elapsed}s)")
                break

            # Check log for fatal errors even while process is running
            # (catches modal dialog popups that keep the process alive)
            elapsed = time.time() - start_time
            if elapsed > 30:  # Give editor 30s before checking
                log_error = _check_log_errors()
                if log_error:
                    result["status"] = "error_dialog"
                    result["error"] = (
                        "Editor appears stuck on an error dialog:\n"
                        f"{log_error}\n\n"
                        "Close the dialog and fix the issue before launching again."
                    )
                    if not _json_output:
                        _skin.error("Editor stuck on error dialog:")
                        _skin.error(f"  {log_error[:500]}")
                        _skin.hint("Close the dialog in the editor, then fix the issue.")
                    break

                # Check for modal dialogs via Windows API (Windows only)
                if sys.platform == "win32":
                    try:
                        from cli_anything.unreal.utils.ue_backend import detect_ue_dialogs
                        dialogs = detect_ue_dialogs()
                        if dialogs:
                            result["status"] = "blocked_by_dialog"
                            result["dialogs"] = [
                                {"title": d["title"], "hwnd": d["hwnd"]} for d in dialogs
                            ]
                            result["error"] = (
                                "Editor is blocked by modal dialog(s). "
                                "Close them and retry. "
                                + ", ".join(f'"{d["title"]}"' for d in dialogs)
                            )
                            if not _json_output:
                                _skin.error("Editor blocked by modal dialog:")
                                for d in dialogs:
                                    _skin.error(f'  "{d["title"]}"')
                                _skin.hint("Close the dialog(s) in the editor window.")
                            break
                    except Exception:
                        pass

            remaining = int(deadline - time.time())
            if not _json_output and int(time.time()) % 15 == 0:
                _skin.hint(f"  Still waiting... ({remaining}s remaining)")
            time.sleep(poll_interval)
        else:
            result["status"] = "timeout"
            result["error"] = (
                f"Editor API did not respond within {timeout}s on port {poll_port}. "
                "Editor may still be loading, or may be stuck on a dialog/popup. "
                "Check the editor window manually."
            )
            log_error = _check_log_errors()
            if log_error:
                result["error"] += f"\nLog hint: {log_error}"
            if not _json_output:
                _skin.warning(f"Timed out after {timeout}s")
                _skin.hint("Editor may still be loading. Check the editor window.")

    output(result)


@editor_group.command("close")
@handle_error
def editor_close():
    """Close the running UE editor (requests quit via console command).

    Sends 'quit' console command to the editor via Remote Control API.
    The editor will close gracefully (may prompt to save unsaved changes).
    """
    import time

    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    api = UEEditorAPI(port=_session.port)
    if not api.is_alive():
        output({"status": "offline", "port": _session.port,
                "message": "No editor running on this port."})
        return

    if not _json_output:
        _skin.info(f"Sending save + quit to editor on port {_session.port}...")

    # Save all dirty packages before quitting (prevents recovery dialog on next launch)
    try:
        api.call_function(
            "/Script/EditorScriptingUtilities.Default__EditorLoadingAndSavingUtils",
            "SaveDirtyPackages",
            {"bPromptUserToSave": False, "bSaveMapPackages": True, "bSaveContentPackages": True},
        )
        time.sleep(1)
    except Exception:
        pass

    # Send quit command
    api.exec_console("quit")

    # Wait for editor to actually close
    deadline = time.time() + 30
    while time.time() < deadline:
        if not api.is_alive():
            output({"status": "closed", "port": _session.port})
            if not _json_output:
                _skin.success("Editor closed.")
            return
        time.sleep(2)

    output({
        "status": "timeout",
        "port": _session.port,
        "message": "Editor did not close within 30s. It may be waiting for save confirmation.",
    })


@editor_group.command("exec")
@click.argument("command")
@click.option("--timeout", default=30, type=int,
              help="Max seconds to wait for results (Python commands only).")
@click.option("--no-save", "no_save", is_flag=True, default=False,
              help="Skip auto-saving dirty packages after Python script execution.")
@handle_error
def editor_exec(command, timeout, no_save):
    """Execute a console command in the editor.

    When the command starts with ``py `` the CLI automatically switches to
    a reliable script-execution mode: the Python code is written to a temp
    file, executed via ``exec_python_file``, and the result is captured as
    structured JSON.  The script may assign a ``result`` dict variable which
    will be returned; otherwise a generic "ok" status is produced.

    By default, dirty packages are saved after Python script execution.
    Use --no-save to skip this.

    For non-Python console commands the behaviour is unchanged.
    """
    api = _require_editor()

    # Python command detection — upgrade to reliable script execution mode
    if command.strip().startswith("py "):
        py_code = command.strip()[3:].strip().strip('"').strip("'")
        from cli_anything.unreal.core.script_runner import run_python_code
        result = run_python_code(
            api, py_code,
            project_dir=_session.project_dir,
            timeout=timeout,
            save=not no_save,
        )
    else:
        result = api.exec_console(command)

        if "error" in result and "400" in str(result["error"]):
            result["hint"] = (
                "Console command execution may be disabled in Remote Control settings. "
                "Run: cli-anything-unreal editor enable-remote"
            )
        elif not result or result == {}:
            result = {
                "status": "executed",
                "command": command,
                "note": "Command executed. Console output is not captured by Remote Control API. "
                        "Check editor Output Log for results.",
            }
    output(result)


@editor_group.command("run-script")
@click.argument("script_path", type=click.Path(exists=True))
@click.option("--timeout", default=30, type=int,
              help="Max seconds to wait for results.")
@click.option("--no-save", "no_save", is_flag=True, default=False,
              help="Skip auto-saving dirty packages after script execution.")
@handle_error
def editor_run_script(script_path, timeout, no_save):
    """Execute a Python script file in the editor with result capture.

    The script should set a ``result`` dict variable.  It will be
    automatically captured and returned as structured JSON output.

    If no ``result`` variable is defined the command returns a generic
    "ok" status.  Non-dict values are wrapped automatically.

    By default, dirty packages are saved after execution.
    Use --no-save to skip this.

    \b
    Example:
        editor run-script build_scene.py --timeout 60
    """
    from cli_anything.unreal.core.script_runner import run_python_script
    api = _require_editor()
    result = run_python_script(
        api, script_path,
        project_dir=_session.project_dir,
        timeout=timeout,
        save=not no_save,
    )
    output(result)


@editor_group.command("enable-remote")
@handle_error
def editor_enable_remote():
    """Enable Remote Control features for CLI use.

    Creates/updates DefaultRemoteControl.ini to allow:
    - Remote console command execution (exec, cvar set)
    - Remote Python execution

    Requires editor restart to take effect.
    """
    from cli_anything.unreal.utils.ue_backend import ensure_remote_control_config

    _require_project()
    result = ensure_remote_control_config(_session.project_dir)

    if not _json_output:
        if result["status"] == "ok":
            _skin.success("Remote Control already configured")
        elif result["status"] == "created":
            _skin.success("Created DefaultRemoteControl.ini")
        else:
            _skin.success("Updated DefaultRemoteControl.ini")
        for change in result.get("changes", []):
            _skin.info(f"  {change}")
        if result["status"] != "ok":
            _skin.warning("Restart the editor for changes to take effect")

    output(result)


@editor_group.group("cvar")
def cvar_group():
    """Get and set console variables."""
    pass


@cvar_group.command("get")
@click.argument("name")
@handle_error
def cvar_get(name):
    """Get a console variable value."""
    api = _require_editor()
    value = api.get_cvar(name)
    output({"name": name, "value": value})


@cvar_group.command("set")
@click.argument("name")
@click.argument("value")
@handle_error
def cvar_set(name, value):
    """Set a console variable value."""
    api = _require_editor()
    result = api.set_cvar(name, value)

    if "error" in result and "400" in str(result["error"]):
        output({
            "name": name,
            "value": value,
            "status": "failed",
            "error": "CVar set failed. Remote console command execution is disabled.",
            "fix": "Run: cli-anything-unreal --project <path> editor enable-remote, then restart editor.",
        })
    else:
        output({"name": name, "value": value, "status": "ok", **result})


# ══════════════════════════════════════════════════════════════════════
#  SESSION commands
# ══════════════════════════════════════════════════════════════════════

@cli.group("session")
def session_group():
    """Session management — undo, redo, status."""
    pass


@session_group.command("status")
@handle_error
def session_status():
    """Show current session status."""
    output(_session.status())


@session_group.command("undo")
@handle_error
def session_undo():
    """Undo the last change."""
    result = _session.undo()
    if result:
        output({"status": "ok", "restored": result["description"]})
    else:
        output({"status": "nothing_to_undo"})


@session_group.command("redo")
@handle_error
def session_redo():
    """Redo the last undone change."""
    result = _session.redo()
    if result:
        output({"status": "ok", "restored": result["description"]})
    else:
        output({"status": "nothing_to_redo"})


@session_group.command("history")
@handle_error
def session_history():
    """Show undo history."""
    history = _session.list_history()
    output(history)


# ══════════════════════════════════════════════════════════════════════
#  REPL
# ══════════════════════════════════════════════════════════════════════

@cli.command("repl")
def repl_cmd():
    """Start interactive REPL mode."""
    global _in_repl
    _in_repl = True

    _skin.print_banner()

    if _session.is_loaded:
        _skin.info(f"Project: {_session.project_name}")
        if _session.engine_root:
            _skin.info(f"Engine: {_session.engine_root}")
    else:
        _skin.hint("No project loaded. Use: project info --project <path>")

    _skin.info(f"Editor port: {_session.port}")
    print()

    # Try to create prompt_toolkit session
    pt_session = _skin.create_prompt_session()

    while True:
        try:
            # Build prompt
            project_name = _session.project_name or ""
            line = _skin.get_input(
                pt_session,
                project_name=project_name,
                modified=_session.modified,
                context=f":{_session.port}" if not project_name else f"{project_name}:{_session.port}",
            )

            if not line:
                continue

            # Built-in REPL commands
            if line.lower() in ("quit", "exit", "q"):
                break
            if line.lower() in ("help", "h", "?"):
                _print_repl_help()
                continue

            # Parse and execute via Click
            try:
                args = shlex.split(line)
            except ValueError as e:
                _skin.error(f"Parse error: {e}")
                continue

            try:
                cli.main(args, standalone_mode=False)
            except SystemExit:
                pass
            except click.exceptions.UsageError as e:
                _skin.error(str(e))
            except Exception as e:
                _skin.error(f"{type(e).__name__}: {e}")

        except KeyboardInterrupt:
            print()
            continue
        except EOFError:
            break

    _skin.print_goodbye()
    _in_repl = False


def _print_repl_help():
    """Print REPL help."""
    _skin.help({
        "project info": "Show project information",
        "project config list": "List configuration files",
        "project config get <name>": "Read a config file",
        "project config set <name> <sec> <k> <v>": "Set a config value",
        "project content": "List content assets",
        "project asset-exists": "Check if asset exists",
        "project asset-delete": "Delete asset (with ref check)",
        "project asset-refs": "List asset referencers",
        "project asset-duplicate": "Duplicate asset (--force to overwrite)",
        "project asset-rename": "Rename/move asset",
        "project generate": "Generate VS project files",
        "": "",
        "build compile": "Compile C++ code",
        "build cook": "Cook content assets",
        "build package": "Full package pipeline",
        "build status": "Check build status",
        " ": "",
        "scene actors": "List all actors in level",
        "scene find <name>": "Find actor by name",
        "scene describe <path>": "Describe actor properties",
        "scene property <path> <prop>": "Get property value",
        "scene components <path>": "List actor components",
        "scene material <path>": "Get actor's material ★",
        "scene transform <path>": "Get actor transform",
        "material list": "List all materials",
        "material info <path>": "Material details + connections ★",
        "material connections <path>": "Connection graph + orphans",
        "material stats <path>": "Compilation statistics",
        "material errors <path>": "Check for errors",
        "material textures <path>": "List referenced textures",
        "material analyze <path>": "Auto-analyze issues ★",
        "  ": "",
        "screenshot take": "Capture viewport",
        "screenshot sequence": "Time-ordered frame atlas",
        "screenshot compare <a> <b>": "Compare screenshots",
        "screenshot cvar-test": "CVar A/B screenshot",
        "screenshot compress <path>": "Compress for Agent",
        "   ": "",
        "editor status": "Check editor connection",
        "editor list": "Discover running editors",
        "editor exec <cmd>": "Run console command",
        "editor cvar get <name>": "Get CVar value",
        "editor cvar set <name> <val>": "Set CVar value",
        "    ": "",
        "session status": "Session info",
        "session undo": "Undo last change",
        "session redo": "Redo",
        "session history": "Undo history",
        "     ": "",
        "help": "Show this help",
        "quit": "Exit REPL",
    })


# ── Entry point ─────────────────────────────────────────────────────────

def main():
    _fix_argv_msys2()
    cli()


if __name__ == "__main__":
    main()
