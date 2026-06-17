"""步骤 7: api_compare — API 完整性对比"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from zl_pipeline.config import get_package_id
from zl_pipeline.context import PipelineContext
from zl_pipeline.result import StepResult
from zl_pipeline.runner import register_step


@register_step("api_compare")
def step_api_compare(ctx: PipelineContext, project: dict) -> StepResult:
    """对比混淆前后的公共 API"""
    project_name = project["name"]
    project_dir = ctx.proj_dir / Path(project["csproj"]).parent

    pkg_id = get_package_id(project_dir, project["csproj"])
    nupkg_path = ctx.artifacts_dir / f"{pkg_id}.{ctx.version}.nupkg"
    obf_dll = ctx.obfuscated_dir / project_name / f"{project_name}.dll"

    if not nupkg_path.exists() or not obf_dll.exists():
        return StepResult(
            step="api_compare", project=project_name, ok=True, duration=0,
            command=["api-compare"], exit_code=0,
            error_detail="nupkg 或混淆 DLL 不存在，跳过 API 对比",
        )

    # 调用 api-compare.py
    script_path = Path(__file__).parents[2] / "scripts" / "api-compare.py"
    cmd = [sys.executable, str(script_path), str(nupkg_path), str(obf_dll)]

    if ctx.dry_run:
        return StepResult(
            step="api_compare", project=project_name, ok=True, duration=0,
            command=cmd, exit_code=0, error_detail="dry-run 跳过",
        )

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )

        # exit 0 = API 一致; exit 2 = 有差异; exit 1 = 脚本错误
        if result.returncode == 0:
            return StepResult(
                step="api_compare",
                project=project_name,
                ok=True,
                duration=0,
                command=cmd,
                exit_code=0,
                stdout_tail=result.stdout[-200:],
                error_detail="Public API fully preserved",
            )
        else:
            # exit 2 = 有差异 (视为失败); exit 1 = 脚本错误
            return StepResult(
                step="api_compare",
                project=project_name,
                ok=False,
                duration=0,
                command=cmd,
                exit_code=result.returncode,
                stdout_tail=result.stdout[-200:],
                stderr_tail=result.stderr[-200:],
                error_detail=result.stdout[:500] if result.stdout else result.stderr[:500],
            )
    except subprocess.TimeoutExpired:
        return StepResult(
            step="api_compare", project=project_name, ok=False, duration=0,
            command=cmd, exit_code=-1, error_detail="超时 (120s)",
        )
    except Exception as e:
        return StepResult(
            step="api_compare", project=project_name, ok=False, duration=0,
            command=cmd, exit_code=1, error_detail=str(e),
        )
