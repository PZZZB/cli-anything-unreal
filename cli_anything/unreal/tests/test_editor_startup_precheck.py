import json
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
    data = json.loads(result.output)
    assert data["status"] == "success"
    instance = data["result"][0]
    assert instance["status"] == "offline"
    assert instance["pid"] == 5678
    assert instance["port"] is None
    assert instance["project_path"] == other_project
    assert "editor launch" in instance["suggestion"]


def test_editor_status_lists_online_port_owner_even_when_other_project(mini_project):
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
    assert data["result"] == [
        {"status": "online", "pid": 5678, "port": 30020, "project_path": other_project},
    ]


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
    assert online == {"status": "online", "pid": 1234, "port": 30020, "project_path": mini_project}
    assert offline["status"] == "offline"
    assert offline["pid"] == 5678
    assert offline["port"] == 30030
    assert offline["project_path"] == other_project
    assert "Remote Control API is not reachable" in offline["message"]
    assert "editor launch" in offline["suggestion"]
    assert offline["next_command"] == f'ue-cli --project "{other_project}" editor launch'


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
         patch("cli_anything.unreal.utils.ue_backend.read_rc_port", return_value=30023):
        result = runner.invoke(cli, [
            "--output", "json",
            "editor", "status",
        ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["result"] == [
        {"status": "online", "pid": 1234, "port": 30023, "project_path": mini_project},
    ]
    assert [call.kwargs["port_range"] for call in scan_ports.call_args_list] == [
        (30010, 30020),
        (30023, 30023),
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
         patch("cli_anything.unreal.utils.ue_backend._kill_process_tree", return_value=True) as kill_process:
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
    mock_api.is_alive.side_effect = [True, True]

    with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI", return_value=mock_api), \
         patch("cli_anything.unreal.commands.editor.time.time", side_effect=[0, 0, 31]), \
         patch("cli_anything.unreal.commands.editor.time.sleep"), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
             {"pid": 1234, "project": mini_project},
         ]), \
         patch("cli_anything.unreal.utils.ue_backend._kill_process_tree", return_value=True) as kill_process:
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
    # 2nd call: wait-for-api loop -> True (editor back online)
    mock_api.is_alive.side_effect = [True, True]

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
    assert len(popen_calls) == 1
    relaunch_cmd = popen_calls[0]
    assert "-nosplash" in relaunch_cmd
    assert "-unattended" in relaunch_cmd


def test_plugin_upgrade_uses_editor_close_helper(mini_project):
    """plugin-upgrade should reuse editor close logic instead of console 'exit'."""
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    mock_api = MagicMock()
    mock_api.is_alive.side_effect = [True, True]

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
             "deployed": True, "action": "fresh_install", "version": "1.13"
         }), \
         patch("cli_anything.unreal.utils.ue_backend._ensure_plugin_enabled", return_value=True), \
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
         patch("cli_anything.unreal.core.build.compile_project") as mock_compile, \
         patch("cli_anything.unreal.commands.editor.sp.Popen", return_value=mock_proc), \
         patch("cli_anything.unreal.commands.editor._wait_for_api", return_value={"status": "online"}):
        result = _run_editor_launch_task(task, estimated_total_seconds=120)

    mock_compile.assert_not_called()
    assert result["status"] == "completed"


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
         patch("cli_anything.unreal.core.build.compile_project", return_value={
             "status": "error", "error": "Build failed", "returncode": 1
         }), \
         patch("cli_anything.unreal.commands.editor.sp.Popen", return_value=mock_proc), \
         patch("cli_anything.unreal.commands.editor._wait_for_api", return_value={
             "status": "error_dialog", "error": "Plugin 'CliAnythingBridge' failed to load because module 'CliAnythingBridge' could not be found."
         }):
        result = _run_editor_launch_task(task, estimated_total_seconds=120)

    assert result["status"] == "failed"
    assert result["error"]["code"] == "COMPILE_FAILED"


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
