"""单元测试: runner 模块"""

from __future__ import annotations

from pathlib import Path

import pytest

from zl_pipeline.context import PipelineContext
from zl_pipeline.runner import STEP_REGISTRY, StepFn, StepResult, StepRunner, register_step


class MockConfig:
    """轻量 mock，替代 MagicMock"""
    projects: list = []
    dry_run: bool = False
    nuget_source: str = "https://api.nuget.org/v3/index.json"
    publish_timeout: int = 120
    consumers: list = []


def _make_ctx(tmp_path: Path, projects: list | None = None, only_projects=None, skip_build=False, **kwargs) -> PipelineContext:
    """创建 PipelineContext 辅助函数"""
    config = MockConfig()
    if projects:
        config.projects = projects
    for k, v in kwargs.items():
        if k != "only_projects":
            setattr(config, k, v)
    return PipelineContext(
        version="1.0.0", config=config, proj_dir=tmp_path,
        artifacts_dir=tmp_path / "artifacts" / "1.0.0",
        state_dir=tmp_path / "artifacts" / ".pipeline-state" / "1.0.0",
        only_projects=only_projects,
        skip_build=skip_build,
    )


class TestStepRunner:
    def test_iter_projects_empty(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path)
        runner = StepRunner(ctx)
        projects = runner._iter_projects()
        assert projects == []

    def test_iter_projects_with_filter(self, tmp_path: Path) -> None:
        class P:
            def __init__(self, name, csproj, obfuscate):
                self.name = name
                self.csproj = csproj
                self.obfuscate = obfuscate
        projects = [
            P("A", "a.csproj", True),
            P("B", "b.csproj", False),
            P("C", "c.csproj", True),
        ]
        ctx = _make_ctx(tmp_path, projects=projects, only_projects=frozenset(["A", "C"]))
        runner = StepRunner(ctx)
        result = runner._iter_projects()
        names = [p["name"] for p in result]
        assert names == ["A", "C"]

    def test_plan(self, tmp_path: Path) -> None:
        class P:
            def __init__(self, name, csproj, obfuscate):
                self.name = name
                self.csproj = csproj
                self.obfuscate = obfuscate
        ctx = _make_ctx(tmp_path, projects=[P("MyLib", "MyLib.csproj", True)])
        runner = StepRunner(ctx)
        plan = runner.plan()
        assert len(plan) == len(STEP_REGISTRY)
        assert plan[0].project == "MyLib"

    def test_execute_step_returns_result(self, tmp_path: Path) -> None:
        @register_step("test_step_xyz")
        def dummy_step(ctx: PipelineContext, project: dict) -> StepResult:
            return StepResult(
                step="test_step", project="TestLib",
                ok=True, duration=0.1, command=["test"], exit_code=0,
            )

        class P:
            def __init__(self, name, csproj, obfuscate):
                self.name = name
                self.csproj = csproj
                self.obfuscate = obfuscate
        ctx = _make_ctx(tmp_path, projects=[P("TestLib", "t.csproj", True)])
        runner = StepRunner(ctx)
        result = runner._execute_step(dummy_step, {"name": "TestLib", "csproj": "t.csproj"}, "test_step_xyz")
        assert result.ok is True
        assert result.step == "test_step"
        # 清理：移除测试步骤
        STEP_REGISTRY[:] = [(n, f) for n, f in STEP_REGISTRY if n != "test_step_xyz"]

    def test_execute_step_handles_exception(self, tmp_path: Path) -> None:
        @register_step("failing_step_xyz")
        def fail_step(ctx: PipelineContext, project: dict) -> StepResult:
            raise RuntimeError("Kaboom")

        class P:
            def __init__(self, name, csproj, obfuscate):
                self.name = name
                self.csproj = csproj
                self.obfuscate = obfuscate
        ctx = _make_ctx(tmp_path, projects=[P("TestLib", "t.csproj", True)])
        runner = StepRunner(ctx)
        result = runner._execute_step(fail_step, {"name": "TestLib", "csproj": "t.csproj"}, "failing_step_xyz")
        assert result.ok is False
        assert "Kaboom" in result.error_detail
        # 清理：移除测试步骤
        STEP_REGISTRY[:] = [(n, f) for n, f in STEP_REGISTRY if n != "failing_step_xyz"]

    def test_skip_build_flag(self, tmp_path: Path) -> None:
        class P:
            def __init__(self, name, csproj, obfuscate):
                self.name = name
                self.csproj = csproj
                self.obfuscate = obfuscate
        ctx = _make_ctx(tmp_path, projects=[P("MyLib", "m.csproj", True)], skip_build=True)
        runner = StepRunner(ctx)
        results = runner.run_all()
        build_results = [r for r in results if r.step == "build"]
        assert len(build_results) == 1
        assert build_results[0].ok is True
        assert "--skip-build" in (build_results[0].error_detail or "")
