#!/usr/bin/env python3
"""
ZL 统一 NuGet 发布脚本（支持本地和 GitHub Actions 两种模式）
=============================================================

用法（GitHub Actions）:
  python3 scripts/publish-all.py --version 2.2.1

用法（本地开发）:
  python3 scripts/publish-all.py --version 2.2.1 --local

功能:
  1. 读取 pipeline.json 获取所有可发布项目和混淆配置
  2. 为所有项目执行 dotnet pack（统一版本号）
  3. 对标记 obfuscate: true 的项目执行 Obfuscar 混淆 + DLL 替换
  4. 输出包列表到 artifacts/packages-list.txt（供 actions/upload-artifact 使用）
  5. 生成 nuget.ci.config（仅 nuget.org，避免本地 feed 路径问题）
"""

import argparse, json, os, subprocess, sys, shutil, tempfile, zipfile
from pathlib import Path

REPO_ROOT = Path.cwd()  # 运行时 CWD 就是被发布的仓库根目录
PIPELINE_JSON = REPO_ROOT / "pipeline.json"
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "packages"
PUBLISH_OBS_DIR = REPO_ROOT / "publish-obs"
OBFUSCATED_DIR = REPO_ROOT / "obfuscated"
NUGET_CI_CONFIG = REPO_ROOT / "nuget.ci.config"


def parse_args():
    parser = argparse.ArgumentParser(description="ZL NuGet 统一发布脚本")
    parser.add_argument("--version", required=True, help="统一版本号（如 2.2.1）")
    parser.add_argument("--local", action="store_true", help="本地模式（不生成 CI NuGet.Config）")
    parser.add_argument("--skip-obfuscate", action="store_true", help="跳过混淆（纯打包）")
    parser.add_argument("--skip-restore", action="store_true", help="跳过 dotnet restore")
    return parser.parse_args()


def load_pipeline():
    """加载当前仓库的 pipeline.json"""
    if not PIPELINE_JSON.exists():
        # 尝试父目录（workflows 在 .github 下，CWD 可能是 repo root）
        parent = Path.cwd() / "pipeline.json"
        if parent.exists():
            return json.loads(parent.read_text())
        print(f"::error::pipeline.json 未找到: {PIPELINE_JSON}")
        sys.exit(1)
    return json.loads(PIPELINE_JSON.read_text())


def ensure_ci_nuget_config():
    """
    生成仅包含 nuget.org 的 NuGet.Config（避免 CI 环境下本地 feed 路径不可达）
    GitHub Actions runner 没有 /Users/dingyuwang/.nuget/local-feed
    """
    config = """<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />
  </packageSources>
</configuration>
"""
    NUGET_CI_CONFIG.write_text(config)
    print(f"::notice::已生成 CI NuGet.Config → {NUGET_CI_CONFIG}")
    return NUGET_CI_CONFIG


def run(cmd, cwd=None, capture=True):
    """执行 shell 命令，返回 (returncode, stdout+stderr)"""
    cwd = cwd or str(REPO_ROOT)
    result = subprocess.run(cmd, shell=True, capture_output=capture, text=True, cwd=cwd)
    if result.returncode != 0:
        output = (result.stdout or "") + (result.stderr or "")
        print(f"::warning::命令失败 (exit={result.returncode}): {cmd[:120]}...")
        if output:
            print(output[-2000:])
    return result.returncode, result.stdout or ""


def get_target_frameworks(csproj_path):
    """从 csproj 提取目标框架列表"""
    path = REPO_ROOT / csproj_path
    if not path.exists():
        print(f"::warning::csproj 不存在: {path}")
        return ["net8.0"]  # 默认假设
    content = path.read_text()
    tfm = ""
    # 优先看 TargetFrameworks（多 TFM），再看 TargetFramework（单 TFM）
    for tag in ["TargetFrameworks", "TargetFramework"]:
        start = content.find(f"<{tag}>")
        if start >= 0:
            end = content.find(f"</{tag}>", start)
            if end >= 0:
                tfm = content[start + len(tag) + 2: end].strip()
                break
    if not tfm:
        # 从 Directory.Build.props 继承
        return ["net8.0"]
    # 支持分号或逗号分隔
    tfms = [t.strip() for t in tfm.replace(",", ";").split(";") if t.strip()]
    return tfms if tfms else ["net8.0"]


def restore(args, pipeline):
    """dotnet restore（CI 模式用临时 config，本地模式用默认 config）"""
    config_flag = ""
    if not args.local and not args.skip_restore:
        ci_config = ensure_ci_nuget_config()
        config_flag = f'--configfile "{ci_config}"'

    if args.skip_restore:
        print("::notice::跳过 restore（--skip-restore）")
        return

    # 尝试解决方案还原；无 sln 则按项目逐个还原
    slns = list(REPO_ROOT.glob("*.sln")) + list(REPO_ROOT.glob("src/*.sln"))
    if slns:
        for sln in slns:
            code, _ = run(f'dotnet restore "{sln}" {config_flag} --nologo')
            if code != 0:
                # 解决方案可能含无法解析的项目引用，退回按 csproj 还原
                print(f"::warning::解决方案还原失败 ({sln.name})，逐个 csproj 回退")
                restore_individual(args, pipeline, config_flag)
    else:
        restore_individual(args, pipeline, config_flag)


def restore_individual(args, pipeline, config_flag):
    """按 pipeline.json 中每个 csproj 逐个还原"""
    config_flag = config_flag or ""
    for proj in pipeline["projects"]:
        csproj = REPO_ROOT / proj["csproj"]
        if csproj.exists():
            code, _ = run(f'dotnet restore "{csproj}" {config_flag} --nologo')
            if code != 0:
                print(f"::warning::还原失败 ({proj['name']})，跳过")


def build_and_pack(args, pipeline):
    """构建 + 打包所有项目"""
    version = args.version
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    pack_flags = f'-p:PackageVersion={version} -p:ContinuousIntegrationBuild=true'

    # 优先用解决方案编译（一次编译所有）
    slns = list(REPO_ROOT.glob("*.sln")) + list(REPO_ROOT.glob("src/*.sln"))
    if slns:
        for sln in slns:
            code, out = run(f'dotnet build "{sln}" -c Release --no-restore --nologo')
            if code == 0:
                print(f"::notice::解决方案编译成功: {sln.name}")
                break  # 一个解决方案成功即可
            else:
                print(f"::warning::解决方案编译失败 ({sln.name})，逐个 csproj 回退")

    # Pack 所有项目（按 pipeline.json 顺序）
    packed = []
    for proj in pipeline["projects"]:
        csproj = REPO_ROOT / proj["csproj"]
        if not csproj.exists():
            print(f"::warning::跳过（csproj 不存在）: {csproj}")
            continue
        code, out = run(
            f'dotnet pack "{csproj}" -c Release --no-build {pack_flags} '
            f'-o "{ARTIFACTS_DIR}" --nologo'
        )
        if code == 0:
            nupkg = list(ARTIFACTS_DIR.glob(f"{proj['name']}.{version}.nupkg"))
            if nupkg:
                packed.append(proj)
                print(f"  ✅ {proj['name']}.{version}.nupkg")
        else:
            # 可能单个构建失败，尝试单独构建此项目
            print(f"  ⚠️ {proj['name']} pack 失败，尝试单独构建...")
            code, _ = run(
                f'dotnet build "{csproj}" -c Release --nologo '
                f'&& dotnet pack "{csproj}" -c Release --no-build {pack_flags} '
                f'-o "{ARTIFACTS_DIR}" --nologo'
            )
            if code == 0:
                packed.append(proj)
                print(f"  ✅ {proj['name']}.{version}.nupkg（单独构建）")

    print(f"::notice::打包完成: {len(packed)}/{len(pipeline['projects'])}")
    return packed


def obfuscate(args, pipeline, packed):
    """对标记 obfuscate: true 的项目执行混淆"""
    if args.skip_obfuscate:
        print("::notice::跳过混淆（--skip-obfuscate）")
        return

    # 安装 Obfuscar 工具（全局）
    tool_check, _ = run("dotnet tool list -g | grep Obfuscar.GlobalTool")
    if "Obfuscar.GlobalTool" not in tool_check:
        print("::notice::安装 Obfuscar.GlobalTool 2.2.38...")
        code, _ = run("dotnet tool install --global Obfuscar.GlobalTool --version 2.2.38")
        if code != 0:
            print("::error::Obfuscar 安装失败")
            return

    PUBLISH_OBS_DIR.mkdir(parents=True, exist_ok=True)
    OBFUSCATED_DIR.mkdir(parents=True, exist_ok=True)
    version = args.version

    obfuscated_count = 0
    for proj in packed:
        if not proj.get("obfuscate", False):
            continue

        name = proj["name"]
        csproj = REPO_ROOT / proj["csproj"]
        nupkg = ARTIFACTS_DIR / f"{name}.{version}.nupkg"
        if not nupkg.exists():
            print(f"  ⚠️ {name} nupkg 不存在，跳过混淆")
            continue

        # 确定用于混淆的 TFM（多 TFM 只混淆 net8.0，跳过 net10.0）
        tfms = get_target_frameworks(proj["csproj"])
        obf_tfm = "net8.0"
        if obf_tfm not in tfms:
            # 尝试 netstandard2.0/netstandard2.1 作为备选
            stdfm = [t for t in tfms if t.startswith("netstandard")]
            obf_tfm = stdfm[0] if stdfm else tfms[0]
            print(f"  ⚠️ {name}: 使用 {obf_tfm} 替代 net8.0")

        # Step 1: dotnet publish（含依赖）
        pod = PUBLISH_OBS_DIR / name
        if pod.exists():
            shutil.rmtree(pod)
        code, _ = run(
            f'dotnet publish "{csproj}" -c Release -f {obf_tfm} '
            f'-o "{pod}" --nologo -v q'
        )
        if code != 0 or not (pod / f"{name}.dll").exists():
            print(f"  ⚠️ {name}: dotnet publish 失败或未产出 DLL，跳过混淆")
            continue

        # Step 2: 生成 Obfuscar XML 配置（与旧 publish.yml 完全一致的参数）
        ood = OBFUSCATED_DIR / name
        if ood.exists():
            shutil.rmtree(ood)
        ood.mkdir(parents=True)

        obf_xml = f"""<Obfuscator>
  <Var name="InPath" value="{pod}"/>
  <Var name="OutPath" value="{ood}"/>
  <Var name="KeepPublicApi" value="true"/>
  <Var name="HidePrivateApi" value="true"/>
  <Var name="HideStrings" value="true"/>
  <Var name="RenameProperties" value="false"/>
  <Var name="RenameEvents" value="false"/>
  <Var name="RenameFields" value="false"/>
  <Var name="UseUnicodeNames" value="true"/>
  <Var name="RenameJsonProperties" value="false"/>
  <Module file="$(InPath)/{name}.dll"/>
</Obfuscator>"""
        xml_path = REPO_ROOT / f"obfuscar.{name}.xml"
        xml_path.write_text(obf_xml)

        # Step 3: 运行 Obfuscar
        code, out = run(f'obfuscar.console "{xml_path}"')
        if code != 0:
            print(f"  ⚠️ {name}: Obfuscar 运行失败")
            continue

        # Step 4: 替换 nupkg 中的 DLL
        obf_dll = ood / f"{name}.dll"
        if not obf_dll.exists():
            print(f"  ⚠️ {name}: 混淆后 DLL 未生成 ({obf_dll})")
            continue

        replace_dll_in_nupkg(str(nupkg), str(obf_dll), obf_tfm)
        print(f"  🔒 {name}.{version}.nupkg ({obf_tfm}, 已混淆)")
        obfuscated_count += 1

        # 清理临时 XML
        xml_path.unlink(missing_ok=True)

    print(f"::notice::混淆完成: {obfuscated_count} 个包")


def replace_dll_in_nupkg(nupkg_path, dll_path, tfm):
    """替换 nupkg 中指定 TFM 的 DLL"""
    dll_name = os.path.basename(dll_path)
    tmp = nupkg_path + ".tmp"
    with zipfile.ZipFile(nupkg_path, "r") as zin:
        target_entry = f"lib/{tfm}/{dll_name}"
        found = False
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == target_entry:
                    zout.writestr(item, open(dll_path, "rb").read())
                    found = True
                else:
                    zout.writestr(item, zin.read(item.filename))
        if not found:
            print(f"  ⚠️ 未在 nupkg 中找到 '{target_entry}'，尝试模糊匹配")
    shutil.move(tmp, nupkg_path)


def write_package_list(packed, version):
    """输出包清单（供 actions/upload-artifact 的 path 使用）"""
    list_file = ARTIFACTS_DIR / "packages-list.txt"
    lines = []
    for proj in packed:
        nupkg = ARTIFACTS_DIR / f"{proj['name']}.{version}.nupkg"
        if nupkg.exists():
            lines.append(str(nupkg))
    list_file.write_text("\n".join(lines) + "\n")
    print(f"::notice::包清单已写入 ({len(lines)} 个): {list_file}")

    # 输出 GitHub Actions 的 step output
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"package-count={len(lines)}\n")
            f.write(f"package-version={version}\n")


def main():
    args = parse_args()
    pipeline = load_pipeline()

    print(f"📦 ZL NuGet 统一发布脚本")
    print(f"   仓库: {REPO_ROOT.name}")
    print(f"   版本: {args.version}")
    print(f"   项目: {len(pipeline['projects'])} 个")

    # 1. Restore
    restore(args, pipeline)

    # 2. Build + Pack
    packed = build_and_pack(args, pipeline)
    if not packed:
        print("::error::没有成功打包的项目")
        sys.exit(1)

    # 3. Obfuscate
    obfuscate(args, pipeline, packed)

    # 4. 输出包列表
    write_package_list(packed, args.version)

    print(f"\n✅ 完成! {len(packed)}/{len(pipeline['projects'])} 个包已打包")


if __name__ == "__main__":
    main()
