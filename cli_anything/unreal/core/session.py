"""core/session.py — Session management with undo/redo.

Manages the active project context, tracks state changes,
and provides undo/redo functionality.
"""

import copy
import json
import os
import time
from pathlib import Path
from typing import Optional

MAX_UNDO = 50


class Session:
    """Manages a CLI session with project context and undo/redo."""

    def __init__(self):
        self.project_path: str | None = None
        self.project_dir: str | None = None
        self.project_name: str | None = None
        self.engine_root: str | None = None
        self.port: int = 30010

        # State tracking
        self._state: dict = {}
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._modified: bool = False

    def load_project(self, uproject_path: str):
        """Load a project into the session.

        Args:
            uproject_path: Path to the .uproject file.
        """
        path = Path(uproject_path)
        if not path.exists():
            raise FileNotFoundError(f"Project not found: {uproject_path}")

        self.project_path = str(path)
        self.project_dir = str(path.parent)
        self.project_name = path.stem

        # Auto-detect engine
        from cli_anything.unreal.utils.ue_backend import find_engine_root
        self.engine_root = find_engine_root(uproject_path)

        # Load initial state
        self._state = {
            "project_path": self.project_path,
            "project_name": self.project_name,
            "loaded_at": time.time(),
        }
        self._modified = False

    def snapshot(self, description: str = ""):
        """Take a state snapshot before a mutation.

        Args:
            description: Human-readable description of the change.
        """
        entry = {
            "state": copy.deepcopy(self._state),
            "description": description,
            "timestamp": time.time(),
        }
        self._undo_stack.append(entry)
        if len(self._undo_stack) > MAX_UNDO:
            self._undo_stack.pop(0)

        # Clear redo stack on new action
        self._redo_stack.clear()
        self._modified = True

    def undo(self) -> dict | None:
        """Undo the last change.

        Returns:
            The restored state, or None if nothing to undo.
        """
        if not self._undo_stack:
            return None

        # Save current state to redo
        self._redo_stack.append({
            "state": copy.deepcopy(self._state),
            "description": "redo point",
            "timestamp": time.time(),
        })

        entry = self._undo_stack.pop()
        self._state = entry["state"]
        return {
            "description": entry["description"],
            "timestamp": entry["timestamp"],
        }

    def redo(self) -> dict | None:
        """Redo the last undone change.

        Returns:
            The restored state, or None if nothing to redo.
        """
        if not self._redo_stack:
            return None

        # Save current state to undo
        self._undo_stack.append({
            "state": copy.deepcopy(self._state),
            "description": "undo point",
            "timestamp": time.time(),
        })

        entry = self._redo_stack.pop()
        self._state = entry["state"]
        return {
            "description": entry["description"],
            "timestamp": entry["timestamp"],
        }

    def status(self) -> dict:
        """Get current session status.

        Returns:
            Dict with session information.
        """
        return {
            "project": self.project_name,
            "project_path": self.project_path,
            "project_dir": self.project_dir,
            "engine_root": self.engine_root,
            "port": self.port,
            "modified": self._modified,
            "undo_available": len(self._undo_stack),
            "redo_available": len(self._redo_stack),
        }

    def list_history(self) -> list[dict]:
        """List undo history (most recent first).

        Returns:
            List of {"description": str, "timestamp": float}.
        """
        return [
            {
                "description": entry["description"],
                "timestamp": entry["timestamp"],
            }
            for entry in reversed(self._undo_stack)
        ]

    @property
    def is_loaded(self) -> bool:
        """Whether a project is loaded."""
        return self.project_path is not None

    @property
    def modified(self) -> bool:
        """Whether the session has unsaved changes."""
        return self._modified

    def save_session(self, path: str | None = None):
        """Save session state to a JSON file.

        Args:
            path: Output path (defaults to project_dir/.cli-session.json).
        """
        if path is None:
            if not self.project_dir:
                return
            path = str(Path(self.project_dir) / ".cli-session.json")

        data = {
            "project_path": self.project_path,
            "engine_root": self.engine_root,
            "port": self.port,
            "state": self._state,
            "saved_at": time.time(),
        }

        Path(path).write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )
        self._modified = False

    def load_session(self, path: str):
        """Load session state from a JSON file.

        Args:
            path: Path to the session file.
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("project_path"):
            self.project_path = data["project_path"]
            self.project_dir = str(Path(data["project_path"]).parent)
            self.project_name = Path(data["project_path"]).stem
        self.engine_root = data.get("engine_root")
        self.port = data.get("port", 30010)
        self._state = data.get("state", {})
        self._modified = False
