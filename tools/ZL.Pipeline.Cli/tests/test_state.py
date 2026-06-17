"""单元测试: state 模块"""

from __future__ import annotations

from pathlib import Path

import pytest

from zl_pipeline.result import StepResult
from zl_pipeline.state import StateStore, StepState


class TestStepState:
    def test_pending(self) -> None:
        s = StepState.pending("build", "MyLib")
        assert s.status == "pending"
        assert s.step == "build"
        assert s.project == "MyLib"

    def test_running(self) -> None:
        s = StepState.running("build", "MyLib", ["dotnet", "build"])
        assert s.status == "running"
        assert s.started_at is not None
        assert s.command == ["dotnet", "build"]

    def test_passed(self) -> None:
        result = StepResult(
            step="build", project="MyLib", ok=True, duration=5.2,
            command=["dotnet", "build"], exit_code=0, error_detail=None,
        )
        s = StepState.passed("build", "MyLib", result)
        assert s.status == "passed"
        assert s.finished_at is not None
        assert s.duration_sec == 5.2
        assert s.exit_code == 0

    def test_failed(self) -> None:
        result = StepResult(
            step="build", project="MyLib", ok=False, duration=3.1,
            command=["dotnet", "build"], exit_code=1, error_detail="Build failed",
        )
        s = StepState.failed("build", "MyLib", result)
        assert s.status == "failed"
        assert s.error == "Build failed"
        assert s.exit_code == 1


class TestStateStore:
    @pytest.fixture
    def store(self, tmp_path: Path) -> StateStore:
        version = "test-1.0"
        proj_dir = tmp_path / "test_project"
        proj_dir.mkdir()
        return StateStore(version, proj_dir)

    def test_get_empty(self, store: StateStore) -> None:
        result = store.get("MyLib", "build")
        assert result is None

    def test_save_and_get(self, store: StateStore) -> None:
        state = StepState.pending("build", "MyLib")
        store.save(state)
        result = store.get("MyLib", "build")
        assert result is not None
        assert result.step == "build"
        assert result.project == "MyLib"
        assert result.status == "pending"

    def test_mark_running(self, store: StateStore) -> None:
        store.mark_running("MyLib", "build", ["dotnet", "build"])
        result = store.get("MyLib", "build")
        assert result.status == "running"

    def test_mark_passed(self, store: StateStore) -> None:
        result = StepResult(
            step="build", project="MyLib", ok=True, duration=1.5,
            command=["dotnet", "build"], exit_code=0, error_detail=None,
        )
        store.mark_passed("MyLib", "build", result)
        state = store.get("MyLib", "build")
        assert state.status == "passed"
        assert state.exit_code == 0
        assert state.duration_sec == 1.5

    def test_mark_failed(self, store: StateStore) -> None:
        result = StepResult(
            step="build", project="MyLib", ok=False, duration=0.5,
            command=["dotnet", "build"], exit_code=1, error_detail="Error",
        )
        store.mark_failed("MyLib", "build", result)
        state = store.get("MyLib", "build")
        assert state.status == "failed"
        assert state.error == "Error"
        assert state.exit_code == 1

    def test_get_skippable(self, store: StateStore) -> None:
        """mark_passed 后，get_skippable 应返回 {"build"}"""
        result = StepResult(
            step="build", project="MyLib", ok=True, duration=1.0,
            command=["dotnet", "build"], exit_code=0, error_detail=None,
        )
        store.mark_passed("MyLib", "build", result)
        skippable = store.get_skippable("MyLib", None)
        assert "build" in skippable

    def test_get_skippable_with_from_step(self, store: StateStore) -> None:
        """from_step='pack' 时应跳过 pack 之前的步骤"""
        result = StepResult(
            step="build", project="MyLib", ok=True, duration=1.0,
            command=["dotnet", "build"], exit_code=0, error_detail=None,
        )
        store.mark_passed("MyLib", "build", result)
        skippable = store.get_skippable("MyLib", "pack")
        # build 在 pack 之前，应该被跳过
        assert "build" in skippable

    def test_list_project_states(self, store: StateStore) -> None:
        result1 = StepResult(
            step="build", project="MyLib", ok=True, duration=1.0,
            command=["dotnet", "build"], exit_code=0, error_detail=None,
        )
        result2 = StepResult(
            step="pack", project="MyLib", ok=True, duration=2.0,
            command=["dotnet", "pack"], exit_code=0, error_detail=None,
        )
        store.mark_passed("MyLib", "build", result1)
        store.mark_passed("MyLib", "pack", result2)
        states = store.list_project_states("MyLib")
        assert len(states) == 2
        assert all(s in ("build", "pack") for s in states)

    def test_atomic_write(self, store: StateStore, tmp_path: Path) -> None:
        """测试原子写入：tmp 文件会被清理"""
        state = StepState.pending("build", "MyLib")
        store.save(state)
        # 检查 state 文件存在（StateStore 保存路径是 base/version/project/step.json）
        state_file = store._base / store._version / "MyLib" / "build.json"
        assert state_file.exists()
        # 不应有 .tmp 文件残留
        tmp_files = list(store._base.rglob("*.json.tmp"))
        assert len(tmp_files) == 0
