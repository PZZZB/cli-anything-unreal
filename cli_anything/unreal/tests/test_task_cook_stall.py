"""Synthetic coverage for running cook/package task diagnostics."""

import json

from click.testing import CliRunner

from cli_anything.unreal.core.tasks import create_task, save_task
from cli_anything.unreal.unreal_cli import cli


BLOCKED_PACKAGE = (
    "/Game/RxArtResource/Assets/Animations/Common/TP/PoseData/"
    "MotionMatching/Database/Dense/PSD_TP_MM_Dense_StandRun"
)


def _running_task(tmp_path, monkeypatch, log_text, *, command="build.package"):
    task_dir = tmp_path / "tasks"
    log_file = tmp_path / "cook.log"
    log_file.write_text(log_text, encoding="utf-8")
    monkeypatch.setenv("UE_CLI_TASK_DIR", str(task_dir))
    monkeypatch.delenv("UE_CLI_COOK_STALL_THRESHOLD_SECONDS", raising=False)
    task = create_task(command, {
        "project_path": str(tmp_path / "Test.uproject"),
        "log_file": str(log_file),
    })
    task["status"] = "running"
    return save_task(task), log_file


def _task_status(task_id):
    result = CliRunner().invoke(
        cli,
        ["--output", "json", "task", "status", task_id],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_task_status_surfaces_stalled_cook_package_and_object(tmp_path, monkeypatch):
    task, log_file = _running_task(
        tmp_path,
        monkeypatch,
        "\n".join([
            "LogCook: Warning: Cooker has been blocked from saving the current packages for 2281 seconds.",
            "LogCook: Warning: 1 packages in the savequeue:",
            f"LogCook: Warning:   {BLOCKED_PACKAGE}",
            "LogCook: Warning: 1 objects that have not yet returned true from IsCachedCookedPlatformDataLoaded:",
            f"LogCook: Warning:   PoseSearchDatabase {BLOCKED_PACKAGE}.{BLOCKED_PACKAGE.rsplit('/', 1)[-1]}",
            "LogCook: Display: Cooked packages 2897 Packages Remain 1 Total 2898",
            "LogCook: Display: CookWorkerHeartbeat: 109",
        ]),
    )

    data = _task_status(task["task_id"])

    assert data["status"] == "running"
    assert data["stalled"] is True
    assert data["log_file"] == str(log_file)
    diagnostic = data["diagnostic"]
    assert diagnostic["code"] == "COOK_SAVE_STALLED"
    assert diagnostic["blocked_seconds"] == 2281
    assert diagnostic["threshold_seconds"] == 600
    assert diagnostic["packages"] == [BLOCKED_PACKAGE]
    assert diagnostic["objects"] == [
        f"PoseSearchDatabase {BLOCKED_PACKAGE}.{BLOCKED_PACKAGE.rsplit('/', 1)[-1]}"
    ]
    assert diagnostic["cancellation_under_user_control"] is True
    assert diagnostic["cancellation_command"] == f"ue-cli task cancel {task['task_id']}"
    assert "retry" in diagnostic["retry_guidance"].casefold()


def test_task_status_reports_blockage_below_configured_threshold(tmp_path, monkeypatch):
    task, _ = _running_task(
        tmp_path,
        monkeypatch,
        "Cooker has been blocked from saving current packages for 42.5 seconds.\n",
        command="build.cook",
    )
    monkeypatch.setenv("UE_CLI_COOK_STALL_THRESHOLD_SECONDS", "60")

    data = _task_status(task["task_id"])

    assert data["stalled"] is False
    assert data["diagnostic"]["code"] == "COOK_SAVE_BLOCKED"
    assert data["diagnostic"]["blocked_seconds"] == 42.5
    assert data["diagnostic"]["threshold_seconds"] == 60


def test_task_status_ignores_unrelated_or_terminal_task_logs(tmp_path, monkeypatch):
    task, _ = _running_task(
        tmp_path,
        monkeypatch,
        "Ordinary cook progress without a blocked-save warning.\n",
    )
    running = _task_status(task["task_id"])
    assert "diagnostic" not in running
    assert "stalled" not in running

    task["status"] = "completed"
    save_task(task)
    completed = _task_status(task["task_id"])
    assert "diagnostic" not in completed
    assert "stalled" not in completed
