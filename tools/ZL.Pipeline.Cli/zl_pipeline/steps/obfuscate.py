"""步骤 5: obfuscate — Obfuscar 混淆"""

from __future__ import annotations

from pathlib import Path

from zl_pipeline.config import check_obfuscar_available
from zl_pipeline.context import PipelineContext
from zl_pipeline.obfuscar import ObfuscarAdapter
from zl_pipeline.result import StepResult
from zl_pipeline.runner import register_step


@register_step("obfuscate")
def step_obfuscate(ctx: PipelineContext, project: dict) -> StepResult:
    """执行 Obfuscar 混淆"""
    project_name = project["name"]

    # --local 模式：跳过混淆
    # 本地调试场景下，混淆环节（Obfuscar 执行约 30~60 秒 / 项目）耗时且无必要，
    # 因为本地 feed 仅用于同一台机器上的依赖解析，不会发布到公网。
    if ctx.local:
        return StepResult(
            step="obfuscate", project=project_name, ok=True, duration=0,
            command=[], exit_code=0, error_detail="--local 模式，跳过混淆",
        )

    # 检查是否启用混淆
    if not project.get("obfuscate", True):
        return StepResult(
            step="obfuscate", project=project_name, ok=True, duration=0,
            command=[], exit_code=0, error_detail="混淆已禁用",
        )

    # 检查 obfuscar 可用性
    if not check_obfuscar_available():
        return StepResult(
            step="obfuscate", project=project_name, ok=False, duration=0,
            command=["obfuscar.console"], exit_code=1,
            error_detail="obfuscar.console 未安装",
        )

    # 检查源 DLL
    pub_dir = ctx.obfuscated_dir / project_name / "publish"
    src_dll = pub_dir / f"{project_name}.dll"

    if not src_dll.exists():
        if ctx.dry_run:
            return StepResult(
                step="obfuscate", project=project_name, ok=True, duration=0,
                command=["obfuscar.console"], exit_code=0,
                error_detail="dry-run 模式，跳过混淆",
            )
        return StepResult(
            step="obfuscate", project=project_name, ok=False, duration=0,
            command=["obfuscar.console"], exit_code=1,
            error_detail=f"源 DLL 不存在: {src_dll}",
        )

    # 执行混淆
    out_dir = ctx.obfuscated_dir / project_name
    out_dir.mkdir(parents=True, exist_ok=True)

    config_path = None
    if project.get("obfuscarConfig"):
        config_path = ctx.proj_dir / project["obfuscarConfig"]

    adapter = ObfuscarAdapter()
    result = adapter.run(
        input_dll=src_dll,
        output_dir=out_dir,
        config_path=config_path,
        timeout=300,
        dry_run=ctx.dry_run,
    )

    out_dll = out_dir / f"{project_name}.dll"

    return StepResult(
        step="obfuscate",
        project=project_name,
        ok=result.ok or ctx.dry_run,
        duration=0,
        command=["obfuscar.console", str(src_dll)],
        exit_code=0 if result.ok else 1,
        stdout_tail=result.stdout[-200:],
        stderr_tail=result.stderr[-200:],
        log_file=result.mapping_file,
        error_detail=result.stderr[:500] if not result.ok and not ctx.dry_run else None,
    )
