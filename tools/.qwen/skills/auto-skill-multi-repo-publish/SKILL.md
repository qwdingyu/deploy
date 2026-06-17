---
name: multi-repo-publish
description: 对齐上下游 .NET 仓库的 NuGet 版本（统一版本策略），构建到 local-feed，并在发布流程中强制版本一致性门禁。
source: auto-skill
extracted_at: '2026-06-14T10:08:00.000Z'
updated_at: '2026-06-14T12:00:00.000Z'
---

## 场景

当多个 .NET 仓库（如 `ZL.PlcBase` 上游 + `iot-sdk` 下游）需要统一版本号发布到 `~/.nuget/local-feed/`，且消费者项目（如 `UseThink.Iot`、`tmom`）的 CPM 中存在版本碎片时，使用本 skill。

## 核心理念

> 紧耦合 SDK 家族应使用统一版本号（SemVer 次版本号对齐），而非每个包独立版本。
> `AssemblyVersion` 只在 breaking change 时变，NuGet `Version` 在 minor/patch 时变。

## 版本治理四层防线

防止版本漂移（部分消费者版本变高/变低）需要四层机制协同：

| 防线 | 机制 | 触发时机 |
|------|------|---------|
| 1️⃣ 自动传播 | `sync-consumers <version>` | 构建后自动执行 |
| 2️⃣ 发布门禁 | `version-check <version>` | 构建后自动检查，不一致则阻止 |
| 3️⃣ 正确来源 | `align-versions --source {auto,nuget,local}` | 查询版本时指定正确的源 |
| 4️⃣ 规则文档 | `VERSION-GOVERNANCE.md` | 版本治理规范 |

### 三种工具的职责划分

| 工具 | 职责 | 输入 | 统一版本模式 | 独立版本模式（未来） |
|------|------|------|------------|------------------|
| `sync-consumers <version>` | **设置版本** — 把所有 ZL 包设成同一版本 | 构建产出版本 | ✅ 主要工具 | ❌ |
| `align-versions` | **查询版本** — 从包源获取每个包最新版 | NuGet.org/local-feed | ❌（会查到旧版本 1.1.0） | ✅ |
| `version-check <version>` | **验证版本** — 检查消费者是否一致 | 预期版本号 | ✅ 门禁 | ✅ |

> ⚡ 统一版本模式用 `sync-consumers`，独立版本模式用 `align-versions`，两者互补不冲突。

### `align-versions --source` 来源策略

| 参数 | 行为 | 适用 |
|------|------|------|
| `--source auto`（默认） | 优先查 local-feed，没有才查 NuGet.org | 当前离线+未来推送混合期 |
| `--source nuget` | 只查 NuGet.org（原行为） | 未来独立版本模式 |
| `--source local` | 只查 local-feed | 纯离线模式 |

## 操作流程

### 前置：调研现状

先全面调研三个层面的版本状态：

```bash
# 1. 生产者版本 — PlcBase
grep -r '<Version>|<AssemblyVersion>' /path/to/ZL.PlcBase/Directory.Build.props

# 2. 生产者版本 — iot-sdk
grep -r '<PackageVersion' /path/to/iot-sdk/Directory.Packages.props | grep -i 'ZL\.'

# 3. 消费者 CPM — UseThink.Iot 和 tmom
grep 'ZL\.' /path/to/UseThink.Iot/api/Directory.Packages.props
grep 'ZL\.' /path/to/tmom/Directory.Packages.props

# 4. 检查 local-feed 已有包
ls ~/.nuget/local-feed/ 2>/dev/null

# 5. 检查全局 NuGet 配置（决定哪些源对消费者 restore 有效）
cat ~/.nuget/NuGet/NuGet.Config

# 6. 运行版本检查作为门禁（如果 pipeline 已配置 consumers）
python3 /path/to/zl-pipeline.py --config /path/to/pipeline.json version-check 2.2.0
```

关键问题清单：
- ❓ 生产者 CPM 中是否所有 ZL 包版本一致？
- ❓ 消费者 CPM 中是否有混合版本（部分 2.2.0、部分 1.1.0）？
- ❓ local-feed 中是否已有目标版本的 nupkg？
- ❓ 消费者项目的 NuGet.Config 是否继承了 local-feed 源？
- ❓ `version-check` 是否通过？（不通过则先运行 `sync-consumers` 修复）

### 步骤 1：对齐消费者 CPM

将所有消费者项目的 `Directory.Packages.props` 中 ZL SDK 包版本修正为统一版本：

```bash
# UseThink.Iot — 检查所有 ZL SDK 包版本
grep 'ZL\.' /path/to/UseThink.Iot/api/Directory.Packages.props

# tmom — 检查并修正 SDK 包从旧版 → 统一版本
grep 'ZL\.' /path/to/tmom/Directory.Packages.props
# 修改示例：ZL.Dao.IotDevice 1.1.0 → 2.2.0（共 4 个包）
```

> ⚠️ PlcSimulator.Core 是独立仓库，不参与版本对齐，保持原版本不变。
> ⚠️ ProtocolGateway（不带 ZL 前缀）是第三方包，从不改动。

或者使用命令自动同步：

```bash
python3 /path/to/zl-pipeline.py --config /path/to/pipeline.json sync-consumers 2.2.0
```

### 步骤 2：使用 `--local` 模式构建

单体版 `zl-pipeline.py` 支持 `--local` 标志（v1.0+），此模式：
- 执行步骤 1~3（build → pack → nuspec 依赖修复）
- 跳过步骤 4~9（obfuscate → replace DLL → API compare → push）
- 完成后自动复制所有 `.nupkg` 到 `~/.nuget/local-feed/`

```bash
# 先构建上游 PlcBase（4 个项目，约 30s）
python3 /path/to/ZL.Pipeline.Cli/zl-pipeline.py \
  --config /path/to/ZL.PlcBase/pipeline.json \
  publish --local 2.2.0

# 再构建下游 iot-sdk（24 个项目，约 3-5min）
python3 /path/to/ZL.Pipeline.Cli/zl-pipeline.py \
  --config /path/to/iot-sdk/pipeline.json \
  publish --local 2.2.0
```

> 构建顺序重要：必须先构建上游（PlcBase），将其包推入 local-feed，再构建下游（iot-sdk）。
> 如果 iot-sdk 使用 PackageReference 而非 ProjectReference 引用自身内部项目，部分下游项目会因 NU1102 失败（找不到上游包），但不影响已成功项目的 nupkg 产出。

### 步骤 3：同步消费者 CPM

构建完成后，必须将版本同步到所有消费者项目的 `Directory.Packages.props`：

```bash
python3 /path/to/zl-pipeline.py --config /path/to/iot-sdk/pipeline.json sync-consumers 2.2.0
python3 /path/to/zl-pipeline.py --config /path/to/ZL.PlcBase/pipeline.json sync-consumers 2.2.0
```

### ⚠️ 步骤 3b：手动更新生产者自身的 CPM（关键遗漏点）

`sync-consumers` **只更新消费者 CPM**，不会更新生产者自身（iot-sdk）的 `Directory.Packages.props`。这意味着 iot-sdk CPM 中所有 ZL 包版本仍是旧的，下次构建时 `dotnet pack` 的依赖版本也会是旧的。

```bash
# 必须手动升级生产者自身 CPM
sed -i '' 's/Version="<旧版本>"/Version="<新版本>"/g' \
  /path/to/iot-sdk/Directory.Packages.props

# 验证：确认所有 ZL. 前缀条目都已更新
grep 'PackageVersion Include="ZL\.' /path/to/iot-sdk/Directory.Packages.props | grep -o 'Version="[^"]*"' | sort | uniq -c
# 输出应为：26 Version="<新版本>"（只有唯一版本号）
```

### ⚠️ 步骤 3c：审计消费者 csproj 中的 PackageReference 名称（ProtocolGateway 陷阱）

消费者项目的 `.csproj` 和 `Directory.Packages.props` 中可能存在**包名不匹配**：
- CPM 中写 `ProtocolGateway = 1.1.0`（无 ZL 前缀 → 第三方包）
- 但实际应该用 `ZL.ProtocolGateway = 2.2.1`（有 ZL 前缀 → 自产包）

这会导致 version-check **查不出问题**（version-check 只检查 pipeline 构建的包名，不检查消费者 CPM 中第三方包），但消费者 restore 到错误版本的包。

必须逐一检查消费者项目的两处：

```bash
# 1. 检查 csproj 中的 PackageReference 名称
grep -rn 'ProtocolGateway\|PackageReference' /path/to/consumer --include="*.csproj" | grep -v 'ZL\.ProtocolGateway'
# → 找到不带 ZL 前缀的 ProtocolGateway 引用，应改为 ZL.ProtocolGateway

# 2. 检查 CPM 中的 PackageVersion 名称和版本
grep 'ProtocolGateway' /path/to/consumer/Directory.Packages.props
# → 应改为 ZL.ProtocolGateway = <目标版本>

# 3. 同步修复
# csproj: ProtocolGateway → ZL.ProtocolGateway
# CPM:   ProtocolGateway = 1.1.0 → ZL.ProtocolGateway = 2.2.0
```

**根因辨析**：`ProtocolGateway`（无 ZL 前缀）在 NuGet.org 上是一个第三方包（版本 1.1.0），而你的流水线产出的包名是 `ZL.ProtocolGateway`（有 ZL 前缀，版本 2.2.1）。两者同名但前缀不同，消费者 csproj 如果引用的是无前缀版本，实际安装的是第三方包而非自己的包。

### 步骤 4：版本一致性门禁

发布前强制执行版本检查，不通过则阻止发布：

```bash
python3 /path/to/zl-pipeline.py --config /path/to/iot-sdk/pipeline.json version-check 2.2.0
# 通过 → exit 0，所有 ZL 包版本一致
# 失败 → exit 1，列出具体不匹配的包和消费者
```

`version-check` 只检查组 **pipeline.json 中 projects 列表定义的包**（即本流水线实际构建的包），对消费者 CPM 中的第三方包（如第三方 `ProtocolGateway`）不检查，避免误报。

### 步骤 5：验证本地 feed

```bash
ls ~/.nuget/local-feed/*.2.2.0.nupkg | wc -l
# 期望：4（PlcBase）+ 24（iot-sdk）= 28 个包
```

### 步骤 6：验证消费者 restore

对每个消费者项目执行 `dotnet restore`：

```bash
# UseThink.Iot
dotnet restore /path/to/UseThink.Iot/api/UseThink.Iot.Web/UseThink.Iot.Web.csproj
# 期望：0 errors，仅可能有 NU1902/NU1903 安全漏洞警告（预存，非本流程引入）

# tmom
dotnet restore /path/to/tmom/api/TMom.Api/TMom.Api.csproj
# 期望：0 errors
```

成功标志：**每个消费者 `dotnet restore` 均为 0 errors**。

### 一键执行：`deploy-fast.sh`

`deploy-fast.sh` 将步骤 2~4 整合为一条命令：

```bash
./deploy-fast.sh 2.2.0
```

该脚本自动完成：
1. 构建 PlcBase + iot-sdk（publish --local）
2. 统计 local-feed 包数量
3. 运行 `sync-consumers` 同步所有消费者 CPM
4. 运行 `version-check` 门禁
5. 任意一步失败则整体退出

## CPM 对齐原则

| 包前缀 | 示例 | 版本策略 |
|--------|------|---------|
| ZL.* | ZL.IotHub, ZL.Dao.IotDevice | 统一版本（全部相同） |
| PlcSimulator.\* | PlcSimulator.Core | 独立版本（不参与对齐） |
| ProtocolGateway（无 ZL 前缀） | ProtocolGateway | 第三方包，从不改动 |

## 版本号确认清单

对齐前：
- ✅ 所有生产者 `Directory.Build.props` 或 `pipeline.json` 中目标版本一致
- ✅ 消费者 CPM 中无混合版本（不能部分 2.2.0、部分 1.1.0）
- ✅ PlcSimulator 和第三方 ProtocolGateway 未被错误修改
- ✅ `nuget.org` 仍可用（消费者应用项目可能需要其他第三方包）
- ✅ `version-check` 通过（发布门禁）

## 构建注意事项

- **`--local` 模式跳过了 obfuscate**：后续需要混淆时，用 `publish <version>`（不带 `--local`）完整跑
- **NU1102 可接受**：如果 iot-sdk 使用 PackageReference 内部引用，部分下游项目构建失败但不影响 nupkg 产出。所有关键包（被消费者引用的）应已验证存在
- **`external_deps` bug**：单体版 `zl-pipeline.py` 的 nuspec 修复步骤需要 `external_deps` 变量，已修复（从 csproj `<ExternalPackageReference>` 自动解析）。如果遇到 `NameError: name 'external_deps' is not defined`，说明运行的是旧版
- **`rtk` 前缀**：在 Qwen Code 环境中，所有 shell 命令需 `rtk` 前缀构建/打包/推送命令；本地 feed 文件写入在 `rtk` 内外共享同一文件系统
- **`version-check` 仅检查流水线构建的包**：从 pipeline.json projects 列表提取包 ID，不会误报消费者 CPM 中的第三方包
- **`align-versions --source auto` 是安全默认值**：优先查询 local-feed（最新本地版本），没有则查 NuGet.org（适应当前混合+未来推送双模式）

## 验证检查清单

- ✅ 消费者 CPM 版本已统一
- ✅ local-feed 中目标版本的 nupkg 文件存在（计数= PlcBase + iot-sdk 项目数）
- ✅ `sync-consumers` 已运行（消费者 CPM 已被工具自动更新）
- ✅ `version-check` 通过（所有流水线构建的包版本一致）
- ✅ UseThink.Iot `dotnet restore` 0 errors
- ✅ tmom `dotnet restore` 0 errors
- ✅ 测试完成后可运行 `deploy-fast.sh [version]` 一键重复此流程
