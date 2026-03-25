"""core/project.py — Project management for Unreal Engine projects.

Handles .uproject parsing, Config/.ini reading/writing, and Content/ listing.
All operations are filesystem-based (no editor needed).
"""

import configparser
import json
import os
from pathlib import Path
from typing import Optional


def parse_uproject(uproject_path: str) -> dict:
    """Parse a .uproject file and return its contents.

    Args:
        uproject_path: Path to the .uproject file.

    Returns:
        Dict with project data.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        json.JSONDecodeError: If the file is invalid JSON.
    """
    path = Path(uproject_path)
    if not path.exists():
        raise FileNotFoundError(f"Project file not found: {uproject_path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def get_project_info(uproject_path: str) -> dict:
    """Get comprehensive project information.

    Args:
        uproject_path: Path to the .uproject file.

    Returns:
        Dict with project name, engine version, modules, plugins, etc.
    """
    path = Path(uproject_path)
    data = parse_uproject(uproject_path)
    project_dir = path.parent

    # Basic info
    info = {
        "name": path.stem,
        "path": str(path),
        "directory": str(project_dir),
        "engine_association": data.get("EngineAssociation", ""),
        "file_version": data.get("FileVersion", 0),
        "category": data.get("Category", ""),
        "description": data.get("Description", ""),
    }

    # Modules
    modules = data.get("Modules", [])
    info["modules"] = [
        {
            "name": m.get("Name", ""),
            "type": m.get("Type", ""),
            "loading_phase": m.get("LoadingPhase", ""),
        }
        for m in modules
    ]

    # Plugins
    plugins = data.get("Plugins", [])
    info["plugins"] = [
        {
            "name": p.get("Name", ""),
            "enabled": p.get("Enabled", False),
        }
        for p in plugins
    ]
    info["plugin_count"] = len(plugins)
    info["enabled_plugins"] = sum(1 for p in plugins if p.get("Enabled", False))

    # Target platforms
    info["target_platforms"] = data.get("TargetPlatforms", [])

    # Directory info
    content_dir = project_dir / "Content"
    config_dir = project_dir / "Config"
    binaries_dir = project_dir / "Binaries"
    intermediate_dir = project_dir / "Intermediate"

    info["has_content"] = content_dir.is_dir()
    info["has_config"] = config_dir.is_dir()
    info["has_binaries"] = binaries_dir.is_dir()
    info["has_intermediate"] = intermediate_dir.is_dir()

    # Source info
    source_dir = project_dir / "Source"
    if source_dir.is_dir():
        cpp_files = list(source_dir.rglob("*.cpp"))
        h_files = list(source_dir.rglob("*.h"))
        info["source"] = {
            "cpp_files": len(cpp_files),
            "header_files": len(h_files),
        }
    else:
        info["source"] = None

    return info


def list_configs(project_dir: str) -> list[dict]:
    """List all .ini configuration files in the project.

    Args:
        project_dir: Path to the project root directory.

    Returns:
        List of {"name": str, "path": str, "size": int}.
    """
    config_dir = Path(project_dir) / "Config"
    if not config_dir.is_dir():
        return []

    configs = []
    for ini_file in sorted(config_dir.glob("*.ini")):
        configs.append({
            "name": ini_file.stem,
            "filename": ini_file.name,
            "path": str(ini_file),
            "size": ini_file.stat().st_size,
        })
    return configs


def get_config(project_dir: str, config_name: str) -> dict:
    """Read a specific ini configuration file.

    Args:
        project_dir: Path to the project root.
        config_name: Config name without extension (e.g., "DefaultEngine").

    Returns:
        Dict of {section: {key: value, ...}, ...}.
    """
    config_path = Path(project_dir) / "Config" / f"{config_name}.ini"
    if not config_path.exists():
        # Try with "Default" prefix
        config_path = Path(project_dir) / "Config" / f"Default{config_name}.ini"
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_name}")

    # UE ini files can have duplicate keys and special syntax
    # Use a more tolerant parser
    result = {}
    current_section = "DEFAULT"

    for line in config_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue

        # Section header
        if line.startswith("[") and "]" in line:
            current_section = line[1:line.index("]")]
            if current_section not in result:
                result[current_section] = {}
            continue

        # Key=Value (UE uses +Key, -Key, .Key prefixes for array operations)
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if current_section not in result:
                result[current_section] = {}
            # Handle array-style keys (+Key, -Key)
            if key.startswith("+") or key.startswith("-") or key.startswith("."):
                prefix = key[0]
                bare_key = key[1:]
                array_key = f"{bare_key}"
                if array_key not in result[current_section]:
                    result[current_section][array_key] = []
                if isinstance(result[current_section][array_key], list):
                    result[current_section][array_key].append(
                        {"op": prefix, "value": value}
                    )
                continue
            result[current_section][key] = value

    return result


def set_config(
    project_dir: str,
    config_name: str,
    section: str,
    key: str,
    value: str,
) -> dict:
    """Set a value in a configuration file.

    Args:
        project_dir: Path to project root.
        config_name: Config name (e.g., "DefaultEngine").
        section: INI section name.
        key: Configuration key.
        value: New value.

    Returns:
        {"status": "ok", "file": str, "section": str, "key": str, "value": str}
    """
    config_path = Path(project_dir) / "Config" / f"{config_name}.ini"
    if not config_path.exists():
        config_path = Path(project_dir) / "Config" / f"Default{config_name}.ini"

    lines = []
    if config_path.exists():
        lines = config_path.read_text(encoding="utf-8-sig").splitlines()

    # Find the section and key, replace or append
    in_section = False
    section_found = False
    key_found = False
    new_lines = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("[") and "]" in stripped:
            if in_section and not key_found:
                # Add key at end of previous section
                new_lines.append(f"{key}={value}")
                key_found = True
            current = stripped[1:stripped.index("]")]
            in_section = (current == section)
            if in_section:
                section_found = True

        if in_section and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k == key:
                new_lines.append(f"{key}={value}")
                key_found = True
                continue

        new_lines.append(line)

    # If section exists but key wasn't found, append at end
    if section_found and not key_found:
        # Find last line of the section and insert
        new_lines.append(f"{key}={value}")
    elif not section_found:
        # Add new section
        new_lines.append("")
        new_lines.append(f"[{section}]")
        new_lines.append(f"{key}={value}")

    config_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    return {
        "status": "ok",
        "file": str(config_path),
        "section": section,
        "key": key,
        "value": value,
    }


def list_content(
    project_dir: str,
    filter_ext: str = "",
    filter_path: str = "",
    max_depth: int = 5,
) -> list[dict]:
    """List assets in the Content/ directory.

    Args:
        project_dir: Path to project root.
        filter_ext: Filter by extension (e.g., ".uasset", ".umap").
        filter_path: Filter by path substring.
        max_depth: Maximum recursion depth.

    Returns:
        List of {"name": str, "path": str, "relative_path": str, "ext": str, "size": int}.
    """
    content_dir = Path(project_dir) / "Content"
    if not content_dir.is_dir():
        return []

    assets = []
    for item in _walk_dir(content_dir, max_depth=max_depth):
        if filter_ext and item.suffix.lower() != filter_ext.lower():
            continue
        rel = item.relative_to(content_dir)
        rel_str = str(rel).replace("\\", "/")
        if filter_path and filter_path.lower() not in rel_str.lower():
            continue

        assets.append({
            "name": item.stem,
            "path": str(item),
            "relative_path": rel_str,
            "content_path": f"/Game/{rel_str.rsplit('.', 1)[0]}",
            "ext": item.suffix,
            "size": item.stat().st_size,
        })

    return assets


def _walk_dir(directory: Path, max_depth: int = 5, _depth: int = 0):
    """Walk directory up to max_depth, yielding files."""
    if _depth >= max_depth:
        return
    try:
        for item in sorted(directory.iterdir()):
            if item.is_file():
                yield item
            elif item.is_dir() and not item.name.startswith("."):
                yield from _walk_dir(item, max_depth, _depth + 1)
    except PermissionError:
        pass
