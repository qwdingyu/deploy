"""CLI 入口 — 定义所有子命令和参数。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from zl_pipeline.config import (
    PipelineConfig,
    check_dotnet_available,
    check_obfuscar_available,
    init_config,
    load_config,
    _expand_consumer_paths,
    _find_cpm_file,
    _update_cpm_version,
    get_package_id,
)

# 导入所有步骤以触发 @register_step 装饰器注册
import zl_pipeline.steps  # noqa: F401

from zl_pipeline.context import PipelineContext
from zl_pipeline.report import get_obfuscated_projects, print_report
from zl_pipeline.runner import ExecutionPlan, STEP_REGISTRY, StepRunner


# ---------------------------------------------------------------------------
# 颜色
# ---------------------------------------------------------------------------
_GREEN = "\033[0;32m"
_RED = "\033[0;31m"
_YELLOW = "\033[1;33m"
_CYAN = "\033[0;36m"
_NC = "\033[0m"


def _ok(msg: str) -> None:
    print(f"  {_GREEN}[PASS]{_NC}  {msg}")


def _fail(msg: str) -> None:
    print(f"  {_RED}[FAIL]{_NC}  {msg}", file=sys.stderr)


def _info(msg: str) -> None:
    print(f"  {_CYAN}[INFO]{_NC}  {msg}")


def _warn(msg: str) -> None:
    print(f"  {_YELLOW}[WARN]{_NC}  {msg}")


# ---------------------------------------------------------------------------
# 命令实现
# ---------------------------------------------------------------------------

def _cmd_plan(args: argparse.Namespace, config: PipelineConfig, proj_dir: Path) -> int:
    """plan: 只展示将执行的操作"""
    version = args.version
    ctx = PipelineContext(
        version=version,
        config=config,
        proj_dir=proj_dir,
        artifacts_dir=proj_dir / "artifacts",
        state_dir=proj_dir / "artifacts" / ".pipeline-state",
        only_projects=frozenset(args.only) if args.only else None,
        dry_run=True,
        verbose=args.verbose,
    )
    runner = StepRunner(ctx)
    plan = runner.plan()

    print(f"\n{'=' * 60}")
    print(f"  执行计划: v{version}")
    print(f"{'=' * 60}\n")

    current_project = ""
    for entry in plan:
        if entry.project != current_project:
            if current_project:
                print()
            current_project = entry.project
            print(f"\n  项目: {entry.project}")
            print(f"  {'─' * 40}")
        print(f"    [{entry.step}] {entry.command_preview}")

    print(f"\n{'=' * 60}")
    _info(f"共 {len(plan)} 个步骤，{len(config.projects)} 个项目")
    print(f"{'=' * 60}\n")
    return 0


def _cmd_verify(args: argparse.Namespace, config: PipelineConfig, proj_dir: Path) -> int:
    """verify: 真实构建验证，不推送"""
    _info("环境检查...")
    _check_env(config)

    version = args.version
    ctx = PipelineContext(
        version=version,
        config=config,
        proj_dir=proj_dir,
        artifacts_dir=proj_dir / "artifacts",
        state_dir=proj_dir / "artifacts" / ".pipeline-state",
        only_projects=frozenset(args.only) if args.only else None,
        from_step=args.from_step if hasattr(args, "from_step") and args.from_step else None,
        skip_build=args.skip_build,
        resume=args.resume,
        dry_run=True,
        verbose=args.verbose,
    )

    print(f"\n{'=' * 60}")
    print(f"  验证模式 (dry-run): v{version}")
    print(f"{'=' * 60}\n")

    runner = StepRunner(ctx)
    results = runner.run_all()
    obfuscated = get_obfuscated_projects(results)
    print_report(results, obfuscated=obfuscated)
    return 0 if all(r.ok for r in results) else 1


def _cmd_publish(args: argparse.Namespace, config: PipelineConfig, proj_dir: Path) -> int:
    """publish: 验证后真实推送"""
    _info("环境检查...")
    _check_env(config)

    version = args.version
    ctx = PipelineContext(
        version=version,
        config=config,
        proj_dir=proj_dir,
        artifacts_dir=proj_dir / "artifacts",
        state_dir=proj_dir / "artifacts" / ".pipeline-state",
        only_projects=frozenset(args.only) if args.only else None,
        from_step=args.from_step if hasattr(args, "from_step") and args.from_step else None,
        skip_build=args.skip_build,
        resume=args.resume,
        local=args.local,
        dry_run=False,
        verbose=args.verbose,
    )

    # 确保禁用 MSBuild 节点重用
    os.environ["MSBUILDDISABLENODEREUSE"] = "1"

    print(f"\n{'=' * 60}")
    print(f"  发布模式: v{version}")
    # --local 模式提示：在发布报告前醒目告知用户当前工作在本地模式下
    if args.local:
        print(f"  --local 模式：跳过混淆和远程推送")
    print(f"{'=' * 60}\n")

    runner = StepRunner(ctx)
    results = runner.run_all()
    obfuscated = get_obfuscated_projects(results)
    print_report(results, obfuscated=obfuscated)
    return 0 if all(r.ok for r in results) else 1


def _cmd_check(args: argparse.Namespace, config: PipelineConfig, proj_dir: Path) -> int:
    """check: 验证已发布的 NuGet 包是否存在且可下载"""
    package_name = args.package
    version = args.version

    _info(f"检查包 {package_name} v{version}...")

    # 尝试从 NuGet API 检查
    import urllib.request

    api_url = f"{config.nuget_source}/registration/{package_name.lower()}/{version}.json"
    
    try:
        req = urllib.request.Request(api_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 200:
                _info(f"✅ 包 {package_name} v{version} 存在于源 {config.nuget_source}")
                return 0
            else:
                _fail(f"HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            _fail(f"包 {package_name} v{version} 未找到")
            return 1
        else:
            _fail(f"HTTP 错误: {e.code}")
            return 1
    except urllib.error.URLError as e:
        _fail(f"网络错误: {e.reason}")
        return 1
    except Exception as e:
        _fail(f"检查失败: {e}")
        return 1


def _cmd_sync_consumers(args: argparse.Namespace, config: PipelineConfig, proj_dir: Path) -> int:
    """sync-consumers: 同步下游消费项目的包版本"""
    version = args.version
    dry_run = args.dry_run
    projects = config.projects

    # 收集已发布的包
    artifacts_dir = proj_dir / "artifacts"
    package_ids = []
    for proj in projects:
        pid = get_package_id(proj_dir / proj.name, proj.csproj)
        nupkg = artifacts_dir / f"{pid}.{version}.nupkg"
        if nupkg.exists():
            package_ids.append(pid)
        else:
            _warn(f"未找到 {pid}.{version}.nupkg，跳过")

    if not package_ids:
        _fail(f"未找到任何 {version} 版本的 nupkg 文件")
        return 1

    consumers = config.consumers
    if not consumers:
        _fail("pipeline.json 中未配置 consumers")
        _info('示例: "consumers": [{"name": "tmom", "path": "/path/to/tmom"}]')
        return 1

    _info(f"同步下游消费项目 (version={version})")
    print()

    total_updated = 0
    total_consumers = 0
    processed_cpm: set[Path] = set()

    for consumer_cfg in consumers:
        expanded = _expand_consumer_paths(consumer_cfg, str(proj_dir))
        for consumer in expanded:
            cname = consumer["name"]
            cpath = Path(consumer["path"])
            if not cpath.exists():
                _fail(f"消费项目路径不存在: {cpath}")
                continue

            total_consumers += 1
            cpm_file = _find_cpm_file(cpath)
            if cpm_file is None:
                custom_cpm = consumer.get("cpmFile")
                if custom_cpm:
                    cpm_file = cpath / custom_cpm
                else:
                    _fail(f"在 {cpath} 中未找到 Directory.Packages.props")
                    continue
            if not cpm_file.exists():
                _fail(f"CPM 文件不存在: {cpm_file}")
                continue

            cpm_real = cpm_file.resolve()
            if cpm_real in processed_cpm:
                _info(f"跳过 {cname}: CPM 文件已被处理 ({cpm_file})")
                continue
            processed_cpm.add(cpm_real)

            _info(f"更新 {cname}: {cpm_file}")
            consumer_updated = 0
            for pid in package_ids:
                if _update_cpm_version(cpm_file, pid, version):
                    consumer_updated += 1
                    if dry_run:
                        _info(f"  [DRYRUN] {pid} -> {version}")
                    else:
                        _ok(f"  {pid} -> {version}")
                else:
                    _info(f"  [SKIP] {pid} 未在 CPM 中定义")
            total_updated += consumer_updated

            # 编译验证
            build_target = consumer.get("buildTarget")
            if build_target:
                csproj = cpath / build_target
                if csproj.exists():
                    _info(f"编译验证 {cname}...")
                    import subprocess
                    result = subprocess.run(
                        ["dotnet", "build", str(csproj), "-c", "Release", "--nologo", "-v", "q"],
                        capture_output=True, text=True, timeout=300,
                    )
                    if result.returncode == 0:
                        _ok(f"{cname} 编译通过")
                    else:
                        _fail(f"{cname} 编译失败")

            # 自动 git commit + push
            if consumer.get("autoCommit", False) and not dry_run and consumer_updated > 0:
                _info(f"Git commit {cname}...")
                result = subprocess.run(
                    ["git", "add", str(cpm_file)],
                    cwd=str(cpath), capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    result = subprocess.run(
                        ["git", "commit", "-m", f"chore: bump ZL packages to {version}"],
                        cwd=str(cpath), capture_output=True, text=True, timeout=30,
                    )
                    if result.returncode == 0:
                        _ok(f"{cname} committed")
                        result = subprocess.run(
                            ["git", "push"],
                            cwd=str(cpath), capture_output=True, text=True, timeout=60,
                        )
                        if result.returncode == 0:
                            _ok(f"{cname} pushed")
                        else:
                            _fail(f"{cname} push 失败")
                    else:
                        _info(f"{cname} commit 失败 (可能无变更)")

    print()
    print(f"{'=' * 60}")
    _info(f"同步完成")
    print(f"  消费项目: {total_consumers}")
    print(f"  更新包数: {total_updated}")
    print(f"{'=' * 60}\n")
    return 0


def _cmd_align_versions(args: argparse.Namespace, config: PipelineConfig, proj_dir: Path) -> int:
    """align-versions: 对齐消费者 CPM 中 ZL 包到各自最新版本"""
    from zl_pipeline.config import (
        _expand_consumer_paths,
        _find_cpm_file,
        _update_cpm_version,
        get_package_id,
    )

    dry_run = args.dry_run
    consumers = config.consumers
    nuget_source = config.nuget_source

    if not consumers:
        _fail("pipeline.json 中未定义 consumers")
        return 1

    # 查询 NuGet.org 最新版本
    import urllib.request
    projects = config.projects
    zl_package_ids = set()
    for proj in projects:
        pkg_id = get_package_id(proj_dir / proj.name, proj.csproj)
        zl_package_ids.add(pkg_id)

    print(f"\n{'=' * 60}")
    _info("查询 NuGet.org 最新版本")
    print(f"{'=' * 60}\n")

    latest_versions: dict[str, str] = {}
    for pkg_id in sorted(zl_package_ids):
        url = f"https://api.nuget.org/v3-flatcontainer/{pkg_id}/"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                content = r.read().decode("utf-8", errors="replace")
            import re
            versions = re.findall(rf'{pkg_id}/([^"]+)"', content)
            stable = [v for v in versions if "-" not in v]
            if stable:
                stable.sort(key=lambda v: [int(x) for x in v.split(".") if x.isdigit()])
                latest_versions[pkg_id] = stable[-1]
                _info(f"  {pkg_id:35s} => {stable[-1]}")
        except Exception:
            _warn(f"{pkg_id}: 无法查询最新版本")

    if not latest_versions:
        _fail("未能获取任何包的版本信息")
        return 1

    # 更新每个消费者的 CPM
    processed_cpm: set[Path] = set()
    for consumer_cfg in consumers:
        expanded = _expand_consumer_paths(consumer_cfg, str(proj_dir))
        for consumer in expanded:
            cname = consumer["name"]
            cpath = Path(consumer["path"])
            if not cpath.exists():
                continue

            cpm_file = _find_cpm_file(cpath)
            if cpm_file is None:
                custom_cpm = consumer.get("cpmFile")
                if custom_cpm:
                    cpm_file = cpath / custom_cpm
                else:
                    continue
            if not cpm_file.exists():
                continue

            cpm_real = cpm_file.resolve()
            if cpm_real in processed_cpm:
                continue
            processed_cpm.add(cpm_real)

            print(f"\n{'=' * 60}")
            _info(f"对齐消费者: {cname}")
            print(f"{'=' * 60}")

            content = cpm_file.read_text(encoding="utf-8")
            updated_count = 0
            unchanged_count = 0

            for pkg_id, new_version in sorted(latest_versions.items()):
                pattern = rf'(PackageVersion Include="{re.escape(pkg_id)}"\s+Version=")([^"]+)(")'
                match = re.search(pattern, content)
                if not match:
                    _info(f"{pkg_id}: CPM 中未找到，跳过")
                    continue

                old_version = match.group(2)
                if old_version == new_version:
                    unchanged_count += 1
                    continue

                content = re2.sub(pattern, rf'\g<1>{new_version}\3', content)
                updated_count += 1
                _info(f"  {pkg_id:35s} {old_version} => {new_version}")

            if updated_count > 0:
                if dry_run:
                    _info(f"将更新 {updated_count} 个包，{unchanged_count} 个已是最新")
                else:
                    cpm_file.write_text(content, encoding="utf-8")
                    _ok(f"已更新 {updated_count} 个包，{unchanged_count} 个已是最新")
            else:
                _ok("所有包已是最新版本")

    print()
    _info("align-versions 完成")
    return 0


def _cmd_clean(args: argparse.Namespace, config: PipelineConfig, proj_dir: Path) -> int:
    """clean: 清理 artifacts"""
    version = args.version if hasattr(args, "version") and args.version else None

    dirs_to_clean = [
        proj_dir / "artifacts",
        proj_dir / "obfuscated",
    ]

    for d in dirs_to_clean:
        if d.exists():
            import shutil
            shutil.rmtree(str(d))
            _info(f"已清理: {d}")

    _ok("清理完成")
    return 0


def _check_env(config: PipelineConfig) -> None:
    """环境检查"""
    print(f"\n{'=' * 60}")
    _info("环境检查")
    print(f"{'=' * 60}\n")

    dotnet_version = check_dotnet_available()
    if dotnet_version:
        _ok(f"dotnet {dotnet_version}")
    else:
        _fail("dotnet SDK 未安装")

    import sys
    _ok(f"python {sys.version.split()[0]}")

    os.environ["MSBUILDDISABLENODEREUSE"] = "1"
    _ok("MSBUILDDISABLENODEREUSE=1")

    if check_obfuscar_available():
        _ok("obfuscar.console 已安装")
    else:
        _info("obfuscar.console 未安装（混淆将被跳过）")

    # 检查脚本
    scripts_dir = Path(__file__).parents[1] / "scripts"
    for script in ["replace-nupkg-dll.py", "api-compare.py"]:
        if (scripts_dir / script).exists():
            _ok(f"{script}")
        else:
            _fail(f"{script} 不存在")
    if (scripts_dir / "verify-nuget-obfuscation.sh").exists():
        _ok("verify-nuget-obfuscation.sh")

    print()


# ---------------------------------------------------------------------------
# CLI 解析
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI 入口 — 解析命令行参数并分发到子命令"""
    parser = argparse.ArgumentParser(
        prog="zl-pipeline",
        description="ZL.Pipeline.Cli — 统一发布流水线工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  zl-pipeline plan 1.0.1                              # 查看执行计划
  zl-pipeline verify 1.0.1                            # 验证（不推送）
  zl-pipeline publish 1.0.1                           # 发布并推送
  zl-pipeline verify 1.0.1 --only ZL.IotHub           # 只验证指定项目
  zl-pipeline verify 1.0.1 --from-step obfuscate      # 从指定步骤开始
  zl-pipeline verify 1.0.1 --resume                   # 断点续跑
  zl-pipeline sync-consumers 1.0.1                    # 同步消费者
        """,
    )
    parser.add_argument("--config", "-c", help="pipeline.json 路径")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # ---- plan ----
    plan_p = subparsers.add_parser("plan", help="查看执行计划")
    plan_p.add_argument("version", help="版本号")
    plan_p.add_argument("--only", nargs="+", help="仅处理指定项目")

    # ---- verify ----
    verify_p = subparsers.add_parser("verify", help="验证（不推送）")
    verify_p.add_argument("version", help="版本号")
    verify_p.add_argument("--only", nargs="+", help="仅处理指定项目")
    verify_p.add_argument("--from-step", help="从指定步骤开始")
    verify_p.add_argument("--skip-build", action="store_true", help="跳过编译")
    verify_p.add_argument("--resume", action="store_true", help="断点续跑")

    # ---- publish ----
    pub_p = subparsers.add_parser("publish", help="发布并推送")
    pub_p.add_argument("version", help="版本号")
    pub_p.add_argument("--only", nargs="+", help="仅处理指定项目")
    pub_p.add_argument("--from-step", help="从指定步骤开始")
    pub_p.add_argument("--skip-build", action="store_true", help="跳过编译")
    pub_p.add_argument("--resume", action="store_true", help="断点续跑")
    # --local: 本地发布模式。仅在 develop/fix 分支调试时使用，跳过 obfuscate / replace_nupkg /
    # api_compare 等混淆相关步骤（这些环节耗时长、且本地调试不关心混淆效果），
    # push 也只复制到 ~/.nuget/local-feed/，不尝试远程推送。
    # 工作流：build → pack → fix_nuspec → push(仅本地缓存)。
    pub_p.add_argument("--local", action="store_true", help="本地模式：仅 pack + nuspec 修复 + 本地缓存，跳过混淆和远程推送")

    # ---- check ----
    check_p = subparsers.add_parser("check", help="验证已发布的 NuGet 包")
    check_p.add_argument("package", help="包名")
    check_p.add_argument("version", help="版本号")
    check_p.add_argument("--tfm", "-t", default="net8.0", help="目标框架")

    # ---- sync-consumers ----
    sync_p = subparsers.add_parser("sync-consumers", help="同步下游消费项目")
    sync_p.add_argument("version", help="版本号")
    sync_p.add_argument("--dry-run", "-n", action="store_true", help="仅验证不修改")

    # ---- align-versions ----
    align_p = subparsers.add_parser("align-versions", help="对齐消费者 CPM 版本")
    align_p.add_argument("--dry-run", "-n", action="store_true", help="仅验证不修改")

    # ---- clean ----
    clean_p = subparsers.add_parser("clean", help="清理 artifacts")
    clean_p.add_argument("--version", help="仅清理指定版本")

    # ---- list-config ----
    subparsers.add_parser("list-config", help="列出所有可配置项")

    # ---- init ----
    init_p = subparsers.add_parser("init", help="生成 pipeline.json")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    # 加载配置（非 init/list-config 需要）
    config_path = getattr(args, "config", None)
    proj_dir = None

    if args.command == "init":
        try:
            p = init_config(Path.cwd())
            _ok(f"已生成 {p}")
            _info(f"发现项目，请编辑后运行 'zl-pipeline publish'")
        except FileExistsError as e:
            _fail(str(e))
            return
        return

    if args.command == "list-config":
        _list_config_help()
        return

    # 需要配置文件
    try:
        config = load_config(config_path)
        proj_dir = Path(config_path).parent if config_path else Path.cwd()
    except FileNotFoundError as e:
        _fail(str(e))
        return
    except json.JSONDecodeError as e:
        _fail(f"JSON 解析错误: {e}")
        return
    except Exception as e:
        _fail(f"配置错误: {e}")
        return

    # 分发命令
    commands = {
        "plan": _cmd_plan,
        "verify": _cmd_verify,
        "publish": _cmd_publish,
        "check": _cmd_check,
        "sync-consumers": _cmd_sync_consumers,
        "align-versions": _cmd_align_versions,
        "clean": _cmd_clean,
    }

    handler = commands.get(args.command)
    if handler:
        exit_code = handler(args, config, proj_dir)
        sys.exit(exit_code)
    else:
        parser.print_help()


def _list_config_help() -> None:
    print("""
pipeline.json 配置项:

  version             配置版本 (当前: 1.0)
  projects            项目列表 (数组)

  projects[].name             项目名 (必填)
  projects[].csproj           csproj 路径 (必填)
  projects[].obfuscate        是否混淆 (默认: true)
  projects[].obfuscarConfig   自定义 obfuscar.xml 路径 (可选)
  projects[].includeDependencies  额外依赖 DLL 列表 (可选)

  obfuscarConfig      默认 obfuscar.xml 路径 (默认: obfuscar.xml)
  nugetSource         NuGet 源 (默认: https://api.nuget.org/v3/index.json)
  publishTimeout      推送超时秒数 (默认: 120)
  dryRun              全局 dry-run 模式 (默认: false)

  consumers           下游消费项目列表 (可选)
  consumers[].name            消费项目名称 (必填)
  consumers[].path            项目根目录 (必填)
  consumers[].cpmFile         Directory.Packages.props 路径 (可选)
  consumers[].buildTarget     编译验证目标 csproj (可选)
  consumers[].autoCommit      自动 git commit+push (默认: false)
  consumers[].autoDiscover    自动扫描 CPM 文件 (默认: false)
  consumers[].discoverDepth   自动扫描最大深度 (默认: 5)

环境变量:
  NUGET_API_KEY       NuGet.org API Key (推送必需)
  OBFUSCAR_PATH       obfuscar.console 路径 (默认: PATH 中查找)
""")


if __name__ == "__main__":
    main()
