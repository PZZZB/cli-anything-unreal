"""ue_http_api.py — HTTP API client for communicating with a running UE editor.

Uses the UE Remote Control API (default port 30010) to execute functions,
manage properties, query assets, and run console commands.

Remote Control API reference:
  GET  /remote/info                — List available routes
  PUT  /remote/object/call         — Call function on UObject
  PUT  /remote/object/property     — Get/set property on UObject
  PUT  /remote/object/describe     — Describe a UObject
  PUT  /remote/search/assets       — Search assets by class/path
  PUT  /remote/object/thumbnail    — Get object thumbnail

Supports multi-instance scenarios via configurable port.
"""

import json
import locale
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore


def _decode_windows_command_output(data: bytes | str | None) -> str:
    """Decode Windows command output without relying on UTF-8 locales."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data

    preferred = locale.getpreferredencoding(False)
    encodings = []
    for encoding in (preferred, "mbcs", "utf-8", "cp936"):
        if encoding and encoding not in encodings:
            encodings.append(encoding)

    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode(preferred or "utf-8", errors="replace")


def _select_editor_window_hwnd(candidates: list[dict]) -> int | None:
    """Pick the best Unreal Editor window from enumerated HWND candidates."""
    eligible = []
    for candidate in candidates:
        class_name = str(candidate.get("class_name") or "")
        title = str(candidate.get("title") or "")
        area = int(candidate.get("area") or 0)
        if not candidate.get("visible") or area <= 0:
            continue
        if not title and class_name != "UnrealWindow":
            continue
        eligible.append(candidate)

    if not eligible:
        return None

    def _score(candidate: dict) -> tuple[int, int, int, int, int]:
        class_name = str(candidate.get("class_name") or "")
        title = str(candidate.get("title") or "")
        pid_rank = int(candidate.get("pid_rank") or 0)
        area = int(candidate.get("area") or 0)
        return (
            -pid_rank,
            1 if "unreal editor" in title.lower() else 0,
            1 if class_name == "UnrealWindow" else 0,
            area,
            1 if title else 0,
        )

    hwnd = max(eligible, key=_score).get("hwnd")
    return int(hwnd) if hwnd else None


class UEEditorAPI:
    """HTTP API client for a running Unreal Editor instance.

    Uses the UE Remote Control plugin (enabled via RemoteControl plugin).
    Default port is 30010.
    """

    def __init__(self, host: str = "localhost", port: int = 30010, timeout: int = 30):
        """Initialize the API client.

        Args:
            host: Editor hostname.
            port: Remote Control HTTP API port (default 30010).
            timeout: Default request timeout in seconds.
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.base_url = f"http://{host}:{port}"

        if requests is None:
            raise ImportError(
                "The 'requests' library is required for HTTP API. "
                "Install it with: pip install requests"
            )

    def _url(self, endpoint: str) -> str:
        """Build full URL for an endpoint."""
        return f"{self.base_url}/{endpoint.lstrip('/')}"

    def _get(self, endpoint: str, params: dict | None = None, **kwargs) -> dict:
        """Send GET request."""
        timeout = kwargs.pop("timeout", self.timeout)
        try:
            resp = requests.get(
                self._url(endpoint),
                params=params,
                timeout=timeout,
                **kwargs,
            )
            resp.raise_for_status()
            return resp.json() if resp.text.strip() else {"status": "ok"}
        except requests.exceptions.JSONDecodeError:
            return {"status": "ok", "raw": resp.text}
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    def _put(self, endpoint: str, data: dict | None = None, **kwargs) -> dict:
        """Send PUT request."""
        timeout = kwargs.pop("timeout", self.timeout)
        try:
            resp = requests.put(
                self._url(endpoint),
                json=data,
                timeout=timeout,
                **kwargs,
            )
            resp.raise_for_status()
            return resp.json() if resp.text.strip() else {"status": "ok"}
        except requests.exceptions.JSONDecodeError:
            return {"status": "ok", "raw": resp.text}
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    # ── Connection ──────────────────────────────────────────────────────

    def is_alive(self) -> bool:
        """Check if the editor Remote Control API is responding."""
        try:
            resp = requests.get(
                self._url("/remote/info"),
                timeout=3,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def wait_for_ready(self, timeout: int = 120, poll_interval: float = 2.0) -> bool:
        """Wait until the editor API is ready.

        Args:
            timeout: Max wait time in seconds.
            poll_interval: Seconds between polls.

        Returns:
            True if editor became ready, False if timed out.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_alive():
                return True
            time.sleep(poll_interval)
        return False

    def get_info(self) -> dict:
        """Get Remote Control API route info."""
        return self._get("/remote/info")

    # ── Remote Control: Object Calls ────────────────────────────────────

    def call_function(self, object_path: str, function_name: str,
                      params: dict | None = None,
                      generate_transaction: bool = False,
                      timeout: int | None = None) -> dict:
        """Call a function on a UObject.

        Args:
            object_path: UObject path (e.g., "/Script/Engine.Default__KismetSystemLibrary").
            function_name: Function name to call.
            params: Function parameters dict.
            generate_transaction: Whether to generate an undo transaction.
            timeout: HTTP request timeout override (uses ``self.timeout`` if *None*).

        Returns:
            API response with ReturnValue.
        """
        data = {
            "objectPath": object_path,
            "functionName": function_name,
            "parameters": params or {},
            "generateTransaction": generate_transaction,
        }
        kwargs = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        return self._put("/remote/object/call", data, **kwargs)

    def get_property(self, object_path: str, property_name: str,
                     skip_private: bool = True) -> dict:
        """Get a property value on a UObject.

        Args:
            object_path: UObject path.
            property_name: Property name.
            skip_private: If True, first check via describe whether the property
                is accessible. Private properties (without AllowPrivateAccess)
                will trigger "Property is not readable" errors in the UE editor
                log if accessed directly. Default True to avoid log spam.

        Returns:
            Property value dict, or {"error": "..."} if inaccessible.
        """
        if skip_private:
            # Check if the property is listed by describe (private props are excluded)
            desc = self.describe_object(object_path)
            if "error" not in desc and "errorMessage" not in desc:
                visible_props = {p.get("Name", "") for p in desc.get("Properties", [])}
                if property_name not in visible_props:
                    return {"error": f"Property '{property_name}' is not accessible via Remote Control (likely private)."}

        data = {
            "objectPath": object_path,
            "propertyName": property_name,
            "access": "READ_ACCESS",
        }
        return self._put("/remote/object/property", data)

    def set_property(self, object_path: str, property_name: str, value) -> dict:
        """Set a property value on a UObject.

        Args:
            object_path: UObject path.
            property_name: Property name.
            value: New value.

        Returns:
            API response.
        """
        data = {
            "objectPath": object_path,
            "propertyName": property_name,
            "propertyValue": {property_name: value},
            "access": "WRITE_ACCESS",
        }
        return self._put("/remote/object/property", data)

    def describe_object(self, object_path: str) -> dict:
        """Describe a UObject (list all properties and functions).

        Args:
            object_path: UObject path.

        Returns:
            Object description dict.
        """
        data = {"objectPath": object_path}
        return self._put("/remote/object/describe", data)

    def get_thumbnail(self, object_path: str) -> dict:
        """Get an object's thumbnail image.

        Args:
            object_path: UObject path.

        Returns:
            Thumbnail data.
        """
        data = {"objectPath": object_path}
        return self._put("/remote/object/thumbnail", data)

    # ── Remote Control: Asset Search ────────────────────────────────────

    def search_assets(
        self,
        query: str = "",
        class_names: list[str] | None = None,
        package_paths: list[str] | None = None,
        recursive: bool = True,
        limit: int = 0,
    ) -> dict:
        """Search for assets in the content browser.

        Args:
            query: Search query string.
            class_names: Filter by class (use full path like "/Script/Engine.Material").
            package_paths: Filter by package paths (e.g., ["/Game"]).
            recursive: Search recursively in paths.
            limit: Max results (0 = unlimited).

        Returns:
            {"Assets": [{"Name": str, "Class": str, "Path": str, "Metadata": dict}, ...]}
        """
        filter_data = {
            "RecursivePaths": recursive,
        }
        if class_names:
            filter_data["ClassNames"] = class_names
        if package_paths:
            filter_data["PackagePaths"] = package_paths

        data = {
            "Query": query,
            "Filter": filter_data,
        }
        if limit > 0:
            data["Limit"] = limit

        return self._put("/remote/search/assets", data)

    # ── Console Commands ────────────────────────────────────────────────

    def exec_console(self, command: str) -> dict:
        """Execute a console command in the editor.

        Uses KismetSystemLibrary.ExecuteConsoleCommand via Remote Control.

        Args:
            command: Console command string (e.g., 'stat fps').

        Returns:
            API response dict.
        """
        return self.call_function(
            "/Script/Engine.Default__KismetSystemLibrary",
            "ExecuteConsoleCommand",
            {
                "Command": command,
            },
        )

    def exec_python(self, python_code: str) -> dict:
        """Execute Python code in the editor via console command.

        Args:
            python_code: Python code string.

        Returns:
            API response dict.
        """
        escaped = python_code.replace('"', '\\"')
        return self.exec_console(f'py "{escaped}"')

    def exec_python_file(self, script_path: str) -> dict:
        """Execute a Python script file in the editor.

        Args:
            script_path: Absolute path to the .py file.

        Returns:
            API response dict.
        """
        path = script_path.replace("\\", "/")
        return self.exec_console(f'py "{path}"')

    def exec_python_ex(self, code: str, *, timeout: int | None = None) -> dict:
        """Execute Python code via ``PythonScriptLibrary.ExecutePythonCommandEx``.

        Unlike :meth:`exec_python`, this captures ``unreal.log()`` output
        and returns it inline — no temp files or polling required.

        Multi-line *code* is automatically wrapped in ``exec(...)`` so that
        it can be passed as a single statement.

        Args:
            code: Python source code (may be multi-line).
            timeout: HTTP request timeout (defaults to ``self.timeout``).

        Returns:
            dict with keys:
            - ``ReturnValue`` (bool): whether execution succeeded.
            - ``CommandResult`` (str): string result (usually ``"None"``).
            - ``LogOutput`` (list[dict]): captured log entries, each with
              ``Type`` (``"Info"`` / ``"Warning"`` / ``"Error"``) and
              ``Output`` (str).
        """
        if "\n" in code.strip():
            command = f"exec({json.dumps(code)})"
        else:
            command = code
        return self.call_function(
            "/Script/PythonScriptPlugin.Default__PythonScriptLibrary",
            "ExecutePythonCommandEx",
            {
                "PythonCommand": command,
                "ExecutionMode": "ExecuteStatement",
            },
            timeout=timeout,
        )

    # ── CVars ───────────────────────────────────────────────────────────

    def get_cvar(self, name: str) -> str:
        """Get the value of a console variable.

        Args:
            name: CVar name (e.g., "r.Shadow.Virtual.Enable").

        Returns:
            CVar value as string.
        """
        result = self.call_function(
            "/Script/Engine.Default__KismetSystemLibrary",
            "GetConsoleVariableStringValue",
            {"VariableName": name},
        )
        if "ReturnValue" in result:
            return str(result["ReturnValue"])
        return str(result)

    def set_cvar(self, name: str, value: str) -> dict:
        """Set a console variable via console command.

        Args:
            name: CVar name.
            value: New value as string.

        Returns:
            API response dict.
        """
        return self.exec_console(f"{name} {value}")

    # ── Editor Window ───────────────────────────────────────────────────

    def find_editor_window_hwnd(self) -> int | None:
        """Resolve the main Unreal Editor top-level window handle (Windows only).

        Uses the Remote Control listener PID when possible so multiple ``UnrealEditor``
        instances do not pick the wrong HWND.

        Returns:
            Native ``HWND`` as ``int``, or ``None`` if not found / not Windows.
        """
        import sys

        if sys.platform != "win32":
            return None

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            listening_pid = self._get_pid_listening_on_port(self.port)

            TH32CS_SNAPPROCESS = 0x00000002

            class PROCESSENTRY32(ctypes.Structure):
                _fields_ = [
                    ("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_char * 260),
                ]

            snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)

            ue_pids: list[int] = []
            if kernel32.Process32First(snapshot, ctypes.byref(entry)):
                while True:
                    raw_name = bytes(entry.szExeFile).split(b"\0", 1)[0]
                    name = _decode_windows_command_output(raw_name)
                    if "UnrealEditor" in name:
                        ue_pids.append(int(entry.th32ProcessID))
                    if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                        break
            kernel32.CloseHandle(snapshot)

            if not ue_pids:
                return None

            target_pids = set(ue_pids)
            candidates: list[dict] = []
            WNDENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
            )

            @WNDENUMPROC
            def _enum_cb(hwnd, _lparam):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value not in target_pids:
                    return True

                title_buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, title_buf, 512)
                class_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_buf, 256)
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                width = max(0, int(rect.right - rect.left))
                height = max(0, int(rect.bottom - rect.top))
                candidates.append(
                    {
                        "hwnd": int(hwnd),
                        "pid": int(pid.value),
                        "pid_rank": (
                            0 if listening_pid == pid.value else (1 if listening_pid else 0)
                        ),
                        "title": title_buf.value,
                        "class_name": class_buf.value,
                        "visible": bool(user32.IsWindowVisible(hwnd)),
                        "area": width * height,
                    }
                )
                return True

            user32.EnumWindows(_enum_cb, 0)
            return _select_editor_window_hwnd(candidates)
        except Exception:
            return None

    def bring_to_foreground(self) -> bool:
        """Activate the UE editor window and expand to full monitor for screenshot.

        UE viewports degrade rendering (skip post-process, reduce tick rate)
        when FSlateApplication::IsActive() returns false — i.e. when the editor
        window is not the foreground window. GDI capture (PrintWindow) can grab
        pixels from occluded windows, but it captures the *degraded* frame.

        This method truly activates the window via SetForegroundWindow so UE
        renders at full quality. Uses AttachThreadInput to bypass Windows'
        restriction on non-foreground processes calling SetForegroundWindow.

        The caller should save/restore the original window rect via
        ``get_window_rect`` / ``set_window_rect``.

        Returns:
            True if the window was successfully activated, False otherwise.
        """
        import sys

        if sys.platform != "win32":
            return False

        try:
            import ctypes
            import ctypes.wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            found_hwnd = self.find_editor_window_hwnd()
            if not found_hwnd:
                return False

            hwnd = ctypes.wintypes.HWND(found_hwnd)

            # ── Step 1: Truly bring the window to foreground ──────────────
            # Windows restricts SetForegroundWindow to the process that owns
            # the current foreground window. AttachThreadInput temporarily
            # merges our thread's input queue with the foreground thread's,
            # granting us permission to call SetForegroundWindow.
            fore_hwnd = user32.GetForegroundWindow()
            fore_tid = user32.GetWindowThreadProcessId(fore_hwnd, None)
            cur_tid = kernel32.GetCurrentThreadId()

            attached = False
            if fore_tid != cur_tid:
                attached = bool(user32.AttachThreadInput(cur_tid, fore_tid, True))

            # Restore if minimized (SW_RESTORE = 9)
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)

            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)

            if attached:
                user32.AttachThreadInput(cur_tid, fore_tid, False)

            # ── Step 2: Expand to full monitor bounds ─────────────────────
            monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.wintypes.DWORD),
                    ("rcMonitor", ctypes.wintypes.RECT),
                    ("rcWork", ctypes.wintypes.RECT),
                    ("dwFlags", ctypes.wintypes.DWORD),
                ]

            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            user32.GetMonitorInfoW(monitor, ctypes.byref(mi))
            mr = mi.rcMonitor

            # SWP_NOZORDER=0x0004 — keep Z-order (already foreground now)
            user32.SetWindowPos(
                hwnd, 0,
                mr.left, mr.top, mr.right - mr.left, mr.bottom - mr.top,
                0x0004,
            )

            # ── Step 3: Verify activation ─────────────────────────────────
            return user32.GetForegroundWindow() == found_hwnd
        except Exception:
            return False

    def get_window_rect(self) -> tuple | None:
        """Return the UE editor window rect (left, top, right, bottom) or None."""
        import sys
        if sys.platform != "win32":
            return None
        try:
            import ctypes, ctypes.wintypes
            user32 = ctypes.windll.user32
            hwnd = self.find_editor_window_hwnd()
            if not hwnd:
                return None
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(ctypes.wintypes.HWND(hwnd), ctypes.byref(rect))
            return (rect.left, rect.top, rect.right, rect.bottom)
        except Exception:
            return None

    def set_window_rect(self, left: int, top: int, right: int, bottom: int) -> bool:
        """Set the UE editor window rect without changing Z-order or focus."""
        import sys
        if sys.platform != "win32":
            return False
        try:
            import ctypes, ctypes.wintypes
            user32 = ctypes.windll.user32
            hwnd = self.find_editor_window_hwnd()
            if not hwnd:
                return False
            # SWP_NOZORDER=0x0004, SWP_NOACTIVATE=0x0010
            user32.SetWindowPos(
                ctypes.wintypes.HWND(hwnd), 0,
                left, top, right - left, bottom - top,
                0x0004 | 0x0010,
            )
            return True
        except Exception:
            return False

    @staticmethod
    def _get_pid_listening_on_port(port: int) -> int | None:
        """Return the process PID that is LISTENING on a TCP port (Windows)."""
        try:
            proc = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=False,
                timeout=3,
                check=False,
            )
        except Exception:
            return None

        if proc.returncode != 0:
            return None

        stdout = _decode_windows_command_output(proc.stdout)
        # Example line:
        # TCP    0.0.0.0:30010   0.0.0.0:0   LISTENING   12345
        line_re = re.compile(r"^\s*TCP\s+\S+:(\d+)\s+\S+\s+(\S+)\s+(\d+)\s*$")
        for line in stdout.splitlines():
            match = line_re.match(line)
            if not match:
                continue
            found_port = int(match.group(1))
            state = match.group(2).upper()
            if found_port == int(port) and (
                state.startswith("LISTEN") or state == "侦听"
            ):
                return int(match.group(3))

        return None

    # ── EditorAssetLibrary Wrappers ─────────────────────────────────────

    def list_assets(
        self,
        directory_path: str = "/Game/",
        recursive: bool = True,
        include_folder: bool = False,
    ) -> dict:
        """List assets using EditorAssetLibrary.

        Args:
            directory_path: Content path to search.
            recursive: Search recursively.
            include_folder: Include folder entries.

        Returns:
            {"ReturnValue": ["asset_path", ...]}
        """
        return self.call_function(
            "/Script/EditorScriptingUtilities.Default__EditorAssetLibrary",
            "ListAssets",
            {
                "DirectoryPath": directory_path,
                "bRecursive": recursive,
                "bIncludeFolder": include_folder,
            },
        )

    def collect_garbage(self) -> dict:
        """Force a full garbage collection cycle in the editor."""
        return self.call_function(
            "/Script/Engine.Default__KismetSystemLibrary",
            "CollectGarbage",
            {},
        )

    def does_asset_exist(self, asset_path: str) -> bool:
        """Check if an asset exists at the given content path."""
        result = self.call_function(
            "/Script/EditorScriptingUtilities.Default__EditorAssetLibrary",
            "DoesAssetExist",
            {"AssetPath": asset_path},
        )
        return bool(result.get("ReturnValue", False))

    def delete_asset(self, asset_path: str) -> bool:
        """Delete an asset via EditorAssetLibrary.DeleteAsset.

        Returns True if the asset was deleted, False otherwise (e.g.
        asset not found, or deletion was rejected internally).
        """
        result = self.call_function(
            "/Script/EditorScriptingUtilities.Default__EditorAssetLibrary",
            "DeleteAsset",
            {"AssetPath": asset_path},
        )
        return bool(result.get("ReturnValue", False))

    def find_asset_referencers(self, asset_path: str) -> list[str]:
        """Return list of assets that reference the given asset."""
        result = self.call_function(
            "/Script/EditorScriptingUtilities.Default__EditorAssetLibrary",
            "FindPackageReferencersForAsset",
            {"AssetPath": asset_path, "bLoadAssetsToConfirm": False},
        )
        return result.get("ReturnValue", [])

    # ── Presets ──────────────────────────────────────────────────────────

    def list_presets(self) -> dict:
        """List available Remote Control presets."""
        return self._get("/remote/presets")

    def get_preset(self, preset_name: str) -> dict:
        """Get a specific preset."""
        return self._get(f"/remote/preset/{preset_name}")

    # ── Batch ───────────────────────────────────────────────────────────

    def batch(self, requests_list: list[dict]) -> dict:
        """Execute multiple API calls in one request.

        Args:
            requests_list: List of request dicts, each with:
                - "RequestId": int
                - "Url": str (e.g., "/remote/object/call")
                - "Verb": str (e.g., "PUT")
                - "Body": dict

        Returns:
            Batch response with individual results.
        """
        data = {"Requests": requests_list}
        return self._put("/remote/batch", data)


def scan_editor_ports(
    host: str = "localhost",
    port_range: tuple[int, int] = (30010, 30020),
) -> list[dict]:
    """Scan for running UE editor instances by checking Remote Control API.

    Args:
        host: Hostname to scan.
        port_range: (start, end) inclusive port range.

    Returns:
        List of {"port": int, "alive": bool, "info": dict}.
    """
    if requests is None:
        return []

    instances = []
    for port in range(port_range[0], port_range[1] + 1):
        try:
            resp = requests.get(f"http://{host}:{port}/remote/info", timeout=1.5)
            if resp.status_code == 200:
                info = {}
                try:
                    info = resp.json()
                except Exception:
                    info = {"raw": resp.text[:200]}
                instances.append({
                    "port": port,
                    "alive": True,
                    "info": info,
                })
        except Exception:
            continue

    return instances
