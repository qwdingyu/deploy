#!/usr/bin/env python3
"""
ZL.Pipeline.Cli — 统一发布流水线 CLI 工具

集中管理所有项目的：build → pack → obfuscate → replace-dll → api-compare → verify-nuget → push

用法:
  zl-pipeline publish [--dry-run]       # 完整发布流水线
  zl-pipeline verify                     # 运行全部验证（不推送）
  zl-pipeline check <包名> <版本>        # 验证已发布的 NuGet 包
  zl-pipeline init                       # 在当前项目生成 pipeline.json
  zl-pipeline list-config                # 列出所有可配置项
  zl-pipeline --help                     # 显示帮助

配置文件:
  1. pipeline.json (项目根目录, 推荐)
  2. --config <path> (指定配置文件)

环境变量:
  NUGET_API_KEY      NuGet.org API Key
  OBFUSCAR_PATH      obfuscar.console 路径 (默认: "obfuscar.console")
"""
import argparse
import json
import os
import subprocess
import sys
import re
from pathlib import Path
from datetime import datetime

# ============================================================================
# 工具路径
# ============================================================================
TOOL_DIR = Path(__file__).parent.resolve()
SCRIPTS_DIR = TOOL_DIR / "scripts"
SCHEMAS_DIR = TOOL_DIR / "schemas"

# ============================================================================
# 配置模型
# ============================================================================
DEFAULT_CONFIG = {
    "$schema": "https://raw.githubusercontent.com/qwdingyu/ZL.Pipeline/main/schemas/pipeline-schema.json",
    "version": "1.0",
    "projects": [],
    "obfuscarConfig": "obfuscar.xml",
    "nugetSource": "https://api.nuget.org/v3/index.json",
    "publishTimeout": 120,
    "dryRun": False
}


def load_config(config_path: str = None) -> dict:
    """加载 pipeline.json 配置"""
    if config_path:
        path = Path(config_path)
    else:
        path = Path.cwd() / "pipeline.json"

    if not path.exists():
        print(f"[ERROR] 配置文件不存在: {path}")
        print(f"[HINT]  运行 'zl-pipeline init' 生成")
        sys.exit(1)

    with open(path) as f:
        cfg = json.load(f)

    # 合并默认值
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)

    return cfg


# ============================================================================
# 工具函数
# ============================================================================
PASS = 0
FAIL = 0


def log(msg):
    print(f"  [INFO]  {msg}")


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS]  {msg}")


def fail(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL]  {msg}")


def run(cmd, **kwargs):
    """执行命令并返回结果，带超时保护和自动重试

    关键改进：当 capture_output=True 时，依然实时流式输出 stdout/stderr，
    防止因长时间无输出（如 dotnet build 55s）导致 bash idle timeout 杀进程。
    """
    dry_run = kwargs.pop("dry_run", False)
    timeout = kwargs.pop("timeout", 300)  # 默认超时 300 秒
    retry = kwargs.pop("retry", 0)       # 重试次数
    capture_output = kwargs.pop("capture_output", None)  # 先取出，自己处理流式
    text = kwargs.pop("text", True)  # 捕获 text 参数，Popen 不再从 kwargs 取

    if dry_run:
        print(f"  [DRYRUN] $ {' '.join(cmd) if isinstance(cmd, list) else cmd}")
        class MockResult:
            returncode = 0
            stdout = ""
            stderr = ""
        return MockResult()

    for attempt in range(retry + 1):
        try:
            if capture_output:
                # 流式模式：实时打印输出，同时捕获
                import subprocess as sp
                proc = sp.Popen(
                    cmd,
                    stdout=sp.PIPE, stderr=sp.PIPE,
                    text=text, bufsize=1,
                    **kwargs
                )
                stdout_lines = []
                stderr_lines = []
                # 流式读取 stdout
                for line in iter(proc.stdout.readline, ''):
                    if line:
                        stdout_lines.append(line)
                        print(line, end='', flush=True)
                # 流式读取 stderr
                for line in iter(proc.stderr.readline, ''):
                    if line:
                        stderr_lines.append(line)
                        print(line, end='', flush=True, file=sys.stderr)
                proc.wait(timeout=timeout)
                stdout_str = ''.join(stdout_lines)
                stderr_str = ''.join(stderr_lines)
                result = sp.CompletedProcess(cmd, proc.returncode, stdout_str, stderr_str)
            else:
                result = subprocess.run(cmd, timeout=timeout, **kwargs)

            if result.returncode == 0:
                return result
            if attempt < retry:
                print(f"  [RETRY]  第 {attempt+1}/{retry} 次失败，重试中... (rc={result.returncode})")
        except subprocess.TimeoutExpired:
            if attempt < retry:
                print(f"  [TIMEOUT] 第 {attempt+1}/{retry} 次超时 ({timeout}s)，重试中...")
            else:
                print(f"  [TIMEOUT] 命令执行超过 {timeout}s，已终止")
                class FailedResult:
                    returncode = -1
                    stdout = ""
                    stderr = f"TIMEOUT: 超过 {timeout}s"
                return FailedResult()
    return result


def step(num, title, cfg=None):
    """打印步骤标题"""
    if cfg and cfg.get("dryRun"):
        prefix = "[DRYRUN] "
    else:
        prefix = ""
    print(f"\n=== {prefix}步骤 {num}: {title} ===")


def get_package_id(proj_dir, proj):
    """从 csproj 获取 PackageId，如果没有则用 name"""
    csproj_path = Path(proj_dir) / proj["csproj"]
    package_id = proj["name"]
    if csproj_path.exists():
        with open(csproj_path) as f:
            content = f.read()
        m = re.search(r'<PackageId[^>]*>(.*?)</PackageId>', content)
        if m:
            package_id = m.group(1).strip()
    return package_id


# ============================================================================
# 子命令实现
# ============================================================================

def cmd_init(args):
    """在项目根目录生成 pipeline.json"""
    config_path = Path.cwd() / "pipeline.json"
    if config_path.exists():
        print(f"[WARN]  {config_path} 已存在")
        resp = input("      覆盖? [y/N] ")
        if resp.lower() != "y":
            print("[SKIP]  已取消")
            return

    # 探测项目中的 csproj 文件
    csproj_files = list(Path.cwd().rglob("*.csproj"))
    # 排除 test/perf/e2e 项目
    projects = []
    for csproj in csproj_files:
        name = csproj.stem
        # 排除测试/性能/基准/E2E/示例项目
        if any(x in name.lower() for x in ["test", "perf", "e2e", "bench", "benchmark", "demo", "sample"]):
            continue
        # 排除有特定输出类型的项目（如控制台应用）
        with open(csproj) as f:
            csproj_content = f.read()
        if '<OutputType>Exe</OutputType>' in csproj_content or '<OutputType>WinExe</OutputType>' in csproj_content:
            continue
        # 判断是否有 pack 条件
        projects.append({
            "name": name,
            "csproj": str(csproj.relative_to(Path.cwd())),
            "obfuscate": True,
            "includeDependencies": []
        })

    config = {
        "$schema": "https://raw.githubusercontent.com/qwdingyu/ZL.Pipeline/main/schemas/pipeline-schema.json",
        "version": "1.0",
        "projects": projects,
        "obfuscarConfig": "obfuscar.xml",
        "nugetSource": "https://api.nuget.org/v3/index.json",
        "publishTimeout": 120,
        "dryRun": False
    }

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"[DONE]  已生成 {config_path}")
    print(f"       发现 {len(projects)} 个库项目")
    print(f"[HINT]  检查并编辑 pipeline.json 确认配置正确")
    print(f"[HINT]  然后运行: zl-pipeline publish")


def cmd_publish(args):
    """完整发布流水线"""
    cfg = load_config(args.config)
    dry_run = args.dry_run or cfg.get("dryRun", False)
    version = args.version

    # 禁用 MSBuild 节点重用，防止顺序编译时 MSB4166 子节点崩溃
    os.environ["MSBUILDDISABLENODEREUSE"] = "1"

    if dry_run:
        print("=" * 60)
        print("  DRY RUN 模式 — 仅验证，不推送")
        print("=" * 60)

    # 检查必要工具
    check_env(cfg)

    projects = cfg.get("projects", [])
    if not projects:
        fail("pipeline.json 中未定义 projects")
        return

    proj_dir = os.path.dirname(os.path.abspath(args.config)) if args.config else str(Path.cwd())
    artifacts_dir = Path(proj_dir) / "artifacts"
    obfuscated_dir = Path(proj_dir) / "obfuscated"

    # ====================================================================
    # 步骤 1: Clean Build
    # ====================================================================
    step(1, "Clean Build", cfg)
    for proj in projects:
        csproj = Path(proj_dir) / proj["csproj"]
        if not csproj.exists():
            fail(f"csproj 不存在: {csproj}")
            continue
        result = run(
            ["dotnet", "build", str(csproj), "-c", "Release", "--nologo", "-v", "q"],
            capture_output=True, text=True, dry_run=dry_run,
            timeout=300, retry=1
        )
        if dry_run or result.returncode == 0:
            ok(f"{proj['name']} build OK")
        else:
            print(result.stdout + result.stderr)
            fail(f"{proj['name']} build FAILED")
            if args.stop_on_error:
                sys.exit(1)

    # ====================================================================
    # 步骤 2: Pack NuGet
    # ====================================================================
    step(2, f"Pack NuGet (version={version})", cfg)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    for proj in projects:
        csproj = Path(proj_dir) / proj["csproj"]
        if not csproj.exists():
            continue

        result = run(
            ["dotnet", "pack", str(csproj), "-c", "Release", "--nologo",
             "-o", str(artifacts_dir),
             f"-p:PackageVersion={version}",
             "-v", "q"],
            capture_output=True, text=True, dry_run=dry_run,
            timeout=600, retry=2  # 打包易因 MSBuild 节点问题失败，重试 2 次
        )

        nupkg_path = artifacts_dir / f"{get_package_id(proj_dir, proj)}.{version}.nupkg"
        if dry_run:
            ok(f"{proj['name']}.{version}.nupkg (dry-run)")
        elif result.returncode == 0 and nupkg_path.exists():
            size = nupkg_path.stat().st_size
            ok(f"{proj['name']}.{version}.nupkg ({size // 1024}K)")
        else:
            print(result.stdout + result.stderr)
            fail(f"{proj['name']} pack FAILED")
            if args.stop_on_error:
                sys.exit(1)

    # ====================================================================
    # 检查是否需要混淆
    # ====================================================================
    obfuscar_available = check_obfuscar()
    obfuscate_projs = [p for p in projects if p.get("obfuscate", True) and obfuscar_available]

    if not obfuscate_projs:
        log("没有需要混淆的项目或 obfuscar.console 未安装，跳过混淆")
        # 直接跳到验证和推送
        do_push(args, cfg, version, proj_dir, artifacts_dir)
        print_report(len(projects), obfuscated=False)
        return

    # ====================================================================
    # 步骤 3: dotnet publish -o (准备 Obfuscar 依赖集)
    # ====================================================================
    step(3, "dotnet publish -o (准备依赖集)", cfg)
    for proj in projects:
        if proj.get("obfuscate", True) != True:
            continue
        csproj = Path(proj_dir) / proj["csproj"]
        pub_dir = obfuscated_dir / proj["name"] / "publish"
        result = run(
            ["dotnet", "publish", str(csproj), "-c", "Release", "--nologo",
             "-o", str(pub_dir), "-v", "q"],
            capture_output=True, text=True, dry_run=dry_run,
            timeout=300, retry=1
        )
        if dry_run or result.returncode == 0:
            ok(f"{proj['name']} publish -o OK")
        else:
            fail(f"{proj['name']} publish FAILED")
            if args.stop_on_error:
                sys.exit(1)

    # ====================================================================
    # 步骤 4: Obfuscar 混淆
    # ====================================================================
    step(4, "Obfuscar 混淆", cfg)
    for proj in obfuscate_projs:
        name = proj["name"]
        pub_dir = obfuscated_dir / name / "publish"
        out_dir = obfuscated_dir / name

        # 在 dry-run 模式下，如果源 DLL 不存在则优雅跳过
        src_dll = pub_dir / f"{name}.dll"
        if not src_dll.exists():
            if dry_run:
                log(f"{name}: 源 DLL 不存在 (dry-run, 跳过)")
                continue
            fail(f"{name}: 源 DLL 不存在: {src_dll}")
            continue

        # 动态生成每项目的 obfuscar XML 配置
        temp_xml = Path(proj_dir) / f"obfuscar.{name}.xml"
        xml_content = f"""<?xml version='1.0' encoding='utf-8'?>
<Obfuscator>
  <Var name='InPath' value='{pub_dir}' />
  <Var name='OutPath' value='{out_dir}' />
  <Var name='KeepPublicApi' value='true' />
  <Var name='HidePrivateApi' value='true' />
  <Var name='UseUnicodeNames' value='true' />
  <Module file='$(InPath)/{name}.dll' />
</Obfuscator>"""
        with open(temp_xml, "w") as f:
            f.write(xml_content)

        result = run(
            ["obfuscar.console", str(temp_xml)],
            capture_output=True, text=True, dry_run=dry_run,
            cwd=str(pub_dir),
            timeout=300, retry=1  # Obfuscar 可能处理大量 DLL 耗时较长
        )

        # 清理临时 XML
        if not dry_run:
            temp_xml.unlink(missing_ok=True)

        out_dll = out_dir / f"{name}.dll"
        if dry_run:
            ok(f"{name} obfuscation (dry-run)")
        elif result.returncode == 0 and out_dll.exists():
            ok(f"{name} obfuscation OK")
        else:
            fail(f"{name} obfuscation FAILED")
            log(result.stdout[-1000:] if result.stdout else "(no output)")
            if args.stop_on_error:
                sys.exit(1)

    # ====================================================================
    # 步骤 5: 替换 nupkg 中的 DLL
    # ====================================================================
    step(5, "替换 nupkg 中的 DLL", cfg)
    replace_script = SCRIPTS_DIR / "replace-nupkg-dll.py"
    for proj in obfuscate_projs:
        name = proj["name"]
        nupkg_path = artifacts_dir / f"{get_package_id(proj_dir, proj)}.{version}.nupkg"
        obf_dll = obfuscated_dir / name / f"{name}.dll"

        if not nupkg_path.exists():
            if dry_run:
                log(f"nupkg 不存在 (dry-run, 跳过): {nupkg_path}")
                continue
            fail(f"nupkg 不存在: {nupkg_path}")
            continue
        if not obf_dll.exists():
            if dry_run:
                log(f"混淆 DLL 不存在 (dry-run, 跳过): {obf_dll}")
                continue
            fail(f"混淆 DLL 不存在: {obf_dll}")
            continue

        # 自动检测 TFM
        csproj_path = Path(proj_dir) / proj["csproj"]
        tfm = "net8.0"
        if csproj_path.exists():
            with open(csproj_path) as f:
                content = f.read()
            m = re.search(r'<TargetFramework[^>]*>(.*?)</TargetFramework>', content)
            if m:
                tfm = m.group(1).strip()

        result = run(
            [sys.executable, str(replace_script), str(nupkg_path), str(obf_dll), tfm],
            capture_output=True, text=True, dry_run=dry_run,
            timeout=120, retry=1  # 替换操作涉及 zip 解压/压缩，超时/重试保护
        )
        if dry_run:
            ok(f"{name} nupkg updated (dry-run)")
        elif result.returncode == 0:
            ok(f"{name} nupkg updated")
        else:
            fail(f"{name} nupkg replace FAILED")
            log(result.stdout + result.stderr)

    # ====================================================================
    # 步骤 6: API 完整性对比
    # ====================================================================
    step(6, "API 完整性对比", cfg)
    api_compare_script = SCRIPTS_DIR / "api-compare.py"
    for proj in obfuscate_projs:
        name = proj["name"]
        nupkg_path = artifacts_dir / f"{get_package_id(proj_dir, proj)}.{version}.nupkg"
        obf_dll = obfuscated_dir / name / f"{name}.dll"

        if not nupkg_path.exists() or not obf_dll.exists():
            if dry_run:
                log(f"{name}: nupkg/混淆 DLL 不存在 (dry-run, 跳过 API 对比)")
                continue
            continue

        result = run(
            [sys.executable, str(api_compare_script), str(nupkg_path), str(obf_dll)],
            capture_output=True, text=True, dry_run=dry_run,
            timeout=120, retry=1  # API 对比涉及 nupkg 解压+反编译，超时/重试保护
        )
        if dry_run:
            ok(f"{name} API intact (dry-run)")
        elif result.returncode == 0:
            ok(f"{name} API intact (public types preserved)")
        else:
            fail(f"{name} API 对比 FAILED")

    # ====================================================================
    # 步骤 7: 混淆强度统计
    # ====================================================================
    step(7, "混淆强度统计", cfg)
    for proj in obfuscate_projs:
        name = proj["name"]
        mapping_file = obfuscated_dir / name / "Mapping.txt"
        if mapping_file.exists():
            with open(mapping_file) as f:
                lines = f.readlines()
            renamed = sum(1 for l in lines if l.strip() and "->" in l)
            ok(f"{name}: renamed_types={renamed} total_lines={len(lines)}")
        elif dry_run:
            log(f"{name}: Mapping.txt not found (dry-run, 跳过)")
        else:
            log(f"{name}: Mapping.txt not found")

    # ====================================================================
    # 步骤 8: 推送 NuGet
    # ====================================================================
    do_push(args, cfg, version, proj_dir, artifacts_dir, obfuscate_projs)

    # ====================================================================
    # 报告
    # ====================================================================
    print_report(len(projects), obfuscated=True)


def cmd_verify(args):
    """运行全部验证（不推送），dry-run 模式"""
    args.dry_run = True
    cmd_publish(args)


def cmd_check(args):
    """验证已发布的 NuGet 包是否包含混淆 DLL"""
    package_name = args.package
    version = args.version
    tfm = args.tfm or "net8.0"
    verify_script = SCRIPTS_DIR / "verify-nuget-obfuscation.sh"
    result = run(
        ["bash", str(verify_script), package_name, version, tfm],
        dry_run=False,
        timeout=120, retry=1  # 下载 nupkg + 解压 + 反编译，超时/重试保护
    )
    sys.exit(result.returncode)


def cmd_list_config(args):
    """显示所有可配置项"""
    print("""
pipeline.json 配置项:

  version             配置版本 (当前: 1.0)
  projects            项目列表 (数组)

  projects[].name             项目名 (必填)
  projects[].csproj           csproj 路径 (必填, 相对于项目根目录)
  projects[].obfuscate        是否混淆 (默认: true)
  projects[].obfuscarConfig   自定义 obfuscar.xml 路径 (可选)
  projects[].includeDependencies  额外包含的依赖 DLL 列表 (可选)

  obfuscarConfig      默认 obfuscar.xml 路径 (默认: obfuscar.xml)
  nugetSource          NuGet 源 (默认: https://api.nuget.org/v3/index.json)
  publishTimeout       推送超时秒数 (默认: 120)
  dryRun               全局 dry-run 模式 (默认: false)

  consumers            下游消费项目列表 (数组, 可选)
  consumers[].name           消费项目名称 (必填)
  consumers[].path           项目根目录 (必填, 绝对路径)
  consumers[].cpmFile        Directory.Packages.props 相对路径 (默认: Directory.Packages.props)
  consumers[].buildTarget    编译验证目标 csproj (可选)
  consumers[].autoCommit     是否自动 git commit+push (默认: false)

环境变量:
  NUGET_API_KEY       NuGet.org API Key (必填)
  OBFUSCAR_PATH       obfuscar.console 路径 (默认: PATH 中查找)
""")


# ============================================================================
# 下游消费项目同步
# ============================================================================

def _find_cpm_file(consumer_root: Path) -> Path | None:
    """在消费项目根目录及上级目录中查找 Directory.Packages.props"""
    for p in [consumer_root, consumer_root.parent]:
        candidate = p / "Directory.Packages.props"
        if candidate.exists():
            return candidate
    return None


def _update_cpm_version(cpm_path: Path, package_id: str, new_version: str) -> bool:
    """更新 Directory.Packages.props 中指定包的版本号，返回是否找到并更新"""
    content = cpm_path.read_text(encoding="utf-8")
    pattern = rf'(PackageVersion Include="{re.escape(package_id)}"\s+Version=")([^"]+)(")'
    match = re.search(pattern, content)
    if not match:
        return False
    old_version = match.group(2)
    if old_version == new_version:
        return True  # already up to date
    new_content = re.sub(pattern, rf'\g<1>{new_version}\3', content)
    cpm_path.write_text(new_content, encoding="utf-8")
    return True


def cmd_sync_consumers(args):
    """同步下游消费项目的包版本"""
    cfg = load_config(args.config)
    version = args.version
    dry_run = args.dry_run or cfg.get("dryRun", False)

    proj_dir = os.path.dirname(os.path.abspath(args.config)) if args.config else str(Path.cwd())

    # 获取所有已发布的包 ID
    artifacts_dir = Path(proj_dir) / "artifacts"
    package_ids = []
    for proj in cfg.get("projects", []):
        pid = get_package_id(proj_dir, proj)
        nupkg = artifacts_dir / f"{pid}.{version}.nupkg"
        if nupkg.exists():
            package_ids.append(pid)
        else:
            log(f"警告: 未找到 {pid}.{version}.nupkg，跳过")

    if not package_ids:
        fail(f"未找到任何 {version} 版本的 nupkg 文件")
        return

    consumers = cfg.get("consumers", [])
    if not consumers:
        fail("pipeline.json 中未配置 consumers，请添加下游消费项目配置")
        log("示例:")
        log('  "consumers": [{"name": "tmom", "path": "/path/to/tmom"}]')
        return

    step(0, f"同步下游消费项目 (version={version})", cfg)

    total_updated = 0
    total_consumers = 0

    for consumer in consumers:
        cname = consumer["name"]
        cpath = Path(consumer["path"])
        if not cpath.exists():
            fail(f"消费项目路径不存在: {cpath}")
            continue

        total_consumers += 1
        cpm_file = _find_cpm_file(cpath)
        if cpm_file is None:
            custom_cpm = consumer.get("cpmFile")
            if custom_cpm:
                cpm_file = cpath / custom_cpm
            else:
                fail(f"在 {cpath} 中未找到 Directory.Packages.props")
                continue
        if not cpm_file.exists():
            fail(f"CPM 文件不存在: {cpm_file}")
            continue

        log(f"更新 {cname}: {cpm_file}")
        consumer_updated = 0
        for pid in package_ids:
            if _update_cpm_version(cpm_file, pid, version):
                consumer_updated += 1
                if dry_run:
                    log(f"  [DRYRUN] {pid} -> {version}")
                else:
                    ok(f"  {pid} -> {version}")
            else:
                log(f"  [SKIP] {pid} 未在 {cname} 的 CPM 中定义")
        total_updated += consumer_updated

        # 编译验证
        build_target = consumer.get("buildTarget")
        if build_target:
            csproj = cpath / build_target
            if csproj.exists():
                log(f"编译验证 {cname}...")
                result = run(
                    ["dotnet", "build", str(csproj), "-c", "Release", "--nologo", "-v", "q"],
                    capture_output=True, text=True, dry_run=dry_run,
                    timeout=300, retry=1
                )
                if dry_run or result.returncode == 0:
                    ok(f"{cname} 编译通过")
                else:
                    print(result.stdout + result.stderr)
                    fail(f"{cname} 编译失败")

        # 自动 git commit + push
        auto_commit = consumer.get("autoCommit", False)
        if auto_commit and not dry_run and consumer_updated > 0:
            log(f"Git commit {cname}...")
            result = run(
                ["git", "add", str(cpm_file)],
                cwd=str(cpath), capture_output=True, text=True,
                timeout=30, retry=0
            )
            if result.returncode == 0:
                result = run(
                    ["git", "commit", "-m", f"chore: bump ZL packages to {version}"],
                    cwd=str(cpath), capture_output=True, text=True,
                    timeout=30, retry=0
                )
                if result.returncode == 0:
                    ok(f"{cname} committed")
                    result = run(
                        ["git", "push"],
                        cwd=str(cpath), capture_output=True, text=True,
                        timeout=60, retry=1
                    )
                    if result.returncode == 0:
                        ok(f"{cname} pushed")
                    else:
                        fail(f"{cname} push 失败: {result.stderr}")
                else:
                    log(f"{cname} commit 失败 (可能无变更): {result.stderr}")

    print()
    print("=" * 60)
    if dry_run:
        print("  DRY RUN 完成")
    else:
        print("  同步完成")
    print(f"  消费项目: {total_consumers}")
    print(f"  更新包数: {total_updated}")
    print("=" * 60)


# ============================================================================
# 辅助函数
# ============================================================================

def check_env(cfg):
    """检查必要工具和环境"""
    print("\n=== 步骤 0: 环境检查 ===")

    # dotnet
    result = subprocess.run(["dotnet", "--version"], capture_output=True, text=True, timeout=15)
    if result.returncode == 0:
        ok(f"dotnet {result.stdout.strip()}")
    else:
        fail("dotnet not found")

    # python3
    result = subprocess.run([sys.executable, "--version"], capture_output=True, text=True, timeout=15)
    if result.returncode == 0:
        ok(f"python3 {result.stdout.strip()}")
    else:
        fail("python3 not found")

    # 禁用 MSBuild 节点重用（防止 MSB4166 子节点崩溃）
    os.environ["MSBUILDDISABLENODEREUSE"] = "1"
    ok("MSBUILDDISABLENODEREUSE=1 (防止 MSBuild 节点崩溃)")

    # 工具脚本
    for script in ["replace-nupkg-dll.py", "api-compare.py", "verify-nuget-obfuscation.sh"]:
        path = SCRIPTS_DIR / script
        if path.exists():
            ok(f"{script}")
        else:
            fail(f"{script} not found")

    # Obfuscar
    check_obfuscar(report=True)

    print()


def check_obfuscar(report=False):
    """检查 obfuscar.console 是否可用"""
    result = subprocess.run(
        ["which", "obfuscar.console"],
        capture_output=True, text=True, timeout=15
    )
    available = result.returncode == 0

    if report:
        if available:
            ok("obfuscar.console found (混淆已启用)")
        else:
            log("obfuscar.console not found (跳过混淆)")

    return available


def do_push(args, cfg, version, proj_dir, artifacts_dir, obfuscate_projs=None):
    """推送 NuGet 包"""
    step(8, "推送 NuGet", cfg)

    # dry-run 模式跳过推送
    dry_run = False
    dry_run = dry_run or cfg.get("dryRun", False)
    dry_run = dry_run or getattr(args, 'dry_run', False)
    if dry_run:
        log("dry-run 模式，跳过推送")
        return

    api_key = os.environ.get("NUGET_API_KEY")
    if not api_key:
        fail("NUGET_API_KEY 未设置")
        log("请设置环境变量: export NUGET_API_KEY=<your-key>")
        return

    nuget_source = cfg.get("nugetSource", "https://api.nuget.org/v3/index.json")

    nupkg_files = sorted(artifacts_dir.glob(f"*.{version}.nupkg"))
    if not nupkg_files:
        fail(f"找不到 *.{version}.nupkg 在 {artifacts_dir}")
        return

    for nupkg in nupkg_files:
        result = run(
            ["dotnet", "nuget", "push", str(nupkg),
             "-k", api_key,
             "-s", nuget_source,
             "--skip-duplicate"],
            capture_output=True, text=True, dry_run=cfg.get("dryRun", args.dry_run),
            timeout=120, retry=1  # 推送可能因网络超时，重试 1 次
        )
        if result.returncode == 0:
            ok(f"{nupkg.name} pushed")
        else:
            fail(f"{nupkg.name} push FAILED")
            log(result.stdout + result.stderr)


def print_report(total, obfuscated=False):
    """打印最终报告"""
    print(f"""
{'=' * 60}
  发布验证报告
{'=' * 60}

  总测试: {PASS + FAIL}
  通过: {PASS}
  失败: {FAIL}
  混淆: {'已启用' if obfuscated else '未启用 (obfuscar.console 未安装)'}

  {'✅ 所有验证通过，可以发布' if FAIL == 0 else '❌ 存在失败项，请修复后重试'}
""")


# ============================================================================
# 主入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="ZL.Pipeline.Cli — 统一发布流水线工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 在当前项目运行完整发布流水线
  zl-pipeline publish 1.0.1

  # 仅验证不推送
  zl-pipeline publish 2.0.0 --dry-run

  # 检查已发布的 NuGet 包是否混淆
  zl-pipeline check PlcSimulator.Core 1.0.1

  # 在新项目中生成 pipeline.json
  zl-pipeline init

  # 发布后同步下游消费项目
  zl-pipeline sync-consumers 1.0.3
  zl-pipeline sync-consumers 1.0.3 --dry-run
        """
    )
    parser.add_argument("--config", "-c", help="pipeline.json 路径 (默认: 当前目录)")
    parser.add_argument("--stop-on-error", action="store_true", help="遇到错误立即停止")

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # publish
    pub_parser = subparsers.add_parser("publish", help="完整发布流水线")
    pub_parser.add_argument("version", help="版本号, e.g. 1.0.1")
    pub_parser.add_argument("--dry-run", "-n", action="store_true", help="仅验证不推送")
    pub_parser.add_argument("--stop-on-error", action="store_true", help="遇到错误立即停止")

    # verify (dry-run 的别名，需要传版本号)
    verify_parser = subparsers.add_parser("verify", help="运行全部验证（不推送）")
    verify_parser.add_argument("version", help="版本号, e.g. 1.0.1")

    # check
    check_parser = subparsers.add_parser("check", help="验证已发布的 NuGet 包")
    check_parser.add_argument("package", help="包名")
    check_parser.add_argument("version", help="版本号")
    check_parser.add_argument("--tfm", "-t", default="net8.0", help="目标框架 (默认: net8.0)")

    # init
    subparsers.add_parser("init", help="在当前项目生成 pipeline.json")

    # list-config
    subparsers.add_parser("list-config", help="列出所有可配置项")

    # sync-consumers
    sync_parser = subparsers.add_parser("sync-consumers", help="同步下游消费项目的包版本")
    sync_parser.add_argument("version", help="版本号, e.g. 1.0.3")
    sync_parser.add_argument("--dry-run", "-n", action="store_true", help="仅验证不修改")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "publish":
        cmd_publish(args)
    elif args.command == "verify":
        cmd_verify(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "list-config":
        cmd_list_config(args)
    elif args.command == "sync-consumers":
        cmd_sync_consumers(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
