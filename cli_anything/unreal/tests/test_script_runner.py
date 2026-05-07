"""Tests for test_script_runner.py — Uses synthetic data only, no UE editor required."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestScriptRunner:
    """Tests for core.script_runner — generic Python execution with result capture.

    The script runner now uses ``api.exec_python_ex()`` under the hood, which
    calls ``PythonScriptLibrary.ExecutePythonCommandEx`` via Remote Control.

    Tests mock ``api.exec_python_ex`` to simulate the UE response format::

        {"ReturnValue": True, "CommandResult": "None",
         "LogOutput": [{"Type": "Info", "Output": "..."}]}
    """

    @staticmethod
    def _make_exec_python_ex_mock(mock_api):
        """Wire up ``mock_api.exec_python_ex`` to locally execute the wrapper
        code (with a fake ``unreal`` module) and return a realistic response.

        Captures ``unreal.log()`` calls from the wrapper to produce
        ``LogOutput`` entries, just like the real UE editor.
        """
        import types

        def _fake_exec_python_ex(code, *, timeout=None):
            log_entries = []
            fake_unreal = types.ModuleType("unreal")
            fake_unreal.log = lambda msg: log_entries.append(
                {"Type": "Info", "Output": msg}
            )

            import sys
            old_unreal = sys.modules.get("unreal")
            sys.modules["unreal"] = fake_unreal
            try:
                exec(compile(code, "<exec_python_ex>", "exec"))
                return {
                    "ReturnValue": True,
                    "CommandResult": "None",
                    "LogOutput": log_entries,
                }
            except Exception as exc:
                return {
                    "ReturnValue": False,
                    "CommandResult": str(exc),
                    "LogOutput": log_entries,
                }
            finally:
                if old_unreal is not None:
                    sys.modules["unreal"] = old_unreal
                else:
                    sys.modules.pop("unreal", None)

        mock_api.exec_python_ex.side_effect = _fake_exec_python_ex

    # -- run_python_script / run_python_code internals ------------------

    def test_run_python_script_captures_result(self, tmp_path):
        """When user script defines ``result``, it should be captured."""
        from cli_anything.unreal.core.script_runner import run_python_script

        script = tmp_path / "test.py"
        script.write_text("result = {'hello': 'world', 'count': 42}\n", encoding="utf-8")

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_script(mock_api, str(script), timeout=5, save=False)
        assert result["hello"] == "world"
        assert result["count"] == 42

    def test_run_python_code_captures_result(self):
        """``run_python_code`` with inline code and a result variable."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(mock_api, "result = {'actors': 99}",
                                 timeout=5, save=False)
        assert result["actors"] == 99

    def test_no_result_variable(self):
        """When user script does NOT define ``result``, a generic ok is returned."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(mock_api, "x = 1 + 1",
                                 timeout=5, save=False)
        assert result["status"] == "ok"

    # -- stdout hijack tests ---------------------------------------------

    def test_stdout_captured(self):
        """print() output should be captured in the 'stdout' field."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(
            mock_api,
            'print("Hello World")',
            timeout=5, save=False,
        )
        assert result["stdout"] == "Hello World\n"
        assert result["status"] == "ok"

    def test_stdout_captured_with_result_dict(self):
        """Both stdout and result dict keys should be present."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(
            mock_api,
            'print("Hello World"); result = {"data": 123}',
            timeout=5, save=False,
        )
        assert result["stdout"] == "Hello World\n"
        assert result["data"] == 123

    def test_stdout_captured_with_result_non_dict(self):
        """Non-dict result should be wrapped as 'value' alongside stdout."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(
            mock_api,
            'print("test"); result = 42',
            timeout=5, save=False,
        )
        assert result["stdout"] == "test\n"
        assert result["value"] == "42"

    def test_stdout_empty_when_no_print(self):
        """stdout field should be empty string when no print() is called."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(
            mock_api,
            "result = {'data': 1}",
            timeout=5, save=False,
        )
        assert result["stdout"] == ""
        assert result["data"] == 1

    def test_stdout_multiple_prints(self):
        """Multiple print() calls should all be captured."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(
            mock_api,
            'print("line1"); print("line2"); result = {"ok": True}',
            timeout=5, save=False,
        )
        assert result["stdout"] == "line1\nline2\n"
        assert result["ok"] is True

    def test_stdout_preserved_on_error(self):
        """stdout should still be captured even when script raises an exception."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(
            mock_api,
            'print("before error"); raise ValueError("boom")',
            timeout=5, save=False,
        )
        assert result["stdout"] == "before error\n"
        assert "error" in result
        assert result["error_type"] == "ValueError"

    # -- api_discover tests ----------------------------------------------

    @staticmethod
    def _make_discover_mock(mock_api, fake_unreal_mod):
        """Wire up mock_api.exec_python_ex for api_discover tests.

        Uses the caller-provided fake_unreal_mod (already in sys.modules)
        and collects unreal.log() calls to produce LogOutput entries.
        Uses an explicit namespace for exec() to avoid scope issues.
        """
        def _fake_exec(code, *, timeout=None):
            log_entries = []
            # Override the log method on the already-in-sys.modules fake
            original_log = fake_unreal_mod.log
            fake_unreal_mod.log = lambda msg: log_entries.append(
                {"Type": "Info", "Output": msg}
            )
            try:
                ns = {"__builtins__": __builtins__}
                exec(compile(code, "<discover>", "exec"), ns)
            except Exception as exc:
                return {
                    "ReturnValue": False,
                    "CommandResult": str(exc),
                    "LogOutput": log_entries,
                }
            finally:
                fake_unreal_mod.log = original_log
            return {
                "ReturnValue": True,
                "CommandResult": "None",
                "LogOutput": log_entries,
            }

        mock_api.exec_python_ex.side_effect = _fake_exec

    @staticmethod
    def _make_fake_bridge(class_info_map):
        """Create a fake CliAnythingBridgeLibrary with get_class_info.

        class_info_map: dict mapping class_name -> dict with "properties" and "functions".
        """
        import json as _json
        class FakeBridge:
            @staticmethod
            def get_class_info(class_name, include_inherited):
                data = class_info_map.get(class_name)
                if data is None:
                    return "{}"
                return _json.dumps(data)
        return FakeBridge

    def test_api_discover_basic(self):
        """api_discover overview should return property/function names only."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()

        import types, sys

        bridge_data = {
            "EditorLevelLibrary": {
                "class": "EditorLevelLibrary",
                "properties": [
                    {"name": "some_property", "type": "int32", "owner": "EditorLevelLibrary",
                     "category": "EditorLevelLibrary", "read": True, "write": True}
                ],
                "functions": [
                    {"name": "get_all_level_actors", "owner": "EditorLevelLibrary",
                     "tooltip": "Returns all actors.", "return_type": "TArray",
                     "params": []},
                    {"name": "get_editor_world", "owner": "EditorLevelLibrary",
                     "tooltip": "Returns the Editor World.", "return_type": "UWorld*",
                     "params": []},
                ],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(
                mock_api, "unreal.EditorLevelLibrary",
                timeout=5,
            )
            assert result["target_name"] == "EditorLevelLibrary"
            assert result["full_path"] == "unreal.EditorLevelLibrary"
            # Overview returns plain name lists
            assert result["properties"] == ["some_property"]
            assert "get_all_level_actors" in result["functions"]
            assert "get_editor_world" in result["functions"]
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_short_name(self):
        """api_discover should accept short names (without 'unreal.' prefix)."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()

        import types, sys

        bridge_data = {
            "Actor": {
                "class": "Actor",
                "properties": [],
                "functions": [],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(mock_api, "Actor", timeout=5)
            assert result["full_path"] == "unreal.Actor"
            assert result["target_name"] == "Actor"
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_query(self):
        """api_discover with query should only return matching names."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()

        import types, sys

        bridge_data = {
            "FakeLib": {
                "class": "FakeLib",
                "properties": [],
                "functions": [
                    {"name": "get_all_level_actors", "owner": "FakeLib",
                     "tooltip": "Get actors.", "return_type": "TArray", "params": []},
                    {"name": "get_editor_world", "owner": "FakeLib",
                     "tooltip": "Get world.", "return_type": "UWorld*", "params": []},
                    {"name": "spawn_actor", "owner": "FakeLib",
                     "tooltip": "Spawn.", "return_type": "AActor*", "params": []},
                ],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(
                mock_api, "unreal.FakeLib",
                query="get",
                timeout=5,
            )
            # Overview returns plain name lists, filtered
            assert "get_all_level_actors" in result["functions"]
            assert "get_editor_world" in result["functions"]
            assert "spawn_actor" not in result["functions"]
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_query_regex_alternation(self):
        """query is a regex — alternation picks up multiple prefixes."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()
        import types, sys

        bridge_data = {
            "FakeLib": {
                "class": "FakeLib", "properties": [],
                "functions": [
                    {"name": "create_material_expression", "owner": "FakeLib",
                     "tooltip": "", "return_type": "", "params": []},
                    {"name": "connect_material_property", "owner": "FakeLib",
                     "tooltip": "", "return_type": "", "params": []},
                    {"name": "recompile_material", "owner": "FakeLib",
                     "tooltip": "", "return_type": "", "params": []},
                ],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(
                mock_api, "unreal.FakeLib",
                query="create|connect",
                timeout=5,
            )
            assert set(result["functions"]) == {
                "create_material_expression", "connect_material_property",
            }
            # recompile_material must NOT be matched — it's the negative control
            assert "recompile_material" not in result["functions"]
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_query_regex_anchor(self):
        """query supports anchors (^ for prefix)."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()
        import types, sys

        bridge_data = {
            "FakeLib": {
                "class": "FakeLib", "properties": [],
                "functions": [
                    {"name": "SetIntensity", "owner": "FakeLib",
                     "tooltip": "", "return_type": "", "params": []},
                    {"name": "SetColor", "owner": "FakeLib",
                     "tooltip": "", "return_type": "", "params": []},
                    {"name": "GetIntensity", "owner": "FakeLib",
                     "tooltip": "", "return_type": "", "params": []},
                ],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(
                mock_api, "unreal.FakeLib",
                query="^Set",
                timeout=5,
            )
            assert set(result["functions"]) == {"SetIntensity", "SetColor"}
            # GetIntensity is NOT ^Set — even though it contains "Set" as a
            # substring, the regex anchor rules it out
            assert "GetIntensity" not in result["functions"]
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_query_invalid_regex(self):
        """An invalid regex returns a structured error, not a raw traceback."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()
        import types, sys

        bridge_data = {
            "FakeLib": {
                "class": "FakeLib", "properties": [],
                "functions": [
                    {"name": "anything", "owner": "FakeLib",
                     "tooltip": "", "return_type": "", "params": []},
                ],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(
                mock_api, "unreal.FakeLib",
                query="[unclosed",
                timeout=5,
            )
            assert "error" in result
            assert "Invalid regex" in result["error"]
            # Raw filter is echoed back so agents can see what they sent
            assert result.get("query") == "[unclosed"
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_detail_single(self):
        """api_discover detail for a single property/function name."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()

        import types, sys

        bridge_data = {
            "SomeClass": {
                "class": "SomeClass",
                "properties": [
                    {"name": "MyProp", "type": "float", "owner": "SomeClass",
                     "category": "SomeClass", "tooltip": "A float property.", "read": True, "write": True}
                ],
                "functions": [
                    {"name": "do_thing", "owner": "SomeClass",
                     "tooltip": "Does a thing.", "return_type": "bool",
                     "params": [{"name": "x", "type": "int32"}]},
                ],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)

            # Overview: names only
            result_summary = api_discover(mock_api, "unreal.SomeClass", timeout=5)
            assert result_summary["properties"] == ["MyProp"]
            assert result_summary["functions"] == ["do_thing"]

            # Detail for one property
            result_prop = api_discover(mock_api, "unreal.SomeClass", detail="MyProp", timeout=5)
            assert result_prop["items"][0]["kind"] == "property"
            assert result_prop["items"][0]["detail"]["tooltip"] == "A float property."

            # Detail for one function
            result_func = api_discover(mock_api, "unreal.SomeClass", detail="do_thing", timeout=5)
            assert result_func["items"][0]["kind"] == "function"
            assert result_func["items"][0]["detail"]["params"][0]["name"] == "x"
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_detail_multiple(self):
        """api_discover detail with comma-separated names returns multiple items."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()

        import types, sys

        bridge_data = {
            "SomeClass": {
                "class": "SomeClass",
                "properties": [
                    {"name": "Prop1", "type": "float", "owner": "SomeClass",
                     "category": "SomeClass", "tooltip": "P1", "read": True, "write": True}
                ],
                "functions": [
                    {"name": "Func1", "owner": "SomeClass",
                     "tooltip": "F1", "return_type": "void", "params": []},
                ],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(mock_api, "unreal.SomeClass", detail="Prop1,Func1,NotFound", timeout=5)
            names = [item["name"] for item in result["items"]]
            assert "Prop1" in names
            assert "Func1" in names
            assert result["not_found"] == ["NotFound"]
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_unresolvable_target(self):
        """api_discover should return error for unresolvable target."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()

        import types, sys

        # Empty bridge — get_class_info returns "{}" for everything
        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge({})

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(mock_api, "unreal.NonExistentClass", timeout=5)
            assert "error" in result
            assert "Class not found" in result["error"]
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_cli(self):
        """editor api-discover CLI should route through api_discover."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.api_discover") as mock_discover:
            mock_editor.return_value = MagicMock()
            mock_discover.return_value = {
                "target_name": "EditorLevelLibrary",
                "full_path": "unreal.EditorLevelLibrary",
                "class": "EditorLevelLibrary",
                "functions": [{"name": "get_editor_world"}],
                "properties": [],
                "function_count": 1,
                "property_count": 0,
                "total_functions_available": 1,
                "truncated": False,
            }

            result = runner.invoke(cli, [
                "--output", "json", "editor", "api-discover", "unreal.EditorLevelLibrary",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["result"]["target_name"] == "EditorLevelLibrary"
            mock_discover.assert_called_once()

    def test_api_discover_cli_with_options(self):
        """editor api-discover CLI with -m and -d options."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.api_discover") as mock_discover:
            mock_editor.return_value = MagicMock()
            mock_discover.return_value = {
                "target_name": "Actor",
                "items": [{"kind": "function", "name": "GetOwner", "detail": {}}],
            }

            result = runner.invoke(cli, [
                "--output", "json", "editor", "api-discover",
                "unreal.Actor", "-q", "spawn", "-d", "GetOwner",
            ])
            assert result.exit_code == 0
            mock_discover.assert_called_once()
            call_kw = mock_discover.call_args[1]
            assert call_kw["query"] == "spawn"
            assert call_kw["detail"] == "GetOwner"

    # -- Instance path tests (actor / asset) ----------------------------------

    def _setup_instance_discover(self, bridge_data, *, actors=None, assets=None):
        """Helper: set up fake unreal module with actor/asset support.

        Returns (mock_api, fake_unreal, cleanup) where cleanup restores sys.modules.
        """
        import types, sys

        mock_api = MagicMock()
        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        # Mock EditorActorSubsystem + get_all_level_actors
        fake_actors = actors or []
        fake_subsystem = MagicMock()
        fake_subsystem.get_all_level_actors.return_value = fake_actors
        fake_unreal.EditorActorSubsystem = type("EditorActorSubsystem", (), {})
        fake_unreal.get_editor_subsystem = lambda cls: fake_subsystem

        # Mock EditorAssetLibrary
        assets_map = assets or {}
        fake_asset_lib = MagicMock()
        fake_asset_lib.does_asset_exist.side_effect = lambda p: p in assets_map
        fake_asset_lib.load_asset.side_effect = lambda p: assets_map.get(p)
        fake_unreal.EditorAssetLibrary = fake_asset_lib

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        self._make_discover_mock(mock_api, fake_unreal)

        def cleanup():
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

        return mock_api, fake_unreal, cleanup

    def test_inspect_instance_actor(self):
        """api_discover with an actor path should resolve class and return actor context."""
        from cli_anything.unreal.core.script_runner import api_discover

        bridge_data = {
            "PointLight": {
                "class": "PointLight",
                "properties": [
                    {"name": "Intensity", "type": "float", "owner": "PointLight",
                     "read": True, "write": True},
                ],
                "functions": [],
            }
        }

        fake_actor = MagicMock()
        fake_actor.get_path_name.return_value = "/Game/Maps/L.L:PersistentLevel.Light_0"
        fake_actor.get_name.return_value = "Light_0"
        fake_actor.get_actor_label.return_value = "Light_0"
        fake_actor.__class__ = type("PointLight", (), {})

        mock_api, _, cleanup = self._setup_instance_discover(
            bridge_data, actors=[fake_actor],
        )
        try:
            result = api_discover(
                mock_api,
                "/Game/Maps/L.L:PersistentLevel.Light_0",
                timeout=5,
            )
            assert "error" not in result
            assert result["class"] == "PointLight"
            assert result["actor"] == "/Game/Maps/L.L:PersistentLevel.Light_0"
            assert result["actor_name"] == "Light_0"
            assert "Intensity" in result["properties"]
        finally:
            cleanup()

    def test_inspect_instance_actor_not_found(self):
        """api_discover should return error for non-existent actor path."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api, _, cleanup = self._setup_instance_discover(
            {}, actors=[],  # no actors in level
        )
        try:
            result = api_discover(
                mock_api,
                "/Game/Maps/L.L:PersistentLevel.DoesNotExist",
                timeout=5,
            )
            assert "error" in result
            assert "not found" in result["error"].lower()
        finally:
            cleanup()

    def test_inspect_instance_actor_with_filter(self):
        """api_discover actor path + query should filter results."""
        from cli_anything.unreal.core.script_runner import api_discover

        bridge_data = {
            "StaticMeshActor": {
                "class": "StaticMeshActor",
                "properties": [
                    {"name": "StaticMeshComponent", "type": "UStaticMeshComponent*",
                     "owner": "StaticMeshActor", "read": True, "write": False},
                    {"name": "bHidden", "type": "bool",
                     "owner": "StaticMeshActor", "read": True, "write": True},
                ],
                "functions": [
                    {"name": "SetMobility", "owner": "StaticMeshActor",
                     "params": [], "return_type": "void"},
                ],
            }
        }

        fake_actor = MagicMock()
        fake_actor.get_path_name.return_value = "/Game/Maps/L.L:PersistentLevel.Cube_0"
        fake_actor.get_name.return_value = "Cube_0"
        fake_actor.get_actor_label.return_value = "Cube_0"
        fake_actor.__class__ = type("StaticMeshActor", (), {})

        mock_api, _, cleanup = self._setup_instance_discover(
            bridge_data, actors=[fake_actor],
        )
        try:
            result = api_discover(
                mock_api,
                "/Game/Maps/L.L:PersistentLevel.Cube_0",
                query="mesh",
                timeout=5,
            )
            assert "error" not in result
            # "mesh" filter should keep StaticMeshComponent but not bHidden
            assert "StaticMeshComponent" in result["properties"]
            assert "bHidden" not in result["properties"]
        finally:
            cleanup()

    def test_inspect_instance_asset(self):
        """api_discover with an asset path should resolve class and return asset context."""
        from cli_anything.unreal.core.script_runner import api_discover

        bridge_data = {
            "MaterialInstanceConstant": {
                "class": "MaterialInstanceConstant",
                "properties": [
                    {"name": "Parent", "type": "UMaterialInterface*",
                     "owner": "MaterialInstanceConstant", "read": True, "write": False},
                ],
                "functions": [],
            }
        }

        fake_asset = MagicMock()
        fake_asset.__class__ = type("MaterialInstanceConstant", (), {})
        fake_asset.get_path_name.return_value = "/Game/Materials/MI_Water.MI_Water"

        mock_api, _, cleanup = self._setup_instance_discover(
            bridge_data, assets={"/Game/Materials/MI_Water": fake_asset},
        )
        try:
            result = api_discover(
                mock_api,
                "/Game/Materials/MI_Water",
                timeout=5,
            )
            assert "error" not in result
            assert result["class"] == "MaterialInstanceConstant"
            assert result["asset"] == "/Game/Materials/MI_Water"
            assert "Parent" in result["properties"]
        finally:
            cleanup()

    def test_inspect_instance_asset_not_found(self):
        """api_discover should return error for non-existent asset path."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api, _, cleanup = self._setup_instance_discover(
            {}, assets={},  # no assets
        )
        try:
            result = api_discover(
                mock_api,
                "/Game/Materials/DoesNotExist",
                timeout=5,
            )
            assert "error" in result
            assert "not found" in result["error"].lower()
        finally:
            cleanup()


    def test_non_dict_result_wrapped(self):
        """A non-dict ``result`` should be wrapped as {"value": ...}."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(mock_api, "result = 'just a string'",
                                 timeout=5, save=False)
        assert result["value"] == "just a string"

    def test_exec_failure_returns_error(self):
        """When exec_python_ex returns ``ReturnValue: false``, an error is returned."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        mock_api.exec_python_ex.return_value = {
            "ReturnValue": False,
            "CommandResult": "SyntaxError: invalid syntax",
            "LogOutput": [],
        }

        result = run_python_code(mock_api, "result = {}", timeout=5)
        assert "error" in result
        assert "SyntaxError" in result["error"]

    def test_http_error_returns_error(self):
        """When exec_python_ex returns an HTTP error, it is forwarded."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        mock_api.exec_python_ex.return_value = {
            "error": "ConnectionError: editor not reachable"
        }

        result = run_python_code(mock_api, "result = {}", timeout=5)
        assert "error" in result
        assert "ConnectionError" in result["error"]

    def test_no_temp_files_created(self, tmp_path):
        """The new transport should not create temp files."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        temp_dir = tmp_path / "Saved" / "Temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        run_python_code(mock_api, "result = {'clean': True}",
                        project_dir=str(tmp_path), timeout=5, save=False)

        remaining = list(temp_dir.iterdir())
        assert remaining == [], f"Unexpected temp files: {remaining}"

    # -- CLI integration tests ------------------------------------------

    def test_editor_exec_py_uses_script_runner(self):
        """``editor exec 'py ...'`` should route through run_python_code."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_editor.return_value = MagicMock()
            mock_run.return_value = {"status": "ok", "actors": 42}

            result = runner.invoke(cli, [
                "--output", "json", "editor", "exec", "py result = {'actors': 42}",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["result"]["actors"] == 42
            mock_run.assert_called_once()

    def test_editor_exec_non_py_unchanged(self):
        """Non-Python console commands still go through exec_console."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.exec_console.return_value = {}
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--output", "json", "editor", "exec", "stat fps",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["result"]["status"] == "executed"
            mock_api.exec_console.assert_called_once_with("stat fps")

    def test_editor_run_script_cli(self, tmp_path):
        """``editor run-script`` should call run_python_script."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        script = tmp_path / "test_scene.py"
        script.write_text("result = {'scene': 'built'}\n", encoding="utf-8")

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_script") as mock_run:
            mock_editor.return_value = MagicMock()
            mock_run.return_value = {"status": "ok", "scene": "built"}

            result = runner.invoke(cli, [
                "--output", "json", "editor", "run-script", str(script),
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["result"]["scene"] == "built"
            mock_run.assert_called_once()

    def test_script_error_captured(self):
        """When user script raises an exception, error details are returned."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(
            mock_api,
            "raise ValueError('something went wrong')",
            timeout=5,
            save=False,
        )
        assert "error" in result
        assert "something went wrong" in result["error"]
        assert result["error_type"] == "ValueError"
        assert "traceback" in result

    def test_script_attribute_error_captured(self):
        """Simulate the real-world AttributeError from the UE module scenario."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        code = "import os\n_ = os.nonexistent_attr\n"
        result = run_python_code(mock_api, code, timeout=5, save=False)
        assert "error" in result
        assert result["error_type"] == "AttributeError"

    def test_script_error_traceback_contains_line_info(self):
        """Traceback must contain real line numbers, not 'NoneType: None'."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        code = "x = 1\ny = 2\nraise RuntimeError('deliberate')\n"
        result = run_python_code(mock_api, code, timeout=5, save=False)
        assert result["error_type"] == "RuntimeError"
        tb = result["traceback"]
        # Must have actual traceback content, not the empty "NoneType: None"
        assert "NoneType: None" not in tb
        assert "RuntimeError" in tb
        assert "deliberate" in tb
        # Should reference the user code file
        assert "cli_anything_user_code" in tb

    def test_run_python_code_isolates_user_globals_between_calls(self):
        """Separate invocations should not leak user globals into later runs."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        first = run_python_code(mock_api, "sticky = 123\nresult = {'ok': True}", timeout=5, save=False)
        second = run_python_code(mock_api, "result = {'sticky_present': 'sticky' in globals()}", timeout=5, save=False)

        assert first["ok"] is True
        assert second["sticky_present"] is False


# ═══════════════════════════════════════════════════════════════════════
#  Test scene.py (mocked API)
# ═══════════════════════════════════════════════════════════════════════


