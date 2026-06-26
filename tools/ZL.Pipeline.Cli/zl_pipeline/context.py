"""PipelineContext — 不可变运行上下文。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from zl_pipeline.config import PipelineConfig


@dataclass(frozen=True)
class PipelineContext:
    """Pipeline 的不可变运行上下文。

    每次 pipeline 执行创建新实例。步骤之间不共享可变状态，
    所有状态通过 StateStore 持久化。

    Args:
        version:          发布版本号
        config:           从 pipeline.json 解析的配置
        proj_dir:         项目根目录
        artifacts_dir:    产物目录
        state_dir:        状态文件目录（artifacts/.pipeline-state）
        only_projects:    仅处理指定项目（frozenset 保证可哈希）
        from_step:        从指定步骤名开始执行
        skip_build:       跳过编译步骤
        resume:           断点续跑模式
        dry_run:          仅验证，不推送
        verbose:          详细输出
    """

    version: str
    config: PipelineConfig
    proj_dir: Path
    artifacts_dir: Path
    state_dir: Path
    only_projects: frozenset[str] | None = None
    from_step: str | None = None
    skip_build: bool = False
    resume: bool = False
    # --local 模式标志：为 True 时，跳过 obfuscate / replace_nupkg / api_compare
    # 等混淆相关步骤，push 步骤也仅复制到本地 ~/.nuget/local-feed/ 而不会尝试远程推送。
    # 适用于本地开发调试、快速验证版本号一致性等场景。
    local: bool = False
    dry_run: bool = False
    verbose: bool = False

    # 预计算的常用路径
    obfuscated_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "obfuscated_dir", self.proj_dir / "artifacts" / "obfuscated")

    @property
    def publish_dir(self) -> Path:
        """全局发布目录（所有项目的依赖集合并）"""
        return self.proj_dir / "artifacts" / "publish"

    @property
    def should_push(self) -> bool:
        """是否应该执行推送步骤"""
        return not self.dry_run
