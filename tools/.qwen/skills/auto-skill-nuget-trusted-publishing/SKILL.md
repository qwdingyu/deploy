---
name: nuget-trusted-publishing
description: 从 NUGET_API_KEY 迁移到 nuget.org Trusted Publishing 的标准流程（GitHub Actions + NuGet/login@v1），含共享脚本 publish-all.py 的集成方式
source: auto-skill
extracted_at: '2026-06-26T07:43:04.487Z'
---

# Trusted Publishing 迁移指南

## 背景

nuget.org 正在弃用长期 API Key 模式，推荐 Trusted Publishing（基于 GitHub OIDC 的短期 token）。
API Key 目前仍可用，但已被标记为"strongly discouraged"。

## 核心概念

- **策略粒度是按 GitHub 仓库，不是按 NuGet 包**：一个 GitHub repo 的一条 workflow 文件，对应一条 Trusted Publishing 策略，允许该 workflow 推送账号名下任意包
- **一个仓库可产出多个 NuGet 包**（如 iot-sdk 一个 repo 产出 23 个包），只配一条策略
- **短期 token 有效期 1 小时**，通过 `NuGet/login@v1` 获取
- **无需在 GitHub Secrets 中存 NUGET_API_KEY**
- **`permissions: id-token: write` 必须加在 `push-to-nuget` job 上**（不是 build job），GitHub OIDC 只在有该权限的 job 中才能获取
- **共享脚本应存入公开仓库**：`publish-all.py` 放在一个公开的 deploy 工具仓库，所有产品 workflow 通过 `actions/checkout` 引用，避免跨私有仓库的权限问题

## 前置条件

- GitHub 仓库已推送到 GitHub（可以私有仓库）
- .NET SDK（推荐 8.0.x）在 GitHub Actions runner 上可用
- nuget.org 账号有包的所有权

## 迁移步骤

### 第 1 步：nuget.org 配置 Trusted Publishing 策略

1. 登录 [nuget.org/account/trusted-publishing](https://www.nuget.org/account/trusted-publishing)
2. 点 **Add policy**
3. 填写：
   - **Package Owner**: nuget.org 用户名（如 `dingyuw`）
   - **Repository Owner**: GitHub 用户名（如 `qwdingyu`）
   - **Repository**: GitHub 仓库名（如 `ZL.PlcBase`）
   - **Workflow File**: workflow 文件名（如 `publish.yml`，不含路径 `.github/workflows/`）
   - **Environment**: 可选，GitHub Actions 环境名

> **注意**：私有仓库的 policy 有 7 天激活期（pending activation），需在 7 天内成功发布一次才会永久激活。公仓库立即生效。激活期内 Trusted Publishing 不会生效。

### 第 2 步：新建/修改 publish.yml（完整模板）

> 以下模板假设 `publish-all.py` 脚本放在公开的 `deploy` 仓库的 `scripts/` 目录下。
> 如果是首次集成，请确保该仓库已改为 public。

```yaml
# ============================================================
# NuGet 发布流水线
# 触发方式: tag push v* 自动发布 / workflow_dispatch 手动触发
# 核心逻辑: 共享脚本 publish-all.py（读取 pipeline.json）
# ============================================================
name: Publish to NuGet

"on":                        # ⚠️ 必须加引号，避免 YAML 解析为布尔值 True
  push:
    tags: ['v*']
  workflow_dispatch:
    inputs:
      version:
        description: 'Package version (e.g. 2.2.1)'
        required: true
        default: '2.2.1'
      obfuscate:
        description: 'Enable Obfuscar obfuscation'
        type: boolean
        default: false
      dry-run:
        description: 'Dry run (pack only, no push)'
        type: boolean
        default: false

env:
  DOTNET_NOLOGO: true

jobs:
  build-and-pack:
    runs-on: ubuntu-latest
    outputs:
      version: ${{ steps.version.outputs.version }}
    steps:
      - uses: actions/checkout@v4

      # ⚠️ 检出 deploy 公开仓库获取 publish-all.py（私有仓库无法跨仓库 checkout）
      - name: Checkout deploy repo (shared scripts)
        uses: actions/checkout@v4
        with:
          repository: qwdingyu/deploy
          path: .pipeline
          ref: main

      - name: Setup .NET
        uses: actions/setup-dotnet@v4
        with:
          dotnet-version: '8.0.x'

      # 版本号：tag push 提取 tag 名（去掉 v），workflow_dispatch 用输入
      - name: Determine version
        id: version
        run: |
          if [ "${{ github.event_name }}" = "push" ]; then
            echo "version=${GITHUB_REF_NAME#v}" >> $GITHUB_OUTPUT
          else
            echo "version=${{ inputs.version }}" >> $GITHUB_OUTPUT
          fi

      # 安装 Obfuscar（注意包名是 Obfuscar.GlobalTool 不是 Obfuscar）
      - name: Install Obfuscar
        if: github.event_name != 'workflow_dispatch' || inputs.obfuscate == true
        run: dotnet tool install --global Obfuscar.GlobalTool --version 2.2.38

      # 核心：publish-all.py 处理 restore → build → pack → obfuscate
      # 该脚本自动读取 pipeline.json，按项目列表逐个打包
      - name: Build, pack & obfuscate
        run: |
          OBF_FLAG=""
          if [ "${{ github.event_name }}" != "push" ] && [ "${{ inputs.obfuscate }}" != "true" ]; then
            OBF_FLAG="--skip-obfuscate"
          fi
          python3 .pipeline/scripts/publish_all.py \
            --version ${{ steps.version.outputs.version }} \
            $OBF_FLAG

      - name: Upload packages
        uses: actions/upload-artifact@v4
        with:
          name: nuget-packages-${{ steps.version.outputs.version }}
          path: artifacts/packages/*.nupkg

  push-to-nuget:
    needs: build-and-pack
    runs-on: ubuntu-latest
    if: github.event_name == 'push' || (github.event_name == 'workflow_dispatch' && inputs.dry-run != true)
    permissions:
      id-token: write       # ⚠️ 必须加在 push job 上！build job 不需要
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: nuget-packages-${{ needs.build-and-pack.outputs.version }}
          path: artifacts/packages

      - name: Setup .NET
        uses: actions/setup-dotnet@v4

      # Trusted Publishing: 通过 GitHub OIDC 获取 1 小时短期 API Key
      - name: NuGet login (OIDC → temp API key)
        uses: NuGet/login@v1
        id: login
        with:
          user: <nuget.org 用户名>   # 注意：是 nuget.org 用户（策略创建者），不是 GitHub 用户名

      - name: Push to NuGet.org
        run: |
          for pkg in artifacts/packages/*.nupkg; do
            echo "  ➡ $(basename $pkg)"
            dotnet nuget push "$pkg" \
              --source https://api.nuget.org/v3/index.json \
              --api-key ${{ steps.login.outputs.NUGET_API_KEY }} \
              --skip-duplicate
          done
          echo "✅ Published version ${{ needs.build-and-pack.outputs.version }} to NuGet.org"
```

### 第 3 步：创建 publish-all.py 共享脚本

```python
#!/usr/bin/env python3
"""
ZL 统一 NuGet 发布脚本
用法: python3 scripts/publish-all.py --version 2.2.1 [--skip-obfuscate] [--local]

功能:
  1. 读取 pipeline.json 获取所有可发布项目和混淆配置
  2. 为所有项目执行 dotnet pack（统一版本号）
  3. 对标记 obfuscate: true 的项目执行 Obfuscar 混淆 + DLL 替换
  4. 生成 CI 友好的 NuGet.Config（仅 nuget.org，避免本地 feed 路径问题）
"""

import argparse, json, os, subprocess, sys, shutil, zipfile
from pathlib import Path

REPO_ROOT = Path.cwd()
PIPELINE_JSON = REPO_ROOT / "pipeline.json"
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "packages"

def load_pipeline():
    if not PIPELINE_JSON.exists():
        print(f"::error::pipeline.json 未找到")
        sys.exit(1)
    return json.loads(PIPELINE_JSON.read_text())

def ensure_ci_nuget_config():
    """生成仅含 nuget.org 的 NuGet.Config（避免本地 feed 路径问题）"""
    config = '''<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />
  </packageSources>
</configuration>'''
    (REPO_ROOT / "nuget.ci.config").write_text(config)

def get_target_frameworks(csproj_path):
    """从 csproj 提取目标框架"""
    content = Path(csproj_path).read_text()
    for tag in ["TargetFrameworks", "TargetFramework"]:
        start = content.find(f"<{tag}>")
        if start >= 0:
            end = content.find(f"</{tag}>", start)
            if end >= 0:
                return [t.strip() for t in content[start+len(tag)+2:end].split(";") if t.strip()]
    return ["net8.0"]

def replace_dll_in_nupkg(nupkg_path, dll_path, tfm):
    """替换 nupkg 中指定 TFM 的 DLL"""
    dll_name = os.path.basename(dll_path)
    tmp = nupkg_path + ".tmp"
    with zipfile.ZipFile(nupkg_path, "r") as zin:
        target = f"lib/{tfm}/{dll_name}"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                zout.writestr(item, open(dll_path, "rb").read() if item.filename == target else zin.read(item.filename))
    shutil.move(tmp, nupkg_path)

def main():
    args = parse_args()
    pipeline = load_pipeline()
    # ... restore, build, pack, obfuscate 循环（详见完整脚本）

if __name__ == "__main__":
    main()
```

> **分发策略**：publish-all.py 应复制到每个使用它的仓库的 `scripts/` 目录。不要尝试跨私有仓库引用（GitHub Actions 的 GITHUB_TOKEN 无法跨私有仓库访问）。

### 第 4 步：测试验证

```bash
# 触发 dry-run（只打包不推送）
gh workflow run publish.yml --repo <owner>/<repo> --ref main \
  -f version=2.2.1 -f obfuscate=false -f dry-run=true

# 触发正式发布
gh workflow run publish.yml --repo <owner>/<repo> --ref main \
  -f version=2.2.1 -f dry-run=false

# 打 tag 自动发布
git tag v2.2.1 && git push origin v2.2.1
```

## 常见坑点

### 坑 1：YAML 中 `on` 被解析为布尔值 True ⚠️ 最高频

**现象**：`gh workflow run` 报错 `Workflow does not have 'workflow_dispatch' trigger`

**原因**：YAML 规范中 `on`、`yes`、`true` 都是布尔值 `True` 的别名

**修复**：
```yaml
# ❌ 错误
on:
  push:
    tags: ['v*']

# ✅ 正确
"on":
  push:
    tags: ['v*']
```

### 坑 2：secrets 不可在 if 条件中使用

**现象**：`Unrecognized named-value: 'secrets'`

**原因**：GitHub Actions 中 `secrets` 上下文只允许在 `env:` 和 `run:` 块中使用

**修复**：通过 `env:` 注入，在 shell 中判断：
```yaml
- name: Push
  env:
    NUGET_API_KEY: ${{ steps.login.outputs.NUGET_API_KEY || secrets.NUGET_API_KEY }}
  run: |
    if [[ -z "$NUGET_API_KEY" ]]; then
      echo "::error::No API key available"
      exit 1
    fi
    dotnet nuget push ... -k "$NUGET_API_KEY"
```

### 坑 3：CI 环境没有本地 feed

**现象**：`NU1301: The local source '/Users/xxx/.nuget/local-feed' doesn't exist`

**原因**：NuGet.config 引用了本地路径，GitHub Actions runner 上不存在

**修复**：创建临时 `nuget.ci.config`，或在 `dotnet restore` 时用 `--source https://api.nuget.org/v3/index.json`

```yaml
- name: Restore
  run: |
    echo '<?xml version="1.0" encoding="utf-8"?>' > nuget.ci.config
    echo '<configuration><packageSources><clear />' >> nuget.ci.config
    echo '<add key="nuget.org" value="https://api.nuget.org/v3/index.json" />' >> nuget.ci.config
    echo '</packageSources></configuration>' >> nuget.ci.config
    dotnet restore --configfile nuget.ci.config
```

### 坑 4：硬编码的绝对路径项目引用

**现象**：CI 中 `The type or namespace name 'ZL' could not be found`

**原因**：csproj 中有 `<ProjectReference Include="/Users/xxx/.../other-repo/...csproj" />` 的绝对路径引用

**修复**：改成 NuGet 包引用 `<PackageReference Include="ZL.Watchdog" />`（版本由 CPM 统一管理）

### 坑 5：Obfuscar 包名不一致

**现象**：`dotnet tool install -g Obfuscar` 报错 `Package obfuscar is not a .NET tool`

**原因**：正确包名是 `Obfuscar.GlobalTool`，安装后的命令名是 `obfuscar.console`

**修复**：
```bash
dotnet tool install --global Obfuscar.GlobalTool --version 2.2.38
```

### 坑 6：API Key 已失效但流水线显示成功

**原因**：本地 pipeline 代码中 `ok=True  # 本地成功即为通过，远程失败不阻断` 吞掉了 403

**修复**：迁移到 Trusted Publishing 后不再依赖长期 Key，短期 token 1 小时后过期自动作废（无泄露风险）

### 坑 7：Trusted Publishing `user` 参数必须是策略创建者

**现象**：`Token exchange failed (HTTP 401) ... Make sure you are using the username of the policy creator`

**原因**：`NuGet/login@v1` 的 `user:` 参数必须填写创建 Trusted Publishing 策略的那个 nuget.org 账号用户名

### 坑 8：跨私有仓库 checkout

私有的 `actions/checkout@v4` 跨仓库引用时，GITHUB_TOKEN 默认不跨仓库。需要将共享脚本（如 `publish-all.py`）直接复制到每个使用它的仓库中，不要尝试用 `repository:` 参数跨仓库引用。

## 文档验证与常见缺口（接入标准文档必须经真实项目验证）

写完发布流水线接入文档后，**必须用真实项目通盘走一遍**来验证文档的完整性、准确性和可操作性。若实施过程中发现文档与实际情况存在差距，**优先更新文档**使之反映真实流程，而不是只修实施而放任文档偏离。

### 已验证的 5 个文档缺口

在 AtomPrint 首次接入共享发布流水线时，发现文档 `docs/03_NuGet发布流水线接入标准` 存在以下缺口：

1. **多 SDK 支持**：文档模板只装了 .NET 8.0 SDK，但项目可能混合 `netstandard2.0` + `net10.0`。需要展示 `setup-dotnet@v4` 的多版本安装语法（`dotnet-version: |`），且区分 build 和 push 步的 SDK 差异。

2. **csproj 发布前检查清单**：文档假定 `pipeline.json` 列好项目就能用，但至少需要检查每个 csproj 的 `<PackageId>`、`<IsPackable>`、`<GeneratePackageOnBuild>`、`<Version>`、`<PackageLicenseExpression>`、`<RepositoryUrl>` 等元数据。

3. **NU5026 警告是预期行为**：无 `.sln` 的多项目仓库，`publish-all.py` 第一次 `--no-build` pack 会找不到 DLL（NU5026），脚本会自动回退到单项目构建。文档应说明这是预期行为，不是失败。

4. **独立项目 vs ZL 生态项目**：文档大量篇幅讲 ZL 内部包版本对照、CPM 同步、Obfuscar 混淆。对于无 ZL 依赖的独立项目，这些不适用。应区分两种接入模式，分别给出最小模板。

5. **publish.yml 混淆步骤可选**：混淆安装/参数是 ZL 生态的默认需求，独立项目不需要。模板应提供两个变体（带混淆/不带混淆），或让混淆成为可选项。

### 文档中的 schema URL 错误

`pipeline.json` 示例中的 `$schema` 应指向 `qwdingyu/ZL.Pipeline`，而非 `usethink/ZL.Pipeline`。旧组织名会导致 JSON Schema 校验 404。

## API Key 回退模式（当 Trusted Publishing 未配置时）

```yaml
- name: NuGet login (OIDC → temp API key)
  uses: NuGet/login@v1
  id: login
  continue-on-error: true
  with:
    user: dingyuw

- name: Push to NuGet.org
  env:
    NUGET_API_KEY: ${{ steps.login.outputs.NUGET_API_KEY || secrets.NUGET_API_KEY }}
  run: |
    for pkg in artifacts/packages/*.nupkg; do
      dotnet nuget push "$pkg" \
        --source https://api.nuget.org/v3/index.json \
        --api-key "$NUGET_API_KEY" \
        --skip-duplicate
    done
```

## Obfuscar 混淆配置（ZL 生态标准）

| 参数 | 值 | 效果 |
|------|-----|------|
| `KeepPublicApi` | `true` | 对外 API 不变，消费者无感 |
| `HidePrivateApi` | `true` | 内部方法/成员全部混淆 |
| `HideStrings` | `true` | 字符串加密 |
| `RenameProperties/Events/Fields` | `false` | 不重命名，序列化不受影响 |
| `UseUnicodeNames` | `true` | 混淆后用 Unicode 字符命名 |

## 快速验证 key 是否有效的测试脚本

```bash
#!/usr/bin/env bash
set -euo pipefail
PKG_ID="${1:?'指定包名'}"
WORK_DIR=$(mktemp -d)
trap "rm -rf $WORK_DIR" EXIT
cat > "$WORK_DIR/$PKG_ID.csproj" <<EOF
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.0</TargetFramework>
    <PackageId>$PKG_ID</PackageId>
    <Version>0.0.1-test</Version>
  </PropertyGroup>
</Project>
EOF
dotnet pack "$WORK_DIR/$PKG_ID.csproj" -c Release -o "$WORK_DIR/out" --nologo -v q
dotnet nuget push "$WORK_DIR/out/$PKG_ID.*.nupkg" \
  --source "https://api.nuget.org/v3/index.json" \
  --api-key "$NUGET_API_KEY" \
  --skip-duplicate
```