"""步骤 6: replace_nupkg — 替换 nupkg 中的 DLL"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from zl_pipeline.config import get_package_id
from zl_pipeline.context import PipelineContext
from zl_pipeline.result import StepResult
from zl_pipeline.runner import register_step


@register_step("replace_nupkg")
def step_replace_nupkg(ctx: PipelineContext, project: dict) -> StepResult:
    """替换 nupkg 中的 DLL 为混淆后的版本（或不混淆则直接用原始 DLL）"""
    project_name = project["name"]

    # --local 模式：跳过 replace_nupkg
    # 此步骤用混淆后的 DLL 替换 nupkg 内的原始 DLL，--local 未执行混淆，
    # nupkg 中已是原始 DLL，无需替换，直接返回成功。
    if ctx.local:
        return StepResult(
            step="replace_nupkg", project=project_name, ok=True, duration=0,
            command=[], exit_code=0, error_detail="--local 模式，跳过",
        )

    project_dir = ctx.proj_dir / Path(project["csproj"]).parent

    # 不混淆的项目：跳过 replace_nupkg（nupkg 中已是原始 DLL，无需替换）
    if not project.get("obfuscate", True):
        return StepResult(
            step="replace_nupkg", project=project_name, ok=True, duration=0,
            command=["replace-nupkg"], exit_code=0,
            error_detail="混淆已禁用，跳过替换",
        )

    pkg_id = get_package_id(project_dir, project["csproj"])
    nupkg_path = ctx.artifacts_dir / f"{pkg_id}.{ctx.version}.nupkg"
    obf_dll = ctx.obfuscated_dir / project_name / f"{project_name}.dll"

    if not nupkg_path.exists():
        if ctx.dry_run:
            return StepResult(
                step="replace_nupkg", project=project_name, ok=True, duration=0,
                command=["replace-nupkg"], exit_code=0,
                error_detail="dry-run 模式，跳过替换",
            )
        return StepResult(
            step="replace_nupkg", project=project_name, ok=False, duration=0,
            command=["replace-nupkg"], exit_code=1,
            error_detail=f"nupkg 不存在: {nupkg_path}",
        )

    if not obf_dll.exists():
        if ctx.dry_run:
            return StepResult(
                step="replace_nupkg", project=project_name, ok=True, duration=0,
                command=["replace-nupkg"], exit_code=0,
                error_detail="dry-run 模式，跳过替换",
            )
        return StepResult(
            step="replace_nupkg", project=project_name, ok=False, duration=0,
            command=["replace-nupkg"], exit_code=1,
            error_detail=f"混淆 DLL 不存在: {obf_dll}",
        )

    # 检测 TFM
    from zl_pipeline.config import detect_tfm
    csproj_full = ctx.proj_dir / project["csproj"]
    tfm = detect_tfm(csproj_full)

    # 调用 replace-nupkg-dll.py
    script_path = Path(__file__).parents[2] / "scripts" / "replace-nupkg-dll.py"
    cmd = [sys.executable, str(script_path), str(nupkg_path), str(obf_dll), tfm]

    if ctx.dry_run:
        return StepResult(
            step="replace_nupkg", project=project_name, ok=True, duration=0,
            command=cmd, exit_code=0, error_detail="dry-run 跳过",
        )

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )
        return StepResult(
            step="replace_nupkg",
            project=project_name,
            ok=result.returncode == 0,
            duration=0,
            command=cmd,
            exit_code=result.returncode,
            stdout_tail=result.stdout[-200:],
            stderr_tail=result.stderr[-200:],
            error_detail=result.stderr[:500] if result.returncode != 0 else None,
        )
    except subprocess.TimeoutExpired:
        return StepResult(
            step="replace_nupkg", project=project_name, ok=False, duration=0,
            command=cmd, exit_code=-1, error_detail="超时 (120s)",
        )
    except Exception as e:
        return StepResult(
            step="replace_nupkg", project=project_name, ok=False, duration=0,
            command=cmd, exit_code=1, error_detail=str(e),
        )
