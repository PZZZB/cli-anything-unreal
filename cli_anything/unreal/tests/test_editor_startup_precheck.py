import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest





@pytest.fixture
def mini_project(tmp_path):
    project_dir = tmp_path / "MiniProject"
    project_dir.mkdir()
    uproject = project_dir / "MiniProject.uproject"
    uproject.write_text('{"FileVersion": 3, "EngineAssociation": "5.7"}', encoding="utf-8")
    return str(uproject)


def test_editor_status_offline_api_blocked_includes_log_error(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[]), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[{"pid": 1234, "project": mini_project}]), \
         patch("cli_anything.unreal.commands.editor._check_log_errors", return_value="Plugin 'libzstd' failed to load"), \
         patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
             "ready": False,
             "engine": {"errors": ["engine error"], "warnings": []},
             "project": {"errors": ["project error"], "warnings": []},
         }):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "status",
        ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["result"][0]["status"] == "offline"
    assert data["result"][0]["log_error"] == "Plugin 'libzstd' failed to load"


def test_editor_status_transient_unreachable_does_not_suggest_relaunch(mini_project, tmp_path, monkeypatch):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
    runner = CliRunner()
    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[]), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[{"pid": 64644, "project": mini_project}]), \
         patch("cli_anything.unreal.utils.ue_backend.read_rc_port", return_value=30011), \
         patch("cli_anything.unreal.commands.editor._check_log_errors", return_value=None):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "status",
        ])

    assert result.exit_code == 0, result.output
    item = json.loads(result.output)["result"][0]
    assert item["status"] == "unreachable"
    assert item["pid"] == 64644
    assert item["port"] == 30011
    assert "temporarily unreachable" in item["message"]
    assert "editor launch" not in item["suggestion"]
    assert item["next_command"] == f'ue-cli --project "{mini_project}" editor status'


def test_editor_status_unreachable_becomes_offline_after_grace(mini_project, tmp_path, monkeypatch):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
    runner = CliRunner()

    base_patches = [
        patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[]),
        patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[{"pid": 64644, "project": mini_project}]),
        patch("cli_anything.unreal.utils.ue_backend.read_rc_port", return_value=30011),
        patch("cli_anything.unreal.commands.editor._check_log_errors", return_value=None),
    ]
    with base_patches[0], base_patches[1], base_patches[2], base_patches[3], \
         patch("cli_anything.unreal.commands.editor.time.time", return_value=1000.0):
        first = runner.invoke(cli, ["--output", "json", "--project", mini_project, "editor", "status"])
    assert first.exit_code == 0, first.output
    assert json.loads(first.output)["result"][0]["status"] == "unreachable"

    base_patches = [
        patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[]),
        patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[{"pid": 64644, "project": mini_project}]),
        patch("cli_anything.unreal.utils.ue_backend.read_rc_port", return_value=30011),
        patch("cli_anything.unreal.commands.editor._check_log_errors", return_value=None),
    ]
    with base_patches[0], base_patches[1], base_patches[2], base_patches[3], \
         patch("cli_anything.unreal.commands.editor.time.time", return_value=1100.0):
        stale = runner.invoke(cli, ["--output", "json", "--project", mini_project, "editor", "status"])

    assert stale.exit_code == 0, stale.output
    item = json.loads(stale.output)["result"][0]
    assert item["status"] == "offline"
    assert item["unreachable_seconds"] == 100
    assert "editor launch" in item["suggestion"]
    assert item["next_command"] == f'ue-cli --project "{mini_project}" editor launch'


def test_editor_status_offline_ignores_other_project_processes(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    other_project = str(Path(mini_project).with_name("Other.uproject"))
    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[]), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 5678, "project": other_project},
         ]), \
         patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
             "ready": True,
             "engine": {"errors": [], "warnings": []},
             "project": {"errors": [], "warnings": []},
         }):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "status",
        ])

    assert result.exit_code == 0
    assert result.output.count('"status": "success"') == 1
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["result"] == []


def test_editor_status_accepts_project_option_after_subcommand(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    other_project = str(Path(mini_project).with_name("Other.uproject"))
    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[]), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 1234, "project": mini_project},
             {"pid": 5678, "project": other_project},
         ]), \
         patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
             "ready": True,
             "engine": {"errors": [], "warnings": []},
             "project": {"errors": [], "warnings": []},
         }):
        result = runner.invoke(cli, [
            "--output", "json",
            "editor", "status", "--project", mini_project,
        ])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert len(data["result"]) == 1
    assert data["result"][0]["project_path"] == mini_project


def test_editor_status_all_lists_other_project_processes(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    other_project = str(Path(mini_project).with_name("Other.uproject"))
    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[]), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 5678, "project": other_project},
         ]), \
         patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
             "ready": True,
             "engine": {"errors": [], "warnings": []},
             "project": {"errors": [], "warnings": []},
         }):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "status", "--all",
        ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "success"
    instance = data["result"][0]
    assert instance["status"] == "unreachable"
    assert instance["pid"] == 5678
    assert instance["project_path"] == other_project
    assert "editor launch" not in instance["suggestion"]


def test_editor_status_filters_online_port_owner_when_other_project(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    other_project = str(Path(mini_project).with_name("Other.uproject"))
    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[
            {"port": 30020, "alive": True, "info": {"ok": True}},
         ]), \
         patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", return_value=5678), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 5678, "project": other_project},
         ]), \
         patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version", return_value="1.13"), \
         patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version", return_value="1.13"), \
         patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
             "ready": True,
             "engine": {"errors": [], "warnings": []},
             "project": {"errors": [], "warnings": []},
         }):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "status",
        ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["result"] == []


def test_editor_status_online_includes_matching_bridge_versions(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[
            {"port": 30020, "alive": True, "info": {"ok": True}},
         ]), \
         patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", return_value=1234), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 1234, "project": mini_project},
         ]), \
         patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version", return_value="1.13"), \
         patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version", return_value="1.13"):
        result = runner.invoke(cli, [
            "--output", "json",
            "editor", "status",
        ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    item = data["result"][0]
    assert item["bridge_version"] == "1.13"
    assert item["bundled_version"] == "1.13"
    assert item["plugin_match"] is True
    assert "next_command" not in item


def test_editor_status_online_suggests_plugin_upgrade_on_bridge_mismatch(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[
            {"port": 30020, "alive": True, "info": {"ok": True}},
         ]), \
         patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", return_value=1234), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 1234, "project": mini_project},
         ]), \
         patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version", return_value="1.14"), \
         patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version", return_value="1.13"):
        result = runner.invoke(cli, [
            "--output", "json",
            "editor", "status",
        ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    item = data["result"][0]
    assert item["bridge_version"] == "1.13"
    assert item["bundled_version"] == "1.14"
    assert item["plugin_match"] is False
    assert item["next_command"] == f'ue-cli --project "{mini_project}" editor plugin-upgrade'
    assert item["restart_required"] is True
    assert "running editor loaded" in item["message"]
    assert "restart" in item["message"]
    assert "plugin-upgrade" in item["suggestion"]


def test_editor_status_online_without_project_still_includes_bridge_versions():
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[
            {"port": 30020, "alive": True, "info": {"ok": True}},
         ]), \
         patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", return_value=None), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[]), \
         patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version", return_value="1.13"), \
         patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version", return_value="1.13"):
        result = runner.invoke(cli, [
            "--output", "json",
            "editor", "status",
        ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    item = data["result"][0]
    assert item["project_path"] is None
    assert item["bridge_version"] == "1.13"
    assert item["bundled_version"] == "1.13"
    assert item["plugin_match"] is True
    assert "next_command" not in item


def test_editor_status_online_bridge_probe_error_is_unknown_not_upgrade(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[
            {"port": 30020, "alive": True, "info": {"ok": True}},
         ]), \
         patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", return_value=1234), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 1234, "project": mini_project},
         ]), \
         patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version", return_value="1.13"), \
         patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version", side_effect=TimeoutError("busy")):
        result = runner.invoke(cli, [
            "--output", "json",
            "editor", "status",
        ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    item = data["result"][0]
    assert item["bridge_version"] is None
    assert item["bundled_version"] == "1.13"
    assert item["plugin_match"] is None
    assert "next_command" not in item
    assert "suggestion" not in item


def test_editor_status_bridge_probe_uses_short_timeout(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    captured = {}

    def fake_loaded(_api, timeout=10.0, raise_on_error=False):
        captured["timeout"] = timeout
        captured["raise_on_error"] = raise_on_error
        return "1.13"

    runner = CliRunner()
    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[
            {"port": 30020, "alive": True, "info": {"ok": True}},
         ]), \
         patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", return_value=1234), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 1234, "project": mini_project},
         ]), \
         patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version", return_value="1.13"), \
         patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version", side_effect=fake_loaded):
        result = runner.invoke(cli, [
            "--output", "json",
            "editor", "status",
        ])

    assert result.exit_code == 0
    assert captured["timeout"] <= 5.0
    assert captured["raise_on_error"] is True


def test_editor_status_bridge_probes_online_ports_concurrently():
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    calls = []
    calls_lock = threading.Lock()
    both_started = threading.Event()

    def fake_loaded(api, timeout=10.0, raise_on_error=False):
        with calls_lock:
            calls.append(api.port)
            if len(calls) == 2:
                both_started.set()
        if not both_started.wait(0.5):
            return None
        return "1.13"

    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[
            {"port": 30020, "alive": True, "info": {"ok": True}},
            {"port": 30021, "alive": True, "info": {"ok": True}},
         ]), \
         patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", return_value=None), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[]), \
         patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version", return_value="1.13"), \
         patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version", side_effect=fake_loaded):
        start = time.perf_counter()
        result = runner.invoke(cli, [
            "--output", "json",
            "editor", "status", "--all",
        ])
        elapsed = time.perf_counter() - start

    assert result.exit_code == 0, result.output
    assert sorted(calls) == [30020, 30021]
    assert elapsed < 0.45


def test_editor_status_resolves_online_port_owners_concurrently():
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    calls = []
    calls_lock = threading.Lock()
    both_started = threading.Event()

    def fake_pid(port):
        with calls_lock:
            calls.append(port)
            if len(calls) == 2:
                both_started.set()
        if not both_started.wait(0.5):
            return None
        return None

    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[
            {"port": 30020, "alive": True, "info": {"ok": True}},
            {"port": 30021, "alive": True, "info": {"ok": True}},
         ]), \
         patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", side_effect=fake_pid), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[]), \
         patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version", return_value="1.13"), \
         patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version", return_value="1.13"):
        start = time.perf_counter()
        result = runner.invoke(cli, [
            "--output", "json",
            "editor", "status", "--all",
        ])
        elapsed = time.perf_counter() - start

    assert result.exit_code == 0, result.output
    assert sorted(calls) == [30020, 30021]
    assert elapsed < 0.45


def test_editor_status_lists_all_editor_processes(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    other_project = str(Path(mini_project).with_name("Other.uproject"))
    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[
            {"port": 30020, "alive": True, "info": {"ok": True}},
         ]), \
         patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", return_value=1234), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 1234, "project": mini_project},
             {"pid": 5678, "project": other_project},
         ]), \
         patch("cli_anything.unreal.utils.ue_backend.read_rc_port", return_value=30030), \
         patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version", return_value="1.13"), \
         patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version", return_value="1.13"), \
         patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
             "ready": True,
             "engine": {"errors": [], "warnings": []},
             "project": {"errors": [], "warnings": []},
         }):
        result = runner.invoke(cli, [
            "--output", "json",
            "editor", "status",
        ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "success"
    online, offline = data["result"]
    assert online == {
        "status": "online",
        "pid": 1234,
        "port": 30020,
        "project_path": mini_project,
        "bridge_version": "1.13",
        "bundled_version": "1.13",
        "plugin_match": True,
    }
    assert offline["status"] == "unreachable"
    assert offline["pid"] == 5678
    assert offline["port"] == 30030
    assert offline["project_path"] == other_project
    assert "temporarily unreachable" in offline["message"]
    assert "editor launch" not in offline["suggestion"]
    assert offline["next_command"] == f'ue-cli --project "{other_project}" editor status'


def test_editor_status_marks_offline_process_as_launching_when_task_active(mini_project, tmp_path, monkeypatch):
    from click.testing import CliRunner
    from cli_anything.unreal.core.tasks import create_task, save_task
    from cli_anything.unreal.unreal_cli import cli

    monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
    task = create_task("editor.launch", {"project_path": mini_project, "port": 30011})
    task["status"] = "running"
    task["pid"] = 16044
    task["result"] = {"pid": 16044, "bridge_binary_status": {"ready": True}}
    save_task(task)

    runner = CliRunner()
    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[]), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 16044, "project": mini_project},
         ]), \
         patch("cli_anything.unreal.utils.ue_backend.read_rc_port", return_value=30011), \
         patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
             "ready": True,
             "engine": {"errors": [], "warnings": []},
             "project": {"errors": [], "warnings": []},
         }):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "status",
        ])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    item = data["result"][0]
    assert item["status"] == "launching"
    assert item["pid"] == 16044
    assert item["port"] == 30011
    assert item["task_id"] == task["task_id"]
    assert item["launch_task_status"] == "running"
    assert "editor status " + task["task_id"] in item["next_command"]
    assert "editor launch" not in item["suggestion"]


def test_editor_status_scans_running_project_config_ports_outside_default_range(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", side_effect=[
            [],
            [{"port": 30023, "alive": True, "info": {"ok": True}}],
         ]) as scan_ports, \
         patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", return_value=1234), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 1234, "project": mini_project},
         ]), \
         patch("cli_anything.unreal.utils.ue_backend.read_rc_port", return_value=30023), \
         patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version", return_value="1.13"), \
         patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version", return_value="1.13"):
        result = runner.invoke(cli, [
            "--output", "json",
            "editor", "status",
        ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["result"] == [
        {
            "status": "online",
            "pid": 1234,
            "port": 30023,
            "project_path": mini_project,
            "bridge_version": "1.13",
            "bundled_version": "1.13",
            "plugin_match": True,
        },
    ]
    assert [call.kwargs["port_range"] for call in scan_ports.call_args_list] == [
        (30010, 30020),
        (30023, 30023),
    ]


def test_editor_status_uses_config_port_when_owner_pid_unavailable(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[
            {"port": 30020, "alive": True, "info": {"ok": True}},
         ]), \
         patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", return_value=None), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 1234, "project": mini_project},
         ]), \
         patch("cli_anything.unreal.utils.ue_backend.read_rc_port", return_value=30020), \
         patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version", return_value="1.13"), \
         patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version", return_value="1.13"):
        result = runner.invoke(cli, [
            "--output", "json",
            "editor", "status",
        ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["result"] == [
        {
            "status": "online",
            "pid": 1234,
            "port": 30020,
            "project_path": mini_project,
            "bridge_version": "1.13",
            "bundled_version": "1.13",
            "plugin_match": True,
        },
    ]


def test_editor_list_command_removed():
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, [
        "--output", "json",
        "editor", "list",
    ])

    assert result.exit_code != 0


def test_check_port_in_use_detects_plain_tcp_listener():
    from cli_anything.unreal.commands import AppState
    from cli_anything.unreal.commands.editor import _check_port_in_use

    state = AppState()
    state.session.port = 30020
    with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI.is_alive", return_value=False), \
         patch("cli_anything.unreal.utils.ue_backend.is_tcp_port_in_use", return_value=True):
        result = _check_port_in_use(30020, state)

    assert result is not None
    assert result["status"] == "port_in_use"
    assert result["port"] == 30020


def test_editor_close_kills_matching_zombie_project_process(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    other_project = str(Path(mini_project).with_name("Other.uproject"))
    with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI.is_alive", return_value=False), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 1234, "project": mini_project},
             {"pid": 5678, "project": other_project},
         ]), \
         patch("cli_anything.unreal.utils.ue_backend._kill_process_tree_result", return_value={"ok": True}) as kill_process:
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "close",
        ])

    assert result.exit_code == 0, result.output
    kill_process.assert_called_once_with(1234)
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["result"]["status"] == "closed"
    assert data["result"]["method"] == "process_tree_kill"
    assert data["result"]["closed_processes"] == [{"pid": 1234, "project": mini_project}]


def test_editor_close_kills_matching_project_process_after_graceful_timeout(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    mock_api = MagicMock()
    mock_api.is_alive.side_effect = [True, False, True]

    with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI", return_value=mock_api), \
         patch("cli_anything.unreal.commands.editor.time.time", side_effect=[0, 0, 31]), \
         patch("cli_anything.unreal.commands.editor.time.sleep"), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 1234, "project": mini_project},
         ]), \
         patch("cli_anything.unreal.utils.ue_backend._kill_process_tree_result", return_value={"ok": True}) as kill_process:
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "close",
        ])

    assert result.exit_code == 0, result.output
    mock_api.call_function.assert_called_once_with(
        "/Script/UnrealEd.Default__EditorLoadingAndSavingUtils",
        "SaveDirtyPackages",
        {"bSaveMapPackages": True, "bSaveContentPackages": True},
    )
    mock_api.exec_console.assert_called_once_with("QUIT_EDITOR")
    kill_process.assert_called_once_with(1234)
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["result"]["status"] == "closed"
    assert data["result"]["method"] == "process_tree_kill"
    assert "did not close gracefully" in data["result"]["message"]


def test_editor_close_waits_for_process_exit_after_api_closes(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    mock_api = MagicMock()
    mock_api.is_alive.side_effect = [True, False]

    with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI", return_value=mock_api), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 98364, "project": mini_project},
         ]), \
         patch("cli_anything.unreal.commands.editor._wait_for_project_editor_exit", return_value={
             "status": "closed",
             "method": "process_exit",
         }) as mock_wait:
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "close",
        ])

    assert result.exit_code == 0, result.output
    mock_wait.assert_called_once_with(mini_project, 30010, timeout=60)
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["result"]["status"] == "closed"
    assert data["result"]["method"] == "process_exit"


def test_editor_close_failure_reports_kill_diagnostics(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    mock_api = MagicMock()
    mock_api.is_alive.side_effect = [True, False]

    kill_detail = {
        "ok": False,
        "pid": 49272,
        "method": "taskkill",
        "returncode": 5,
        "stdout": "",
        "stderr": "ERROR: Access is denied.",
        "access_denied": True,
        "retry_suggested": False,
        "suggestion": "Run from an elevated administrator shell or close the process manually.",
    }

    with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI", return_value=mock_api), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 49272, "project": mini_project},
         ]), \
         patch("cli_anything.unreal.commands.editor.time.time", side_effect=[0, 0, 0, 61, 122]), \
         patch("cli_anything.unreal.commands.editor.time.sleep"), \
         patch("cli_anything.unreal.utils.ue_backend._kill_process_tree_result", return_value=kill_detail):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "close",
        ])

    assert result.exit_code == 3
    data = json.loads(result.output)
    assert data["status"] == "error"
    assert data["code"] == "EDITOR_CLOSE_FAILED"
    failed = data["details"]["failed_processes"][0]
    assert failed["pid"] == 49272
    assert failed["kill_result"]["access_denied"] is True
    assert failed["kill_result"]["retry_suggested"] is False
    assert "administrator" in data["details"]["suggestion"].lower()


def test_editor_close_timeout_without_matching_process_returns_error(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    mock_api = MagicMock()
    mock_api.is_alive.side_effect = [True, True]

    with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI", return_value=mock_api), \
         patch("cli_anything.unreal.commands.editor.time.time", side_effect=[0, 0, 31]), \
         patch("cli_anything.unreal.commands.editor.time.sleep"), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", side_effect=[
             [{"pid": 1234, "project": mini_project}],
             [],
         ]):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "close",
        ])

    assert result.exit_code == 3
    data = json.loads(result.output)
    assert data["status"] == "error"
    assert data["code"] == "EDITOR_CLOSE_TIMEOUT"
    assert "Editor did not close within 30s." in data["message"]
    assert result.output.count('"status": "error"') == 1
    assert result.output.count('"code": "EDITOR_CLOSE_TIMEOUT"') == 1
    assert result.output.count("Editor did not close within 30s.") == 1


def test_editor_close_does_not_quit_other_project_on_same_port(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    mock_api = MagicMock()
    mock_api.is_alive.return_value = True
    other_project = str(Path(mini_project).with_name("Other.uproject"))

    with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI", return_value=mock_api), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 5678, "project": other_project},
         ]):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "close",
        ])

    assert result.exit_code == 3
    mock_api.exec_console.assert_not_called()
    data = json.loads(result.output)
    assert data["status"] == "error"
    assert data["code"] == "EDITOR_PROJECT_NOT_RUNNING"
    assert data["details"]["running_editors"] == [{"pid": 5678, "project": other_project}]


def test_editor_launch_preflight_failed_includes_startup_precheck(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    with patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
        "ready": False,
        "engine": {"errors": ["engine error"], "warnings": ["engine warning"]},
        "project": {"errors": ["project error"], "warnings": []},
    }), \
         patch("cli_anything.unreal.commands.editor.submit_task", return_value={"task_id": "launch-task"}):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "launch", "--no-wait",
        ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["result"]["status"] == "submitted"
    assert "task_id" in data["result"]


def test_editor_launch_success_includes_startup_precheck(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    mock_proc = MagicMock()
    mock_proc.pid = 4242

    with patch("cli_anything.unreal.utils.ue_backend.find_engine_root", return_value="F:/MockEngine"), \
         patch("cli_anything.unreal.utils.ue_backend.find_editor_exe", return_value="F:/MockEngine/Engine/Binaries/Win64/UnrealEditor.exe"), \
         patch("cli_anything.unreal.commands.editor._check_already_running", return_value=None), \
         patch("cli_anything.unreal.commands.editor._check_port_in_use", return_value=None), \
         patch("cli_anything.unreal.commands.editor._deploy_bridge", return_value={"deployed": False}), \
         patch("cli_anything.unreal.commands.editor.sp.Popen", return_value=mock_proc), \
         patch("cli_anything.unreal.commands.editor.submit_task", return_value={"task_id": "launch-task"}), \
         patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
             "ready": True,
             "engine": {"errors": [], "warnings": ["engine warning"]},
             "project": {"errors": [], "warnings": ["project warning"]},
         }):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "launch", "--no-wait",
        ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["result"]["status"] == "submitted"
    assert "task_id" in data["result"]


# ── _build_launch_cmd unit tests ────────────────────────────────────


def test_build_launch_cmd_without_map():
    from cli_anything.unreal.commands.editor import _build_launch_cmd

    cmd = _build_launch_cmd("UnrealEditor.exe", "MyProject.uproject", None)
    assert cmd == ["UnrealEditor.exe", "MyProject.uproject", "-nosplash", "-unattended"]


def test_build_launch_cmd_with_map():
    from cli_anything.unreal.commands.editor import _build_launch_cmd

    cmd = _build_launch_cmd("UnrealEditor.exe", "MyProject.uproject", "/Game/Maps/Main")
    assert cmd == ["UnrealEditor.exe", "MyProject.uproject", "-nosplash", "-unattended", "/Game/Maps/Main"]


def test_build_launch_cmd_with_extra_args():
    from cli_anything.unreal.commands.editor import _build_launch_cmd

    cmd = _build_launch_cmd(
        "UnrealEditor.exe",
        "MyProject.uproject",
        None,
        ["-vulkan", "-ResX=1280", "-ResY=720"],
    )
    assert cmd == [
        "UnrealEditor.exe",
        "MyProject.uproject",
        "-nosplash",
        "-unattended",
        "-vulkan",
        "-ResX=1280",
        "-ResY=720",
    ]


def test_build_launch_cmd_with_map_and_extra_args():
    from cli_anything.unreal.commands.editor import _build_launch_cmd

    cmd = _build_launch_cmd(
        "UnrealEditor.exe",
        "MyProject.uproject",
        "/Game/Maps/Main",
        ["-vulkan"],
    )
    assert cmd == [
        "UnrealEditor.exe",
        "MyProject.uproject",
        "-nosplash",
        "-unattended",
        "/Game/Maps/Main",
        "-vulkan",
    ]


def test_build_launch_cmd_filters_empty_extra_args():
    from cli_anything.unreal.commands.editor import _build_launch_cmd

    cmd = _build_launch_cmd("UnrealEditor.exe", "MyProject.uproject", None, [None, "", "-server"])
    assert cmd == ["UnrealEditor.exe", "MyProject.uproject", "-nosplash", "-unattended", "-server"]


def test_editor_launch_extra_args_propagate_to_payload(mini_project):
    """--extra-arg values must be persisted into the task payload so the worker forwards them."""
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    captured = {}

    def fake_submit_task(command, payload):
        captured["command"] = command
        captured["payload"] = payload
        return {"task_id": "task-xyz", "status": "submitted"}

    with patch("cli_anything.unreal.commands.editor.submit_task", side_effect=fake_submit_task), \
         patch("cli_anything.unreal.commands.editor._check_already_running", return_value=None):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "launch", "--no-wait",
            "--extra-arg", "-vulkan",
            "--extra-arg", "-ResX=1280",
            "--extra-arg", "-ResY=720",
        ])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["result"]["task_id"] == "task-xyz"
    assert captured["command"] == "editor.launch"
    assert captured["payload"]["extra_args"] == ["-vulkan", "-ResX=1280", "-ResY=720"]


def test_editor_launch_accepts_command_level_project(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    captured = {}

    def fake_submit_task(command, payload):
        captured["command"] = command
        captured["payload"] = payload
        return {"task_id": "task-xyz", "status": "submitted"}

    with patch("cli_anything.unreal.commands.editor.submit_task", side_effect=fake_submit_task), \
         patch("cli_anything.unreal.commands.editor._check_already_running", return_value=None):
        result = runner.invoke(cli, [
            "--output", "json",
            "editor", "launch", "--project", mini_project, "--no-wait",
        ])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert captured["command"] == "editor.launch"
    assert captured["payload"]["project_path"] == mini_project


def test_editor_launch_help_lists_command_level_project():
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    result = CliRunner().invoke(cli, ["editor", "launch", "--help"])

    assert result.exit_code == 0, result.output
    assert "--project" in result.output


def test_editor_launch_no_extra_args_yields_empty_list(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    captured = {}

    def fake_submit_task(command, payload):
        captured["payload"] = payload
        return {"task_id": "task-xyz", "status": "submitted"}

    with patch("cli_anything.unreal.commands.editor.submit_task", side_effect=fake_submit_task), \
         patch("cli_anything.unreal.commands.editor._check_already_running", return_value=None):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "launch", "--no-wait",
        ])

    assert result.exit_code == 0, result.output
    assert captured["payload"]["extra_args"] == []


# ── plugin-upgrade relaunch uses _build_launch_cmd ──────────────────


def test_editor_launch_treats_matching_project_process_offline_when_api_owner_differs(mini_project):
    """A live API on another PID must not make a same-project offline editor ALREADY_RUNNING."""
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    captured = {}

    def fake_submit_task(command, payload):
        captured["command"] = command
        captured["payload"] = payload
        return {"task_id": "task-xyz", "status": "submitted"}

    other_project = str(Path(mini_project).with_name("Other.uproject"))
    running = [
        {"pid": 60504, "project": mini_project},
        {"pid": 99999, "project": other_project},
    ]

    with patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=running), \
         patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI.is_alive", return_value=True), \
         patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", return_value=99999), \
         patch("cli_anything.unreal.utils.ue_backend.detect_ue_dialogs", return_value=[]), \
         patch("cli_anything.unreal.utils.ue_backend._kill_process_tree", return_value=True) as kill_proc, \
         patch("cli_anything.unreal.commands.editor.submit_task", side_effect=fake_submit_task):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "launch", "--no-wait",
        ])

    assert result.exit_code == 0, result.output
    kill_proc.assert_called_once_with(60504)
    assert captured["command"] == "editor.launch"
    assert captured["payload"]["project_path"] == mini_project


def test_editor_launch_does_not_kill_process_owned_by_active_launch_task(mini_project, tmp_path, monkeypatch):
    from click.testing import CliRunner
    from cli_anything.unreal.core.tasks import create_task, save_task
    from cli_anything.unreal.unreal_cli import cli

    monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
    task = create_task("editor.launch", {"project_path": mini_project, "port": 30011})
    task["status"] = "running"
    task["pid"] = 16044
    save_task(task)

    runner = CliRunner()
    with patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 16044, "project": mini_project},
         ]), \
         patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI.is_alive", return_value=False), \
         patch("cli_anything.unreal.utils.ue_backend.detect_ue_dialogs", return_value=[]), \
         patch("cli_anything.unreal.utils.ue_backend._kill_process_tree") as kill_proc, \
         patch("cli_anything.unreal.commands.editor.submit_task") as submit_task:
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "launch", "--no-wait",
        ])

    assert result.exit_code == 3
    data = json.loads(result.output)
    assert data["status"] == "error"
    assert data["code"] == "EDITOR_STARTING"
    assert data["details"]["task_id"] == task["task_id"]
    kill_proc.assert_not_called()
    submit_task.assert_not_called()


def test_editor_launch_without_timeout_uses_bounded_foreground_wait(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    captured = {}

    def fake_submit_task(command, payload):
        captured["payload"] = payload
        return {"task_id": "launch-task", "command": command, "payload": payload}

    def fake_wait_for_task(task_id, timeout):
        captured["wait_timeout"] = timeout
        return {
            "task_id": task_id,
            "command": "editor.launch",
            "status": "completed",
            "result": {"status": "online", "port": 30010},
        }

    with patch("cli_anything.unreal.commands.editor.submit_task", side_effect=fake_submit_task), \
         patch("cli_anything.unreal.commands.editor.wait_for_task", side_effect=fake_wait_for_task), \
         patch("cli_anything.unreal.commands.editor._check_already_running", return_value=None):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "launch",
        ])

    assert result.exit_code == 0, result.output
    assert captured["payload"]["timeout"] is not None
    assert captured["wait_timeout"] is not None
    assert captured["wait_timeout"] <= 120


def test_editor_launch_returns_online_when_task_wait_times_out_but_editor_is_online(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    running_task = {
        "task_id": "launch-task",
        "command": "editor.launch",
        "status": "running",
        "pid": 68348,
        "suggested_poll_interval_seconds": 5,
    }

    with patch("cli_anything.unreal.commands.editor.submit_task", return_value={
            "task_id": "launch-task",
            "command": "editor.launch",
        }), \
         patch("cli_anything.unreal.commands.editor.wait_for_task", return_value=None), \
         patch("cli_anything.unreal.commands.editor.load_task", return_value=running_task), \
         patch("cli_anything.unreal.commands.editor._check_already_running", return_value=None), \
         patch("cli_anything.unreal.commands.editor._scan_editor_status_instances", return_value=[{
             "status": "online",
             "pid": 68348,
             "port": 30011,
             "project_path": mini_project,
             "bridge_version": "1.17",
             "bundled_version": "1.17",
             "plugin_match": True,
         }]):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "launch", "--timeout", "120",
        ])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["result"]["status"] == "online"
    assert data["result"]["pid"] == 68348
    assert data["result"]["port"] == 30011
    assert data["result"]["task_id"] == "launch-task"
    assert data["result"]["launch_task_status"] == "running"


def test_plugin_upgrade_relaunch_includes_nosplash_unattended(mini_project):
    """Verify plugin-upgrade relaunch passes -nosplash -unattended (regression test)."""
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    mock_proc = MagicMock()
    mock_proc.pid = 9999
    popen_calls = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append(cmd)
        return mock_proc

    mock_api = MagicMock()
    # 1st call: editor_was_running check -> True
    # 2nd call: post-close wait -> False
    # 3rd call: wait-for-api loop -> True (editor back online)
    mock_api.is_alive.side_effect = [True, False, True]

    with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI", return_value=mock_api), \
         patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version", return_value="2.0"), \
         patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version", side_effect=["1.0", "2.0"]), \
         patch("cli_anything.unreal.commands.editor._close_editor_for_project", return_value={"status": "closed"}), \
         patch("cli_anything.unreal.core.plugin_bridge.ensure_plugin_deployed", return_value={
             "deployed": True, "action": "updated", "version": "2.0", "plugin_dir": "/tmp/plugin"
         }), \
         patch("cli_anything.unreal.core.build.compile_project", return_value={"status": "ok"}), \
         patch("cli_anything.unreal.utils.ue_backend.find_editor_exe", return_value="F:/Engine/Binaries/Win64/UnrealEditor.exe"), \
         patch("cli_anything.unreal.commands.editor.sp.Popen", side_effect=fake_popen), \
         patch("cli_anything.unreal.commands.editor.time.sleep"):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "plugin-upgrade",
        ])

    assert result.exit_code == 0
    # The relaunch Popen call must include -nosplash and -unattended
    relaunch_calls = [cmd for cmd in popen_calls if cmd and str(cmd[0]).endswith("UnrealEditor.exe")]
    assert len(relaunch_calls) == 1
    relaunch_cmd = relaunch_calls[0]
    assert "-nosplash" in relaunch_cmd
    assert "-unattended" in relaunch_cmd


def test_plugin_upgrade_uses_editor_close_helper(mini_project):
    """plugin-upgrade should reuse editor close logic instead of console 'exit'."""
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    mock_api = MagicMock()
    mock_api.is_alive.side_effect = [True, False, True]

    with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI", return_value=mock_api), \
         patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version", return_value="2.0"), \
         patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version", side_effect=["1.0", "2.0"]), \
         patch("cli_anything.unreal.commands.editor._close_editor_for_project", return_value={"status": "closed"}) as mock_close, \
         patch("cli_anything.unreal.core.plugin_bridge.ensure_plugin_deployed", return_value={
             "deployed": True, "action": "updated", "version": "2.0", "plugin_dir": "/tmp/plugin"
         }), \
         patch("cli_anything.unreal.core.build.compile_project", return_value={"status": "ok"}), \
         patch("cli_anything.unreal.utils.ue_backend.find_editor_exe", return_value="F:/Engine/Binaries/Win64/UnrealEditor.exe"), \
         patch("cli_anything.unreal.commands.editor.sp.Popen", return_value=MagicMock(pid=9999)), \
         patch("cli_anything.unreal.commands.editor.time.sleep"):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "plugin-upgrade",
        ])

    assert result.exit_code == 0
    mock_close.assert_called_once()
    mock_api.exec_console.assert_not_called()


# ── auto-compile on plugin load failure / skip when OK ────────────────


def test_plugin_upgrade_kills_residual_project_editor_before_compile(mini_project):
    """plugin-upgrade must not compile while same-project editor process still locks DLLs."""
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    mock_api = MagicMock()
    mock_api.is_alive.side_effect = [True, False, True]

    with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI", return_value=mock_api), \
         patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version", return_value="2.0"), \
         patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version", side_effect=["1.0", "2.0"]), \
         patch("cli_anything.unreal.commands.editor._close_editor_for_project", return_value={"status": "closed"}), \
         patch("cli_anything.unreal.commands.editor._wait_for_project_editor_exit", return_value={
             "status": "closed",
             "method": "process_tree_kill",
             "closed_processes": [{"pid": 1234, "project": mini_project}],
         }) as mock_drain, \
         patch("cli_anything.unreal.core.plugin_bridge.ensure_plugin_deployed", return_value={
             "deployed": True, "action": "updated", "version": "2.0", "plugin_dir": "/tmp/plugin"
         }), \
         patch("cli_anything.unreal.core.build.compile_project", return_value={"status": "ok"}) as mock_compile, \
         patch("cli_anything.unreal.utils.ue_backend.find_editor_exe", return_value="F:/Engine/Binaries/Win64/UnrealEditor.exe"), \
         patch("cli_anything.unreal.commands.editor.sp.Popen", return_value=MagicMock(pid=9999)), \
         patch("cli_anything.unreal.commands.editor.time.sleep"):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "plugin-upgrade",
        ])

    assert result.exit_code == 0, result.output
    mock_drain.assert_called_once_with(mini_project, 30010, timeout=60)
    mock_compile.assert_called_once()


def test_plugin_upgrade_reports_locked_dll_from_compile_log(mini_project, tmp_path):
    """LNK1104 locked DLL failures should identify the locked file and recovery."""
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    log_file = tmp_path / "cli_compile.log"
    locked = r"F:\RXGame\Plugins\Tencent\UnLua\Binaries\Win64\UnrealEditor-UnLua.dll"
    log_file.write_text(f"LINK : fatal error LNK1104: cannot open file '{locked}'\n", encoding="utf-8")

    runner = CliRunner()
    mock_api = MagicMock()
    mock_api.is_alive.return_value = False

    with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI", return_value=mock_api), \
         patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version", return_value="2.0"), \
         patch("cli_anything.unreal.core.plugin_bridge.ensure_plugin_deployed", return_value={
             "deployed": True, "action": "updated", "version": "2.0", "plugin_dir": "/tmp/plugin"
         }), \
         patch("cli_anything.unreal.core.build.compile_project", return_value={
             "status": "error",
             "error": "Compile failed (exit 6). See log_file for details.",
             "log_file": str(log_file),
             "returncode": 6,
         }):
        result = runner.invoke(cli, [
            "--output", "json", "--project", mini_project,
            "editor", "plugin-upgrade",
        ])

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["code"] == "COMPILE_FAILED"
    assert data["details"]["locked_file"] == locked
    assert data["details"]["lock_error"] == "LNK1104"
    assert "UnrealEditor" in data["suggestion"]


def test_run_editor_launch_task_auto_compiles_on_plugin_load_failure(tmp_path):
    """_run_editor_launch_task compiles and retries when plugin fails to load."""
    from cli_anything.unreal.core.tasks import _run_editor_launch_task, create_task

    mock_proc = MagicMock()
    mock_proc.pid = 4242

    project_dir = tmp_path / "TestProj"
    project_dir.mkdir()
    uproject = project_dir / "TestProj.uproject"
    uproject.write_text('{"FileVersion": 3, "EngineAssociation": "5.7"}', encoding="utf-8")

    task = create_task("editor.launch", {
        "project_path": str(uproject),
        "port": 30010,
    })

    with patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
        "ready": True,
        "engine": {"errors": [], "warnings": []},
        "project": {"errors": [], "warnings": []},
    }), \
         patch("cli_anything.unreal.utils.ue_backend.find_engine_root", return_value="F:/MockEngine"), \
         patch("cli_anything.unreal.utils.ue_backend.find_editor_exe", return_value="F:/MockEngine/Binaries/UnrealEditor.exe"), \
         patch("cli_anything.unreal.commands.editor._check_already_running", return_value=None), \
         patch("cli_anything.unreal.commands.editor._check_port_in_use", return_value=None), \
         patch("cli_anything.unreal.commands.editor._deploy_bridge", return_value={
             "deployed": True, "action": "already_up_to_date", "version": "1.13"
         }), \
         patch("cli_anything.unreal.utils.ue_backend._ensure_plugin_enabled", return_value=True), \
         patch("cli_anything.unreal.core.plugin_bridge.get_plugin_binary_status", return_value={
             "ready": True,
             "reason": "ok",
             "message": "Bridge plugin binary is ready.",
         }), \
         patch("cli_anything.unreal.core.build.compile_project", return_value={"status": "ok"}) as mock_compile, \
         patch("cli_anything.unreal.commands.editor.sp.Popen", return_value=mock_proc), \
         patch("cli_anything.unreal.commands.editor._wait_for_api", side_effect=[
             {"status": "error_dialog", "error": "Plugin 'CliAnythingBridge' failed to load because module 'CliAnythingBridge' could not be found."},
             {"status": "online"},
         ]):
        result = _run_editor_launch_task(task, estimated_total_seconds=120)

    mock_compile.assert_called_once()
    assert result["status"] == "completed"
    assert result["result"].get("recompiled") is True


def test_run_editor_launch_task_precompiles_when_bridge_binary_missing(tmp_path):
    """_run_editor_launch_task should compile the bridge before launching when its DLL is absent."""
    from cli_anything.unreal.core.tasks import _run_editor_launch_task, create_task

    mock_proc = MagicMock()
    mock_proc.pid = 4242

    project_dir = tmp_path / "TestProj"
    project_dir.mkdir()
    uproject = project_dir / "TestProj.uproject"
    uproject.write_text('{"FileVersion": 3, "EngineAssociation": "5.7"}', encoding="utf-8")

    task = create_task("editor.launch", {
        "project_path": str(uproject),
        "port": 30010,
    })

    with patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
        "ready": True,
        "engine": {"errors": [], "warnings": []},
        "project": {"errors": [], "warnings": []},
    }), \
         patch("cli_anything.unreal.utils.ue_backend.find_engine_root", return_value="F:/MockEngine"), \
         patch("cli_anything.unreal.utils.ue_backend.find_editor_exe", return_value="F:/MockEngine/Binaries/UnrealEditor.exe"), \
         patch("cli_anything.unreal.commands.editor._check_already_running", return_value=None), \
         patch("cli_anything.unreal.commands.editor._check_port_in_use", return_value=None), \
         patch("cli_anything.unreal.commands.editor._deploy_bridge", return_value={
             "deployed": True, "action": "already_up_to_date"
         }), \
         patch("cli_anything.unreal.utils.ue_backend._ensure_plugin_enabled", return_value=False), \
         patch("cli_anything.unreal.core.plugin_bridge.get_plugin_binary_status", side_effect=[
             {
                 "ready": False,
                 "reason": "missing_binary",
                 "message": "Bridge plugin binary is missing.",
             },
             {
                 "ready": True,
                 "reason": "ok",
                 "message": "Bridge plugin binary is ready.",
             },
         ], create=True), \
         patch("cli_anything.unreal.core.build.compile_project", return_value={"status": "ok"}) as mock_compile, \
         patch("cli_anything.unreal.commands.editor.sp.Popen", return_value=mock_proc), \
         patch("cli_anything.unreal.commands.editor._wait_for_api", return_value={"status": "online"}):
        result = _run_editor_launch_task(task, estimated_total_seconds=120)

    mock_compile.assert_called_once()
    assert result["status"] == "completed"
    assert result["result"].get("precompiled_bridge") is True
    assert result["result"].get("compile_reason") == "Bridge plugin binary is missing."


def test_run_editor_launch_task_skips_compile_when_plugin_loads_ok(tmp_path):
    """_run_editor_launch_task skips compilation when plugin loads successfully."""
    from cli_anything.unreal.core.tasks import _run_editor_launch_task, create_task

    mock_proc = MagicMock()
    mock_proc.pid = 4242

    project_dir = tmp_path / "TestProj"
    project_dir.mkdir()
    uproject = project_dir / "TestProj.uproject"
    uproject.write_text('{"FileVersion": 3, "EngineAssociation": "5.7"}', encoding="utf-8")

    task = create_task("editor.launch", {
        "project_path": str(uproject),
        "port": 30010,
    })

    with patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
        "ready": True,
        "engine": {"errors": [], "warnings": []},
        "project": {"errors": [], "warnings": []},
    }), \
         patch("cli_anything.unreal.utils.ue_backend.find_engine_root", return_value="F:/MockEngine"), \
         patch("cli_anything.unreal.utils.ue_backend.find_editor_exe", return_value="F:/MockEngine/Binaries/UnrealEditor.exe"), \
         patch("cli_anything.unreal.commands.editor._check_already_running", return_value=None), \
         patch("cli_anything.unreal.commands.editor._check_port_in_use", return_value=None), \
         patch("cli_anything.unreal.commands.editor._deploy_bridge", return_value={
             "deployed": True, "action": "already_up_to_date"
         }), \
         patch("cli_anything.unreal.utils.ue_backend._ensure_plugin_enabled", return_value=False), \
         patch("cli_anything.unreal.core.plugin_bridge.get_plugin_binary_status", return_value={
             "ready": True,
             "reason": "ok",
             "message": "Bridge plugin binary is ready.",
         }), \
         patch("cli_anything.unreal.core.build.compile_project") as mock_compile, \
         patch("cli_anything.unreal.commands.editor.sp.Popen", return_value=mock_proc), \
         patch("cli_anything.unreal.commands.editor._wait_for_api", return_value={"status": "online"}):
        result = _run_editor_launch_task(task, estimated_total_seconds=120)

    mock_compile.assert_not_called()
    assert result["status"] == "completed"


def test_run_editor_launch_task_skips_bridge_for_ue4(tmp_path):
    """UE4 launch should not deploy or enable the UE5 bridge plugin."""
    from cli_anything.unreal.core.tasks import _run_editor_launch_task, create_task

    mock_proc = MagicMock()
    mock_proc.pid = 4242

    project_dir = tmp_path / "UE4Proj"
    project_dir.mkdir()
    uproject = project_dir / "UE4Proj.uproject"
    uproject.write_text('{"FileVersion": 3, "EngineAssociation": "4.26"}', encoding="utf-8")

    task = create_task("editor.launch", {
        "project_path": str(uproject),
        "port": 30010,
    })

    with patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
        "ready": True,
        "engine": {"errors": [], "warnings": [], "details": {"editor_binary_prefix": "UE4Editor"}},
        "project": {"errors": [], "warnings": []},
    }), \
         patch("cli_anything.unreal.utils.ue_backend.find_engine_root", return_value="F:/MockUE4"), \
         patch("cli_anything.unreal.utils.ue_backend.find_editor_exe", return_value="F:/MockUE4/Binaries/UE4Editor.exe"), \
         patch("cli_anything.unreal.commands.editor._check_already_running", return_value=None), \
         patch("cli_anything.unreal.commands.editor._check_port_in_use", return_value=None), \
         patch("cli_anything.unreal.commands.editor._deploy_bridge") as mock_deploy, \
         patch("cli_anything.unreal.utils.ue_backend._ensure_plugin_enabled") as mock_enable, \
         patch("cli_anything.unreal.core.plugin_bridge.ensure_project_bridge_disabled_by_default", return_value={
             "status": "ok",
             "changed": True,
         }), \
         patch("cli_anything.unreal.core.build.compile_project") as mock_compile, \
         patch("cli_anything.unreal.commands.editor.sp.Popen", return_value=mock_proc), \
         patch("cli_anything.unreal.commands.editor._wait_for_api", return_value={"status": "online"}):
        result = _run_editor_launch_task(task, estimated_total_seconds=120)

    mock_deploy.assert_not_called()
    mock_enable.assert_not_called()
    mock_compile.assert_not_called()
    assert result["status"] == "completed"
    assert result["result"]["bridge_deploy"]["action"] == "skipped_ue4"


def test_run_editor_launch_task_fails_on_compile_error(tmp_path):
    """_run_editor_launch_task fails with COMPILE_FAILED when auto-compile after plugin load failure fails."""
    from cli_anything.unreal.core.tasks import _run_editor_launch_task, create_task

    mock_proc = MagicMock()
    mock_proc.pid = 4242

    project_dir = tmp_path / "TestProj"
    project_dir.mkdir()
    uproject = project_dir / "TestProj.uproject"
    uproject.write_text('{"FileVersion": 3, "EngineAssociation": "5.7"}', encoding="utf-8")

    task = create_task("editor.launch", {
        "project_path": str(uproject),
        "port": 30010,
    })

    with patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
        "ready": True,
        "engine": {"errors": [], "warnings": []},
        "project": {"errors": [], "warnings": []},
    }), \
         patch("cli_anything.unreal.utils.ue_backend.find_engine_root", return_value="F:/MockEngine"), \
         patch("cli_anything.unreal.utils.ue_backend.find_editor_exe", return_value="F:/MockEngine/Binaries/UnrealEditor.exe"), \
         patch("cli_anything.unreal.commands.editor._check_already_running", return_value=None), \
         patch("cli_anything.unreal.commands.editor._check_port_in_use", return_value=None), \
         patch("cli_anything.unreal.commands.editor._deploy_bridge", return_value={
             "deployed": True, "action": "already_up_to_date"
         }), \
         patch("cli_anything.unreal.utils.ue_backend._ensure_plugin_enabled", return_value=True), \
         patch("cli_anything.unreal.core.plugin_bridge.get_plugin_binary_status", return_value={
             "ready": True,
             "reason": "ok",
             "message": "Bridge plugin binary is ready.",
         }), \
         patch("cli_anything.unreal.core.build.compile_project", return_value={
             "status": "error", "error": "Build failed", "returncode": 1
         }) as mock_compile, \
         patch("cli_anything.unreal.commands.editor.sp.Popen", return_value=mock_proc) as mock_popen, \
         patch("cli_anything.unreal.commands.editor._wait_for_api", return_value={
             "status": "error_dialog", "error": "Plugin 'CliAnythingBridge' failed to load because module 'CliAnythingBridge' could not be found."
         }) as mock_wait:
        result = _run_editor_launch_task(task, estimated_total_seconds=120)

    mock_popen.assert_called_once()
    mock_wait.assert_called_once()
    mock_compile.assert_called_once()
    assert result["status"] == "failed"
    assert result["error"]["code"] == "COMPILE_FAILED"


def test_wait_for_api_timeout_reports_listening_port_with_http_server_log_hints(tmp_path):
    from cli_anything.unreal.commands.editor import _wait_for_api

    log_dir = tmp_path / "Saved" / "Logs"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "RXGame.log"
    log_file.write_text(
        "\n".join(
            [
                "LogRemoteControl: Display: Remote Control HTTP server started on port 30010",
                "LogRemoteControl: Display: WebSocket server started on port 30020",
                "LogHttpServerModule: Stopping all listeners...",
                "LogHttpServerModule: All listeners stopped",
                "LogFalconTunnel: StartHttpServer on port 14632",
                "LogHttpServerModule: Starting all listeners...",
                "LogHttpServerModule: All listeners started",
                "LogFalconTunnel: OnServiceConnected: pid:90524, err:connect failed",
            ]
        ),
        encoding="utf-8",
    )
    proc = MagicMock()
    proc.poll.return_value = None
    state = MagicMock()
    state.json_output = True

    with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI.is_alive", return_value=False), \
         patch("cli_anything.unreal.commands.editor._tcp_port_accepts_connection", return_value=True), \
         patch("cli_anything.unreal.commands.editor.time.time", side_effect=[100.0, 101.0, 101.0]), \
         patch("cli_anything.unreal.commands.editor.time.sleep"):
        result = _wait_for_api(proc, 30010, 1, log_file, state)

    assert result["status"] == "timeout"
    assert result["failure_kind"] == "api_route_unhealthy"
    assert result["port_listening"] is True
    assert result["api_route_healthy"] is False
    assert result["likely_cause"] == "http_server_restarted_by_project_plugin"
    assert "FalconTunnel" in result["log_hints"][0]
    assert "port is listening" in result["suggestion"]


def test_summarize_startup_precheck_includes_bridge_plugin_issues():
    """_summarize_startup_precheck includes bridge_plugin issues as warnings."""
    from cli_anything.unreal.commands.editor import _summarize_startup_precheck

    check = {
        "ready": True,
        "engine": {"errors": [], "warnings": []},
        "project": {"errors": [], "warnings": []},
        "bridge_plugin": {
            "ready": False,
            "issues": ["CliAnythingBridge plugin not enabled in .uproject"],
            "auto_fixable": True,
        },
    }
    result = _summarize_startup_precheck(check)
    assert "Fixed: CliAnythingBridge plugin not enabled in .uproject" in result["warnings"]

def test_remove_tree_with_retries_handles_locked_dll():
    from pathlib import Path
    from unittest.mock import patch
    from cli_anything.unreal.commands.editor import _remove_tree_with_retries

    with patch("pathlib.Path.exists", return_value=True), \
         patch("shutil.rmtree", side_effect=[PermissionError("locked"), None]) as mock_rmtree, \
         patch("time.sleep") as mock_sleep:
        _remove_tree_with_retries(Path("F:/Test574/Plugins/CliAnythingBridge"), attempts=2, delay=0.01)

    assert mock_rmtree.call_count == 2
    mock_sleep.assert_called_once_with(0.01)
