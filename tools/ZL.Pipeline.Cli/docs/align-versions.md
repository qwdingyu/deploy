# align-versions 命令使用说明

## 背景问题

ZL.Pipeline 管理的 iot-sdk 包含 **23 个 NuGet 包**，这些包采用**独立发版策略**——只有实际变更的包才发布新版本。这导致下游消费者项目（如 tmom）的 `Directory.Packages.props`（中央包管理，CPM）中出现**版本碎片化**：

```xml
<!-- 消费者 CPM 中各包版本不一致 -->
<PackageVersion Include="ZL.Iot.Runner" Version="1.0.5" />          <!-- 最新 -->
<PackageVersion Include="ZL.Iot.Runner.Generator" Version="1.0.3" /> <!-- 旧版本 -->
<PackageVersion Include="ZL.ProtocolGateway.Core" Version="1.0.4" />  <!-- 中间版本 -->
```

手动逐个更新版本号不仅繁琐，而且容易遗漏，导致 `dotnet pack` 失败（引用了不存在的 NuGet 版本）。

## 解决方案：align-versions 命令

`align-versions` 是 `zl-pipeline` CLI 工具的子命令，用于**自动将消费者 CPM 中所有 ZL 包的版本号对齐到各自在 NuGet.org 上的最新版本**。

### 核心特性

| 特性 | 说明 |
|------|------|
| 独立版本查询 | 每个包独立查询 NuGet.org 最新版本，不强制统一版本 |
| 多消费者支持 | 一次执行可同步 pipeline.json 中定义的所有消费者项目 |
| 安全预览 | 支持 `--dry-run` 模式，先预览变更再决定执行 |
| 智能跳过 | 已是最新版本的包自动跳过，只更新有变更的包 |
| 非稳定版过滤 | 自动过滤预发布版本（如 `-beta`、`-rc`），只取稳定版本 |

## 使用方法

### 基本语法

```bash
zl-pipeline align-versions [选项]
```

### 选项

| 选项 | 简写 | 说明 |
|------|------|------|
| `--dry-run` | `-n` | 预览模式，不实际修改文件，仅显示将要进行的变更 |
| `--config` | `-c` | 指定 pipeline.json 路径（默认：当前目录） |

### 使用场景

#### 场景 1：预览变更（推荐先执行）

```bash
# 在 iot-sdk 根目录执行
cd /path/to/iot-sdk
zl-pipeline align-versions --dry-run
```

输出示例：
```
============================================================
  查询 NuGet.org 最新版本
============================================================
  ZL.Iot.Core                         => 1.0.5
  ZL.Iot.Runner                       => 1.0.5
  ZL.Iot.Runner.Generator             => 1.0.3
  ZL.ProtocolGateway.Core             => 1.0.4
  ...

============================================================
  对齐消费者: tmom
  CPM: /path/to/tmom/Directory.Packages.props
============================================================
  ZL.Iot.Runner                       1.0.3 => 1.0.5
  ZL.Iot.Runner.Generator             1.0.2 => 1.0.3
  [DRY-RUN] 将更新 2 个包，21 个已是最新

  [DRY-RUN] 未实际修改任何文件
```

#### 场景 2：执行对齐

```bash
# 确认预览无误后，执行实际更新
zl-pipeline align-versions
```

输出示例：
```
============================================================
  对齐消费者: tmom
  CPM: /path/to/tmom/Directory.Packages.props
============================================================
  ZL.Iot.Runner                       1.0.3 => 1.0.5
  ZL.Iot.Runner.Generator             1.0.2 => 1.0.3
  ✅ 已更新 2 个包，21 个已是最新

  ✅ align-versions 完成
```

#### 场景 3：指定配置文件路径

```bash
# 从任意目录执行，指定 pipeline.json 位置
zl-pipeline align-versions -c /path/to/iot-sdk/pipeline.json
```

## 前置条件

### 1. pipeline.json 配置

`pipeline.json` 中必须正确配置 `consumers` 字段：

```json
{
  "projects": [
    "src/core/ZL.Iot.Core.csproj",
    "src/runner/ZL.Iot.Runner.csproj",
    "... 其他 23 个包 ..."
  ],
  "consumers": [
    {
      "name": "tmom",
      "path": "/absolute/path/to/tmom"
    }
  ],
  "nugetSource": "https://api.nuget.org/v3/index.json"
}
```

### 2. consumers 配置详解

`consumers` 数组中每个元素支持以下字段：

| 字段 | 必需 | 说明 |
|------|------|------|
| `name` | 是 | 消费者项目名称（用于日志输出） |
| `path` | 是 | 消费者项目根目录的绝对路径 |
| `cpmPath` | 否 | 自定义 CPM 文件路径（默认：`{path}/Directory.Packages.props`） |

示例——多消费者：
```json
{
  "consumers": [
    {
      "name": "tmom",
      "path": "/Users/dingyuwang/0-X/tmom"
    },
    {
      "name": "another-project",
      "path": "/Users/dingyuwang/0-X/another-project",
      "cpmPath": "src/Directory.Packages.props"
    }
  ]
}
```

### 3. 消费者 CPM 格式要求

消费者的 `Directory.Packages.props` 必须使用标准 CPM 格式：

```xml
<Project>
  <PropertyGroup>
    <ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally>
  </PropertyGroup>
  <ItemGroup>
    <PackageVersion Include="ZL.Iot.Core" Version="1.0.3" />
    <PackageVersion Include="ZL.Iot.Runner" Version="1.0.3" />
    <!-- ... -->
  </ItemGroup>
</Project>
```

**注意**：`align-versions` 匹配模式为 `PackageVersion Include="包名" Version="版本号"`，如果格式不同则无法识别。

## 工作流程

### 完整发布 → 对齐流程

```
1. 开发者修复 ZL.Iot.Runner 中的 Bug
         ↓
2. zl-pipeline publish 1.0.5
   （只发布变更的包，如 ZL.Iot.Runner → 1.0.5）
         ↓
3. 消费者执行对齐：
   zl-pipeline align-versions
   （自动将 tmom CPM 中的 ZL.Iot.Runner 更新为 1.0.5）
         ↓
4. 消费者执行：
   cd /path/to/tmom
   dotnet restore
   dotnet build
   （恢复包引用，编译通过）
```

### 命令内部执行流程

```
align-versions 执行步骤：
┌─────────────────────────────────┐
│ 1. 读取 pipeline.json           │
│    - 获取 projects 列表         │
│    - 获取 consumers 列表        │
│    - 获取 nugetSource           │
└──────────────┬──────────────────┘
               ↓
┌─────────────────────────────────┐
│ 2. 解析每个 project 的包名      │
│    - 读取 .csproj 获取 PackageId│
│    - 构建 ZL 包 ID 集合         │
└──────────────┬──────────────────┘
               ↓
┌─────────────────────────────────┐
│ 3. 查询 NuGet.org 最新版本      │
│    - 对每个包 ID 发起 HTTP 请求  │
│    - 解析 v3-flatcontainer 索引 │
│    - 过滤预发布版本             │
│    - 取最高稳定版本号            │
└──────────────┬──────────────────┘
               ↓
┌─────────────────────────────────┐
│ 4. 遍历每个消费者               │
│    - 定位 CPM 文件              │
│    - 读取 XML 内容              │
│    - 对每个 ZL 包：             │
│      · 正则匹配当前版本号        │
│      · 与最新版本比较            │
│      · 如不同则替换版本号        │
│    - 写回 CPM 文件              │
└─────────────────────────────────┘
```

## 与 sync-consumers 命令的区别

| 特性 | `sync-consumers` | `align-versions` |
|------|------------------|-------------------|
| 用途 | 发布后立即同步到**指定版本** | 日常维护时拉到**各自最新版本** |
| 参数 | 需要传版本号（如 `1.0.5`） | 不需要传版本号（自动查询） |
| 版本策略 | 所有 ZL 包统一设为同一版本 | 每个包独立取最新版本 |
| 适用场景 | 全量发布后立即执行 | 日常开发中消费者需要更新时执行 |
| 典型用法 | `zl-pipeline sync-consumers 1.0.5` | `zl-pipeline align-versions` |

**推荐**：
- 全量发布（所有包同版本）→ 用 `sync-consumers`
- 独立发版（各包不同版本）→ 用 `align-versions`

## 常见问题

### Q1: 执行后某个包版本没有更新？

**原因**：该包在 NuGet.org 上已经是最新版本，无需更新。

**验证**：
```bash
# 查看该包在 NuGet.org 上的最新版本
dotnet package search ZL.Iot.Core --take 5
```

### Q2: 提示 "无法查询最新版本"？

**可能原因**：
1. 网络连接问题（无法访问 api.nuget.org）
2. 包名在 NuGet.org 上不存在（尚未发布）
3. 包名拼写错误

**解决方法**：
```bash
# 检查网络
curl -s https://api.nuget.org/v3-flatcontainer/zl.iot.core/ | head -20

# 检查包是否已发布
dotnet package search ZL.Iot.Core
```

### Q3: 提示 "pipeline.json 中未定义 consumers"？

**原因**：`pipeline.json` 中没有配置 `consumers` 字段。

**解决方法**：编辑 `pipeline.json`，添加消费者配置（参考上方 [前置条件](#1-pipelinejson-配置)）。

### Q4: CPM 文件没有被修改？

**原因**：
1. 使用了 `--dry-run` 模式（预览模式不修改文件）
2. 所有包的版本已经是最新，无需更新

**验证**：先执行 `--dry-run` 查看是否有变更，再执行正式命令。

### Q5: align-versions 会更新非 ZL 包吗？

**不会**。`align-versions` 只处理 `pipeline.json` 中 `projects` 字段定义的 ZL 包。消费者 CPM 中的第三方包（如 `Newtonsoft.Json`、`Serilog` 等）不受影响。

### Q6: 执行 align-versions 后需要 git commit 吗？

**需要**。`align-versions` 修改的是消费者项目的 `Directory.Packages.props` 文件，这个变更应该提交到消费者项目的 Git 仓库中：

```bash
# 在消费者项目中
cd /path/to/tmom
git add Directory.Packages.props
git commit -m "chore: update ZL packages to latest versions"
git push
```

## 技术细节

### NuGet 版本查询机制

`align-versions` 通过 NuGet.org v3 Flat Container API 查询最新版本：

```
请求: GET https://api.nuget.org/v3-flatcontainer/{package-id}/
响应: HTML 索引页，包含所有已发布版本的链接
```

解析逻辑：
1. 从 HTML 中提取所有版本号
2. 过滤掉预发布版本（包含 `-` 字符的版本，如 `1.0.0-beta`）
3. 按语义化版本号排序（`[major, minor, patch]`）
4. 返回最高稳定版本号

### 版本匹配正则

```regex
(PackageVersion Include="ZL\.Iot\.Core"\s+Version=")([^"]+)(")
```

- 组 1：`PackageVersion Include="ZL.Iot.Core" Version="`（前缀）
- 组 2：当前版本号（将被替换）
- 组 3：`"`（后缀）

替换后：`PackageVersion Include="ZL.Iot.Core" Version="{最新版本}"`

### 限制

| 限制 | 说明 |
|------|------|
| 仅支持 NuGet.org | 目前只支持从 `api.nuget.org` 查询版本，不支持私有 NuGet 源 |
| 仅支持稳定版本 | 预发布版本（`-alpha`、`-beta`、`-rc`）会被自动过滤 |
| 需要网络访问 | 查询 NuGet.org API 需要网络连接 |
| 超时设置 | 每个包的查询超时为 10 秒 |

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0 | 2025-07-27 | 初始实现，支持 NuGet.org 版本查询和 CPM 自动更新 |
