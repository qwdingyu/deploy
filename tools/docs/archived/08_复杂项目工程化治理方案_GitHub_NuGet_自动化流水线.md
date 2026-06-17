# 复杂项目工程化治理方案：GitHub + NuGet 自动化流水线

> **文档编号**：134  
> **日期**：2026-06-04  
> **背景**：ZL.PlcBase 经历了完整的 build → obfuscate → verify → publish 链路踩坑，  
>   暴露出临时脚本不可复用、流水线断裂、错误排查困难等问题。  
>   本文档总结教训，给出可规模化推广的工程化治理方案。  
> **适用范围**：ZL.PlcBase、ZL.PlcSimulator 及后续所有 ZL 产品线项目

---

## 1. 核心原则

### 1.1 铁律：所有过程必须固化为脚本

| 原则 | 说明 | 反面案例 |
|------|------|---------|
| **No Ad-hoc Commands** | 禁止在终端临时敲命令完成关键流程 | 本次混淆流水线全程手动敲命令，脚本是事后补的 |
| **Script Once, Run Forever** | 脚本写一次，后续每次发布直接运行 | replace-nupkg-dll.py 写了 3 版才稳定 |
| **Self-Documenting** | 脚本本身就是文档，README 只需指向脚本 | 踩坑记录散落 3 个文档，难以检索 |
| **Idempotent** | 脚本可重复运行，不依赖特定前置状态 | release-verify.sh 的 cleanup 函数确保每次从零开始 |
| **Fail Fast** | 任何步骤失败立即停止，不产生部分完成的中间状态 | Obfuscar 失败后继续替换 nupkg，导致推送 400 错误 |

### 1.2 脚本层级架构

```
scripts/
├── release-verify.sh          ← 【入口脚本】一键走完完整发布流水线
│   ├── Step 0: 环境检查
│   ├── Step 1: Build
│   ├── Step 2: Pack
│   ├── Step 3: publish -o
│   ├── Step 4: Obfuscar
│   ├── Step 5: replace-nupkg-dll.py  ← 调用子脚本
│   ├── Step 6: api-compare.py        ← 调用子脚本
│   ├── Step 7: 混淆强度统计
│   ├── Step 8: 运行时验证
│   └── Step 9: 报告
│
├── api-compare.py             ← 【工具脚本】混淆前后 API 完整性对比
│   - 独立可调用
│   - 支持 --deps 参数
│   - 输出结构化结果供 shell 解析
│
├── replace-nupkg-dll.py      ← 【工具脚本】nupkg 内 DLL 替换
│   - 独立可调用
│   - 幂等操作
│   - 不修改 nuspec XML
│
├── test_plcbase.sh           ← 【测试脚本】日常开发测试
│
└── publish_nuget.sh          ← 【发布脚本】NuGet 推送（含 API Key 安全处理）
```

**设计要点**：
- **入口脚本**（release-verify.sh）编排流程，不包含业务逻辑
- **工具脚本**（api-compare.py, replace-nupkg-dll.py）独立可调用，有完整 CLI 接口
- 工具脚本之间**无耦合**，可通过命令行参数传递数据
- 每个脚本都有 shebang + 使用说明 + 错误退出码

---

## 2. 本次踩坑总结：为什么需要固化

### 2.1 问题清单

| # | 问题 | 根因 | 后果 | 固化解法 |
|---|------|------|------|---------|
| 1 | Obfuscar 找不到依赖 DLL | 用 `bin/Release/net8.0/` 而非 `dotnet publish -o` | 混淆失败，浪费 1 小时排查 | release-verify.sh Step 3 固定用 publish -o |
| 2 | replace-nupkg-dll.py 用 zip append 模式 | Python zipfile "a" 模式追加而非替换 | nupkg 出现重复文件，NuGet 400 | 改用 read-all → write-new 模式，脚本固化 |
| 3 | replace-nupkg-dll.py 修改 nuspec XML | xml.etree.ElementTree 序列化引入 ns0: 前缀 | nuspec 命名空间污染，NuGet 400 | 新版脚本完全不碰 nuspec |
| 4 | api-compare.py 在 /tmp/ 临时目录 | 临时创建，未纳入版本控制 | 每次都要重新写 | 固化到 scripts/api-compare.py |
| 5 | release-verify.sh 有 bash 语法错误 | ZL.PlcSimulator 版用了 C 三元运算符 | 脚本无法运行 | 统一用 if/else，两个项目脚本同步 |
| 6 | 混淆后未验证 API 完整性 | 没有自动化对比工具 | 可能破坏公共 API 而不自知 | api-compare.py 强制检查 |
| 7 | 混淆后未做运行时验证 | 仅检查类型数量，未实际加载 | 混淆可能破坏反射/依赖加载 | release-verify.sh Step 8 创建消费端项目实测 |
| 8 | 手动命令散落多轮对话 | 没有统一入口 | 无法复现，无法审计 | release-verify.sh 一键执行 |

### 2.2 教训

```
临时脚本的代价 = 编写时间 × 使用次数 + 调试时间 × 失败次数 + 知识流失风险

本次实际代价：
- 编写了 3 版 replace-nupkg-dll.py（2 版废弃）
- 调试了 5+ 轮 NuGet 400 错误
- api-compare.py 在 /tmp/ 创建，差点丢失
- 混淆流水线走了 4 个多小时才完全打通

如果一开始就固化：
- 1 小时写好脚本 + 测试
- 后续每次发布 15 分钟
```

---

## 3. 本地发布流水线设计

### 3.1 完整流程图

```
开发者准备发布
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  bash scripts/release-verify.sh 2.0.2 [--dry-run]           │
│                                                             │
│  ┌─ Step 0: 环境检查 ─────────────────────────────────┐    │
│  │  dotnet ✓  python3 ✓  obfuscar.console ✓           │    │
│  │  replace-nupkg-dll.py ✓  api-compare.py ✓          │    │
│  └────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─ Step 1: Clean Build ───────────────────────────────┐   │
│  │  cleanup() 删除所有中间产物                            │    │
│  │  dotnet build *.csproj -c Release (每个项目)          │    │
│  └────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─ Step 2: Pack NuGet ──────────────────────────────────┐ │
│  │  dotnet pack *.csproj -c Release --no-build           │    │
│  │  → artifacts/packages/*.nupkg                         │    │
│  └────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─ Step 3: dotnet publish -o ────────────────────────────┐│
│  │  dotnet publish *.csproj -c Release --no-build        │    │
│  │    -f net8.0 -o publish-obs/<ProjectName>/            │    │
│  │  → 完整依赖集（Obfuscar 需要）                          │    │
│  └────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─ Step 4: Obfuscar 混淆 ────────────────────────────────┐│
│  │  生成 obfuscar.<Project>.xml 配置                       │    │
│  │  obfuscar.console obfuscar.<Project>.xml              │    │
│  │  → obfuscated/<Project>/*.dll                         │    │
│  │  → obfuscated/<Project>/Mapping.txt                   │    │
│  └────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─ Step 5: 替换 nupkg ───────────────────────────────────┐│
│  │  python3 scripts/replace-nupkg-dll.py                 │    │
│  │    artifacts/packages/<Project>.x.y.z.nupkg           │    │
│  │    obfuscated/<Project>/<Project>.dll                  │    │
│  │    net8.0                                             │    │
│  │  → nupkg 内 DLL 替换为混淆版（不碰 nuspec）             │    │
│  └────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─ Step 6: API 完整性对比 ────────────────────────────────┐│
│  │  python3 scripts/api-compare.py                       │    │
│  │    publish-obs/<Project>/<Project>.dll                │    │
│  │    obfuscated/<Project>/<Project>.dll                 │    │
│  │    --deps publish-obs/<Project>                       │    │
│  │  → [OK] Public API is fully preserved                │    │
│  └────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─ Step 7: 混淆强度统计 ──────────────────────────────────┐│
│  │  解析 Mapping.txt                                      │    │
│  │  → renamed_types=N skipped=M total_renames=K          │    │
│  └────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─ Step 8: 运行时验证 ────────────────────────────────────┐│
│  │  创建临时消费端项目                                      │    │
│  │  引用混淆后 DLL + 依赖                                  │    │
│  │  dotnet build + dotnet run                             │    │
│  │  → 程序集加载 ✓ 类型实例化 ✓ 属性读写 ✓ 反射 ✓         │    │
│  └────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─ Step 9: 报告 ──────────────────────────────────────────┐│
│  │  总测试: N  通过: N  失败: 0                            │    │
│  │  ✓ 所有验证通过，可以发布 vx.y.z                        │    │
│  │  推送命令: dotnet nuget push ...                        │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
    │
    ▼ 全部通过
dotnet nuget push artifacts/packages/*.nupkg -k $NUGET_API_KEY -s https://api.nuget.org/v3/index.json
    │
    ▼ 推送成功
git tag vx.y.z && git push origin vx.y.z
```

### 3.2 质量门禁（Quality Gates）

每个 Step 都是质量门禁，任何一项失败即终止流水线：

| 门禁 | 检查内容 | 失败处理 |
|------|---------|---------|
| G0: 环境检查 | dotnet/obfuscar/python3/脚本都存在 | 立即退出，提示缺失项 |
| G1: 构建 | 0 错误 | 立即退出，显示错误信息 |
| G2: 打包 | nupkg 文件存在且大小合理 | 立即退出 |
| G3: Publish | 输出目录有完整依赖集 | 立即退出 |
| G4: 混淆 | Obfuscar 输出 "Completed" + DLL 存在 | 立即退出 |
| G5: 替换 | replace-nupkg-dll.py 返回 0 | 立即退出 |
| G6: API 对比 | api-compare.py 输出 "[OK]" | 立即退出，显示差异 |
| G7: 混淆统计 | Mapping.txt 存在 | 警告但不阻止 |
| G8: 运行时 | 临时项目 build + run 成功 | 立即退出 |

---

## 4. CI/CD 流水线设计（GitHub Actions）

### 4.1 设计原则

| 原则 | 说明 |
|------|------|
| **Local First** | 先在本地 release-verify.sh 跑通，再推到 CI |
| **CI 不发明新逻辑** | CI workflow 应尽可能复用本地脚本 |
| **Tag 驱动发布** | 只有打 tag 才触发 NuGet 推送 |
| **Dry Run 默认** | develop 分支只构建不推送 |
| **Secrets 安全** | NuGet API Key 通过 GitHub Secrets 注入，不硬编码 |
| **Artifact 可追溯** | 所有中间产物上传为 GitHub Actions Artifact |

### 4.2 publish.yml 核心流程

```yaml
# .github/workflows/publish.yml
name: Publish to NuGet

on:
  push:
    tags:
      - 'v*'          # tag 推送触发完整流水线
    branches:
      - 'main'        # main 推送只做 build+test
  workflow_dispatch:  # 支持手动触发
    inputs:
      version:
        description: 'Package version'
        required: true
        default: '2.0.0'
      dry_run:
        description: 'Dry run (no NuGet push)'
        type: boolean
        default: true

jobs:
  # ── Job 1: 构建和测试 ─────────────────────────
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-dotnet@v4
        with:
          global-json-file: global.json
      - name: Build
        run: dotnet build -c Release
      - name: Test
        run: dotnet test -c Release --no-build
      - name: Upload build artifacts
        uses: actions/upload-artifact@v4
        with:
          name: build-outputs
          path: |
            **/bin/Release/
            !**/bin/Release/**/*.pdb

  # ── Job 2: 打包 ─────────────────────────────
  pack:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-dotnet@v4
        with:
          global-json-file: global.json
      - name: Determine version
        id: version
        run: |
          if [[ "${GITHUB_REF}" == refs/tags/v* ]]; then
            echo "version=${GITHUB_REF_NAME#v}" >> $GITHUB_OUTPUT
          elif [ "${{ github.event_name }}" = "workflow_dispatch" ]; then
            echo "version=${{ inputs.version }}" >> $GITHUB_OUTPUT
          else
            echo "version=0.0.0-dev.${GITHUB_RUN_NUMBER}" >> $GITHUB_OUTPUT
          fi
      - name: Pack
        run: |
          mkdir -p artifacts/packages
          for proj in ZL.PFLite ZL.Tag ZL.PlcBase ZL.PlcBase.Bridges; do
            dotnet pack ${proj}/${proj}.csproj -c Release --no-build \
              -p:PackageVersion=${{ steps.version.outputs.version }} \
              -p:ContinuousIntegrationBuild=true \
              -o artifacts/packages
          done
      - name: Upload packages
        uses: actions/upload-artifact@v4
        with:
          name: nuget-packages
          path: artifacts/packages/*.nupkg

  # ── Job 3: 混淆 ─────────────────────────────
  obfuscate:
    needs: pack
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-dotnet@v4
        with:
          global-json-file: global.json
      - name: Download packages
        uses: actions/download-artifact@v4
        with:
          name: nuget-packages
          path: artifacts/packages
      - name: Install Obfuscar
        run: dotnet tool install -g obfuscar
      - name: Publish for Obfuscar dependencies
        run: |
          mkdir -p publish-obs
          for proj in ZL.PFLite ZL.PlcBase ZL.PlcBase.Bridges; do
            mkdir -p publish-obs/$proj
            dotnet publish ${proj}/${proj}.csproj -c Release --no-build \
              -f net8.0 -o publish-obs/$proj
          done
      - name: Run Obfuscar
        run: |
          # 复用本地脚本逻辑
          for proj in ZL.PFLite ZL.PlcBase ZL.PlcBase.Bridges; do
            # 生成配置 + 执行混淆
            ...
          done
      - name: Replace DLLs in nupkg
        run: |
          for proj in ZL.PFLite ZL.PlcBase ZL.PlcBase.Bridges; do
            python3 scripts/replace-nupkg-dll.py \
              artifacts/packages/${proj}-${VERSION}.nupkg \
              obfuscated/$proj/$proj.dll \
              net8.0
          done
      - name: API comparison
        run: |
          for proj in ZL.PFLite ZL.PlcBase ZL.PlcBase.Bridges; do
            python3 scripts/api-compare.py \
              publish-obs/$proj/$proj.dll \
              obfuscated/$proj/$proj.dll \
              --deps publish-obs/$proj
          done
      - name: Upload obfuscated packages
        uses: actions/upload-artifact@v4
        with:
          name: nuget-packages-obfuscated
          path: artifacts/packages/*.nupkg

  # ── Job 4: 推送到 NuGet ─────────────────────
  publish:
    needs: obfuscate
    runs-on: ubuntu-latest
    if: >-
      (github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')) ||
      (github.event_name == 'workflow_dispatch' && inputs.dry_run != 'true')
    steps:
      - name: Download obfuscated packages
        uses: actions/download-artifact@v4
        with:
          name: nuget-packages-obfuscated
          path: artifacts/packages
      - name: Push to NuGet.org
        run: |
          for pkg in artifacts/packages/*.nupkg; do
            dotnet nuget push "$pkg" \
              --source https://api.nuget.org/v3/index.json \
              --api-key ${{ secrets.NUGET_API_KEY }} \
              --skip-duplicate
          done
```

### 4.3 CI/CD 与本地脚本的关系

```
┌────────────────────────────────────────────────────┐
│                    本地开发                          │
│                                                    │
│  bash scripts/release-verify.sh 2.0.2 --dry-run    │
│       │                                            │
│       ▼                                            │
│  全部通过？ ──否──→ 修复问题，重新运行                 │
│       │                                            │
│       是                                           │
│       │                                            │
│       ▼                                            │
│  dotnet nuget push ... (手动推送)                    │
│  git tag v2.0.2 && git push origin v2.0.2          │
│       │                                            │
└───────┼────────────────────────────────────────────┘
        │ push tag
        ▼
┌────────────────────────────────────────────────────┐
│              GitHub Actions CI/CD                   │
│                                                    │
│  publish.yml 触发                                   │
│       │                                            │
│       ▼                                            │
│  build → pack → obfuscate → verify → publish       │
│       │                                            │
│       ▼                                            │
│  NuGet.org 发布                                     │
│                                                    │
│  ★ CI 复用本地脚本：                                 │
│    - scripts/replace-nupkg-dll.py                  │
│    - scripts/api-compare.py                        │
│    - Obfuscar 配置生成逻辑相同                       │
└────────────────────────────────────────────────────┘
```

**关键原则**：
1. 本地脚本是**单一事实来源**（Single Source of Truth）
2. CI workflow **调用**本地脚本，不重复实现逻辑
3. 本地先跑通 → 推代码 → CI 自动复现 → 消除"在我机器上能跑"问题

---

## 5. 脚本管理规范

### 5.1 脚本生命周期

```
创建 → 测试 → 纳入版本控制 → 被 release-verify.sh 引用 → 被 CI 调用
  │         │              │                      │             │
  ▼         ▼              ▼                      ▼             ▼
编写时   手动运行2-3次   git add + commit      每次发布执行    每次 push 执行
加注释   验证边界情况     代码审查               日志可查        失败即告警
```

### 5.2 脚本编写规范

```python
#!/usr/bin/env python3
"""
[一句话说明脚本用途]

用法:
    python3 scripts/<script-name>.py <参数1> <参数2> [--选项]

示例:
    python3 scripts/api-compare.py original.dll obfuscated.dll --deps ./deps

退出码:
    0 - 成功
    1 - 失败（具体原因见 stderr）
"""

import sys
import os

def main():
    # 1. 参数校验（立即失败）
    if len(sys.argv) < 3:
        print("Usage: ...", file=sys.stderr)
        sys.exit(1)

    # 2. 前置条件检查（立即失败）
    if not os.path.exists(sys.argv[1]):
        print(f"ERROR: file not found", file=sys.stderr)
        sys.exit(1)

    # 3. 核心逻辑
    try:
        result = do_work()
        print(f"OK: {result}")
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

### 5.3 Shell 脚本规范

```bash
#!/usr/bin/env bash
set -euo pipefail   # 任何错误立即退出

# 颜色常量
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

# 计数器
PASS=0
FAIL=0
TOTAL=0

# 标准化输出函数
ok()   { printf "${GREEN}[PASS]${NC}  $*\n"; PASS=$((PASS+1)); TOTAL=$((TOTAL+1)); }
fail() { printf "${RED}[FAIL]${NC}  $*\n"; FAIL=$((FAIL+1)); TOTAL=$((TOTAL+1)); }

# cleanup 函数（总是能清理）
cleanup() {
    rm -rf "$ARTIFACTS" "$PUBLISH_OBS" "$OBFUSCATED" 2>/dev/null || true
}

# 主流程：每个步骤独立，失败即退出
step "1. Build"
for proj in "${PROJS[@]}"; do
    if dotnet build ...; then
        ok "$proj"
    else
        fail "$proj"
    fi
done

# 最终报告
if [[ $FAIL -eq 0 ]]; then
    echo "All passed"
    exit 0
else
    echo "$FAIL failures"
    exit 1
fi
```

### 5.4 脚本检查清单

在将脚本纳入版本控制前，必须通过以下检查：

| # | 检查项 | Python | Shell |
|---|--------|--------|-------|
| 1 | 有 shebang | ✅ `#!/usr/bin/env python3` | ✅ `#!/usr/bin/env bash` |
| 2 | 有文档字符串/注释 | ✅ `"""..."""` | ✅ `# 用途说明` |
| 3 | 有使用示例 | ✅ `Usage:` 部分 | ✅ `# 用法:` 部分 |
| 4 | 参数校验 | ✅ `sys.exit(1)` | ✅ `set -euo pipefail` |
| 5 | 退出码规范 | ✅ 0=成功, 1=失败 | ✅ 0=成功, 非0=失败 |
| 6 | 不硬编码路径 | ✅ 用 `os.path` / 参数 | ✅ 用 `$PROJECT_DIR` |
| 7 | 不硬编码密钥 | ✅ N/A | ✅ 用 `$NUGET_API_KEY` |
| 8 | cleanup 函数 | ✅ `finally:` 块 | ✅ `trap` / 显式清理 |
| 9 | 幂等性 | ✅ 可重复运行 | ✅ cleanup 后从头开始 |
| 10 | 已在两个项目间同步 | ✅ 同一脚本 | ✅ 同一脚本 |

---

## 6. 跨项目脚本同步

### 6.1 问题

ZL.PlcBase 和 ZL.PlcSimulator 都有 `release-verify.sh`、`replace-nupkg-dll.py`、`api-compare.py`。
如果只在一个项目中修复 bug，另一个项目仍然是旧的有 bug 版本。

### 6.2 解决方案：共享脚本仓库

```
方案 A：共享 scripts 仓库（推荐）
┌─────────────────────────────────────┐
│  github.com/usethink-zl/zl-scripts  │ ← 独立脚本仓库
│                                      │
│  scripts/                            │
│  ├── api-compare.py                 │
│  ├── replace-nupkg-dll.py           │
│  ├── release-verify.template.sh     │ ← 模板，各项目填充项目列表
│  └── CHANGELOG.md                   │
└──────────┬──────────┬───────────────┘
           │          │
    git submodule   git submodule
    /symlink        /symlink
           │          │
    ZL.PlcBase/    ZL.PlcSimulator/
    scripts/ → ../zl-scripts/scripts/
```

```
方案 B：复制但加版本标记（简单但需手动同步）
在每个脚本头部加版本标记：

#!/usr/bin/env python3
# SCRIPT_VERSION=1.2.0
# SCRIPT_SOURCE=github.com/usethink-zl/zl-scripts/scripts/replace-nupkg-dll.py
# SCRIPT_CHECKSUM=sha256:abc123...
"""
Replace a DLL inside a .nupkg...
"""
```

**推荐**：先用方案 B（简单），等脚本稳定后再升级到方案 A。

### 6.3 当前状态

| 脚本 | ZL.PlcBase | ZL.PlcSimulator | 同步状态 |
|------|-----------|-----------------|---------|
| api-compare.py | ✅ v1.0 (255行) | ✅ v1.0 (255行) | ✅ 已同步 |
| replace-nupkg-dll.py | ✅ v2.0 (97行, read/write模式) | ✅ v2.0 (97行) | ✅ 已同步 |
| release-verify.sh | ✅ v2.0 (358行, 完整10步) | ✅ v2.0 (279行) | ✅ 已同步 |

---

## 7. 版本管理策略

### 7.1 SemVer 语义化版本

```
主版本号.次版本号.修订号
    │         │          │
    ▼         ▼          ▼
  不兼容    新功能      Bug修复
  的 API   (向后兼容)  (向后兼容)
  变更

示例：
  2.0.0  → 首次正式发布（混淆支持）
  2.0.1  → Bug修复（replace-nupkg-dll.py 修复）
  2.1.0  → 新增功能（新 PLC 驱动）
  3.0.0  → 破坏性变更（API 重构）
```

### 7.2 版本号自动管理

```xml
<!-- Directory.Build.props -->
<PropertyGroup>
  <VersionPrefix>2.0</VersionPrefix>
  <VersionSuffix Condition="'$(GITHUB_RUN_NUMBER)' != ''">dev.$(GITHUB_RUN_NUMBER)</VersionSuffix>
  <!-- 最终版本号 = VersionPrefix[-VersionSuffix] -->
  <!-- CI 上: 2.0-dev.123 -->
  <!-- Tag 发布: 2.0.1 (显式指定) -->
</PropertyGroup>
```

### 7.3 Git Tag 规范

```bash
# 打 tag（触发 CI 发布）
git tag -a v2.0.1 -m "Release v2.0.1: fix nupkg DLL replacement"
git push origin v2.0.1

# 查看已发布版本
git tag -l 'v*' | sort -V

# 回滚（NuGet 不允许删除版本，只能发新版本）
git tag -a v2.0.2 -m "Release v2.0.2: fix regression from v2.0.1"
git push origin v2.0.2
```

---

## 8. 错误处理与回滚

### 8.1 NuGet 发布的不可逆性

**NuGet.org 不允许删除或覆盖已发布的包版本。** 这是 NuGet 的核心设计原则。

| 场景 | 处理方式 |
|------|---------|
| 发布了有 bug 的包 | 立即发布新版本（修订号+1），在包描述中标注 "Replaces x.y.z" |
| 混淆破坏了 API | 发布未混淆版本（或修复后重新混淆），修订号+1 |
| 版本号打错了 | 正确版本号重新发布，错误版本在描述中标注 "Deprecated, use x.y.z" |
| API Key 泄露 | 立即在 nuget.org 撤销 Key，生成新 Key，更新 GitHub Secrets |

### 8.2 发布前检查清单

```bash
# 发布前必须完成的检查
bash scripts/release-verify.sh 2.0.2 --dry-run

# 手动检查：
# [ ] release-verify.sh 全部通过
# [ ] git log 确认变更正确
# [ ] CHANGELOG.md 已更新
# [ ] NuGet 包描述准确
# [ ] 下游项目兼容性确认（ZL.PlcBase 变更需通知 tmom/PcStationIot）
# [ ] NUGET_API_KEY 有效
```

### 8.3 发布后验证

```bash
# 1. 验证 NuGet 包可下载
dotnet new console -n TestRef -o /tmp/testref
cd /tmp/testref
dotnet add package ZL.PlcBase -v 2.0.2

# 2. 验证可引用
cat >> TestRef.csproj << 'EOF'
<ItemGroup>
  <PackageReference Include="ZL.PlcBase" Version="2.0.2" />
</ItemGroup>
EOF

# 3. 验证可构建
dotnet build

# 4. 验证基本功能
dotnet run
```

---

## 9. 安全规范

### 9.1 Secrets 管理

| Secret | 存储位置 | 使用方式 |
|--------|---------|---------|
| NUGET_API_KEY | GitHub Secrets + ~/.zshenv | `$NUGET_API_KEY` 环境变量 |
| GitHub Token | GitHub Actions `${{ secrets.GITHUB_TOKEN }}` | 自动注入 |
| SSH Key | `~/.ssh/` + ssh-agent | `gh` CLI 认证 |

### 9.2 安全红线

| # | 规则 | 说明 |
|---|------|------|
| 1 | **永不**将 API Key 提交到代码 | 包括 commit history |
| 2 | **永不**在日志中打印完整 Key | 打码：`key: oy2i****5m` |
| 3 | **永不**在脚本中硬编码 Key | 必须用环境变量 |
| 4 | **定期**轮换 API Key | 建议每季度一次 |
| 5 | **最小权限**原则 | NuGet Key 只授权需要的包 |

### 9.3 .gitignore 必须包含

```gitignore
# Secrets
*.key
*.pfx
secrets.*
.env
.env.local

# NuGet credentials
NuGet.Config
nuget.config
**/bin/
**/obj/

# OS
.DS_Store
Thumbs.db

# IDE
.vs/
.vscode/
*.suo
*.user

# AI tools (not part of product)
.claude/
.roo/
.serena/
.omx/
.qwen/
.codex/
.tocodex/
```

---

## 10. 推广路线图

### 10.1 当前已完成

| 项目 | release-verify.sh | api-compare.py | replace-nupkg-dll.py | publish.yml | NuGet 发布 |
|------|-------------------|----------------|---------------------|-------------|-----------|
| ZL.PlcBase | ✅ | ✅ | ✅ | ✅ | ✅ v2.0.1 |
| ZL.PlcSimulator | ✅ | ✅ | ✅ | ✅ | ✅ v1.0.0 |

### 10.2 下一步推广

| 优先级 | 项目 | 操作 | 预计时间 |
|--------|------|------|---------|
| P0 | tmom/iot-sdk | 添加 release-verify.sh + publish.yml | 1 天 |
| P1 | PcStationIot | 迁移到 PackageReference + 添加 CI | 0.5 天 |
| P2 | ZL.Gear | 迁移到 PackageReference | 0.5 天 |
| P3 | ZLBox | 迁移到 PackageReference | 0.5 天 |

### 10.3 推广模板

对每个新项目，执行以下步骤：

```bash
# 1. 复制脚本
cp /0-X/ZL.PlcBase/scripts/api-compare.py     <project>/scripts/
cp /0-X/ZL.PlcBase/scripts/replace-nupkg-dll.py <project>/scripts/

# 2. 定制 release-verify.sh
#    - 修改 PROJECT_DIR
#    - 修改 PACK_PROJS 列表
#    - 修改 OBFUSCATE_NAMES 列表
#    - 修改默认版本号

# 3. 复制 publish.yml
cp /0-X/ZL.PlcBase/.github/workflows/publish.yml <project>/.github/workflows/
#    - 修改项目名列表
#    - 修改包名列表

# 4. 本地验证
cd <project>
bash scripts/release-verify.sh 1.0.0 --dry-run

# 5. 提交
git add scripts/ .github/
git commit -m "chore: add release pipeline scripts"
git push
```

---

## 11. 监控与告警

### 11.1 CI 失败告警

```yaml
# 在 publish.yml 末尾添加
notifications:
  if: failure()
  run: |
    # 发送告警（邮件/钉钉/飞书）
    curl -X POST "$WEBHOOK_URL" \
      -H 'Content-Type: application/json' \
      -d "{\"text\":\"CI 失败: $GITHUB_REPOSITORY @ $GITHUB_SHA\"}"
```

### 11.2 NuGet 下载统计

```bash
# 定期检查包下载量
# nuget.org/packages/ZL.PlcBase/2.0.1 → Statistics tab

# 或用 API
curl https://azuresearch-usnc.nuget.org/query?q=packageid:ZL.PlcBase
```

### 11.3 依赖健康度

```bash
# 检查下游项目是否及时升级
for project in tmom PcStationIot ZL.Gear; do
    cd /0-X/$project
    echo "=== $project ==="
    grep -r "ZL.PlcBase" **/*.csproj | grep "Version"
done
```

---

## 12. 总结：零事故发布checklist

```
┌────────────────────────────────────────────────────────────┐
│                    零事故发布 Checklist                       │
│                                                            │
│  发布前：                                                   │
│  ☐ release-verify.sh 全部通过（含 API 对比 + 运行时验证）     │
│  ☐ CHANGELOG.md 已更新                                     │
│  ☐ 版本号符合 SemVer                                       │
│  ☐ 下游项目兼容性确认                                       │
│  ☐ git commit 信息清晰                                     │
│                                                            │
│  发布中：                                                   │
│  ☐ git tag vx.y.z                                         │
│  ☐ git push origin vx.y.z                                 │
│  ☐ CI workflow 全部通过                                     │
│  ☐ NuGet 推送成功                                          │
│  ☐ nuget.org 页面验证                                      │
│                                                            │
│  发布后：                                                   │
│  ☐ 空项目引用验证（dotnet add package）                      │
│  ☐ 下游项目升级验证（至少一个消费方）                          │
│  ☐ 清理临时文件（artifacts/, publish-obs/, obfuscated/）     │
│  ☐ 通知相关人员                                            │
│                                                            │
│  永远不要：                                                 │
│  ✗ 跳过 release-verify.sh 直接推送                          │
│  ✗ 在代码中硬编码 API Key                                  │
│  ✗ 发布后不验证                                            │
│  ✗ 忽略 CI 失败继续操作                                    │
│  ✗ 手动修改 nuspec XML                                     │
└────────────────────────────────────────────────────────────┘
```

---

## 附录 A：脚本文件清单

| 脚本 | 位置 | 行数 | 用途 | 依赖 |
|------|------|------|------|------|
| release-verify.sh | scripts/ | ~300 | 完整发布流水线入口 | dotnet, obfuscar, python3 |
| api-compare.py | scripts/ | 255 | 混淆前后 API 对比 | dotnet, python3 |
| replace-nupkg-dll.py | scripts/ | 97 | nupkg 内 DLL 替换 | python3 |
| publish_nuget.sh | scripts/ | ~60 | NuGet 推送封装 | dotnet, $NUGET_API_KEY |
| test_plcbase.sh | scripts/ | ~40 | 日常测试 | dotnet |

## 附录 B：本次踩坑时间线

| 时间 | 事件 | 耗时 |
|------|------|------|
| T+0 | 开始混淆流水线 | - |
| T+15min | Obfuscar 依赖解析失败 | 发现 bin/ 无依赖 |
| T+45min | 切换到 publish -o，Obfuscar 成功 | 修复 |
| T+60min | 写第1版 replace-nupkg-dll.py (append模式) | 编写 |
| T+75min | NuGet 推送 400 (重复文件) | 发现 append bug |
| T+90min | 写第2版 (改nuspec模式) | 编写 |
| T+105min | NuGet 推送 400 (XML命名空间) | 发现 nuspec bug |
| T+120min | 写第3版 (不碰nuspec) | 编写 |
| T+135min | NuGet 推送成功 | 验证通过 |
| T+150min | 发现 api-compare.py 在 /tmp/ | 固化到 scripts/ |
| T+180min | 同步 ZL.PlcSimulator 脚本 | 修复 + 同步 |
| T+240min | 完成全部文档 | 总结 |

**总耗时：4 小时（如果一开始就固化脚本，预计 1 小时）**
