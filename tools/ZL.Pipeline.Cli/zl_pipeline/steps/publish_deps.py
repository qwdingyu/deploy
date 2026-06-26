"""步骤 4: publish_deps — 准备依赖集（dotnet publish -o）"""

from __future__ import annotations

from pathlib import Path

from zl_pipeline.config import detect_tfm
from zl_pipeline.context import PipelineContext
from zl_pipeline.dotnet import DotnetAdapter
from zl_pipeline.result import StepResult
from zl_pipeline.runner import register_step


@register_step("publish_deps")
def step_publish_deps(ctx: PipelineContext, project: dict) -> StepResult:
    """dotnet publish -o 准备依赖集（为 Obfuscar 做准备）"""
    project_name = project["name"]

    # --local 模式：跳过 publish_deps（此步骤是为 Obfuscar 混淆准备依赖集，
    # --local 模式下混淆被跳过，因此无需准备依赖集，直接返回成功。）
    if ctx.local:
        return StepResult(
            step="publish_deps", project=project_name, ok=True, duration=0,
            command=[], exit_code=0, error_detail="--local 模式，跳过",
        )

    project_dir = ctx.proj_dir / Path(project["csproj"]).parent
    csproj_full = ctx.proj_dir / project["csproj"]

    if not csproj_full.exists():
        return StepResult(
            step="publish_deps", project=project_name, ok=False, duration=0,
            command=["dotnet", "publish"], exit_code=1,
            error_detail=f"csproj 不存在: {csproj_full}",
        )

    # 检测 TFM
    tfm = detect_tfm(csproj_full)
    pub_dir = ctx.obfuscated_dir / project_name / "publish"
    pub_dir.mkdir(parents=True, exist_ok=True)

    adapter = DotnetAdapter(project_dir)
    result = adapter.publish(
        output=pub_dir,
        framework=tfm,
        configuration="Release",
        timeout=300,
        dry_run=ctx.dry_run,
    )

    src_dll = pub_dir / f"{project_name}.dll"
    return StepResult(
        step="publish_deps",
        project=project_name,
        ok=result.returncode == 0 or ctx.dry_run,
        duration=0,
        command=["dotnet", "publish", str(project["csproj"]), "-c", "Release",
                 "-o", str(pub_dir), f"-p:TargetFramework={tfm}"],
        exit_code=result.returncode if not ctx.dry_run else 0,
        stdout_tail=result.stdout[-200:],
        stderr_tail=result.stderr[-200:],
        error_detail=result.stderr[:500] if result.returncode != 0 and not ctx.dry_run else None,
    )
