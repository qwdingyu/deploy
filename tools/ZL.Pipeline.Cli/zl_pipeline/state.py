"""PipelineState — 状态持久化管理。

所有步骤的执行结果持久化为 JSON 文件，支持断点续传和精确重试。

目录结构:
    artifacts/.pipeline-state/<version>/<project>/<step>.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from zl_pipeline.result import StepResult

Status = Literal["pending", "running", "passed", "failed"]


@dataclass
class StepState:
    """单个步骤的状态记录（可序列化到 JSON）"""

    step: str
    project: str
    status: Status
    exit_code: int | None
    started_at: str          # ISO 8601
    finished_at: str | None  # ISO 8601
    duration_sec: float | None
    command: list[str] | None
    log_file: str | None
    error: str | None

    @classmethod
    def pending(cls, step: str, project: str) -> StepState:
        return cls(
            step=step, project=project, status="pending",
            exit_code=None, started_at=_now_iso(), finished_at=None,
            duration_sec=None, command=None, log_file=None, error=None,
        )

    @classmethod
    def running(cls, step: str, project: str, command: list[str]) -> StepState:
        return cls(
            step=step, project=project, status="running",
            exit_code=None, started_at=_now_iso(), finished_at=None,
            duration_sec=None, command=command, log_file=None, error=None,
        )

    @classmethod
    def passed(cls, step: str, project: str, result: StepResult) -> StepState:
        return cls(
            step=step, project=project, status="passed",
            exit_code=result.exit_code, started_at=_now_iso(),
            finished_at=_now_iso(), duration_sec=result.duration,
            command=result.command, log_file=str(result.log_file) if result.log_file else None,
            error=None,
        )

    @classmethod
    def failed(cls, step: str, project: str, result: StepResult) -> StepState:
        return cls(
            step=step, project=project, status="failed",
            exit_code=result.exit_code, started_at=_now_iso(),
            finished_at=_now_iso(), duration_sec=result.duration,
            command=result.command, log_file=str(result.log_file) if result.log_file else None,
            error=result.error_detail or "",
        )

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "project": self.project,
            "status": self.status,
            "exitCode": self.exit_code,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "durationSec": self.duration_sec,
            "command": self.command,
            "log": self.log_file,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> StepState:
        return cls(
            step=data["step"],
            project=data["project"],
            status=data["status"],
            exit_code=data.get("exitCode"),
            started_at=data["startedAt"],
            finished_at=data.get("finishedAt"),
            duration_sec=data.get("durationSec"),
            command=data.get("command"),
            log_file=data.get("log"),
            error=data.get("error"),
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# StateStore
# ---------------------------------------------------------------------------

class StateStore:
    """状态持久化存储。

    每个步骤的状态保存在独立的 JSON 文件中。
    支持原子写入（先写 tmp 再 rename）。
    """

    def __init__(self, version: str, proj_dir: Path) -> None:
        self._version = version
        self._base = proj_dir / "artifacts" / ".pipeline-state"
        self._base.mkdir(parents=True, exist_ok=True)

    def _path(self, project: str, step: str) -> Path:
        """返回状态文件的路径"""
        dir_path = self._base / self._version / project
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path / f"{step}.json"

    def get(self, project: str, step: str) -> StepState | None:
        """查询步骤状态。不存在返回 None"""
        path = self._path(project, step)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return StepState.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None

    def save(self, state: StepState) -> None:
        """保存步骤状态（原子写入）"""
        path = self._path(state.project, state.step)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.rename(path)

    def mark_running(self, project: str, step: str, command: list[str]) -> None:
        state = StepState.running(step, project, command)
        self.save(state)

    def mark_passed(self, project: str, step: str, result: StepResult) -> None:
        state = StepState.passed(step, project, result)
        self.save(state)

    def mark_failed(self, project: str, step: str, result: StepResult) -> None:
        state = StepState.failed(step, project, result)
        self.save(state)

    def get_skippable(self, project: str, from_step: str | None) -> set[str]:
        """返回可以跳过的步骤集合。

        如果 from_step 为 None，跳过所有 passed 步骤。
        如果 from_step 不为 None，跳过 from_step 之前的所有 passed 步骤。

        Returns:
            已完成的步骤名集合，例如 {"build", "pack"}
        """
        skipped: set[str] = set()
        steps_dir = self._base / self._version / project

        if not steps_dir.exists():
            return skipped

        # 按 STEP_REGISTRY 顺序处理
        from zl_pipeline.runner import STEP_REGISTRY
        step_names = [name for name, _ in STEP_REGISTRY]

        for i, state_file in enumerate(sorted(steps_dir.glob("*.json"))):
            state = self.get(project, state_file.stem)
            if state is None or state.status != "passed":
                break
            if from_step is not None and state_file.stem == from_step:
                break
            # 只计入已知的 pipeline 步骤
            if state_file.stem in step_names:
                skipped.add(state_file.stem)

        return skipped

    def list_project_states(self, project: str) -> dict[str, StepState]:
        """列出某个项目的所有步骤状态"""
        states: dict[str, StepState] = {}
        steps_dir = self._base / self._version / project
        if not steps_dir.exists():
            return states
        for state_file in sorted(steps_dir.glob("*.json")):
            state = self.get(project, state_file.stem)
            if state:
                states[state.step] = state
        return states
