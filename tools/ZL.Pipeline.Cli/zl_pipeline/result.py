"""StepResult — 步骤执行结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class StepResult:
    """单个步骤的执行结果。

    不可变数据类，保证步骤间不会意外修改。
    """

    step: str                        # 步骤名
    project: str                     # 项目名称
    ok: bool                         # 是否成功
    duration: float                  # 执行耗时（秒）
    command: list[str] = field(repr=False)  # 执行的命令
    exit_code: int | None = None     # 退出码
    stdout_tail: str = ""            # 最后 200 行 stdout
    stderr_tail: str = ""            # 最后 200 行 stderr
    log_file: Path | None = None     # 日志文件路径
    error_detail: str | None = None  # 错误详情（用于排错提示）

    @property
    def log_path(self) -> Path | None:
        """日志文件路径（别名）"""
        return self.log_file

    @classmethod
    def skipped(cls, step: str, project: str, reason: str = "") -> StepResult:
        """创建一个跳过结果的工厂方法"""
        return cls(
            step=step,
            project=project,
            ok=True,
            duration=0.0,
            command=[],
            exit_code=0,
            error_detail=f"skipped: {reason}",
        )
