"""步骤 1: build — 编译"""

from __future__ import annotations

from pathlib import Path

from zl_pipeline.config import detect_tfm
from zl_pipeline.context import PipelineContext
from zl_pipeline.dotnet import DotnetAdapter
from zl_pipeline.result import StepResult
from zl_pipeline.runner import register_step


@register_step("build")
def step_build(ctx: PipelineContext, project: dict) -> StepResult:
    """编译项目"""
    # project["csproj"] = "TestLib1/TestLib1.csproj"
    # project_dir = ctx.proj_dir / "TestLib1" (csproj 所在目录)
    project_dir = ctx.proj_dir / Path(project["csproj"]).parent
    csproj_full = ctx.proj_dir / project["csproj"]

    if not csproj_full.exists():
        return StepResult(
            step="build", project=project["name"], ok=False, duration=0,
            command=["dotnet", "build", str(csproj_full)],
            exit_code=1, error_detail=f"csproj 不存在: {csproj_full}",
        )

    adapter = DotnetAdapter(project_dir)

    # 如果是 skip_build 模式，这一步会被 runner 跳过
    result = adapter.build(configuration="Release", timeout=300, dry_run=ctx.dry_run)

    return StepResult(
        step="build",
        project=project["name"],
        ok=result.returncode == 0,
        duration=0,
        command=["dotnet", "build", str(project["csproj"]), "-c", "Release"],
        exit_code=result.returncode,
        stdout_tail=result.stdout[-200:] if result.stdout else "",
        stderr_tail=result.stderr[-200:] if result.stderr else "",
        error_detail=result.stderr[:500] if result.returncode != 0 else None,
    )
