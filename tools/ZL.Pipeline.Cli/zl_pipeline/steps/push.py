"""步骤 8: push — 推送 NuGet 包到本地缓存 + 可选远程推送"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from zl_pipeline.config import get_package_id
from zl_pipeline.context import PipelineContext
from zl_pipeline.result import StepResult
from zl_pipeline.runner import register_step

# 本地 NuGet 源路径（dotnet nuget add source 时创建的 flat feed）
_LOCAL_FEED_DEFAULT = Path.home() / ".nuget" / "local-feed"


def _extract_first_line(text: str) -> str:
    """提取错误信息的第一行关键内容"""
    if not text:
        return ""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    # dotnet nuget push 的错误格式：第一行是"正在推送..."，后续行包含真实错误
    # 找包含关键信息（Forbidden/NotFound/Unauthorized/403/401/404）的行
    for line in lines:
        if any(kw in line for kw in ("Forbidden", "NotFound", "Unauthorized", "403", "401", "404", "timeout", "expired")):
            return line[:200]
    # 没找到关键行，返回最后一行（通常包含详细错误）
    return lines[-1][:200] if lines else ""


@register_step("push")
def step_push(ctx: PipelineContext, project: dict) -> StepResult:
    """推送 NuGet 包到本地缓存（始终执行），再尝试推送到远程源（可选）。

    流程:
        1. 将 nupkg 复制到本地 NuGet 源目录（~/.nuget/local-feed 或配置的 nugetSource 对应的 flat feed）
        2. 如果 NUGET_API_KEY 已设置，尝试推送到远程源
        3. 本地缓存成功即视为 push 通过
    """
    project_name = project["name"]

    # dry_run 模式下不推送
    if ctx.dry_run:
        return StepResult(
            step="push", project=project_name, ok=True, duration=0,
            command=["dotnet", "nuget", "push"], exit_code=0,
            error_detail="dry-run 跳过推送",
        )

    # 获取 nupkg 路径
    project_dir = ctx.proj_dir / Path(project["csproj"]).parent
    pkg_id = get_package_id(project_dir, project["csproj"])
    nupkg_path = ctx.artifacts_dir / f"{pkg_id}.{ctx.version}.nupkg"

    if not nupkg_path.exists():
        return StepResult(
            step="push", project=project_name, ok=False, duration=0,
            command=["dotnet", "nuget", "push"], exit_code=1,
            error_detail=f"nupkg 不存在: {nupkg_path}",
        )

    # === 步骤 1: 本地缓存（始终执行）=============================================
    # 无论是否为 --local 模式，nupkg 都会复制一份到 ~/.nuget/local-feed/，
    # 方便同一台机器上的其他项目（如 iot-sdk / UseThink.Iot）通过本地 NuGet 源直接引用。
    # 如果已存在同名文件，shutil.copy2 会静默覆盖。
    local_feed = _resolve_local_feed()
    local_feed.mkdir(parents=True, exist_ok=True)
    dest = local_feed / nupkg_path.name
    try:
        shutil.copy2(str(nupkg_path), str(dest))
    except OSError as e:
        return StepResult(
            step="push", project=project_name, ok=False, duration=0,
            command=["cp", str(nupkg_path), str(dest)], exit_code=1,
            error_detail=f"本地缓存失败: {e}",
        )

    # === 步骤 2: 远程推送（仅在 --local 未设置且 NUGET_API_KEY 存在时尝试）==========
    #
    # --local 模式：本地开发 / 快速验证时，不应该污染远程 NuGet 源。
    # 此时 nupkg 刚刚已经被复制到本地 feed，直接返回成功，不再检查 API_KEY。
    #
    # 非 --local 模式：
    #   - 如果 NUGET_API_KEY 已设置 → 推送到 remote nugetSource（如 NuGet.org / 私有源）
    #   - 如果未设置 → 仅本地缓存成功即视为 push 通过
    #
    # 异常处理：远程超时 / 404 / Forbidden 等异常不会使本地缓存失效，
    # push 步骤仍返回 ok=True（本地已成功），但 error_detail 会附带远程失败原因。
    if ctx.local:
        return StepResult(
            step="push", project=project_name, ok=True, duration=0,
            command=["cp", str(nupkg_path), str(dest)], exit_code=0,
            error_detail=f"--local 模式，已保存到本地: {dest}",
        )

    api_key = os.environ.get("NUGET_API_KEY")
    if not api_key:
        return StepResult(
            step="push", project=project_name, ok=True, duration=0,
            command=["cp", str(nupkg_path), str(dest)], exit_code=0,
            error_detail=f"已保存到本地: {dest}",
        )

    # 调用 dotnet nuget push
    import subprocess
    cmd = [
        "dotnet", "nuget", "push", str(nupkg_path),
        "-k", api_key,
        "-s", ctx.config.nuget_source,
        "--skip-duplicate",
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=ctx.config.publish_timeout,
        )
        remote_ok = result.returncode == 0
        return StepResult(
            step="push",
            project=project_name,
            ok=True,  # 本地成功即为通过，远程失败不阻断
            duration=0,
            command=cmd,
            exit_code=result.returncode,
            stdout_tail=result.stdout[-200:],
            stderr_tail=result.stderr[-200:],
            error_detail=(
                f"本地: OK | 远程: {_extract_first_line(result.stderr or result.stdout)}"
                if not remote_ok
                else None,
            ),
        )
    except subprocess.TimeoutExpired:
        return StepResult(
            step="push", project=project_name, ok=True, duration=0,
            command=cmd, exit_code=-1, error_detail=f"本地: OK | 远程: 超时 ({ctx.config.publish_timeout}s)",
        )
    except Exception as e:
        return StepResult(
            step="push", project=project_name, ok=True, duration=0,
            command=cmd, exit_code=1, error_detail=f"本地: OK | 远程: {e}",
        )


def _resolve_local_feed() -> Path:
    """解析本地 NuGet 源目录路径。"""
    # 尝试从 dotnet nuget list source 获取 local-feed 路径
    env_path = os.environ.get("NUGET_LOCAL_FEED")
    if env_path:
        return Path(env_path)

    # 默认路径
    return _LOCAL_FEED_DEFAULT
