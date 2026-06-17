# ZL 产品线全局组织方案：多项目协作 + GitHub + NuGet + 自动推送

> **文档编号**：133  
> **日期**：2025-06-04  
> **核心发现**：ZL.PlcBase 不是 tmom 专属库，而是被 6+ 个独立项目共享的基础库。方案必须基于"多项目协作"而非"单项目吞并"  
> **数据来源**：对 /0-X/ 下所有 csproj 的实际扫描，非假设

---

## 1. 现状全景图（基于实际扫描）

### 1.1 ZL 产品线项目地图

```
/0-X/
├── ZL.PlcBase/           ← 【共享基础库】被 6+ 项目引用
│   ├── ZL.PFLite/           (netstandard2.0;net48;net8.0)
│   ├── ZL.Tag/              (netstandard2.0;net48;net8.0)
│   ├── ZL.PlcBase/          (netstandard2.0;net48;net7.0;net8.0)
│   ├── ZL.PlcBase.Bridges/  (netstandard2.0;net48;net7.0;net8.0)
│   └── (Tests/Bench/Demos)
│
├── ZL.PlcSimulator/      ← 【独立产品】PLC 仿真工具
│   └── src/PlcSimulator.Core, .Cli, .UI, .Grpc
│       ProtocolGateway/
│   Git: 无远程 | 已有 .github/workflows/
│
├── ZL.Simulator/          ← 【独立产品】综合仿真平台
│   └── src/Simulator.Core, .Cli, .WinForms, .Avalonia, .Grpc...
│   Git: github.com/qwdingyu/ZL.Simulator
│
├── ZL.Gear/               ← 【独立产品】齿轮检测设备
│   └── ZL.Gear.Core, .Drivers, .Engine, .Bus...
│   Git: 本地，无远程
│
├── tmom/                  ← 【核心产品】工业 IoT 平台
│   ├── iot-sdk/    (ZL.Biz.Execute, ZL.DB.Acc, ZL.EdgeService...)
│   ├── api/        (TMom.Api, TMom.Device.Runtime.Host...)
│   ├── plcbase/    ← 旧副本（已废弃，与外部 ZL.PlcBase/ 分叉）
│   ├── web/        (Vue 前端)
│   └── web_mini/   (精简前端)
│   Git: gitee.com/thgao/tmom
│
├── PcStationIot/          ← 【独立产品】PC 站点 IoT 客户端
│   Git: 本地，无远程
│
├── ZLBox/                 ← 【独立产品】ZLIot 工具箱
│   └── ZLIot.Solution/ (含自己的 ZL.PlcBase 副本)
│   Git: github.com/qwdingyu/ZLBox
│
├── ZL.ParamEditor/        ← 【独立工具】参数编辑器
│   Git: 无
│
└── ZL.BusCom/             ← 【硬件通信库】net48
    Git: 无
```

### 1.2 ZL.PlcBase 被谁引用？（关键事实）

| 消费方项目 | 引用方式 | 引用了什么 | 引用路径 |
|-----------|---------|-----------|---------|
| **tmom/iot-sdk** (6个csproj) | ProjectReference | ZL.PFLite, ZL.Tag, ZL.PlcBase | `../../../ZL.PlcBase/...` |
| **tmom/api** (5个csproj) | ProjectReference | ZL.PlcBase, ZL.Tag, ZL.PlcBase.Bridges | `../../../ZL.PlcBase/...` |
| **PcStationIot** (3个csproj) | ProjectReference | ZL.PFLite, ZL.Tag, ZL.PlcBase | `../../ZL.PlcBase/...` |
| **ZLBox** (3个csproj) | ProjectReference | ZL.PlcBase | `..\\09.ZLIot.PlcBase\\` (内部副本) |
| **Avalonia.GetStartedApp** (1个csproj) | ProjectReference | ZL.PFLite, ZL.Tag, ZL.PlcBase | `..\\..\\ZL.PlcBase\\...` |
| **tmom/api** (注释) | 注释建议 NuGet | - | 代码注释："正式环境建议使用NuGet包" |
| **ZL.Gear** (2个csproj) | DLL Reference | ZL.PlcBase, ZL.Tag, ZL.PFLite | `..\\libs\\ZL.PlcBase.dll` |
| **0-ProcessDataHub** (1个csproj) | DLL Reference | ZL.PlcBase, ZL.Tag, ZL.PFLite | `../libs/ZL.PlcBase.dll` |
| **ZL.ParamEditor** (3个版本) | ProjectReference | ZL.PFLite | `..\\ZL.PFLite\\` (条件引用) |

**总计：10+ 个独立项目依赖 ZL.PlcBase，通过 3 种不同方式引用**

### 1.3 ZL.PlcSimulator 被谁引用？

| 消费方 | 引用方式 | 引用路径 |
|--------|---------|---------|
| tmom/api/TMom.Device.Runtime.Host | ProjectReference + Protobuf | `../../../ZL.PlcSimulator/src/...` |
| PcStationIot.Tests | ProjectReference | `../../ZL.PlcSimulator/src/S7Simulator.Standalone/` |
| ZL.PlcSimulator 自身测试 | ProjectReference | 内部引用 |

### 1.4 Git 现状汇总

| 项目 | 远程仓库 | CI/CD | 分支策略 |
|------|---------|-------|---------|
| ZL.PlcBase | ❌ 无远程 | ❌ 无 | 本地 |
| ZL.PlcSimulator | ❌ 无远程 | ✅ 有 workflow（但无远程无法触发） | 本地 |
| ZL.Simulator | github.com/qwdingyu/ZL.Simulator | ❌ 无 | main |
| ZL.Gear | ❌ 无远程 | ❌ 无 | 本地 |
| tmom | gitee.com/thgao/tmom | ❌ 无 | master/develop |
| PcStationIot | ❌ 无远程 | ❌ 无 | 本地 |
| ZLBox | github.com/qwdingyu/ZLBox | ❌ 无 | main |

### 1.5 NuGet 现状

| 包名 | nuget.org 状态 |
|------|---------------|
| ZL.PFLite | ✅ 已注册 (0.0.1-placeholder) |
| ZL.Tag | ❌ 未注册 |
| ZL.PlcBase | ❌ 未注册 |
| ZL.PlcBase.Bridges | ❌ 未注册 |

---

## 2. 核心问题重新诊断

### 问题 1：共享库通过文件路径引用 → 不可移植、不可 CI

ZL.PlcBase 是共享库，但 6 个项目通过 `../../../ZL.PlcBase/...` 引用源码。这意味着：
- 只在特定目录布局下能编译
- CI/CD 无法构建（除非精确 clone 所有仓库到相对位置）
- 版本不一致风险（每个项目可能引用不同时期的代码）

### 问题 2：代码副本遍地 → 版本混乱

| 副本位置 | 文件数 | 与主库差异 |
|---------|--------|-----------|
| ZL.PlcBase/ZL.PFLite (主库) | 115 | - |
| tmom/plcbase/ZL.PFLite (旧副本) | 113 | 少 2 文件 |
| ZLBox/ZLIot.Solution/09.ZLIot.PlcBase | 独立实现 | 完全不同的文件结构 |

### 问题 3：所有项目无远程或远程分散 → 无法协作

- ZL.PlcBase、ZL.PlcSimulator、ZL.Gear、PcStationIot 无远程
- tmom 在 Gitee，ZL.Simulator 和 ZLBox 在 GitHub
- 无统一组织，无 CI/CD

### 问题 4：引用方式不统一 → 维护噩梦

同一时刻，3 种引用方式并存：
- ProjectReference（6 个项目，路径各不同）
- DLL Reference（ZL.Gear, 0-ProcessDataHub）
- 内部副本（ZLBox）

---

## 3. 方案设计：GitHub 组织 + NuGet 分发 + Multi-repo 协作

### 3.1 总体架构

```
┌──────────────────────────────────────────────────────────┐
│              GitHub 组织: usethink-zl                      │
│                                                          │
│  ┌─────────────────┐  ┌──────────────────┐              │
│  │ usethink-zl/     │  │ usethink-zl/      │              │
│  │ ZL.PlcBase       │  │ ZL.PlcSimulator   │              │
│  │                  │  │                    │              │
│  │ → ZL.PFLite      │  │ → PlcSimulator.Core│              │
│  │ → ZL.Tag         │  │ → PlcSimulator.Cli │              │
│  │ → ZL.PlcBase     │  │ → ProtocolGateway  │              │
│  │ → ZL.Bridges     │  │ → PlcSimulator.UI  │              │
│  └───────┬──────────┘  └────────┬──────────┘              │
│          │ NuGet 推送            │ NuGet 推送              │
│          ▼                       ▼                         │
│     ┌──────────────────────────────────┐                  │
│     │         nuget.org                │                  │
│     │  ZL.PFLite  ZL.Tag              │                  │
│     │  ZL.PlcBase ZL.PlcBase.Bridges  │                  │
│     └──────────────────────────────────┘                  │
│          │ PackageReference            │ PackageReference │
│          ▼                              ▼                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ usethink-zl/  │  │ usethink-zl/  │  │ usethink-zl/  │   │
│  │ tmom          │  │ ZL.Simulator  │  │ ZL.Gear       │   │
│  │               │  │               │  │               │   │
│  │ (私有仓库)    │  │ (公开仓库)    │  │ (私有仓库)    │   │
│  └──────────────┘  └──────────────┘  └──────────────┘   │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐                     │
│  │ PcStationIot │  │ ZLBox         │                     │
│  │ (私有仓库)   │  │ (私有仓库)    │                     │
│  └──────────────┘  └──────────────┘                     │
└──────────────────────────────────────────────────────────┘
```

### 3.2 为什么选 Multi-repo 而不是 Monorepo

| 维度 | Multi-repo（本方案） | Monorepo（上版方案） |
|------|---------------------|---------------------|
| ZL.PlcBase 的归属 | **独立仓库，身份清晰** | 被某个项目"吞并"，其他项目不知道去哪找 |
| 版本独立性 | 每个项目独立版本号 | 被迫统一版本号 |
| 访问控制 | 可按仓库设权限 | 全有或全无 |
| CI/CD 触发范围 | 只构建变更的仓库 | 任何变更触发全量构建 |
| 发布节奏 | ZL.PlcBase 发新版，消费方按需升级 | 绑在一起，牵一发动全身 |
| **适合度** | ✅ ZL.PlcBase 被 6+ 项目共享，必须独立 | ❌ 上一版方案完全忽略了这个事实 |

**关键原则**：**共享库独立仓库 + NuGet 分发，消费方通过 PackageReference 引用**

### 3.3 仓库划分

| 仓库 | 可见性 | 包含项目 | 发布到 NuGet | 理由 |
|------|--------|---------|-------------|------|
| `usethink-zl/ZL.PlcBase` | **Public** | ZL.PFLite, ZL.Tag, ZL.PlcBase, ZL.PlcBase.Bridges, Tests, Demos | nuget.org 公开 | 被 6+ 项目共享，必须是独立仓库 |
| `usethink-zl/ZL.PlcSimulator` | **Public** | PlcSimulator.Core, .Cli, .UI, .Grpc, ProtocolGateway | nuget.org 公开 | 独立产品，tmom 和 PcStationIot 都引用 |
| `usethink-zl/ZL.Simulator` | Public | Simulator.* | nuget.org（可选） | 已有 GitHub 远程，迁移组织即可 |
| `usethink-zl/tmom` | **Private** | iot-sdk, api, web | GitHub Packages（内部包） | 核心业务代码，不公开 |
| `usethink-zl/ZL.Gear` | Private | ZL.Gear.* | 不发布 | 设备专用，DLL 引用 |
| `usethink-zl/PcStationIot` | Private | PcStationIot.* | 不发布 | 客户端，引用 NuGet 包 |
| `usethink-zl/ZLBox` | Private | ZLIot.Solution | 不发布 | 工具箱 |

**为什么 ZL.PlcBase 和 ZL.PlcSimulator 是 Public**：
- 它们是 SDK/工具库，需要被多个项目引用
- 发布到 nuget.org 后，任何项目都可以 `dotnet add package ZL.PlcBase` 引用
- 源码公开有助于客户二次开发（配合 Obfuscar 混淆保护核心算法）
- 与 NuGet 包名 UseThink.* / ZL.* 品牌一致

---

## 4. NuGet 分发方案

### 4.1 包分类

| 层级 | 仓库 | 包名 | 发布渠道 | 混淆 |
|------|------|------|---------|------|
| **L0 基础库** | ZL.PlcBase | ZL.PFLite | nuget.org | ✅ |
| **L0 基础库** | ZL.PlcBase | ZL.Tag | nuget.org | ❌（纯模型） |
| **L0 基础库** | ZL.PlcBase | ZL.PlcBase | nuget.org | ✅ |
| **L0 基础库** | ZL.PlcBase | ZL.PlcBase.Bridges | nuget.org | ✅ |
| **L0 仿真库** | ZL.PlcSimulator | PlcSimulator.Core | nuget.org | ✅ |
| **L0 仿真库** | ZL.PlcSimulator | ProtocolGateway | nuget.org | ❌ |
| **L1 业务库** | tmom | ZL.Biz.Execute | GitHub Packages (私有) | ❌ |
| **L1 业务库** | tmom | ZL.DB.Acc | GitHub Packages (私有) | ❌ |
| **L1 业务库** | tmom | ZL.Dao.IotDevice | GitHub Packages (私有) | ❌ |
| **L1 业务库** | tmom | ZL.Dao.Edge | GitHub Packages (私有) | ❌ |
| **L1 业务库** | tmom | ZL.Iot.Interface | GitHub Packages (私有) | ❌ |
| **L1 业务库** | tmom | ZL.Iot.Plugin | GitHub Packages (私有) | ❌ |
| **L1 业务库** | tmom | ZL.EdgeService | GitHub Packages (私有) | ❌ |
| **L1 业务库** | tmom | ZL.DataConvert | GitHub Packages (私有) | ❌ |
| **L2 边缘SDK** | tmom | ZL.Iot.Runner.Lib | nuget.org | ✅ |
| **L2 边缘SDK** | tmom | ZL.Iot.Runner.Cli | nuget.org (dotnet tool) | ✅ |
| **L3 应用** | tmom | TMom.* | 不发布 NuGet | ❌ |

### 4.2 依赖关系（发布顺序）

```
L0: ZL.PFLite → ZL.Tag → ZL.PlcBase → ZL.PlcBase.Bridges
                                    ↘
L0: PlcSimulator.Core → ProtocolGateway
                                    ↘
L1: ZL.DB.Acc ← ZL.PFLite (NuGet)
    ZL.Iot.Interface ← ZL.PFLite, ZL.Tag (NuGet)
    ZL.Dao.IotDevice ← ZL.DB.Acc
    ZL.Dao.Edge ← ZL.DB.Acc, ZL.DataConvert
    ZL.Biz.Execute ← ZL.Dao.IotDevice, ZL.DB.Acc, ZL.Iot.Interface
    ZL.EdgeService ← ZL.Dao.Edge, ZL.Biz.Execute, ZL.Dao.IotDevice, ZL.Iot.Interface, ZL.PlcBase (NuGet)
    ZL.Iot.Plugin ← ZL.Iot.Interface, ZL.Dao.IotDevice, ZL.PlcBase (NuGet)
    ↘
L2: ZL.Iot.Runner ← ZL.Biz.Execute, ZL.Iot.Interface, ZL.PlcBase (NuGet)
    ZL.Iot.Runner.Cli ← ZL.Iot.Runner
    ↘
L3: TMom.Device.Runtime ← ZL.PlcBase (NuGet)
    TMom.Device.Runtime.Host ← ZL.PlcBase, ZL.PlcBase.Bridges, PlcSimulator.Core (NuGet)
    TMom.Api ← ZL.PlcBase.Bridges (NuGet)
```

### 4.3 引用方式迁移

**目标**：所有跨仓库引用从 `ProjectReference` 改为 `PackageReference`（NuGet 包）

| 消费方 | 当前方式 | 迁移后 |
|--------|---------|--------|
| tmom/iot-sdk 中 6 个项目 | `ProjectReference ../../../ZL.PlcBase/...` | `PackageReference ZL.PFLite / ZL.Tag / ZL.PlcBase` |
| tmom/api 中 5 个项目 | `ProjectReference ../../../ZL.PlcBase/...` | `PackageReference ZL.PlcBase / ZL.Tag / ZL.PlcBase.Bridges` |
| tmom/api (PlcSimulator) | `ProjectReference ../../../ZL.PlcSimulator/...` | `PackageReference PlcSimulator.Core / ProtocolGateway` |
| PcStationIot | `ProjectReference ../../ZL.PlcBase/...` | `PackageReference ZL.PFLite / ZL.Tag / ZL.PlcBase` |
| ZL.Gear | DLL Reference | `PackageReference ZL.PFLite / ZL.PlcBase / ZL.Tag` |
| 0-ProcessDataHub | DLL Reference | `PackageReference ZL.PlcBase / ZL.Tag / ZL.PFLite` |
| ZLBox | 内部副本 ProjectReference | `PackageReference ZL.PlcBase` |

**开发时的灵活性**：可以用条件编译切换 ProjectReference 和 PackageReference：

```xml
<!-- 开发时用本地源码，正式构建用 NuGet 包 -->
<ItemGroup Condition="'$(UseLocalPlcBase)' == 'true'">
  <ProjectReference Include="..\..\ZL.PlcBase\ZL.PlcBase\ZL.PlcBase.csproj" />
</ItemGroup>
<ItemGroup Condition="'$(UseLocalPlcBase)' != 'true'">
  <PackageReference Include="ZL.PlcBase" Version="2.0.0" />
</ItemGroup>
```

这样开发者在本地可以 clone ZL.PlcBase 仓库到相邻目录，设置 `UseLocalPlcBase=true` 即可用源码调试；CI/CD 中不设置此变量，自动用 NuGet 包。

---

## 5. GitHub 管理方案

### 5.1 创建 GitHub 组织

| 项目 | 值 |
|------|-----|
| 组织名 | `usethink-zl`（与 NuGet 包名 UseThink.* / ZL.* 品牌一致） |
| 计划 | Free（无限公开仓库 + 无限私有仓库） |
| 成员 | 按需邀请 |

### 5.2 仓库创建与迁移

| 步骤 | 操作 | 命令 |
|------|------|------|
| 1 | 创建组织 `usethink-zl` | GitHub 网页操作 |
| 2 | 创建 `ZL.PlcBase` 仓库 (Public) | GitHub 网页操作 |
| 3 | 推送 ZL.PlcBase 代码 | `cd /0-X/ZL.PlcBase && git remote add origin git@github.com:usethink-zl/ZL.PlcBase.git && git push -u origin main` |
| 4 | 创建 `ZL.PlcSimulator` 仓库 (Public) | GitHub 网页操作 |
| 5 | 推送 ZL.PlcSimulator 代码 | 同上 |
| 6 | Fork `qwdingyu/ZL.Simulator` → `usethink-zl/ZL.Simulator` | GitHub Fork |
| 7 | 创建 `tmom` 仓库 (Private) | GitHub 网页操作 |
| 8 | 推送 tmom 代码 | `cd /0-X/tmom && git remote add github git@github.com:usethink-zl/tmom.git && git push github master` |
| 9 | 创建其他私有仓库 | 按需 |

### 5.3 分支策略

所有仓库统一：

```
main (protected)          ← 稳定版本，只接受 PR
  │
  ├── develop             ← 开发主线
  │     │
  │     ├── feature/xxx
  │     └── fix/xxx
  │
  └── release/x.y.z      ← 发布分支
```

### 5.4 保护规则

- `main` 分支：禁止直接 push，需 PR + CI 通过
- `develop` 分支：允许直接 push，CI 必须通过
- ZL.PlcBase 仓库额外规则：PR 需检查下游兼容性

---

## 6. CI/CD 方案

### 6.1 ZL.PlcBase 仓库的 CI/CD（最核心）

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  build-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-dotnet@v4
        with:
          global-json-file: global.json
      - run: dotnet restore ZL.PlcBase.sln
      - run: dotnet build ZL.PlcBase.sln --no-restore -c Release
      - run: dotnet test ZL.PlcBase.sln --no-build -c Release

  pack:
    needs: build-and-test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/tags/v')
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
          else
            echo "version=0.0.0-dev.$(date +%Y%m%d%H%M%S)" >> $GITHUB_OUTPUT
          fi
      - name: Pack
        run: |
          for proj in ZL.PFLite ZL.Tag ZL.PlcBase ZL.PlcBase.Bridges; do
            dotnet pack ${proj}/${proj}.csproj -c Release \
              -p:PackageVersion=${{ steps.version.outputs.version }} \
              -p:ContinuousIntegrationBuild=true \
              -o artifacts/packages
          done
      - uses: actions/upload-artifact@v4
        with:
          name: nuget-packages
          path: artifacts/packages/*.nupkg

  publish:
    needs: pack
    runs-on: ubuntu-latest
    if: startsWith(github.ref, 'refs/tags/v')
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: nuget-packages
          path: artifacts/packages
      - name: Push to NuGet
        run: |
          for pkg in artifacts/packages/*.nupkg; do
            dotnet nuget push "$pkg" \
              --source https://api.nuget.org/v3/index.json \
              --api-key ${{ secrets.NUGET_API_KEY }} \
              --skip-duplicate
          done
```

### 6.2 tmom 仓库的 CI/CD

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

env:
  # 所有 NuGet 包从 nuget.org 拉取，不再需要本地 ZL.PlcBase 源码
  DOTNET_NOLOGO: true

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-dotnet@v4
        with:
          global-json-file: global.json
      - run: dotnet restore TMom.sln
      - run: dotnet build TMom.sln --no-restore -c Release
      - run: dotnet test TMom.sln --no-build -c Release

  # 发布内部包到 GitHub Packages
  publish-internal:
    needs: build
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-dotnet@v4
        with:
          global-json-file: global.json
      - name: Pack & Push internal packages
        run: |
          for proj in ZL.Biz.Execute ZL.DB.Acc ZL.Dao.IotDevice ZL.Dao.Edge \
                      ZL.DataConvert ZL.Iot.Interface ZL.Iot.Plugin ZL.EdgeService; do
            dotnet pack iot-sdk/${proj}/${proj}.csproj -c Release \
              -p:PackageVersion=1.0.$GITHUB_RUN_NUMBER \
              -o artifacts/packages
          done
          for pkg in artifacts/packages/*.nupkg; do
            dotnet nuget push "$pkg" \
              --source https://nuget.pkg.github.com/usethink-zl/index.json \
              --api-key ${{ secrets.GITHUB_TOKEN }} \
              --skip-duplicate
          done
```

### 6.3 发布流程

| 场景 | 流程 | 涉及仓库 |
|------|------|---------|
| **ZL.PlcBase 发新版** | 1. 在 ZL.PlcBase 仓库打 tag `v2.0.0`<br>2. CI 自动 pack + push 到 nuget.org<br>3. 下游项目 `dotnet add package ZL.PlcBase -v 2.0.0` 升级 | ZL.PlcBase |
| **tmom 发版** | 1. 在 tmom 仓库打 tag<br>2. CI 构建 + 测试 + 发布内部包到 GitHub Packages<br>3. 构建 Docker 镜像 | tmom |
| **紧急修复 ZL.PlcBase** | 1. 在 ZL.PlcBase 仓库修 bug + 打 tag `v2.0.1`<br>2. CI 自动发布<br>3. 下游项目按需升级 | ZL.PlcBase → 下游 |
| **开发新功能（跨仓库）** | 1. ZL.PlcBase 发布 prerelease `v2.1.0-beta.1`<br>2. tmom 引用 prerelease 版本开发<br>3. ZL.PlcBase 正式发布后，tmom 切换到正式版 | ZL.PlcBase + tmom |

---

## 7. tmom 内部目录重组

### 7.1 当前 tmom 目录问题

1. `plcbase/` 是旧副本，与外部 ZL.PlcBase/ 分叉
2. `iot-sdk/` 和 `api/` 之间有相对路径引用 `../../iot-sdk/...`
3. 根目录散落 ZL.Iot.Runner.Generator 等空目录
4. 根目录有 SQL 文件、Python 脚本等杂物

### 7.2 重组方案

**核心改动**：
1. **删除 `plcbase/` 旧副本** — 改用 NuGet PackageReference
2. **保持 `iot-sdk/` 和 `api/` 命名** — 只改引用方式，不改目录结构（风险最小化）
3. **清理根目录杂物** — SQL 文件移到 docs/，空目录删除

```
tmom/                              ← GitHub: usethink-zl/tmom (Private)
├── iot-sdk/                       ← 保持不变
│   ├── ZL.Biz.Execute/
│   ├── ZL.DB.Acc/
│   ├── ... (其他项目保持不变)
│   └── IoT.Sdk.sln
│
├── api/                           ← 保持不变
│   ├── TMom.Api/
│   ├── TMom.Device.Runtime.Host/
│   ├── ... (其他项目保持不变)
│   └── TMom.sln
│
├── web/                           ← 保持不变
├── web_mini/                      ← 保持不变
├── deploy/                        ← 保持不变
├── docs/                          ← 保持不变
├── scripts/                       ← 保持不变
│
├── TMom.sln                       ← 新建：顶层解决方案
├── global.json                    ← SDK 版本锁定
├── Directory.Build.props          ← 全局构建属性
├── Directory.Packages.props       ← CPM 版本管理
├── NuGet.config                   ← 包源配置（含 GitHub Packages）
├── .editorconfig                  ← 代码风格
└── .github/
    └── workflows/
        ├── ci.yml
        └── publish-internal.yml
```

**改动量最小化**：
- `iot-sdk/` 和 `api/` 的目录结构完全不动
- 只改 csproj 中的引用方式（`ProjectReference ../../../ZL.PlcBase/...` → `PackageReference ZL.PlcBase`）
- 删除 `plcbase/` 旧副本
- 新增 5 个根配置文件

### 7.3 csproj 引用变更

| 文件 | 旧引用 | 新引用 |
|------|--------|--------|
| iot-sdk/ZL.DB.Acc/ZL.DB.Acc.csproj | `<ProjectReference Include="../../../ZL.PlcBase/ZL.PFLite/ZL.PFLite.csproj" />` | `<PackageReference Include="ZL.PFLite" />` |
| iot-sdk/ZL.Iot.Interface/ZL.Iot.Interface.csproj | `<ProjectReference Include="../../../ZL.PlcBase/ZL.PFLite/..." />` + `<ProjectReference Include="../../../ZL.PlcBase/ZL.Tag/..." />` | `<PackageReference Include="ZL.PFLite" />` + `<PackageReference Include="ZL.Tag" />` |
| iot-sdk/ZL.EdgeService/ZL.EdgeService.csproj | 2 个 ProjectReference | `<PackageReference Include="ZL.PlcBase" />` + `<PackageReference Include="ZL.PFLite" />` |
| ... (其他 9 个 csproj 同理) | ... | ... |
| api/TMom.Device.Runtime.Host/...csproj | 2 个 ProjectReference + 1 个 Protobuf | `<PackageReference Include="ZL.PlcBase" />` + `<PackageReference Include="ZL.PlcBase.Bridges" />` + `<PackageReference Include="PlcSimulator.Core" />` + `<PackageReference Include="ProtocolGateway" />` |

**注意**：api/TMom.Device.Runtime.Host 中对 PlcSimulator 的 Protobuf 引用需要特殊处理：
- 方案 A：将 proto 文件复制到 tmom 仓库内部（推荐，proto 很少变化）
- 方案 B：通过 NuGet 包引用 PlcSimulator.Grpc（需要 ZL.PlcSimulator 发布包含 proto 的包）

---

## 8. ZL.PlcBase 仓库内部组织

### 8.1 目录结构

```
ZL.PlcBase/                        ← GitHub: usethink-zl/ZL.PlcBase (Public)
├── ZL.PFLite/
│   └── ZL.PFLite.csproj
├── ZL.Tag/
│   └── ZL.Tag.csproj
├── ZL.PlcBase/
│   └── ZL.PlcBase.csproj
├── ZL.PlcBase.Bridges/
│   └── ZL.PlcBase.Bridges.csproj
├── tests/
│   ├── ZL.PFLite.Tests/
│   ├── ZL.PlcBase.Tests/
│   ├── ZL.PlcBase.E2ETest/
│   └── ZL.PlcBase.PerfTest/
├── demos/
│   ├── ZL.PlcBase.Demo.ModbusUnified/
│   ├── ZL.PlcBase.Demo.SiemensInherited/
│   └── ZL.PlcBase.PerfDemo/
├── bench/
│   └── ZL.PlcBase.Bench/
├── scripts/
│   └── publish_nuget.sh           ← 已有
├── docs/
│   ├── NUGET_PUBLISH.md           ← 已有
│   └── NUGET_PUBLISH_SOP.md       ← 已有
├── ZL.PlcBase.sln                 ← 新建：包含所有项目的解决方案
├── global.json
├── Directory.Build.props
├── Directory.Packages.props
├── NuGet.config
├── .editorconfig
└── .github/
    └── workflows/
        ├── ci.yml
        └── publish.yml
```

### 8.2 Directory.Build.props（ZL.PlcBase 专用）

```xml
<Project>
  <PropertyGroup>
    <Company>UseThink</Company>
    <Authors>UseThink Team</Authors>
    <Copyright>Copyright © UseThink 2024-2025</Copyright>
    <RepositoryUrl>https://github.com/usethink-zl/ZL.PlcBase</RepositoryUrl>
    <RepositoryType>git</RepositoryType>
    <PackageLicenseExpression>Apache-2.0</PackageLicenseExpression>
    <PublishRepositoryUrl>true</PublishRepositoryUrl>
    <IncludeSymbols>true</IncludeSymbols>
    <SymbolPackageFormat>snupkg</SymbolPackageFormat>
    <LangVersion>latest</LangVersion>
    <Nullable>enable</Nullable>
    <GenerateDocumentationFile>true</GenerateDocumentationFile>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Microsoft.SourceLink.GitHub" Version="8.0.0" PrivateAssets="All" />
  </ItemGroup>
</Project>
```

---

## 9. 执行路线图

### Phase 0：ZL.PlcBase 仓库就位（1 天）

| 步骤 | 操作 | 验证 |
|------|------|------|
| 0.1 | 创建 GitHub 组织 `usethink-zl` | 组织页面可见 |
| 0.2 | 创建仓库 `usethink-zl/ZL.PlcBase` (Public) | 仓库页面可见 |
| 0.3 | 清理 ZL.PlcBase 本地仓库（删除 bin/obj/coverage 等） | `git status` 干净 |
| 0.4 | 添加 global.json, Directory.Build.props, Directory.Packages.props, NuGet.config | 文件存在 |
| 0.5 | 创建 ZL.PlcBase.sln（包含所有项目） | `dotnet sln list` 正确 |
| 0.6 | `dotnet build ZL.PlcBase.sln` 成功 | 构建通过 |
| 0.7 | `dotnet test` 通过 | 测试通过 |
| 0.8 | 配置 GitHub Secrets (NUGET_API_KEY) | Secret 存在 |
| 0.9 | 创建 .github/workflows/ci.yml | push 触发 CI |
| 0.10 | 推送到 GitHub | `git push origin main` |

### Phase 1：ZL.PlcBase 首次正式发布（0.5 天）

| 步骤 | 操作 | 验证 |
|------|------|------|
| 1.1 | 打 tag `v2.0.0` | CI 触发 |
| 1.2 | CI 自动 pack + push 到 nuget.org | nuget.org 页面可见 4 个包 |
| 1.3 | 验证：空项目 `dotnet add package ZL.PlcBase -v 2.0.0` | 引用成功 |

### Phase 2：ZL.PlcSimulator 仓库就位（0.5 天）

| 步骤 | 操作 | 验证 |
|------|------|------|
| 2.1 | 创建仓库 `usethink-zl/ZL.PlcSimulator` | 仓库可见 |
| 2.2 | 推送代码 | push 成功 |
| 2.3 | 修复已有 workflow 的 remote 触发 | CI 运行 |
| 2.4 | 配置 NuGet 发布 workflow | 手动触发成功 |

### Phase 3：tmom 引用方式迁移（1 天）

| 步骤 | 操作 | 验证 |
|------|------|------|
| 3.1 | 删除 `tmom/plcbase/` 旧副本 | 目录不存在 |
| 3.2 | 修改 iot-sdk/ 中 6 个 csproj：ProjectReference → PackageReference | `grep -r '../../../ZL.PlcBase'` 返回 0 |
| 3.3 | 修改 api/ 中 5 个 csproj | `grep -r '../../../ZL.PlcBase'` 返回 0 |
| 3.4 | 处理 PlcSimulator 的 Protobuf 引用（复制 proto 到本地） | 构建不依赖外部目录 |
| 3.5 | 修复 NuGet.config | `dotnet restore` 成功 |
| 3.6 | 添加根配置文件 | 文件存在 |
| 3.7 | `dotnet build TMom.sln` 全量构建 | 构建通过 |
| 3.8 | `dotnet test TMom.sln` | 测试通过 |
| 3.9 | 创建 tmom 仓库 + 推送 | GitHub 仓库可见 |

### Phase 4：其他项目迁移（按需）

| 步骤 | 操作 | 优先级 |
|------|------|--------|
| 4.1 | PcStationIot: ProjectReference → PackageReference | 高（活跃项目） |
| 4.2 | ZL.Gear: DLL Reference → PackageReference | 中 |
| 4.3 | ZLBox: 内部副本 → PackageReference | 中 |
| 4.4 | ZL.ParamEditor: 条件 ProjectReference → PackageReference | 低 |
| 4.5 | 0-ProcessDataHub: DLL Reference → PackageReference | 低 |

**总计：Phase 0-3 约 3 天，Phase 4 按需逐步推进**

---

## 10. 开发体验：本地开发如何调试 ZL.PlcBase 源码？

改为 PackageReference 后，开发者如何调试 ZL.PlcBase 源码？

### 方案 A：Source Link（推荐，零配置）

ZL.PlcBase 发布 snupkg 符号包后，Visual Studio / Rider / VS Code 会自动从 nuget.org 下载源码：
- 按 F11 步入 ZL.PlcBase 代码 → 自动下载对应源码
- 断点、单步、查看变量，全部正常
- **前提**：ZL.PlcBase 的 csproj 中已配置 `PublishRepositoryUrl` + `SourceLink` + `IncludeSymbols`

### 方案 B：条件 ProjectReference（需要时手动切换）

```xml
<ItemGroup Condition="'$(UseLocalPlcBase)' == 'true'">
  <ProjectReference Include="..\..\ZL.PlcBase\ZL.PlcBase\ZL.PlcBase.csproj" />
</ItemGroup>
<ItemGroup Condition="'$(UseLocalPlcBase)' != 'true'">
  <PackageReference Include="ZL.PlcBase" />
</ItemGroup>
```

开发者需要修改 ZL.PlcBase 源码时：
```bash
# 1. clone ZL.PlcBase 到相邻目录
cd /0-X && git clone git@github.com:usethink-zl/ZL.PlcBase.git

# 2. 设置环境变量
export UseLocalPlcBase=true

# 3. 正常开发，可以断点调试 ZL.PlcBase 源码
dotnet build tmom/TMom.sln
```

### 方案 C：NuGet 本地缓存（调试时替换）

```bash
# 1. 修改 ZL.PlcBase 源码
cd /0-X/ZL.PlcBase
dotnet pack ZL.PlcBase/ZL.PlcBase.csproj -c Debug -o /tmp/local-feed

# 2. 在 NuGet.config 添加本地源
# <add key="local" value="/tmp/local-feed" />

# 3. tmom 项目引用本地 Debug 版本
dotnet add package ZL.PlcBase --source /tmp/local-feed
```

**推荐组合**：日常用方案 A（Source Link），需要修改 ZL.PlcBase 源码时用方案 B（条件引用）。

---

## 11. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| NuGet 包版本不兼容导致下游构建失败 | 中 | 高 | ZL.PlcBase 严格遵守 SemVer； prerelease 版本供测试；下游锁定主版本号 |
| 删除 plcbase/ 旧副本后遗漏引用 | 低 | 高 | 先 `grep -r '../../../ZL.PlcBase'` 确认清零，再删除 |
| Source Link 不生效 | 低 | 中 | 确保发布 snupkg；验证 nuget.org 符号包页面 |
| GitHub 组织名已被占用 | 低 | 低 | 备选：`usethink-iot`、`zl-usethink` |
| ZL.PlcBase 发布频率低，下游等不及 | 中 | 中 | 提供 prerelease 通道；下游可用方案 B 本地开发 |
| PlcSimulator Protobuf 引用处理复杂 | 中 | 中 | 复制 proto 到 tmom 内部（最简单） |

---

## 12. 不做的事

1. **不把 ZL.PlcBase 吞入 tmom** — 它被 6+ 项目共享，必须独立
2. **不把所有项目合成 Monorepo** — 项目独立发布节奏不同
3. **不强制统一所有项目的 TargetFramework** — PlcBase 多 TFM 有历史原因
4. **不删除 ZLBox 等项目的内部 PlcBase 副本** — 它们自己决定何时迁移
5. **不立即启用混淆** — 等 CI/CD 和 NuGet 分发稳定后再引入
6. **不改动 ZL.BusCom** — net48 项目，与 .NET 生态隔离

---

## 13. 决策点

| # | 决策 | 选项 | 建议 | 需确认 |
|---|------|------|------|--------|
| D1 | GitHub 账号/组织 | `qwdingyu`（个人）/ 创建组织 `usethink-zl` | **先用 `qwdingyu` 个人账号**（已有认证） | ☐ |
| D2 | ZL.PlcBase 仓库可见性 | Public / Private | **Public**（SDK 需要公开分发） | ☐ |
| D3 | tmom 仓库是否保留 Gitee | 保留双远程 / 迁移到 GitHub | 迁移到 GitHub | ☐ |
| D4 | ZL.PlcBase 首个正式版本号 | 2.0.0 / 1.0.0 | **2.0.0**（与已有脚本一致） | ☐ |
| D5 | tmom 内部包发布渠道 | GitHub Packages / Azure Artifacts / 不发布 | **GitHub Packages**（免费、集成好） | ☐ |
| D6 | 开发调试方案 | Source Link / 条件 ProjectReference / 两者兼有 | **两者兼有** | ☐ |
| D7 | plcbase/ 旧副本处理 | 直接删除 / 归档后删除 | **直接删除**（已有外部活跃版本） | ☐ |
| D8 | PlcSimulator proto 引用处理 | 复制到 tmom 内部 / 发布 NuGet 包 | **复制到 tmom 内部**（最简单） | ☐ |

---

## 14. 批量自动化脚本（参考 Cloudflare 脚本模式）

### 14.1 设计原则

参考 `github_workflow/scripts/cloudflare/pages_github_domain_workflow.mjs` 的**无脑自动化模式**：
- **幂等**：可重复运行，已存在的仓库/Secrets 不会重复创建
- **失败可恢复**：单个仓库失败不影响其他仓库
- **日志完整**：所有操作记录到 `github-batch-setup.log`
- **零人工干预**：一条命令完成所有仓库的 GitHub 创建 + Secrets + CI/CD

### 14.2 脚本位置

```
tmom/scripts/github-batch-setup.mjs
```

### 14.3 使用方式

```bash
# 完整执行（创建仓库 + 推送代码 + 配置 Secrets + 部署 CI/CD）
source ~/.zshenv && cd /Users/dingyuwang/0-X/tmom && node scripts/github-batch-setup.mjs

# 预览不执行
node scripts/github-batch-setup.mjs --dry-run

# 只执行某个阶段
node scripts/github-batch-setup.mjs --phase github    # 只创建仓库+推送
node scripts/github-batch-setup.mjs --phase secrets    # 只配置 Secrets
node scripts/github-batch-setup.mjs --phase ci         # 只部署 CI/CD

# 只处理单个仓库
node scripts/github-batch-setup.mjs --repo ZL.PlcBase
```

### 14.4 脚本覆盖范围

| 阶段 | 操作 | 覆盖仓库 |
|------|------|---------|
| Phase 1: GitHub | 创建仓库、设置 topics、推送代码、切换 main 分支 | 5 个（ZL.PlcBase, ZL.PlcSimulator, tmom, PcStationIot, ZL.Gear） |
| Phase 2: Secrets | 配置 NUGET_API_KEY、DOTNET_NOLOGO | 2 个（ZL.PlcBase, tmom） |
| Phase 3: CI/CD | 生成并推送 ci.yml workflow | 5 个（每个仓库定制不同 workflow） |

### 14.5 前置条件

```bash
# 1. gh CLI 已认证
gh auth status

# 2. NUGET_API_KEY 环境变量
source ~/.zshenv

# 3. 所有本地仓库在 /Users/dingyuwang/0-X/ 下
ls /Users/dingyuwang/0-X/ZL.PlcBase/.git
ls /Users/dingyuwang/0-X/ZL.PlcSimulator/.git
ls /Users/dingyuwang/0-X/tmom/.git
```

### 14.6 执行日志

```
[2026-06-04T05:40:16.915Z] [INFO] Processing ZL.PlcBase
[2026-06-04T05:40:18.215Z] [INFO] Processing ZL.PlcSimulator
[2026-06-04T05:40:19.406Z] [INFO] Processing tmom
[2026-06-04T05:40:20.469Z] [INFO] Processing PcStationIot
[2026-06-04T05:40:21.700Z] [INFO] Processing ZL.Gear
[2026-06-04T05:40:22.908Z] [SUMMARY] Phase 1: 5 success, 0 skipped, 0 failed
```

日志文件：`tmom/scripts/github-batch-setup.log`

---

## 15. 执行路线图（更新版：使用批量脚本）

### Phase 0：批量 GitHub 初始化（0.5 天，一条命令）

```bash
# 1. Dry-run 预览
cd /Users/dingyuwang/0-X/tmom && node scripts/github-batch-setup.mjs --dry-run

# 2. 正式执行（全自动）
source ~/.zshenv && node scripts/github-batch-setup.mjs

# 3. 验证
gh repo view qwdingyu/ZL.PlcBase
gh repo view qwdingyu/tmom
gh run list --repo qwdingyu/ZL.PlcBase
```

| 步骤 | 操作 | 验证 |
|------|------|------|
| 0.1 | Dry-run 预览 | 5 个仓库全部识别 |
| 0.2 | 正式执行 | 日志显示全部 success |
| 0.3 | 验证仓库创建 | GitHub 页面可见 |
| 0.4 | 验证 Secrets | `gh secret list --repo qwdingyu/ZL.PlcBase` |
| 0.5 | 验证 CI workflow | `gh run list --repo qwdingyu/ZL.PlcBase` |

### Phase 1：tmom 内部引用迁移（1 天，手动）

> 这部分无法完全自动化，因为需要修改 csproj 文件并验证构建

| 步骤 | 操作 | 验证 |
|------|------|------|
| 1.1 | 删除 `tmom/plcbase/` 旧副本 | 目录不存在 |
| 1.2 | 修改 iot-sdk/ 中 6 个 csproj：ProjectReference → PackageReference | `grep -r '../../../ZL.PlcBase'` 返回 0 |
| 1.3 | 修改 api/ 中 5 个 csproj | 同上 |
| 1.4 | 处理 PlcSimulator Protobuf 引用 | 复制 proto 到 tmom 内部 |
| 1.5 | 修复根配置文件（NuGet.config, CPM） | `dotnet restore` 成功 |
| 1.6 | 全量构建验证 | `dotnet build` 通过 |
| 1.7 | 全量测试验证 | `dotnet test` 通过 |

### Phase 2：ZL.PlcBase 首次正式发布（0.5 天）

```bash
# 在 ZL.PlcBase 仓库打 tag 触发 CI 发布
cd /Users/dingyuwang/0-X/ZL.PlcBase
git tag v2.0.0
git push origin v2.0.0

# CI 自动执行：build → test → pack → push to nuget.org
```

| 步骤 | 操作 | 验证 |
|------|------|------|
| 2.1 | 打 tag `v2.0.0` | CI 触发 |
| 2.2 | CI 自动 pack + push | nuget.org 页面可见 4 个包 |
| 2.3 | 验证引用 | 空项目 `dotnet add package ZL.PlcBase -v 2.0.0` |

### Phase 3：其他项目迁移（按需，逐步推进）

| 项目 | 操作 | 优先级 |
|------|------|--------|
| PcStationIot | ProjectReference → PackageReference | 高 |
| ZL.Gear | DLL Reference → PackageReference | 中 |
| ZLBox | 内部副本 → PackageReference | 中 |
| ZL.ParamEditor | 条件引用 → PackageReference | 低 |

**总计：Phase 0 一条命令 + Phase 1 手动 1 天 + Phase 2 打 tag 触发 = 约 1.5 天完成核心迁移**
