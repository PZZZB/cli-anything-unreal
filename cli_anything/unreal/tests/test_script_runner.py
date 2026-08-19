"""Tests for test_script_runner.py — Uses synthetic data only, no UE editor required."""

import io
import json
import time
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
    def _make_exec_python_ex_mock(mock_api, configure_unreal=None):
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
            if configure_unreal is not None:
                configure_unreal(fake_unreal)

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

    def test_run_python_script_uses_main_entrypoint_context(self, tmp_path):
        """Script files execute as ``__main__`` with an absolute ``__file__``."""
        from cli_anything.unreal.core.script_runner import run_python_script

        script = tmp_path / "entrypoint.py"
        script.write_text(
            "if __name__ == '__main__':\n"
            "    result = {'entrypoint': True, 'name': __name__, 'file': __file__}\n",
            encoding="utf-8",
        )

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_script(mock_api, str(script), timeout=5, save=False)

        assert result["entrypoint"] is True
        assert result["name"] == "__main__"
        assert result["file"] == str(script.resolve())

    def test_run_python_script_traceback_uses_source_path(self, tmp_path):
        """File-script tracebacks identify the actual source file."""
        from cli_anything.unreal.core.script_runner import run_python_script

        script = tmp_path / "broken_entrypoint.py"
        script.write_text("raise RuntimeError('broken')\n", encoding="utf-8")

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_script(mock_api, str(script), timeout=5, save=False)

        assert str(script.resolve()) in result["traceback"]

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

    def test_save_policy_never_has_no_persistence_code(self):
        from cli_anything.unreal.core.script_runner import SavePolicy, run_python_code

        mock_api = MagicMock()
        mock_api.exec_python_ex.return_value = {
            "ReturnValue": True,
            "CommandResult": "None",
            "LogOutput": [],
        }

        run_python_code(
            mock_api,
            "result = {'status': 'ok'}",
            timeout=5,
            save_policy=SavePolicy.NEVER,
        )

        wrapper = mock_api.exec_python_ex.call_args.args[0]
        assert "get_dirty_content_packages" not in wrapper
        assert "save_asset(" not in wrapper

    def test_save_policy_target_packages_never_scans_unrelated_dirty_packages(self):
        from cli_anything.unreal.core.script_runner import SavePolicy, run_python_code

        mock_api = MagicMock()
        mock_api.exec_python_ex.return_value = {
            "ReturnValue": True,
            "CommandResult": "None",
            "LogOutput": [],
        }

        run_python_code(
            mock_api,
            "result = {'status': 'ok'}",
            timeout=5,
            save_policy=SavePolicy.TARGET_PACKAGES,
            target_packages=["/Game/M_Test.M_Test", "/Game/M_Test"],
        )

        wrapper = mock_api.exec_python_ex.call_args.args[0]
        assert "get_dirty_content_packages" not in wrapper
        assert 'for _cli_path in ["/Game/M_Test"]' in wrapper
        assert "save_asset(_cli_path, only_if_is_dirty=False)" in wrapper
        assert "PACKAGE_SAVE_FAILED" in wrapper
        compile(wrapper, "<target-save-wrapper>", "exec")

    def test_save_policy_all_dirty_is_explicit(self):
        from cli_anything.unreal.core.script_runner import SavePolicy, run_python_code

        mock_api = MagicMock()
        mock_api.exec_python_ex.return_value = {
            "ReturnValue": True,
            "CommandResult": "None",
            "LogOutput": [],
        }

        run_python_code(
            mock_api,
            "result = {'status': 'ok'}",
            timeout=5,
            save_policy=SavePolicy.ALL_DIRTY_EXPLICIT,
        )

        wrapper = mock_api.exec_python_ex.call_args.args[0]
        assert "get_dirty_content_packages" in wrapper
        assert "get_dirty_map_packages" in wrapper

    @pytest.mark.parametrize("save_ok", [True, False])
    def test_save_policy_all_dirty_reports_save_result(self, save_ok):
        from cli_anything.unreal.core.script_runner import SavePolicy, run_python_code

        class DirtyPackage:
            @staticmethod
            def get_path_name():
                return "/Game/M_Dirty.M_Dirty"

        class EditorAssetLibrary:
            @staticmethod
            def save_asset(_path):
                return save_ok

        class EditorLoadingAndSavingUtils:
            @staticmethod
            def get_dirty_content_packages():
                return [DirtyPackage()]

            @staticmethod
            def get_dirty_map_packages():
                return []

        def configure_unreal(fake_unreal):
            fake_unreal.EditorAssetLibrary = EditorAssetLibrary
            fake_unreal.EditorLoadingAndSavingUtils = EditorLoadingAndSavingUtils

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api, configure_unreal)

        result = run_python_code(
            mock_api,
            "x = 1",
            timeout=5,
            save_policy=SavePolicy.ALL_DIRTY_EXPLICIT,
        )

        if save_ok:
            assert result["saved"] is True
            assert result["saved_packages"] == ["/Game/M_Dirty"]
        else:
            assert result["code"] == "PACKAGE_SAVE_FAILED"
            assert "save_asset returned false" in result["error"]

    def test_legacy_save_boolean_maps_to_policy(self):
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        mock_api.exec_python_ex.return_value = {
            "ReturnValue": True,
            "CommandResult": "None",
            "LogOutput": [],
        }

        run_python_code(mock_api, "result = {}", timeout=5, save=False)
        never_wrapper = mock_api.exec_python_ex.call_args.args[0]
        run_python_code(mock_api, "result = {}", timeout=5, save=True)
        all_dirty_wrapper = mock_api.exec_python_ex.call_args.args[0]

        assert "get_dirty_content_packages" not in never_wrapper
        assert "get_dirty_content_packages" in all_dirty_wrapper

    def test_target_save_policy_requires_target_packages(self):
        from cli_anything.unreal.core.script_runner import SavePolicy, run_python_code

        with pytest.raises(ValueError, match="requires at least one target package"):
            run_python_code(
                MagicMock(),
                "result = {}",
                timeout=5,
                save_policy=SavePolicy.TARGET_PACKAGES,
            )

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

        import types
        import sys

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
        fake_unreal.EditorLevelLibrary = object()
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

        import types
        import sys

        bridge_data = {
            "Actor": {
                "class": "Actor",
                "properties": [],
                "functions": [],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.Actor = object()
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

    def test_api_discover_does_not_claim_unexposed_python_full_path(self):
        """Reflected UE classes are not always exported by the Python module."""
        from cli_anything.unreal.core.script_runner import api_discover

        import sys
        import types

        mock_api = MagicMock()
        bridge_data = {
            "EditorPerformanceSettings": {
                "class": "EditorPerformanceSettings",
                "properties": [
                    {
                        "name": "bThrottleCPUWhenNotForeground",
                        "type": "uint8",
                        "owner": "EditorPerformanceSettings",
                        "read": False,
                        "write": True,
                    }
                ],
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
            result = api_discover(
                mock_api,
                "EditorPerformanceSettings",
                detail="bThrottleCPUWhenNotForeground",
                timeout=5,
            )

            assert result["target_name"] == "EditorPerformanceSettings"
            assert result["python_exposed"] is False
            assert "full_path" not in result
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_query(self):
        """api_discover with query should only return matching names."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()

        import types
        import sys

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
        import types
        import sys

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
        import types
        import sys

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
        import types
        import sys

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

        import types
        import sys

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

        import types
        import sys

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

    def test_api_discover_marks_reflected_functions_missing_from_python(self):
        """Reflection-only functions must not look callable on a Python class."""
        from cli_anything.unreal.core.script_runner import api_discover

        import sys
        import types

        class FakeEditorSubsystemBlueprintLibrary:
            @staticmethod
            def set_preview_platform(name):
                pass

            @staticmethod
            def disable_preview_platform():
                pass

        mock_api = MagicMock()
        bridge_data = {
            "EditorSubsystemBlueprintLibrary": {
                "class": "EditorSubsystemBlueprintLibrary",
                "properties": [],
                "functions": [
                    {
                        "name": "SetPreviewPlatform",
                        "owner": "EditorSubsystemBlueprintLibrary",
                        "params": [{"name": "Name", "type": "FName"}],
                    },
                    {
                        "name": "GetPreviewPlatformOptions",
                        "owner": "EditorSubsystemBlueprintLibrary",
                        "params": [],
                    },
                    {
                        "name": "DisablePreviewPlatform",
                        "owner": "EditorSubsystemBlueprintLibrary",
                        "params": [],
                    },
                ],
            }
        }
        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.EditorSubsystemBlueprintLibrary = (
            FakeEditorSubsystemBlueprintLibrary
        )
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            detail = api_discover(
                mock_api,
                "EditorSubsystemBlueprintLibrary",
                detail=(
                    "GetPreviewPlatformOptions,SetPreviewPlatform,"
                    "DisablePreviewPlatform"
                ),
                timeout=5,
            )

            assert detail["python_callability_checked"] is True
            items = {item["name"]: item["detail"] for item in detail["items"]}
            assert items["SetPreviewPlatform"]["python_callable"] is True
            assert items["SetPreviewPlatform"]["python_name"] == (
                "set_preview_platform"
            )
            assert items["SetPreviewPlatform"]["python_path"] == (
                "unreal.EditorSubsystemBlueprintLibrary.set_preview_platform"
            )
            assert items["DisablePreviewPlatform"]["python_callable"] is True
            assert items["GetPreviewPlatformOptions"]["python_callable"] is False
            assert "python_name" not in items["GetPreviewPlatformOptions"]
            assert "python_path" not in items["GetPreviewPlatformOptions"]

            summary = api_discover(
                mock_api,
                "EditorSubsystemBlueprintLibrary",
                query="PreviewPlatform",
                timeout=5,
            )
            assert summary["python_callability_checked"] is True
            assert summary["python_unavailable_functions"] == [
                "GetPreviewPlatformOptions"
            ]
            assert summary["python_function_bindings"] == {
                "SetPreviewPlatform": "set_preview_platform",
                "DisablePreviewPlatform": "disable_preview_platform",
            }
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_detail_includes_python_only_wrapper_methods(self):
        """Exact detail lookup should find Python bindings omitted by reflection."""
        from cli_anything.unreal.core.script_runner import api_discover

        import sys
        import types

        class FakeEditorLevelLibrary:
            @staticmethod
            def get_level_viewport_camera_info():
                """Return the active viewport camera."""

            @staticmethod
            def set_level_viewport_camera_info(location, rotation):
                """Set the active viewport camera."""

        mock_api = MagicMock()
        bridge_data = {
            "EditorLevelLibrary": {
                "class": "EditorLevelLibrary",
                "properties": [],
                "functions": [],
            }
        }
        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.EditorLevelLibrary = FakeEditorLevelLibrary
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(
                mock_api,
                "EditorLevelLibrary",
                detail=(
                    "set_level_viewport_camera_info,"
                    "get_level_viewport_camera_info"
                ),
                timeout=5,
            )

            assert "not_found" not in result
            assert [item["name"] for item in result["items"]] == [
                "set_level_viewport_camera_info",
                "get_level_viewport_camera_info",
            ]
            assert all(item["kind"] == "function" for item in result["items"])
            assert all(
                item["detail"]["source"] == "python_binding"
                and item["detail"]["python_only"] is True
                for item in result["items"]
            )
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_query_includes_python_only_wrapper_methods(self):
        """Filtered overview should include matching live Python-only symbols."""
        from cli_anything.unreal.core.script_runner import api_discover

        import sys
        import types

        class FakeEditorLevelLibrary:
            @staticmethod
            def get_level_viewport_camera_info():
                pass

            @staticmethod
            def unrelated_python_method():
                pass

        mock_api = MagicMock()
        bridge_data = {
            "EditorLevelLibrary": {
                "class": "EditorLevelLibrary",
                "properties": [],
                "functions": [],
            }
        }
        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.EditorLevelLibrary = FakeEditorLevelLibrary
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(
                mock_api,
                "EditorLevelLibrary",
                query="viewport_camera",
                timeout=5,
            )

            assert result["functions"] == ["get_level_viewport_camera_info"]
            assert result["python_only_functions"] == [
                "get_level_viewport_camera_info"
            ]
            assert "unrelated_python_method" not in result["functions"]
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_python_fallback_is_fail_open_when_dir_raises(self):
        """Python wrapper discovery must not replace valid reflection results."""
        from cli_anything.unreal.core.script_runner import api_discover

        import sys
        import types

        class RaisingDirMeta(type):
            def __dir__(cls):
                raise RuntimeError("dir unavailable")

        class FakeLibrary(metaclass=RaisingDirMeta):
            pass

        mock_api = MagicMock()
        bridge_data = {
            "FakeLibrary": {
                "class": "FakeLibrary",
                "properties": [],
                "functions": [
                    {
                        "name": "reflected_method",
                        "owner": "FakeLibrary",
                        "tooltip": "",
                        "return_type": "void",
                        "params": [],
                    }
                ],
            }
        }
        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.FakeLibrary = FakeLibrary
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(
                mock_api,
                "FakeLibrary",
                query="method",
                timeout=5,
            )

            assert result["functions"] == ["reflected_method"]
            assert "error" not in result
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_does_not_execute_python_descriptors(self):
        """Python-only symbol inspection must not invoke descriptor code."""
        from cli_anything.unreal.core.script_runner import api_discover

        import sys
        import types

        descriptor_reads = []

        class SideEffectDescriptor:
            def __get__(self, instance, owner):
                descriptor_reads.append(owner)
                raise RuntimeError("descriptor executed")

        class FakeLibrary:
            dangerous_setting = SideEffectDescriptor()

        mock_api = MagicMock()
        bridge_data = {
            "FakeLibrary": {
                "class": "FakeLibrary",
                "properties": [],
                "functions": [],
            }
        }
        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.FakeLibrary = FakeLibrary
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(
                mock_api,
                "FakeLibrary",
                query="dangerous",
                timeout=5,
            )

            assert descriptor_reads == []
            assert result["properties"] == ["dangerous_setting"]
            assert result["python_only_properties"] == ["dangerous_setting"]
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_struct_custom_input(self):
        """api_discover should inspect UE Python struct wrappers such as CustomInput."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()

        import types
        import sys

        class FakeProp:
            def __init__(self, name, cpp_type):
                self._name = name
                self._cpp_type = cpp_type

            def get_name(self):
                return self._name

            def get_cpp_type(self):
                return self._cpp_type

            def get_tool_tip_text(self):
                return ""

        class FakeStruct:
            def get_name(self):
                return "CustomInput"

            def get_path_name(self):
                return "/Script/Engine.CustomInput"

            def get_properties(self):
                return [FakeProp("InputName", "FName"), FakeProp("Input", "FExpressionInput")]

        class FakeCustomInput:
            @staticmethod
            def static_struct():
                return FakeStruct()

        class FakeBridge:
            @staticmethod
            def get_class_info(class_name, include_inherited):
                return "{}"

            @staticmethod
            def get_struct_info(struct_obj, include_inherited):
                import json as _json
                return _json.dumps({
                    "struct": "CustomInput",
                    "struct_path": "/Script/Engine.CustomInput",
                    "properties": [
                        {"name": "InputName", "type": "FName", "owner": "CustomInput"},
                        {"name": "Input", "type": "FExpressionInput", "owner": "CustomInput"},
                    ],
                    "functions": [],
                })

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = FakeBridge
        fake_unreal.CustomInput = FakeCustomInput

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(mock_api, "CustomInput", timeout=5)
            assert result["struct"] == "CustomInput"
            assert result["full_path"] == "unreal.CustomInput"
            assert result["property_count"] == 2
            assert "InputName" in result["properties"]
            assert result["functions"] == []
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_unresolvable_target(self):
        """api_discover should return error for unresolvable target."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()

        import types
        import sys

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
        import types
        import sys

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
        fake_unreal.find_object = lambda outer, path: None

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        self._make_discover_mock(mock_api, fake_unreal)

        def cleanup():
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

        return mock_api, fake_unreal, cleanup

    def test_api_discover_instance_includes_python_only_methods(self):
        """Instance targets should use the same Python fallback as class targets."""
        from cli_anything.unreal.core.script_runner import api_discover

        class PointLight:
            @staticmethod
            def python_only_method():
                pass

            def get_path_name(self):
                return "/Game/Maps/L.L:PersistentLevel.Light_0"

            def get_name(self):
                return "Light_0"

            def get_actor_label(self):
                return "Light_0"

        bridge_data = {
            "PointLight": {
                "class": "PointLight",
                "properties": [],
                "functions": [],
            }
        }
        actor = PointLight()
        mock_api, _, cleanup = self._setup_instance_discover(
            bridge_data,
            actors=[actor],
        )
        try:
            result = api_discover(
                mock_api,
                actor.get_path_name(),
                query="python_only",
                timeout=5,
            )

            assert result["functions"] == ["python_only_method"]
            assert result["python_only_functions"] == ["python_only_method"]
        finally:
            cleanup()

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

    def test_inspect_instance_asset_package_path_skips_package_object(self):
        """api_discover should load the primary asset when find_object returns its Package."""
        from cli_anything.unreal.core.script_runner import api_discover

        bridge_data = {
            "MaterialInstanceConstant": {
                "class": "MaterialInstanceConstant",
                "properties": [
                    {"name": "Parent", "type": "UMaterialInterface*",
                     "owner": "MaterialInstanceConstant", "read": True, "write": False},
                ],
                "functions": [],
            },
            "Package": {"class": "Package", "properties": [], "functions": []},
        }

        fake_package = MagicMock()
        fake_package.__class__ = type("Package", (), {})
        fake_package.get_path_name.return_value = "/Game/Materials/MI_Water"
        fake_package.get_name.return_value = "MI_Water"

        fake_asset = MagicMock()
        fake_asset.__class__ = type("MaterialInstanceConstant", (), {})
        fake_asset.get_path_name.return_value = "/Game/Materials/MI_Water.MI_Water"
        fake_asset.get_name.return_value = "MI_Water"

        mock_api, fake_unreal, cleanup = self._setup_instance_discover(
            bridge_data, assets={"/Game/Materials/MI_Water": fake_asset},
        )
        fake_unreal.find_object = lambda outer, path: fake_package if path == "/Game/Materials/MI_Water" else None
        try:
            result = api_discover(
                mock_api,
                "/Game/Materials/MI_Water",
                timeout=5,
            )
            assert "error" not in result
            assert result["class"] == "MaterialInstanceConstant"
            assert result["asset"] == "/Game/Materials/MI_Water"
            assert result["object_path"] == "/Game/Materials/MI_Water.MI_Water"
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

    def test_inspect_blueprint_component_template_subobject(self):
        """api_discover should resolve generated-class component templates via find_object."""
        from cli_anything.unreal.core.script_runner import api_discover

        bridge_data = {
            "SGCharacterTakeDamageComponent": {
                "class": "SGCharacterTakeDamageComponent",
                "properties": [
                    {"name": "HitPartInfoLookupTable", "type": "UDataTable*",
                     "owner": "SGCharacterTakeDamageComponent", "read": True, "write": True},
                ],
                "functions": [],
            }
        }

        subobject_path = (
            "/Game/InBattle/Blueprints/Game/BP_CharacterBase.BP_CharacterBase_C:"
            "SGCharacterTakeDamage_GEN_VARIABLE"
        )
        fake_component = MagicMock()
        fake_component.__class__ = type("SGCharacterTakeDamageComponent", (), {})
        fake_component.get_path_name.return_value = subobject_path
        fake_component.get_name.return_value = "SGCharacterTakeDamage_GEN_VARIABLE"

        mock_api, fake_unreal, cleanup = self._setup_instance_discover(bridge_data, assets={})
        fake_unreal.find_object = lambda outer, path: fake_component if path == subobject_path else None
        try:
            result = api_discover(
                mock_api,
                subobject_path,
                detail="HitPartInfoLookupTable",
                timeout=5,
            )
            assert "error" not in result
            assert result["class"] == "SGCharacterTakeDamageComponent"
            assert result["object"] == subobject_path
            assert result["object_name"] == "SGCharacterTakeDamage_GEN_VARIABLE"
            assert result["items"][0]["name"] == "HitPartInfoLookupTable"
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

    def test_editor_run_script_inline_code(self):
        """``editor run-script -c '...'`` should route through run_python_code."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_editor.return_value = MagicMock()
            mock_run.return_value = {"status": "ok", "actors": 42}

            result = runner.invoke(cli, [
                "--output", "json", "editor", "run-script", "-c", "result = {'actors': 42}",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["result"]["actors"] == 42
            mock_run.assert_called_once()

    def test_editor_run_script_no_save_does_not_probe_bridge_version(self):
        """Remote Control Python execution must stay usable across bridge mismatches."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run, \
             patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version") as mock_loaded, \
             patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version") as mock_bundled:
            mock_editor.return_value = MagicMock()
            mock_run.return_value = {"status": "ok", "validated": True}
            mock_loaded.return_value = "1.18"
            mock_bundled.return_value = "1.19"

            result = runner.invoke(cli, [
                "--output", "json", "editor", "run-script", "--no-save", "-",
            ], input="result = {'validated': True}\n")

        assert result.exit_code == 0
        assert json.loads(result.output)["result"]["validated"] is True
        assert mock_run.call_args.kwargs["save"] is False
        mock_loaded.assert_not_called()
        mock_bundled.assert_not_called()

    def test_editor_run_script_stdin_code(self):
        """``editor run-script -`` should read multiline Python from stdin."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        code = "value = 41\nresult = {'actors': value + 1}\n"
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_editor.return_value = MagicMock()
            mock_run.return_value = {"status": "ok", "actors": 42}

            result = runner.invoke(cli, [
                "--output", "json", "editor", "run-script", "-",
            ], input=code)
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["result"]["actors"] == 42
            mock_run.assert_called_once()
            assert mock_run.call_args.args[1] == code

    def test_editor_run_script_decodes_powershell_51_utf8_bom_stdin(self):
        """PowerShell 5.1 native pipelines prefix UTF-8 stdin with a BOM."""
        from cli_anything.unreal.commands.editor import _read_stdin_python_code

        raw = b"\xef\xbb\xbfimport unreal\nresult = {'ok': True}\r\n"
        stream = io.TextIOWrapper(io.BytesIO(raw), encoding="gbk")

        assert _read_stdin_python_code(stream) == (
            "import unreal\nresult = {'ok': True}\r\n"
        )

    @pytest.mark.parametrize(
        ("raw", "stream_encoding", "expected"),
        [
            (
                b"\xff\xfe" + "result = {'ok': True}\n".encode("utf-16-le"),
                "gbk",
                "result = {'ok': True}\n",
            ),
            (
                b"\xfe\xff" + "result = {'ok': True}\n".encode("utf-16-be"),
                "gbk",
                "result = {'ok': True}\n",
            ),
            (
                "result = {'label': '\u6d4b\u8bd5'}\n".encode("gbk"),
                "gbk",
                "result = {'label': '\u6d4b\u8bd5'}\n",
            ),
        ],
        ids=("utf16-le-bom", "utf16-be-bom", "console-encoding"),
    )
    def test_editor_run_script_decodes_other_windows_stdin_encodings(
        self, raw, stream_encoding, expected
    ):
        from cli_anything.unreal.commands.editor import _read_stdin_python_code

        stream = io.TextIOWrapper(io.BytesIO(raw), encoding=stream_encoding)

        assert _read_stdin_python_code(stream) == expected

    def test_editor_run_script_error_is_top_level_error(self):
        """User script exceptions should fail the CLI command."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_editor.return_value = MagicMock()
            mock_run.return_value = {
                "stdout": "",
                "error": "'tuple' object has no attribute 'set_editor_property'",
                "error_type": "AttributeError",
                "traceback": "Traceback ...",
            }

            result = runner.invoke(cli, [
                "--output", "json", "editor", "run-script", "-",
                "--no-save",
            ], input="raise AttributeError('boom')\n")

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "SCRIPT_EXECUTION_FAILED"
        assert data["message"] == "'tuple' object has no attribute 'set_editor_property'"
        assert data["details"]["error_type"] == "AttributeError"

    def test_editor_run_script_connection_reset_is_transport_error(self):
        """Transport disconnects should not be diagnosed as script exceptions."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_editor.return_value = MagicMock()
            mock_run.return_value = {
                "error": "('Connection aborted.', ConnectionResetError(10054, 'remote host forcibly closed', None, 10054, None))",
            }

            result = runner.invoke(cli, [
                "--output", "json", "editor", "run-script", "-",
                "--no-save",
            ], input="result = {}\n")

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "EDITOR_CONNECTION_LOST"
        assert "connection was lost" in data["message"]
        assert "editor status" in data["suggestion"]
        assert data["details"]["failure_kind"] == "transport_disconnect"

    def test_editor_run_script_read_timeout_is_timeout_error(self):
        """HTTP read timeouts should not be diagnosed as Python exceptions."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_editor.return_value = MagicMock()
            mock_run.return_value = {
                "error": "HTTPConnectionPool(host='localhost', port=30021): Read timed out. (read timeout=30)",
            }

            result = runner.invoke(cli, [
                "--output", "json", "editor", "run-script", "-",
                "--no-save",
            ], input="result = {}\n")

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "EDITOR_SCRIPT_TIMEOUT"
        assert "timed out" in data["message"]
        assert "--timeout" in data["suggestion"]
        assert "editor status" in data["suggestion"]
        assert data["details"]["failure_kind"] == "transport_timeout"
        assert data["details"]["operation"] == "editor run-script"
        assert data["details"]["timeout_seconds"] == 30
        assert data["details"]["retry_timeout_seconds"] == 60
        assert "retry_command" not in data["details"]

    def test_editor_run_script_file_timeout_includes_exact_retry_command(self, tmp_path):
        """File-backed timeouts should return a safe, copyable retry command."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        project = tmp_path / "Retry Project.uproject"
        project.write_text("{}\n", encoding="utf-8")
        script = tmp_path / "slow scan.py"
        script.write_text("result = {}\n", encoding="utf-8")

        runner = CliRunner()
        with patch(
            "cli_anything.unreal.utils.ue_backend.find_engine_root",
            return_value=str(tmp_path / "Engine"),
        ), patch(
            "cli_anything.unreal.commands.editor.require_editor",
        ) as mock_editor, patch(
            "cli_anything.unreal.core.script_runner.run_python_script",
        ) as mock_run:
            mock_editor.return_value = MagicMock()
            mock_run.return_value = {
                "error": "HTTPConnectionPool(host='localhost', port=30021): Read timed out. (read timeout=30)",
            }
            result = runner.invoke(cli, [
                "--output", "json",
                "--project", str(project),
                "--port", "30021",
                "editor", "run-script", "--no-save", str(script),
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["code"] == "EDITOR_SCRIPT_TIMEOUT"
        assert data["details"]["retry_timeout_seconds"] == 60
        retry_command = data["details"]["retry_command"]
        assert retry_command.startswith("ue-cli --output json")
        assert "--timeout 60 --no-save" in retry_command
        assert "--port 30021" in retry_command
        assert str(project.resolve()) in retry_command
        assert str(script.resolve()) in retry_command
        assert retry_command in data["suggestion"]

    def test_editor_new_level_connection_reset_is_top_level_error(self):
        """Level creation transport disconnects should not be wrapped as success."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.scene.new_level") as mock_new_level:
            mock_editor.return_value = MagicMock()
            mock_new_level.return_value = {
                "error": "('Connection aborted.', ConnectionResetError(10054, 'remote host forcibly closed', None, 10054, None))",
            }

            result = runner.invoke(cli, [
                "--output", "json", "editor", "new-level", "/Game/Test/L_Test",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "EDITOR_CONNECTION_LOST"
        assert "connection was lost" in data["message"]
        assert "editor status" in data["suggestion"]
        assert data["details"]["failure_kind"] == "transport_disconnect"
        assert data["details"]["operation"] == "editor new-level"

    def test_editor_save_level_connection_reset_is_top_level_error(self):
        """Level save transport disconnects should not be wrapped as success."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.scene.save_level") as mock_save_level:
            mock_editor.return_value = MagicMock()
            mock_save_level.return_value = {
                "error": "('Connection aborted.', ConnectionResetError(10054, 'remote host forcibly closed', None, 10054, None))",
            }

            result = runner.invoke(cli, [
                "--output", "json", "editor", "save-level",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["code"] == "EDITOR_CONNECTION_LOST"
        assert data["details"]["operation"] == "editor save-level"

    def test_editor_open_level_connection_reset_is_top_level_error(self):
        """Level open transport disconnects should not be wrapped as success."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.scene.open_level") as mock_open_level:
            mock_editor.return_value = MagicMock()
            mock_open_level.return_value = {
                "error": "('Connection aborted.', ConnectionResetError(10054, 'remote host forcibly closed', None, 10054, None))",
            }

            result = runner.invoke(cli, [
                "--output", "json", "editor", "open-level", "/Game/Test/L_Test",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["code"] == "EDITOR_CONNECTION_LOST"
        assert data["details"]["operation"] == "editor open-level"

    def test_editor_open_level_success(self):
        """The open-level CLI should expose the safe LevelEditorSubsystem path."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.scene.open_level") as mock_open_level:
            mock_editor.return_value = MagicMock()
            mock_open_level.return_value = {
                "status": "ok",
                "success": True,
                "path": "/Game/Test/L_Test",
            }

            result = runner.invoke(cli, [
                "--output", "json", "editor", "open-level", "/Game/Test/L_Test",
            ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["result"]["status"] == "ok"
        mock_open_level.assert_called_once()

    def test_editor_open_level_rejects_unrooted_name_before_contacting_editor(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.scene.open_level") as mock_open_level:
            result = runner.invoke(cli, [
                "--output", "json", "editor", "open-level", "Oregon_Main",
            ])

        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["code"] == "INVALID_LEVEL_PATH"
        assert "/Game/" in data["suggestion"]
        assert data["details"]["path"] == "Oregon_Main"
        mock_editor.assert_not_called()
        mock_open_level.assert_not_called()

    def test_editor_open_level_mismatch_is_top_level_error(self):
        """Open-level active-world verification failures should fail the CLI."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.scene.open_level") as mock_open_level:
            mock_editor.return_value = MagicMock()
            mock_open_level.return_value = {
                "status": "failed",
                "success": False,
                "path": "/Game/Test/L_Test",
                "error": "Active editor world did not match requested level.",
                "expected_package": "/Game/Test/L_Test",
                "active_world": {"package": "/Temp/Untitled_3"},
            }

            result = runner.invoke(cli, [
                "--output", "json", "editor", "open-level", "/Game/Test/L_Test",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "EDITOR_OPEN_LEVEL_FAILED"
        assert data["details"]["active_world"]["package"] == "/Temp/Untitled_3"

    def test_editor_run_script_blocks_load_map_inline_code(self):
        """Known-crashy map loading APIs should be blocked before contacting the editor."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            result = runner.invoke(cli, [
                "--output", "json", "editor", "run-script",
                "-c", "import unreal; unreal.EditorLoadingAndSavingUtils.load_map('/Game/Test/L_Test')",
            ])

        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["code"] == "UNSAFE_RUN_SCRIPT_OPERATION"
        assert "load_map" in data["message"]
        assert "editor open-level" in data["suggestion"]
        mock_editor.assert_not_called()
        mock_run.assert_not_called()

    def test_editor_run_script_allows_load_map_inside_unused_helper(self):
        """Reusable helpers may define offline load_map paths without executing them."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        code = """
import unreal

def commandlet_only_load():
    return unreal.EditorLoadingAndSavingUtils.load_map('/Game/Test/L_Test')

result = {'status': 'live_editor_ok'}
"""

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_editor.return_value = MagicMock()
            mock_run.return_value = {"status": "live_editor_ok"}
            result = runner.invoke(cli, [
                "--output", "json", "editor", "run-script", "-",
            ], input=code)

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["result"]["status"] == "live_editor_ok"
        mock_editor.assert_called_once()
        mock_run.assert_called_once()

    def test_editor_run_script_blocks_new_blank_map_inline_code(self):
        """Known-crashy map creation APIs should be blocked before contacting the editor."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            result = runner.invoke(cli, [
                "--output", "json", "editor", "run-script",
                "-c", "import unreal; unreal.EditorLoadingAndSavingUtils.new_blank_map(False)",
            ])

        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "UNSAFE_RUN_SCRIPT_OPERATION"
        assert "new_blank_map" in data["message"]
        assert "editor new-level" in data["suggestion"]
        mock_editor.assert_not_called()
        mock_run.assert_not_called()

    def test_editor_run_script_blocks_new_blank_map_script_file(self, tmp_path):
        """Script files are inspected for known-crashy map creation APIs."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        script = tmp_path / "make_scene.py"
        script.write_text(
            "import unreal\nunreal.EditorLoadingAndSavingUtils.new_blank_map(False)\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor:
            result = runner.invoke(cli, [
                "--output", "json", "editor", "run-script", str(script),
            ])

        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["code"] == "UNSAFE_RUN_SCRIPT_OPERATION"
        assert "editor new-level" in data["suggestion"]
        mock_editor.assert_not_called()

    def test_editor_run_script_blocks_new_blank_map_inline_exec_file(self, tmp_path):
        """Inline exec(open(...)) is inspected so unsafe code cannot hide in another file."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        script = tmp_path / "make_scene.py"
        script.write_text(
            "import unreal\nunreal.EditorLoadingAndSavingUtils.new_blank_map(False)\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor:
            result = runner.invoke(cli, [
                "--output", "json", "editor", "run-script",
                "-c", f"exec(open(r'{script}').read())",
            ])

        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["code"] == "UNSAFE_RUN_SCRIPT_OPERATION"
        assert data["details"]["source_path"] == str(script)
        mock_editor.assert_not_called()

    def test_editor_run_script_missing_file_errors(self):
        """Missing script path should return a structured file error."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--output", "json", "editor", "run-script", "missing_script.py",
        ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "FILE_NOT_FOUND"
        assert "missing_script.py" in data["message"]

    def test_editor_exec_captures_console_log_output(self):
        """Console commands should return log output captured by Python execution."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.exec_python_ex.return_value = {
                "ReturnValue": True,
                "LogOutput": [
                    {"Type": "Info", "Output": "__ue_cli_exec_begin__:abc"},
                    {"Type": "Info", "Output": "Render target pool dump line"},
                    {"Type": "Info", "Output": "__ue_cli_exec_end__:abc"},
                ],
            }
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--output", "json", "editor", "exec", "r.DumpRenderTargetPoolMemory",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["result"]["status"] == "executed"
            assert data["result"]["capture_mode"] == "python_log_output"
            assert data["result"]["log_text"] == "Render target pool dump line"
            mock_api.exec_python_ex.assert_called_once()
            mock_api.exec_console.assert_not_called()

    def test_editor_exec_prepares_automation_without_persisting_config(self):
        from cli_anything.unreal.commands.editor import _exec_console_with_log_capture

        api = MagicMock()
        api.exec_python_ex.return_value = {
            "ReturnValue": True,
            "LogOutput": [],
        }

        result = _exec_console_with_log_capture(
            api,
            "Automation RunTests System.Core.HAL.Platform Verification",
        )

        script = api.exec_python_ex.call_args.args[0]
        assert '/Script/Engine.AutomationTestSettings' in script
        assert 'set_editor_property("DefaultInteractiveFramerate", 1.0)' in script
        assert "save_config" not in script
        assert script.index("set_editor_property") < script.index(
            "execute_console_command"
        )
        assert result["status"] == "executed"

    def test_editor_exec_bounds_unmarked_remote_log_output(self):
        """Historical Remote Control output cannot flood one CLI response."""
        from click.testing import CliRunner
        from cli_anything.unreal.commands.editor import (
            EDITOR_EXEC_INLINE_LOG_LIMIT_BYTES,
        )
        from cli_anything.unreal.unreal_cli import cli

        entries = [
            {"Type": "Info", "Output": f"historical-{index:04d}-" + "x" * 200}
            for index in range(200)
        ]
        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.exec_python_ex.return_value = {
                "ReturnValue": True,
                "LogOutput": entries,
            }
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--output", "json", "editor", "exec", "stat fps",
            ])

        assert result.exit_code == 0
        data = json.loads(result.output)["result"]
        assert data["omitted_line_count"] > 0
        assert len(data["log_text"].encode("utf-8")) <= EDITOR_EXEC_INLINE_LOG_LIMIT_BYTES
        assert data["log_output"][-1]["Output"] == entries[-1]["Output"]

    def test_editor_exec_automation_keeps_only_lifecycle_output(self, tmp_path):
        """Automation inline output stays focused while full log remains on disk."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        log_file = tmp_path / "RXGame.log"
        noise = [f"LogBlueprint: discovery warning {index}" for index in range(100)]
        lifecycle = [
            "LogAutomationController: Test Started. Path={SDOC.Unit}",
            "LogAutomationController: Test Completed. Result={Success} Path={SDOC.Unit}",
            "LogAutomationCommandLine: Automation Test Queue Empty 1 tests performed.",
        ]
        log_file.write_text("before\n", encoding="utf-8")

        def fake_exec_python_ex(script, *, timeout=None):
            with log_file.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(noise + lifecycle) + "\n")
            return {
                "ReturnValue": True,
                "LogOutput": [
                    {"Type": "Warning", "Output": line}
                    for line in noise + lifecycle
                ],
            }

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch(
                 "cli_anything.unreal.commands.editor._resolve_editor_log_file",
                 return_value=log_file,
             ):
            mock_api = MagicMock()
            mock_api.exec_python_ex.side_effect = fake_exec_python_ex
            mock_editor.return_value = mock_api
            result = runner.invoke(cli, [
                "--output", "json", "editor", "exec", "--log-wait", "0",
                "Automation RunTests SDOC.Unit",
            ])

        assert result.exit_code == 0
        data = json.loads(result.output)["result"]
        assert data["automation_completed"] is True
        assert data["omitted_line_count"] >= len(noise)
        assert data["log_file"] == str(log_file)
        assert "discovery warning" not in data["log_text"]
        assert "Result={Success}" in data["log_text"]
        assert "Queue Empty" in data["log_text"]

    def test_editor_exec_reports_synchronous_python_exception(self):
        """A failing ``py`` statement must not be reported as executed."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.exec_python_ex.return_value = {
                "ReturnValue": True,
                "LogOutput": [
                    {"Type": "Info", "Output": "__ue_cli_exec_begin__:abc"},
                    {"Type": "Error", "Output": "Traceback (most recent call last):"},
                    {"Type": "Error", "Output": '  File "<string>", line 1, in <module>'},
                    {"Type": "Error", "Output": "RuntimeError: sentinel"},
                    {"Type": "Info", "Output": "__ue_cli_exec_end__:abc"},
                ],
            }
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--output", "json", "editor", "exec",
                "py raise RuntimeError('sentinel')",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "PYTHON_EXEC_FAILED"
        assert data["details"]["status"] == "failed"
        assert data["details"]["command"] == "py raise RuntimeError('sentinel')"
        assert "Traceback (most recent call last):" in data["details"]["python_error"]
        assert "RuntimeError: sentinel" in data["details"]["python_error"]
        mock_api.exec_console.assert_not_called()

    def test_editor_exec_reports_python_exception_from_editor_log(self, tmp_path):
        """Project-log fallback must also surface synchronous Python failures."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        log_file = tmp_path / "RXGame.log"
        log_file.write_text("before\n", encoding="utf-8")

        def fake_exec_python_ex(script, *, timeout=None):
            import re

            begin = re.search(r'_begin = "([^"]+)"', script).group(1)
            end = re.search(r'_end = "([^"]+)"', script).group(1)
            with log_file.open("a", encoding="utf-8") as handle:
                handle.write(f"{begin}\n")
                handle.write(
                    "[2026.07.20-21.29.58:425][332]LogPython: Error: "
                    "|PyUtil.cpp:1701|Traceback (most recent call last):\n"
                )
                handle.write(
                    "[2026.07.20-21.29.58:425][332]LogPython: Error: "
                    "|PyUtil.cpp:1701|RuntimeError: sentinel\n"
                )
                handle.write(f"{end}\n")
            return {"ReturnValue": True, "LogOutput": []}

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch(
                 "cli_anything.unreal.commands.editor._resolve_editor_log_file",
                 return_value=log_file,
             ):
            mock_api = MagicMock()
            mock_api.exec_python_ex.side_effect = fake_exec_python_ex
            mock_editor.return_value = mock_api
            result = runner.invoke(cli, [
                "--output", "json", "editor", "exec",
                "py raise RuntimeError('sentinel')",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["code"] == "PYTHON_EXEC_FAILED"
        assert data["details"]["capture_mode"] == "editor_log_file"
        assert "RuntimeError: sentinel" in data["details"]["python_error"]

    def test_editor_exec_falls_back_to_remote_console(self):
        """An explicit pre-dispatch rejection may use remote-console fallback."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.exec_python_ex.return_value = {
                "error": "400 Client Error: Bad Request",
            }
            mock_api.exec_console.return_value = {}
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--output", "json", "editor", "exec", "stat fps",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["result"]["status"] == "executed"
            assert data["result"]["capture_mode"] == "remote_console"
            mock_api.exec_console.assert_called_once_with("stat fps", timeout=15)

    def test_editor_exec_does_not_retry_after_read_timeout(self):
        """A timed-out non-idempotent command may have run and must not be resent."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.exec_python_ex.return_value = {
                "error": "HTTPConnectionPool: Read timed out. (read timeout=1)",
            }
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--output", "json", "editor", "exec", "--timeout", "1",
                "MutationCommand",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["code"] == "EDITOR_EXEC_DELIVERY_UNKNOWN"
        assert data["details"]["delivery_state"] == "unknown"
        assert data["details"]["fallback_attempted"] is False
        assert data["details"]["timeout_seconds"] == 1
        mock_api.exec_python_ex.assert_called_once()
        mock_api.exec_console.assert_not_called()

    def test_editor_exec_does_not_retry_after_python_dispatch_failure(self):
        """A failed Python wrapper may have partial effects and must not be resent."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.exec_python_ex.return_value = {
                "ReturnValue": False,
                "CommandResult": "wrapper failed",
            }
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--output", "json", "editor", "exec", "MutationCommand",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["code"] == "EDITOR_EXEC_FAILED"
        assert data["details"]["delivery_state"] == "attempted"
        assert data["details"]["fallback_attempted"] is False
        mock_api.exec_console.assert_not_called()

    def test_editor_exec_uses_editor_log_delta_when_python_log_is_empty(self, tmp_path):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        log_file = tmp_path / "RXGame.log"
        log_file.write_text("before\n", encoding="utf-8")

        def fake_exec_python_ex(script, *, timeout=None):
            import re

            begin = re.search(r'_begin = "([^"]+)"', script).group(1)
            end = re.search(r'_end = "([^"]+)"', script).group(1)
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(f"{begin}\n")
                fh.write("LogRHI: Render target pool dump line\n")
                fh.write(f"{end}\n")
            return {"ReturnValue": True, "LogOutput": []}

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.commands.editor._resolve_editor_log_file", return_value=log_file):
            mock_api = MagicMock()
            mock_api.exec_python_ex.side_effect = fake_exec_python_ex
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--output", "json", "editor", "exec", "r.DumpRenderTargetPoolMemory",
            ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["result"]["capture_mode"] == "editor_log_file"
        assert data["result"]["log_text"] == "LogRHI: Render target pool dump line"
        assert data["result"]["log_file"] == str(log_file)

    def test_editor_exec_log_resolver_uses_uproject_name_not_directory_name(
        self, tmp_path
    ):
        from cli_anything.unreal.commands.editor import _resolve_editor_log_file

        project_dir = tmp_path / "RXGame_2"
        log_dir = project_dir / "Saved" / "Logs"
        log_dir.mkdir(parents=True)
        active_log = log_dir / "RXGame.log"
        wrong_log = log_dir / "RXGame_2.log"
        active_log.write_text("active editor log\n", encoding="utf-8")
        wrong_log.write_text("directory-named stale log\n", encoding="utf-8")

        state = MagicMock()
        state.session.project_dir = str(project_dir)
        state.session.project_path = str(project_dir / "RXGame.uproject")

        assert _resolve_editor_log_file(state) == active_log

    def test_editor_exec_log_wait_captures_async_automation_completion(self, tmp_path):
        import re
        import threading

        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        log_file = tmp_path / "RXGame.log"
        log_file.write_text("before\n", encoding="utf-8")
        writer = None

        def fake_exec_python_ex(script, *, timeout=None):
            nonlocal writer
            begin = re.search(r'_begin = "([^"]+)"', script).group(1)
            end = re.search(r'_end = "([^"]+)"', script).group(1)
            with log_file.open("a", encoding="utf-8") as handle:
                handle.write(f"{begin}\n{end}\n")

            def finish_automation():
                time.sleep(0.05)
                with log_file.open("a", encoding="utf-8") as handle:
                    handle.write(
                        "LogAutomationController: Test Completed. "
                        "Result={Success} Path={SDOC.Unit}\n"
                    )
                    handle.write(
                        "LogAutomationCommandLine: ...Automation Test Queue Empty "
                        "1 tests performed.\n"
                    )

            writer = threading.Thread(target=finish_automation)
            writer.start()
            return {"ReturnValue": True, "LogOutput": []}

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.commands.editor._resolve_editor_log_file", return_value=log_file):
            mock_api = MagicMock()
            mock_api.exec_python_ex.side_effect = fake_exec_python_ex
            mock_editor.return_value = mock_api
            result = runner.invoke(cli, [
                "--output", "json", "editor", "exec",
                "--log-wait", "1", "Automation RunTests SDOC.Unit",
            ])

        if writer is not None:
            writer.join(timeout=1)
        assert result.exit_code == 0
        data = json.loads(result.output)["result"]
        assert data["capture_mode"] == "editor_log_file"
        assert data["log_capture_status"] == "completed"
        assert data["automation_completed"] is True
        assert "Result={Success}" in data["log_text"]
        assert "Automation Test Queue Empty 1 tests performed" in data["log_text"]
        assert any("Result={Success}" in item["Output"] for item in data["log_output"])
        assert any("Queue Empty" in item["Output"] for item in data["log_output"])

    def test_editor_exec_log_wait_scans_past_capture_limit(self, tmp_path):
        from cli_anything.unreal.commands.editor import (
            EDITOR_LOG_CAPTURE_LIMIT_BYTES,
            _read_log_delta,
        )

        completion = (
            b"LogAutomationCommandLine: Automation Test Queue Empty "
            b"1 tests performed.\n"
        )
        log_file = tmp_path / "RXGame.log"
        log_file.write_bytes(b"x" * (EDITOR_LOG_CAPTURE_LIMIT_BYTES + 1) + completion)

        log_text = _read_log_delta(
            log_file,
            0,
            wait_seconds=0,
            completion_markers=("Automation Test Queue Empty",),
        )

        assert "Automation Test Queue Empty 1 tests performed" in log_text
        assert len(log_text.encode("utf-8")) <= EDITOR_LOG_CAPTURE_LIMIT_BYTES


    def test_editor_exec_log_wait_reports_automation_timeout(self, tmp_path):
        import re

        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        log_file = tmp_path / "RXGame.log"
        log_file.write_text("before\n", encoding="utf-8")

        def fake_exec_python_ex(script, *, timeout=None):
            begin = re.search(r'_begin = "([^"]+)"', script).group(1)
            end = re.search(r'_end = "([^"]+)"', script).group(1)
            with log_file.open("a", encoding="utf-8") as handle:
                handle.write(f"{begin}\n{end}\n")
            return {"ReturnValue": True, "LogOutput": []}

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.commands.editor._resolve_editor_log_file", return_value=log_file):
            mock_api = MagicMock()
            mock_api.exec_python_ex.side_effect = fake_exec_python_ex
            mock_editor.return_value = mock_api
            result = runner.invoke(cli, [
                "--output", "json", "editor", "exec",
                "--log-wait", "0", "Automation RunTests SDOC.Unit",
            ])

        assert result.exit_code == 4
        response = json.loads(result.output)
        assert response["code"] == "AUTOMATION_RESULT_TIMEOUT"
        data = response["details"]
        assert data["automation_completed"] is False
        assert data["log_capture_status"] == "timeout"
        assert data["log_file"] == str(log_file)
        assert "Get-Content -LiteralPath" in data["next_command"]
        assert "longer wait" in data["suggestion"]


    def test_editor_exec_reports_live_coding_result_as_unobservable(self, tmp_path):
        import re

        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        log_file = tmp_path / "RXGame.log"
        log_file.write_text("before\n", encoding="utf-8")

        def fake_exec_python_ex(script, *, timeout=None):
            begin = re.search(r'_begin = "([^"]+)"', script).group(1)
            end = re.search(r'_end = "([^"]+)"', script).group(1)
            with log_file.open("a", encoding="utf-8") as handle:
                handle.write(f"{begin}\n")
                handle.write("LogLiveCoding: Starting Live Coding compile.\n")
                handle.write(f"{end}\n")
            return {"ReturnValue": True, "LogOutput": []}

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.commands.editor._resolve_editor_log_file", return_value=log_file):
            mock_api = MagicMock()
            mock_api.exec_python_ex.side_effect = fake_exec_python_ex
            mock_editor.return_value = mock_api
            result = runner.invoke(cli, [
                "--output", "json", "editor", "exec",
                "--log-wait", "0", "livecoding.compile",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "LIVECODING_RESULT_UNOBSERVABLE"
        assert "LiveCodingConsole" in data["message"]
        assert "build compile" in data["suggestion"]
        assert data["details"]["status"] == "submitted"
        assert data["details"]["completion_observable"] is False
        assert data["details"]["completion_status"] == "unknown"
        assert data["details"]["log_capture_status"] == "unobservable"
        assert "Starting Live Coding compile" in data["details"]["log_text"]
        assert data["details"]["next_commands"] == [
            "ue-cli --project <path-to-.uproject> editor close",
            "ue-cli --project <path-to-.uproject> build compile",
        ]


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

    def test_traceback_robust_when_exc_info_cleared(self):
        """Traceback must still work even when sys.exc_info() is cleared.

        In UE's embedded Python, the exception context (sys.exc_info()) can
        be cleared by the engine between the except block and subsequent code.
        Our fix uses format_exception(type, value, tb) from the exception
        object's __traceback__ attribute, which is immune to this issue.

        This test verifies the wrapper template uses format_exception (which
        takes explicit type/value/tb args) rather than format_exc() (which
        relies on sys.exc_info()).
        """
        from cli_anything.unreal.core.script_runner import _WRAPPER_TEMPLATE

        # Verify the wrapper template uses format_exception, not format_exc
        assert "format_exception(" in _WRAPPER_TEMPLATE
        # The actual traceback assignment must NOT use format_exc()
        # (comments mentioning it are fine, only check executable lines)
        for line in _WRAPPER_TEMPLATE.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "_cli_traceback" in stripped and "format_exc()" in stripped:
                raise AssertionError(
                    f"Wrapper uses format_exc() for traceback capture: {stripped}"
                )

    def test_traceback_has_line_number_for_multiline_script(self):
        """Traceback should show the exact line where the error occurs."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        code = "a = 1\nb = 2\nc = 3\nd = a / 0\n"
        result = run_python_code(mock_api, code, timeout=5, save=False)
        assert result["error_type"] == "ZeroDivisionError"
        tb = result["traceback"]
        # Should contain a line number reference
        assert "line 4" in tb or "line 4," in tb
        assert "NoneType: None" not in tb

    def test_run_python_code_isolates_user_globals_between_calls(self):
        """Separate invocations should not leak user globals into later runs."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        first = run_python_code(mock_api, "sticky = 123\nresult = {'ok': True}", timeout=5, save=False)
        second = run_python_code(mock_api, "result = {'sticky_present': 'sticky' in globals()}", timeout=5, save=False)

        assert first["ok"] is True
        assert second["sticky_present"] is False

    def test_run_python_code_removes_user_namespace_from_wrapper_globals(self):
        """Wrapper globals must not retain the invocation namespace."""
        from cli_anything.unreal.core.script_runner import run_python_code

        import sys
        import types

        log_entries = []
        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: log_entries.append({"Type": "Info", "Output": msg})
        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        persistent_globals = {}

        def _fake_exec_python_ex(code, *, timeout=None):
            exec(compile(code, "<exec_python_ex>", "exec"), persistent_globals, persistent_globals)
            return {
                "ReturnValue": True,
                "CommandResult": "None",
                "LogOutput": list(log_entries),
            }

        mock_api = MagicMock()
        mock_api.exec_python_ex.side_effect = _fake_exec_python_ex
        try:
            result = run_python_code(
                mock_api,
                "held_world_like_object = object()\nresult = {'ok': True}",
                timeout=5,
                save=False,
            )
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

        assert result["ok"] is True
        assert "_cli_user_ns" not in persistent_globals
        assert "_cli_user_result" not in persistent_globals
        assert "held_world_like_object" not in persistent_globals

    def test_run_python_code_preserves_globals_for_registered_callback(self):
        """A retained callback must keep its invocation namespace usable."""
        from cli_anything.unreal.core.script_runner import run_python_code

        import sys
        import types

        callbacks = []
        log_entries = []
        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: log_entries.append({"Type": "Info", "Output": msg})
        fake_unreal.register_slate_post_tick_callback = lambda callback: callbacks.append(callback)
        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        persistent_globals = {}

        def _fake_exec_python_ex(code, *, timeout=None):
            exec(compile(code, "<exec_python_ex>", "exec"), persistent_globals, persistent_globals)
            return {
                "ReturnValue": True,
                "CommandResult": "None",
                "LogOutput": list(log_entries),
            }

        mock_api = MagicMock()
        mock_api.exec_python_ex.side_effect = _fake_exec_python_ex
        try:
            result = run_python_code(
                mock_api,
                "import unreal\n"
                "state = {'ticks': 0}\n"
                "def tick(delta):\n"
                "    state['ticks'] += 1\n"
                "unreal.register_slate_post_tick_callback(tick)\n"
                "result = {'registered': True}",
                timeout=5,
                save=False,
            )
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

        assert result["registered"] is True
        assert "_cli_user_ns" not in persistent_globals
        assert len(callbacks) == 1

        callback = callbacks[0]
        callback(0.016)
        assert callback.__globals__["state"] == {"ticks": 1}


# ═══════════════════════════════════════════════════════════════════════
#  Test scene.py (mocked API)
# ═══════════════════════════════════════════════════════════════════════
