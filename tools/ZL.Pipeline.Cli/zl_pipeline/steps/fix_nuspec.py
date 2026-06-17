"""步骤 3: fix_nuspec — 修复 nuspec 依赖版本。

将 nupkg 内所有 ZL.* 依赖版本统一修正为 ctx.version。
（全生态已统一版本号，不再需要区分内部/外部包）
"""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from zl_pipeline.config import get_package_id
from zl_pipeline.context import PipelineContext
from zl_pipeline.result import StepResult
from zl_pipeline.runner import register_step


@register_step("fix_nuspec")
def step_fix_nuspec(ctx: PipelineContext, project: dict) -> StepResult:
    """将 nupkg 中所有 ZL.* 依赖版本统一修正为 ctx.version。

    CPM 统一管理版本后，nuspec 通常已正确。本步作为安全网，
    确保任何偏离 ctx.version 的 ZL.* 依赖被修正。
    """
    project_dir = ctx.proj_dir / Path(project["csproj"]).parent
    pkg_id = get_package_id(project_dir, project["csproj"])
    nupkg_path = ctx.artifacts_dir / f"{pkg_id}.{ctx.version}.nupkg"

    if not nupkg_path.exists():
        if ctx.dry_run:
            return StepResult(step="fix_nuspec", project=project["name"], ok=True, duration=0,
                              command=["fix-nuspec"], exit_code=0,
                              error_detail="dry-run 模式，跳过修复")
        return StepResult(step="fix_nuspec", project=project["name"], ok=False, duration=0,
                          command=["fix-nuspec"], exit_code=1,
                          error_detail=f"nupkg 不存在: {nupkg_path}")

    try:
        with zipfile.ZipFile(nupkg_path, "r") as zf:
            nuspec_files = [f for f in zf.namelist() if f.endswith(".nuspec")]
            if not nuspec_files:
                return StepResult(step="fix_nuspec", project=project["name"], ok=True, duration=0,
                                  command=["fix-nuspec"], exit_code=0,
                                  error_detail="无 nuspec 文件，无需修复")

            deps_pattern = re.compile(r'<dependency\s+id="(ZL\.[^"]+)"\s+version="([^"]+)"')
            new_nuspecs: dict[str, bytes] = {}

            for nf in nuspec_files:
                nuspec_xml = zf.read(nf).decode("utf-8", errors="replace")
                original = nuspec_xml

                for m in deps_pattern.finditer(nuspec_xml):
                    dep_id, dep_ver = m.group(1), m.group(2)
                    if dep_ver != ctx.version:
                        nuspec_xml = nuspec_xml.replace(
                            f'dependency id="{dep_id}" version="{dep_ver}"',
                            f'dependency id="{dep_id}" version="{ctx.version}"', 1,
                        )

                if nuspec_xml != original:
                    new_nuspecs[nf] = nuspec_xml.encode("utf-8")

            if not new_nuspecs:
                return StepResult(step="fix_nuspec", project=project["name"], ok=True, duration=0,
                                  command=["fix-nuspec"], exit_code=0,
                                  error_detail="依赖版本已一致，无需修复")

            # 重建 nupkg
            tmp = Path(tempfile.mktemp(suffix=".nupkg"))
            try:
                with zipfile.ZipFile(nupkg_path, "r") as src:
                    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
                        for info in src.infolist():
                            dst.writestr(info, new_nuspecs.get(info.filename) or src.read(info.filename))

                sha_file = nupkg_path.with_suffix(".nupkg.sha512")
                if sha_file.exists():
                    sha_file.unlink()
                shutil.move(str(tmp), str(nupkg_path))

                return StepResult(step="fix_nuspec", project=project["name"], ok=True, duration=0,
                                  command=["fix-nuspec"], exit_code=0,
                                  error_detail=f"已修复 {len(new_nuspecs)} 个 nuspec")
            except Exception:
                tmp.unlink(missing_ok=True)
                raise

    except Exception as e:
        return StepResult(step="fix_nuspec", project=project["name"], ok=False, duration=0,
                          command=["fix-nuspec"], exit_code=1, error_detail=str(e))
