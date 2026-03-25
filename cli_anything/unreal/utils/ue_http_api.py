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
import os
import time
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore


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
                      generate_transaction: bool = False) -> dict:
        """Call a function on a UObject.

        Args:
            object_path: UObject path (e.g., "/Script/Engine.Default__KismetSystemLibrary").
            function_name: Function name to call.
            params: Function parameters dict.
            generate_transaction: Whether to generate an undo transaction.

        Returns:
            API response with ReturnValue.
        """
        data = {
            "objectPath": object_path,
            "functionName": function_name,
            "parameters": params or {},
            "generateTransaction": generate_transaction,
        }
        return self._put("/remote/object/call", data)

    def get_property(self, object_path: str, property_name: str) -> dict:
        """Get a property value on a UObject.

        Args:
            object_path: UObject path.
            property_name: Property name.

        Returns:
            Property value dict.
        """
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

    def bring_to_foreground(self) -> bool:
        """Bring the UE editor window to the foreground.

        The viewport only renders when the editor window is visible/focused.
        This is required before taking screenshots.

        Uses multiple Windows API tricks to bypass SetForegroundWindow
        restrictions (Windows blocks this unless the calling process owns
        the foreground lock):
        1. AttachThreadInput — attach to foreground thread to inherit permission
        2. BringWindowToTop + ShowWindow(SW_RESTORE)
        3. SetForegroundWindow
        4. Simulated Alt keypress — tricks Windows into thinking it's user input

        Returns:
            True if successful, False otherwise.
        """
        import subprocess
        import sys
        if sys.platform != "win32":
            return False

        try:
            ps_script = '''
$p = Get-Process UnrealEditor -EA SilentlyContinue | Select-Object -First 1
if (-not $p) { Write-Host "NOT_FOUND"; exit }

$hwnd = $p.MainWindowHandle
if ($hwnd -eq [IntPtr]::Zero) { Write-Host "NO_WINDOW"; exit }

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinFocus {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
    [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
}
"@

# Get foreground thread to attach to it
$fgWnd = [WinFocus]::GetForegroundWindow()
$fgPid = 0
$fgThread = [WinFocus]::GetWindowThreadProcessId($fgWnd, [ref]$fgPid)
$myThread = [WinFocus]::GetCurrentThreadId()

# Attach to foreground thread (inherit foreground permission)
[WinFocus]::AttachThreadInput($myThread, $fgThread, $true) | Out-Null

# Simulate Alt key press/release (tricks Windows foreground lock)
[WinFocus]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero)      # Alt down
[WinFocus]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)      # Alt up

# Now activate the window
[WinFocus]::ShowWindow($hwnd, 9)            # SW_RESTORE
[WinFocus]::BringWindowToTop($hwnd)
$ok = [WinFocus]::SetForegroundWindow($hwnd)

# Detach
[WinFocus]::AttachThreadInput($myThread, $fgThread, $false) | Out-Null

if ($ok) { Write-Host "OK" } else { Write-Host "FAILED" }
'''
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=10,
            )
            return "OK" in result.stdout
        except Exception:
            return False

    # ── Screenshot ──────────────────────────────────────────────────────

    def take_screenshot(
        self,
        filename: str = "screenshot",
        res_x: int = 1920,
        res_y: int = 1080,
        delay: float = 0.5,
    ) -> dict:
        """Take an editor viewport screenshot.

        Uses AutomationBlueprintFunctionLibrary.TakeHighResScreenshot via
        the FunctionalTesting module. The screenshot is saved to:
        {ProjectDir}/Saved/Screenshots/WindowsEditor/{filename}.png

        Args:
            filename: Output filename (without extension).
            res_x: Screenshot width.
            res_y: Screenshot height.
            delay: Seconds to wait for viewport to render before capture.

        Returns:
            API response dict with ReturnValue (automation task path).
        """
        return self.call_function(
            "/Script/FunctionalTesting.Default__AutomationBlueprintFunctionLibrary",
            "TakeHighResScreenshot",
            {
                "ResX": res_x,
                "ResY": res_y,
                "Filename": filename,
                "bMaskEnabled": False,
                "bCaptureHDR": False,
                "ComparisonTolerance": "Low",
                "ComparisonNotes": "",
                "Delay": delay,
                "bForceGameView": False,
            },
        )

    def take_high_res_screenshot(
        self,
        filename: str = "highres",
        resolution_multiplier: int = 2,
    ) -> dict:
        """Take a high-resolution screenshot.

        Args:
            filename: Output filename.
            resolution_multiplier: Resolution multiplier (2 = 2x).

        Returns:
            API response dict.
        """
        return self.exec_console(f"HighResShot {resolution_multiplier}")

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
