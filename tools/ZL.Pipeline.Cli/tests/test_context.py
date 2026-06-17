"""单元测试: context 模块"""

from __future__ import annotations

from pathlib import Path

import pytest

from zl_pipeline.context import PipelineContext


class TestPipelineContext:
    @pytest.fixture
    def config_mock(self, tmp_path: Path) -> object:
        """创建一个真实的 mock 对象，支持 setattr/getattr"""
        class MockConfig:
            projects: list = []
            dry_run: bool = False
            nuget_source: str = "https://api.nuget.org/v3/index.json"
            publish_timeout: int = 120
            consumers: list = []
        return MockConfig()

    @pytest.fixture
    def base_ctx(self, tmp_path: Path, config_mock: object) -> PipelineContext:
        return PipelineContext(
            version="1.0.0",
            config=config_mock,
            proj_dir=tmp_path,
            artifacts_dir=tmp_path / "artifacts" / "1.0.0",
            state_dir=tmp_path / "artifacts" / ".pipeline-state" / "1.0.0",
        )

    def test_should_push_not_dry_run(self, base_ctx: PipelineContext) -> None:
        assert base_ctx.should_push is True

    def test_should_push_is_dry_run(self, tmp_path: Path) -> None:
        class SimpleConfig:
            projects: list = []
            nuget_source: str = "https://api.nuget.org/v3/index.json"
            publish_timeout: int = 120
            consumers: list = []
        ctx = PipelineContext(
            version="1.0.0", config=SimpleConfig(), proj_dir=tmp_path,
            artifacts_dir=tmp_path / "artifacts" / "1.0.0",
            state_dir=tmp_path / "artifacts" / ".pipeline-state" / "1.0.0",
            dry_run=True,
        )
        assert ctx.should_push is False

    def test_obfuscated_dir_is_project_scoped(self, tmp_path: Path) -> None:
        class ScopedConfig:
            projects: list = []
            dry_run: bool = False
            nuget_source: str = "https://api.nuget.org/v3/index.json"
            publish_timeout: int = 120
            consumers: list = []
        ctx = PipelineContext(
            version="1.0.0", config=ScopedConfig(), proj_dir=tmp_path,
            artifacts_dir=tmp_path / "artifacts" / "1.0.0",
            state_dir=tmp_path / "artifacts" / ".pipeline-state" / "1.0.0",
        )
        assert "artifacts" in str(ctx.obfuscated_dir)
        assert "obfuscated" in str(ctx.obfuscated_dir)
        assert str(ctx.obfuscated_dir).startswith(str(tmp_path))

    def test_frozen_dataclass(self, base_ctx: PipelineContext) -> None:
        with pytest.raises(Exception):
            base_ctx.version = "2.0.0"

    def test_only_projects_filter(self, tmp_path: Path) -> None:
        class FilterConfig:
            projects: list = []
            dry_run: bool = False
            nuget_source: str = "https://api.nuget.org/v3/index.json"
            publish_timeout: int = 120
            consumers: list = []
        ctx = PipelineContext(
            version="1.0.0", config=FilterConfig(), proj_dir=tmp_path,
            artifacts_dir=tmp_path / "artifacts" / "1.0.0",
            state_dir=tmp_path / "artifacts" / ".pipeline-state" / "1.0.0",
            only_projects=frozenset(["OnlyThis"]),
        )
        assert ctx.only_projects == frozenset(["OnlyThis"])
