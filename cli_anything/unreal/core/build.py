"""Build system wrapper for Unreal Engine."""

from __future__ import annotations

import json
import re
from pathlib import Path

from cli_anything.unreal.utils.ue_backend import (
    BuildProcessProbeError,
    _build_output_encoding,
    find_engine_root,
    find_generate_project_files,
    find_running_build_processes,
    find_uat,
    get_engine_version,
    kill_build_processes,
    run_build,
    run_uat,
)


_UNSAFE_PACKAGE_VALUE_CHARS = frozenset('"&|<>\0\r\n')
_GAME_TARGET_PATTERN = re.compile(
    r"\bType\s*=\s*TargetType\s*\.\s*Game\s*;"
)
_EDITOR_TARGET_PATTERN = re.compile(
    r"\bType\s*=\s*TargetType\s*\.\s*Editor\s*;"
)
_MODULE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PE_BUILD_PRODUCT_TYPES = frozenset({"dynamiclibrary", "executable"})
_PE_BUILD_PRODUCT_SUFFIXES = frozenset({".dll", ".exe"})
_MAX_REPORTED_INVALID_BUILD_PRODUCTS = 20
_MAX_REPORTED_MISSING_RUNTIME_DEPENDENCIES = 20
_BUILD_STATE_PROCESS_PROBE_TIMEOUT_SECONDS = 3

_TARGET_LEXICAL_NOISE_PATTERN = re.compile(
    r"//[^\r\n]*|/\*.*?\*/|"
    r'@"(?:""|[^"])*"|'
    r'"(?:\\.|[^"\\\r\n])*"|'
    r"'(?:\\.|[^'\\\r\n])*'",
    re.DOTALL,
)


def validate_package_uat_value(
    value: str,
    *,
    label: str,
    require_option: bool = False,
    require_value: bool = False,
) -> str:
    """Validate a package option before it reaches the Windows UAT wrapper."""
    if require_value and not value:
        raise ValueError(f"{label} must not be empty")
    if require_option and not value.startswith("-"):
        raise ValueError(
            f"{label} must start with '-' (for example --uat-arg=-pak)"
        )
    if any(char in _UNSAFE_PACKAGE_VALUE_CHARS for char in value):
        raise ValueError(
            f"Unsafe {label}: literal quotes, shell control characters, and "
            "NUL/CR/LF are not allowed"
        )
    return value


def validate_cook_package(value: str) -> str:
    """Validate one package before combining UE's ``+``-separated list."""
    value = validate_package_uat_value(
        value,
        label="cook package",
        require_value=True,
    )
    if "+" in value:
        raise ValueError("Cook package must not contain '+'")
    return value


def validate_cook_ini_override(value: str) -> str:
    """Validate one ini override before adding the native prefix."""
    value = validate_package_uat_value(
        value,
        label="ini override",
        require_value=True,
    )
    if value.lower().startswith("-ini:"):
        raise ValueError("ini override must omit the '-ini:' prefix")
    return value


def _sanitize_target_source(source: str) -> str:
    def preserve_newlines(value: str) -> str:
        return "".join(char if char in "\r\n" else " " for char in value)

    source = _TARGET_LEXICAL_NOISE_PATTERN.sub(
        lambda match: preserve_newlines(match.group(0)),
        source,
    )
    conditional_depth = 0
    sanitized_lines = []
    for line in source.splitlines(keepends=True):
        directive = re.match(r"^\s*#\s*(if|endif)\b", line)
        if directive:
            if directive.group(1) == "if":
                conditional_depth += 1
            elif conditional_depth:
                conditional_depth -= 1
            sanitized_lines.append(preserve_newlines(line))
        elif conditional_depth:
            sanitized_lines.append(preserve_newlines(line))
        else:
            sanitized_lines.append(line)
    return "".join(sanitized_lines)


def _resolve_game_target(uproject_path: str) -> tuple[str | None, str | None]:
    project_path = Path(uproject_path)
    source_dir = project_path.parent / "Source"
    game_targets = []
    if source_dir.is_dir():
        for target_file in sorted(source_dir.rglob("*.Target.cs")):
            try:
                source = target_file.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                return None, f"Could not read target file {target_file}: {exc}"
            if _GAME_TARGET_PATTERN.search(_sanitize_target_source(source)):
                game_targets.append(target_file.name.removesuffix(".Target.cs"))

    game_targets = sorted(set(game_targets))
    if len(game_targets) > 1:
        return None, (
            "Multiple Game targets found; cannot choose one for compile: "
            + ", ".join(game_targets)
        )
    if game_targets:
        return game_targets[0], None
    return project_path.stem, None


def _resolve_editor_target(uproject_path: str) -> tuple[str | None, str | None]:
    project_path = Path(uproject_path)
    source_dir = project_path.parent / "Source"
    editor_targets = []
    if source_dir.is_dir():
        for target_file in sorted(source_dir.rglob("*.Target.cs")):
            try:
                source = target_file.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                return None, f"Could not read target file {target_file}: {exc}"
            if _EDITOR_TARGET_PATTERN.search(_sanitize_target_source(source)):
                editor_targets.append(
                    target_file.name.removesuffix(".Target.cs")
                )

    editor_targets = sorted(set(editor_targets))
    if len(editor_targets) > 1:
        return None, (
            "Multiple Editor targets found; cannot choose one for module compile: "
            + ", ".join(editor_targets)
        )
    if editor_targets:
        return editor_targets[0], None
    return project_path.stem + "Editor", None


def validate_module_name(value: str) -> str:
    if not _MODULE_NAME_PATTERN.fullmatch(value):
        raise ValueError(
            f"Invalid module name {value!r}; expected a C++ identifier such as Renderer"
        )
    return value


def _find_module_hot_reload_state_files(
    uproject_path: str,
    target: str,
    platform: str,
    config: str,
) -> list[Path]:
    """Find UBT state that a module-only build must preserve."""
    build_root = Path(uproject_path).parent / "Intermediate" / "Build" / platform
    if not build_root.is_dir():
        return []

    matches = []
    for state_file in build_root.rglob("HotReloadState.bin"):
        relative_parts = state_file.relative_to(build_root).parts
        if len(relative_parts) < 3:
            continue
        if (
            relative_parts[-3].casefold() == target.casefold()
            and relative_parts[-2].casefold() == config.casefold()
        ):
            matches.append(state_file)
    return sorted(matches)


def _check_already_building(uproject_path: str) -> dict | None:
    processes = find_running_build_processes(uproject_path)
    if not processes:
        return None
    return {
        "status": "error",
        "error": "Build already in progress for this project.",
        "running_processes": processes,
    }


def _build_failure_diagnostics(log_file: str | None) -> dict:
    """Extract bounded, factual diagnostics from a failed UAT/UBT log."""
    if not log_file:
        return {}
    path = Path(log_file)
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - 2 * 1024 * 1024))
            text = handle.read().decode(_build_output_encoding(), errors="replace")
    except OSError:
        return {}

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    compiler_diagnostics = []
    for line in lines:
        if re.search(
            r"\bfatal error\b|\berror (?:C|LNK)\d+\b|:\s*error:",
            line,
            re.IGNORECASE,
        ):
            compiler_diagnostics.append(line)
    compiler_diagnostics = list(dict.fromkeys(compiler_diagnostics))[-20:]
    if compiler_diagnostics:
        return {
            "failure_kind": "compiler_diagnostics",
            "diagnostics": compiler_diagnostics,
        }

    if not re.search(r"failed to compile with bk tools|bk-ubt-tool", text, re.IGNORECASE):
        return {}

    result = {
        "failure_kind": "distributed_executor_failed_without_diagnostic",
        "executor": "bk_dist",
        "diagnostic": (
            "bk_dist failed without emitting a compiler diagnostic; inspect the "
            "actions JSON or rerun through the project's normal build path for the failing action."
        ),
    }
    action_matches = re.findall(
        r"(?:Parallel executor to run|Building)\s+(\d+)\s+action",
        text,
        re.IGNORECASE,
    )
    if action_matches:
        result["action_count"] = int(action_matches[-1])
    exit_matches = re.findall(r"exit code:\s*(-?\d+)", text, re.IGNORECASE)
    if exit_matches:
        result["executor_exit_code"] = int(exit_matches[-1])
    actions_matches = re.findall(
        r"(?:--actions_json_file\s+|failed to run actions with json file:\s*)([^\s\"']+|\"[^\"]+\"|'[^']+')",
        text,
        re.IGNORECASE,
    )
    if actions_matches:
        result["actions_json_file"] = actions_matches[-1].strip("\"'")
    return result


def _normalize_result(result: dict, action: str) -> dict:
    out = {
        "status": "ok" if result["returncode"] == 0 else "error",
        "returncode": result["returncode"],
        "duration_seconds": result.get("duration_seconds", 0.0),
        "log_file": result.get("log_file", ""),
    }
    if result.get("command"):
        out["uat_command"] = result["command"]
    if result["returncode"] != 0:
        out["error"] = result.get(
            "error",
            f"{action} failed (exit {result['returncode']}). See log_file for details.",
        )
        out.update(_build_failure_diagnostics(result.get("log_file")))
    return out


def _validate_pe_image(path: Path) -> str | None:
    """Return a concise reason when a Windows build product is not a PE image."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            dos_header = handle.read(64)
            if len(dos_header) < 64:
                return f"file is too small for a DOS header ({size} bytes)"
            if dos_header[:2] != b"MZ":
                return "missing DOS MZ signature"

            pe_offset = int.from_bytes(dos_header[0x3C:0x40], "little")
            if pe_offset < 64 or pe_offset > size - 26:
                return f"invalid PE header offset {pe_offset}"

            handle.seek(pe_offset)
            coff_header = handle.read(24)
            if len(coff_header) != 24 or coff_header[:4] != b"PE\0\0":
                return "missing PE signature"

            machine = int.from_bytes(coff_header[4:6], "little")
            section_count = int.from_bytes(coff_header[6:8], "little")
            optional_header_size = int.from_bytes(coff_header[20:22], "little")
            characteristics = int.from_bytes(coff_header[22:24], "little")
            if machine == 0:
                return "COFF machine is zero"
            if section_count == 0:
                return "COFF section count is zero"
            if optional_header_size < 64:
                return "PE optional header is missing"

            optional_header_end = pe_offset + 24 + optional_header_size
            if optional_header_end > size:
                return "optional header extends past end of file"
            section_table_end = optional_header_end + section_count * 40
            if section_table_end > size:
                return "section table extends past end of file"

            optional_header = handle.read(optional_header_size)
            optional_magic = int.from_bytes(optional_header[:2], "little")
            if optional_magic not in (0x10B, 0x20B):
                return f"invalid PE optional header magic 0x{optional_magic:04x}"
            section_alignment = int.from_bytes(optional_header[32:36], "little")
            file_alignment = int.from_bytes(optional_header[36:40], "little")
            size_of_image = int.from_bytes(optional_header[56:60], "little")
            size_of_headers = int.from_bytes(optional_header[60:64], "little")
            if section_alignment == 0 or file_alignment == 0:
                return "PE alignment is zero"
            if size_of_headers < section_table_end:
                return "SizeOfHeaders does not include the section table"
            if size_of_headers > size:
                return "SizeOfHeaders extends past end of file"
            if size_of_image < size_of_headers:
                return "SizeOfImage is smaller than SizeOfHeaders"
            if path.suffix.casefold() == ".dll" and not characteristics & 0x2000:
                return "COFF DLL characteristic is missing"

            section_table = handle.read(section_count * 40)
            for index in range(section_count):
                section = section_table[index * 40:(index + 1) * 40]
                raw_size = int.from_bytes(section[16:20], "little")
                raw_offset = int.from_bytes(section[20:24], "little")
                if raw_size and (
                    raw_offset == 0
                    or raw_offset > size
                    or raw_size > size - raw_offset
                ):
                    return f"section {index} raw data extends past end of file"
    except FileNotFoundError:
        return "file is missing"
    except OSError as exc:
        return f"could not read file: {exc}"
    return None


def _resolve_receipt_product_path(
    value: str,
    *,
    project_dir: Path,
    engine_root: Path,
) -> Path | None:
    replacements = {
        "$(ProjectDir)": str(project_dir),
        "$(EngineDir)": str(engine_root / "Engine"),
    }
    for prefix, root in replacements.items():
        if value.startswith(prefix):
            return Path(root + value[len(prefix):])
    if "$(" in value:
        return None
    path = Path(value)
    return path if path.is_absolute() else project_dir / path


def _invalid_build_receipt(receipt_path: Path, reason: str) -> dict:
    return {
        "status": "error",
        "code": "INVALID_BUILD_OUTPUT",
        "failure_kind": "invalid_build_receipt",
        "receipt_file": str(receipt_path),
        "error": f"Compile exited 0, but the Editor target receipt is invalid: {reason}",
    }


def _load_editor_target_receipt(
    project_dir: Path,
    target: str,
    config: str,
) -> tuple[Path | None, dict | None, dict | None]:
    """Load the receipt path selected by UE's target/config naming rules."""
    bin_dir = project_dir / "Binaries" / "Win64"
    candidates = []
    if config.casefold() == "development":
        default_path = bin_dir / f"{target}.target"
        if default_path.is_file():
            candidates.append(default_path)
    candidates.extend(bin_dir.glob(f"{target}-Win64-{config}*.target"))
    candidates = sorted(
        dict.fromkeys(candidates),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )

    first_error = None
    for receipt_path in candidates:
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            if first_error is None:
                first_error = _invalid_build_receipt(receipt_path, str(exc))
            continue
        if not isinstance(receipt, dict):
            if first_error is None:
                first_error = _invalid_build_receipt(
                    receipt_path,
                    "root value is not an object",
                )
            continue
        if str(receipt.get("TargetName", "")).casefold() != target.casefold():
            continue
        if str(receipt.get("TargetType", "")).casefold() != "editor":
            continue
        if str(receipt.get("Platform", "")).casefold() != "win64":
            continue
        if str(receipt.get("Configuration", "")).casefold() != config.casefold():
            continue
        return receipt_path, receipt, None
    return None, None, first_error


def inspect_win64_editor_runtime_dependencies(
    uproject_path: str,
    engine_root: str | None,
    config: str = "Development",
) -> dict:
    """Inspect runtime dependencies declared by the current Editor receipt."""
    target, target_error = _resolve_editor_target(uproject_path)
    if target_error or not target:
        return {
            "status": "unavailable",
            "reason": "editor_target_unresolved",
            "message": target_error or "Could not resolve the Editor target.",
        }

    resolved_engine_root = engine_root or find_engine_root(uproject_path)
    if not resolved_engine_root:
        return {
            "status": "unavailable",
            "reason": "engine_root_unresolved",
            "message": "Could not resolve the engine root for output inspection.",
        }

    project_dir = Path(uproject_path).parent
    receipt_path, receipt, receipt_error = _load_editor_target_receipt(
        project_dir,
        target,
        config,
    )
    if receipt_error:
        return {
            "status": "unavailable",
            "reason": "invalid_editor_target_receipt",
            "receipt_file": receipt_error.get("receipt_file"),
            "message": "Could not read a valid Editor target receipt for output inspection.",
        }
    if receipt_path is None or receipt is None:
        return {
            "status": "unavailable",
            "reason": "editor_target_receipt_not_found",
            "expected_receipt_directory": str(project_dir / "Binaries" / "Win64"),
            "message": "No matching Editor target receipt exists for output inspection.",
        }

    runtime_dependencies = receipt.get("RuntimeDependencies")
    if not isinstance(runtime_dependencies, list):
        return {
            "status": "unavailable",
            "reason": "runtime_dependencies_not_declared",
            "receipt_file": str(receipt_path),
            "message": "Editor target receipt does not declare RuntimeDependencies.",
        }

    missing_paths: list[str] = []
    unresolved_entries: list[dict] = []
    seen_paths: set[str] = set()
    engine_path = Path(resolved_engine_root)
    for index, dependency in enumerate(runtime_dependencies):
        if not isinstance(dependency, dict):
            unresolved_entries.append({
                "index": index,
                "reason": "entry is not an object",
            })
            continue
        raw_path = dependency.get("Path")
        if not isinstance(raw_path, str) or not raw_path:
            unresolved_entries.append({
                "index": index,
                "reason": "Path is missing or is not a string",
            })
            continue
        path = _resolve_receipt_product_path(
            raw_path,
            project_dir=project_dir,
            engine_root=engine_path,
        )
        if path is None:
            unresolved_entries.append({
                "index": index,
                "path": raw_path,
                "reason": "unsupported path macro",
            })
            continue
        path_text = str(path)
        path_key = path_text.replace("/", "\\").casefold()
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        if not path.exists():
            missing_paths.append(path_text)

    recovery_command = (
        f'ue-cli --project "{uproject_path}" build compile '
        f"--platform Win64 --config {config}"
    )
    result = {
        "status": "ok",
        "receipt_file": str(receipt_path),
        "checked_runtime_dependency_count": len(seen_paths),
        "unresolved_runtime_dependency_count": len(unresolved_entries),
    }
    if unresolved_entries:
        result["unresolved_runtime_dependencies"] = unresolved_entries[
            :_MAX_REPORTED_MISSING_RUNTIME_DEPENDENCIES
        ]
    if not missing_paths:
        return result

    missing_count = len(missing_paths)
    result.update({
        "status": "incomplete",
        "code": "BUILD_CANCELLED_OUTPUTS_INCOMPLETE",
        "failure_kind": "missing_runtime_dependencies",
        "missing_runtime_dependency_count": missing_count,
        "missing_runtime_dependencies": missing_paths[
            :_MAX_REPORTED_MISSING_RUNTIME_DEPENDENCIES
        ],
        "missing_runtime_dependencies_truncated": (
            missing_count > _MAX_REPORTED_MISSING_RUNTIME_DEPENDENCIES
        ),
        "recovery_command": recovery_command,
        "message": (
            f"Cancellation completed, but {missing_count} runtime dependency "
            f"path(s) declared by {receipt_path.name} are missing. The Editor "
            "target may not launch; run a full Editor build to restore it."
        ),
    })
    return result


def _validate_win64_editor_build_products(
    uproject_path: str,
    engine_root: str,
    config: str,
    modules: list[str] | tuple[str, ...] | None = None,
) -> dict:
    """Validate PE products declared by UE's generated Editor target receipt."""
    target, target_error = _resolve_editor_target(uproject_path)
    if target_error or not target:
        return {}

    project_dir = Path(uproject_path).parent
    receipt_path, receipt, receipt_error = _load_editor_target_receipt(
        project_dir,
        target,
        config,
    )
    if receipt_error:
        return receipt_error
    if receipt_path is None or receipt is None:
        if modules:
            return {
                "status": "error",
                "code": "INVALID_BUILD_OUTPUT",
                "failure_kind": "missing_editor_target_receipt",
                "expected_receipt_directory": str(project_dir / "Binaries" / "Win64"),
                "error": (
                    "Compile exited 0, but the module-targeted build left no "
                    "Editor target receipt. The target may not be launchable; "
                    "run a full build compile to restore launch metadata."
                ),
            }
        return {}

    products = receipt.get("BuildProducts")
    if not isinstance(products, list):
        return _invalid_build_receipt(
            receipt_path,
            "BuildProducts is not an array",
        )

    invalid_products = []
    missing_module_manifests = []
    validated_count = 0
    engine_path = Path(engine_root)
    requested_modules = {module.casefold() for module in (modules or ())}
    for index, product in enumerate(products):
        if not isinstance(product, dict):
            return _invalid_build_receipt(
                receipt_path,
                f"BuildProducts[{index}] is not an object",
            )
        product_type = str(product.get("Type", ""))
        raw_path = str(product.get("Path", ""))
        if (
            requested_modules
            and product_type.casefold() == "requiredresource"
            and Path(raw_path).suffix.casefold() == ".modules"
        ):
            path = _resolve_receipt_product_path(
                raw_path,
                project_dir=project_dir,
                engine_root=engine_path,
            )
            if path is None:
                return _invalid_build_receipt(
                    receipt_path,
                    f"unsupported path macro in BuildProducts[{index}]: {raw_path}",
                )
            if not path.is_file():
                missing_module_manifests.append(str(path))
            continue
        if product_type.casefold() not in _PE_BUILD_PRODUCT_TYPES:
            continue
        if Path(raw_path).suffix.casefold() not in _PE_BUILD_PRODUCT_SUFFIXES:
            continue
        if requested_modules:
            binary_tokens = set(Path(raw_path).stem.casefold().split("-"))
            if requested_modules.isdisjoint(binary_tokens):
                continue

        path = _resolve_receipt_product_path(
            raw_path,
            project_dir=project_dir,
            engine_root=engine_path,
        )
        if path is None:
            return _invalid_build_receipt(
                receipt_path,
                f"unsupported path macro in BuildProducts[{index}]: {raw_path}",
            )
        validated_count += 1
        reason = _validate_pe_image(path)
        if reason:
            invalid_products.append({
                "path": str(path),
                "type": product_type,
                "reason": reason,
            })

    if missing_module_manifests:
        missing_count = len(missing_module_manifests)
        return {
            "status": "error",
            "code": "INVALID_BUILD_OUTPUT",
            "failure_kind": "missing_editor_module_manifests",
            "receipt_file": str(receipt_path),
            "missing_module_manifest_count": missing_count,
            "missing_module_manifests": missing_module_manifests[
                :_MAX_REPORTED_INVALID_BUILD_PRODUCTS
            ],
            "error": (
                f"Compile exited 0, but {missing_count} Editor module manifest(s) "
                "declared by the target receipt are missing. The target is not "
                "launchable; run a full build compile to restore launch metadata."
            ),
        }

    if validated_count == 0:
        if requested_modules:
            reason = (
                "BuildProducts contains no PE file for requested module(s): "
                + ", ".join(sorted(modules or ()))
            )
        else:
            reason = "BuildProducts contains no resolvable PE files"
        return _invalid_build_receipt(
            receipt_path,
            reason,
        )
    if not invalid_products:
        return {}

    invalid_count = len(invalid_products)
    return {
        "status": "error",
        "code": "INVALID_BUILD_OUTPUT",
        "failure_kind": "invalid_pe_build_product",
        "receipt_file": str(receipt_path),
        "validated_pe_products": validated_count,
        "invalid_build_product_count": invalid_count,
        "invalid_build_products": invalid_products[
            :_MAX_REPORTED_INVALID_BUILD_PRODUCTS
        ],
        "error": (
            f"Compile exited 0, but {invalid_count} PE build product(s) declared "
            f"by {receipt_path.name} are missing or malformed. The target is not "
            "launchable; inspect invalid_build_products and rebuild through the "
            "project's normal local build path."
        ),
    }


def _normalize_compile_result(
    result: dict,
    *,
    uproject_path: str,
    engine_root: str,
    config: str,
    platform: str,
    modules: list[str] | tuple[str, ...] | None = None,
) -> dict:
    out = _normalize_result(result, "Compile")
    if out["status"] != "ok" or platform.casefold() != "win64":
        return out
    validation = _validate_win64_editor_build_products(
        uproject_path,
        engine_root,
        config,
        modules,
    )
    if validation.get("status") == "error":
        out.update(validation)
    return out


def compile_project(
    uproject_path: str,
    config: str = "Development",
    platform: str = "Win64",
    engine_root: str | None = None,
    log_file: str | None = None,
    on_start=None,
    modules: list[str] | tuple[str, ...] | None = None,
) -> dict:
    try:
        modules = [validate_module_name(value) for value in (modules or ())]
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    if modules and platform.lower() != "win64":
        return {
            "status": "error",
            "error": "Module-targeted compile is supported only for Win64 Editor targets.",
        }

    already = _check_already_building(uproject_path)
    if already:
        return already

    engine_root = engine_root or find_engine_root(uproject_path)
    if not engine_root:
        return {"status": "error", "error": "Could not find engine root"}

    if modules:
        target, target_error = _resolve_editor_target(uproject_path)
        if target_error:
            return {"status": "error", "error": target_error}
        try:
            hot_reload_state_files = _find_module_hot_reload_state_files(
                uproject_path,
                target,
                platform,
                config,
            )
        except OSError as exc:
            return {
                "status": "error",
                "code": "HOT_RELOAD_STATE_PROBE_FAILED",
                "error": (
                    "Could not inspect existing UBT hot-reload state before the "
                    f"module-targeted build: {exc}"
                ),
            }
        extra_args = [f"-Project={uproject_path}"]
        if hot_reload_state_files:
            # UBT's disabled-hot-reload setup deletes previous temporary metadata
            # before -Module filters output actions. Keeping hot reload enabled
            # reapplies that state and rewrites the affected manifests instead.
            extra_args.append("-ForceHotReload")
        extra_args.extend(f"-Module={module}" for module in modules)
        extra_args.append("-WaitMutex")
        result = run_build(
            engine_root,
            target,
            platform,
            config,
            extra_args=extra_args,
            log_file=log_file,
            log_label="compile",
            project_dir=str(Path(uproject_path).parent),
            on_start=on_start,
        )
        return _normalize_compile_result(
            result,
            uproject_path=uproject_path,
            engine_root=engine_root,
            config=config,
            platform=platform,
            modules=modules,
        )

    if platform.lower() != "win64":
        target, target_error = _resolve_game_target(uproject_path)
        if target_error:
            return {"status": "error", "error": target_error}
        result = run_build(
            engine_root,
            target,
            platform,
            config,
            extra_args=[f"-Project={uproject_path}", "-WaitMutex"],
            log_file=log_file,
            log_label="compile",
            project_dir=str(Path(uproject_path).parent),
            on_start=on_start,
        )
        return _normalize_compile_result(
            result,
            uproject_path=uproject_path,
            engine_root=engine_root,
            config=config,
            platform=platform,
            modules=modules,
        )

    args = [
        f"-project={uproject_path}",
        f"-platform={platform}",
        f"-clientconfig={config}",
        "-build",
        "-noP4",
    ]
    result = run_uat(
        engine_root,
        "BuildCookRun",
        args,
        log_file=log_file,
        log_label="compile",
        project_dir=str(Path(uproject_path).parent),
        on_start=on_start,
    )
    return _normalize_compile_result(
        result,
        uproject_path=uproject_path,
        engine_root=engine_root,
        config=config,
        platform=platform,
        modules=modules,
    )


def cook_content(
    uproject_path: str,
    platform: str = "Win64",
    engine_root: str | None = None,
    log_file: str | None = None,
    on_start=None,
    *,
    packages: list[str] | tuple[str, ...] | None = None,
    output_dir: str | None = None,
    ini_overrides: list[str] | tuple[str, ...] | None = None,
) -> dict:
    try:
        packages = [validate_cook_package(value) for value in (packages or ())]
        if output_dir is not None:
            output_dir = validate_package_uat_value(
                output_dir,
                label="cook output directory",
                require_value=True,
            )
        ini_overrides = [
            validate_cook_ini_override(value)
            for value in (ini_overrides or ())
        ]
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}

    already = _check_already_building(uproject_path)
    if already:
        return already

    engine_root = engine_root or find_engine_root(uproject_path)
    if not engine_root:
        return {"status": "error", "error": "Could not find engine root"}

    args = [
        f"-project={uproject_path}",
        f"-platform={platform}",
        "-cook",
        "-noP4",
    ]
    if packages:
        args.append(
            "-AdditionalCookerOptions=-Package=" + "+".join(packages)
        )
    else:
        args.append("-allmaps")
    if output_dir:
        args.append(f"-CookOutputDir={output_dir}")
    args.extend(f"-ini:{override}" for override in ini_overrides)
    result = run_uat(
        engine_root,
        "BuildCookRun",
        args,
        log_file=log_file,
        log_label="cook",
        project_dir=str(Path(uproject_path).parent),
        on_start=on_start,
    )
    return _normalize_result(result, "Cook")


def package_project(
    uproject_path: str,
    platform: str = "Win64",
    config: str = "Development",
    output_dir: str | None = None,
    engine_root: str | None = None,
    log_file: str | None = None,
    on_start=None,
    *,
    maps: list[str] | tuple[str, ...] | None = None,
    cook_flavor: str | None = None,
    uat_args: list[str] | tuple[str, ...] | None = None,
) -> dict:
    try:
        maps = [
            validate_package_uat_value(value, label="map")
            for value in (maps or ())
        ]
        if cook_flavor is not None:
            cook_flavor = validate_package_uat_value(
                cook_flavor,
                label="cook flavor",
            )
        uat_args = [
            validate_package_uat_value(
                value,
                label="UAT argument",
                require_option=True,
            )
            for value in (uat_args or ())
        ]
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}

    already = _check_already_building(uproject_path)
    if already:
        return already

    engine_root = engine_root or find_engine_root(uproject_path)
    if not engine_root:
        return {"status": "error", "error": "Could not find engine root"}

    path = Path(uproject_path)
    output_dir = output_dir or str(path.parent / "Packaged")
    args = [
        f"-project={uproject_path}",
        f"-platform={platform}",
        f"-clientconfig={config}",
        "-build",
        "-cook",
        "-stage",
        "-package",
        "-archive",
        f"-archivedirectory={output_dir}",
        "-noP4",
    ]
    if maps:
        args.append("-map=" + "+".join(maps))
    if cook_flavor:
        args.append(f"-cookflavor={cook_flavor}")
    if uat_args:
        args.extend(uat_args)
    result = run_uat(
        engine_root,
        "BuildCookRun",
        args,
        log_file=log_file,
        log_label="package",
        project_dir=str(path.parent),
        on_start=on_start,
    )
    out = _normalize_result(result, "Package")
    out["output_dir"] = output_dir
    return out


def build_status(uproject_path: str) -> dict:
    path = Path(uproject_path)
    project_dir = path.parent
    project_name = path.stem
    binaries_dir = project_dir / "Binaries"
    intermediate_dir = project_dir / "Intermediate"

    status = {
        "project": project_name,
        "has_binaries": binaries_dir.is_dir(),
        "has_intermediate": intermediate_dir.is_dir(),
        "platforms": {},
    }

    if binaries_dir.is_dir():
        for platform_dir in binaries_dir.iterdir():
            if not platform_dir.is_dir():
                continue
            binaries = list(platform_dir.glob("*.dll")) + list(platform_dir.glob("*.exe"))
            newest = None
            newest_time = 0.0
            for binary in binaries:
                mtime = binary.stat().st_mtime
                if mtime > newest_time:
                    newest = binary.name
                    newest_time = mtime
            status["platforms"][platform_dir.name] = {
                "binary_count": len(binaries),
                "newest_binary": newest,
                "newest_time": newest_time,
            }

    saved_dir = project_dir / "Saved" / "Logs"
    if saved_dir.is_dir():
        log_files = sorted(saved_dir.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        status["recent_logs"] = [
            {"name": log.name, "size": log.stat().st_size}
            for log in log_files[:5]
        ]

    return status


def generate_project_files(uproject_path: str, engine_root: str | None = None) -> dict:
    engine_root = engine_root or find_engine_root(uproject_path)
    if not engine_root:
        return {"status": "error", "error": "Could not find engine root"}

    project_dir = str(Path(uproject_path).parent)
    gen_bat = find_generate_project_files(engine_root)
    if gen_bat:
        from cli_anything.unreal.utils.ue_backend import _allocate_log_path, _run_subprocess

        log_file = _allocate_log_path(project_dir, "genproj")
        result = _run_subprocess([gen_bat, f"-project={uproject_path}", "-game", "-engine"], log_file=log_file)
    else:
        result = run_uat(
            engine_root,
            "GenerateProjectFiles",
            [f"-project={uproject_path}", "-game", "-engine"],
            log_label="genproj",
            project_dir=project_dir,
        )
    return _normalize_result(result, "Generate project files")


def stop_build(uproject_path: str) -> dict:
    from cli_anything.unreal.core.tasks import (
        FINAL_TASK_STATUSES,
        active_build_tasks,
        cancel_task,
        reconcile_task_cancellation,
    )

    task_results = []
    for task in active_build_tasks(uproject_path):
        cancelled = cancel_task(task["task_id"])
        if cancelled is None:
            continue
        cancel_result = cancelled.get("cancel_result", {})
        task_result = {
            "task_id": cancelled["task_id"],
            "status": cancelled.get("status"),
            "pid": cancelled.get("pid"),
            "worker_pid": cancelled.get("worker_pid"),
            "killed": cancel_result.get("killed", []),
            "remaining": cancel_result.get("remaining", []),
        }
        if cancel_result.get("processes"):
            task_result["processes"] = cancel_result["processes"]
        if cancelled.get("error"):
            task_result["error"] = cancelled["error"]
        task_results.append(task_result)

    tracked_tasks_cancelled = bool(task_results) and all(
        task["status"] in FINAL_TASK_STATUSES and not task["remaining"]
        for task in task_results
    )
    if tracked_tasks_cancelled:
        result = {
            "status": "skipped",
            "killed": [],
            "remaining": [],
            "process_probe": {
                "status": "skipped",
                "reason": "tracked_tasks_cancelled",
            },
        }
    else:
        try:
            result = kill_build_processes(
                uproject_path,
                query_timeout=_BUILD_STATE_PROCESS_PROBE_TIMEOUT_SECONDS,
                fail_on_probe_error=True,
            )
        except BuildProcessProbeError as exc:
            result = {
                "status": "partial",
                "killed": [],
                "remaining": [],
                "process_probe": {
                    "status": "failed",
                    "message": str(exc),
                    "details": exc.details,
                },
            }
    final_scan_killed = result.get("killed", [])
    for task in task_results:
        reconciled = reconcile_task_cancellation(task["task_id"], final_scan_killed)
        if reconciled is None:
            continue
        cancel_result = reconciled.get("cancel_result", {})
        task.update({
            "status": reconciled.get("status"),
            "killed": cancel_result.get("killed", []),
            "remaining": cancel_result.get("remaining", []),
        })
        if cancel_result.get("processes"):
            task["processes"] = cancel_result["processes"]
        else:
            task.pop("processes", None)
        if reconciled.get("error"):
            task["error"] = reconciled["error"]
        else:
            task.pop("error", None)

    killed = list(result.get("killed", []))
    remaining = list(result.get("remaining", []))
    for task in task_results:
        killed.extend(task["killed"])
        remaining.extend(task["remaining"])
    killed = list(dict.fromkeys(killed))
    killed_set = set(killed)
    remaining = [
        pid for pid in dict.fromkeys(remaining)
        if pid not in killed_set
    ]

    if result.get("status") == "partial" or remaining or any(
        task["status"] not in FINAL_TASK_STATUSES for task in task_results
    ):
        status = "partial"
    elif task_results or killed:
        status = "ok"
    else:
        status = result["status"]

    response = {
        "status": status,
        "killed": killed,
        "remaining": remaining,
    }
    if task_results:
        response["tasks"] = task_results
    if "process_probe" in result:
        response["process_probe"] = result["process_probe"]
    return response


def is_building(uproject_path: str) -> dict:
    from cli_anything.unreal.core.tasks import active_build_tasks

    tasks = []
    for task in active_build_tasks(uproject_path):
        evidence = {
            key: task[key]
            for key in (
                "task_id",
                "command",
                "status",
                "worker_pid",
                "pid",
                "log_file",
            )
            if key in task
        }
        tasks.append(evidence)

    # A non-final ue-cli task already answers the busy-state question. Avoid
    # delaying its JSON response on the much slower Windows CIM process scan.
    if tasks:
        processes = []
        process_probe = {
            "status": "skipped",
            "reason": "active_task_state",
        }
    else:
        processes = find_running_build_processes(
            uproject_path,
            include_cmdline=False,
            query_timeout=_BUILD_STATE_PROCESS_PROBE_TIMEOUT_SECONDS,
            fail_on_error=True,
        )
        process_probe = {"status": "ok"}

    kinds: dict[str, int] = {}
    for process in processes:
        name = process.get("name", "")
        kinds[name] = kinds.get(name, 0) + 1

    result = {
        "building": bool(processes or tasks),
        "count": len(processes),
        "kinds": kinds,
        "processes": processes,
        "active_task_count": len(tasks),
        "active_tasks": tasks,
        "process_probe": process_probe,
    }

    saved_logs = Path(uproject_path).parent / "Saved" / "Logs"
    if saved_logs.is_dir():
        cli_logs = sorted(saved_logs.glob("cli_*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        if cli_logs:
            result["latest_log"] = str(cli_logs[0])
    return result
