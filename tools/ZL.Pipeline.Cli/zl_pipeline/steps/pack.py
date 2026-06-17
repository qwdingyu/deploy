"""步骤 2: pack — 打包 NuGet"""

from __future__ import annotations

from pathlib import Path

from zl_pipeline.config import get_package_id
from zl_pipeline.context import PipelineContext
from zl_pipeline.dotnet import DotnetAdapter
from zl_pipeline.result import StepResult
from zl_pipeline.runner import register_step


@register_step("pack")
def step_pack(ctx: PipelineContext, project: dict) -> StepResult:
    """打包 NuGet 包"""
    project_dir = ctx.proj_dir / Path(project["csproj"]).parent
    adapter = DotnetAdapter(project_dir)

    result = adapter.pack(
        no_build=ctx.skip_build,
        configuration="Release",
        package_version=ctx.version,
        output_dir=ctx.artifacts_dir,
        timeout=600,
        dry_run=ctx.dry_run,
    )

    pkg_id = get_package_id(project_dir, project["csproj"])
    nupkg_path = ctx.artifacts_dir / f"{pkg_id}.{ctx.version}.nupkg"

    return StepResult(
        step="pack",
        project=project["name"],
        ok=result.returncode == 0 or ctx.dry_run,
        duration=0,
        command=["dotnet", "pack", str(project["csproj"]), "-c", "Release",
                 f"-p:PackageVersion={ctx.version}", f"-o", str(ctx.artifacts_dir)],
        exit_code=result.returncode if not ctx.dry_run else 0,
        stdout_tail=result.stdout[-200:],
        stderr_tail=result.stderr[-200:],
        error_detail=result.stderr[:500] if result.returncode != 0 and not ctx.dry_run else None,
    )
