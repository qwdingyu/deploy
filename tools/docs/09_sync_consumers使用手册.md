# zl-pipeline sync-consumers 使用手册

> **目的**：发布 NuGet 包后，一键同步所有下游消费项目的版本号，消除手动编辑 CPM 文件的重复劳动。

---

## 命令格式

```bash
zl-pipeline sync-consumers <版本号> [选项]
```

| 参数 | 说明 |
|---|---|
| `<版本号>` | 必填，如 `1.0.3` |
| `--dry-run`, `-n` | 仅预览不修改（**强烈推荐先执行**） |
| `--config`, `-c` | 指定 pipeline.json 路径（默认当前目录） |

---

## 执行流程

```
zl-pipeline sync-consumers 1.0.3
  │
  ├─ 1. 扫描 artifacts/*.1.0.3.nupkg → 获取包 ID 列表
  ├─ 2. 读取 pipeline.json 中 consumers 配置
  ├─ 3. 展开配置（glob/auto-discover/精确路径）
  ├─ 4. 对每个消费项目：
  │     ├─ 定位 Directory.Packages.props
  │     ├─ 更新匹配的包版本号
  │     ├─ 编译验证（如配置了 buildTarget）
  │     └─ git commit + push（如 autoCommit=true）
  └─ 5. 输出统计报告
```

---

## 三种配置模式

### 模式 1：精确指定（适合少量已知项目）

```jsonc
{
  "consumers": [
    {
      "name": "tmom",
      "path": "/Users/dingyuwang/0-X/tmom",
      "cpmFile": "Directory.Packages.props",       // 可选，自动查找
      "buildTarget": "api/TMom.Api/TMom.Api.csproj", // 可选，编译验证
      "autoCommit": false                            // 可选，自动 git commit+push
    }
  ]
}
```

**适用场景**：下游项目数量少（1~5 个），路径固定。

### 模式 2：Glob 通配符（适合同名结构的多个项目）

```jsonc
{
  "consumers": [
    {
      "name": "all-tmom-projects",
      "path": "/Users/dingyuwang/0-X/tmom-*",       // glob 匹配
      "cpmFile": "Directory.Packages.props"
    }
  ]
}
```

**适用场景**：多个项目放在同一父目录下，命名有规律（如 `tmom-v1`, `tmom-v2`, `tmom-api`）。

**展开后**：
```
tmom-v1  → /Users/dingyuwang/0-X/tmom-v1/Directory.Packages.props
tmom-v2  → /Users/dingyuwang/0-X/tmom-v2/Directory.Packages.props
```

### 模式 3：自动发现（适合大量下游项目）⭐ 推荐

```jsonc
{
  "consumers": [
    {
      "name": "all-downstream",
      "path": "/Users/dingyuwang/0-X",               // 根目录
      "autoDiscover": true,                           // 开启自动扫描
      "discoverDepth": 4                              // 最大递归深度
    }
  ]
}
```

**工作原理**：
1. 从 `path` 开始递归扫描所有子目录
2. 找到每个 `Directory.Packages.props` 文件
3. 检查其中是否包含已发布的包 ID（如 `ZL.Dao.IotDevice`）
4. 如果包含，自动更新版本号

**适用场景**：下游项目数量多（10+），分布在不同的子目录中。

**discoverDepth 建议值**：
| 项目结构深度 | 建议值 |
|---|---|
| `/root/project/Directory.Packages.props` | 2 |
| `/root/solution/api/Directory.Packages.props` | 3 |
| `/root/org/solution/api/Directory.Packages.props` | 4 |
| 不确定 | 5（默认值） |

---

## 混合使用

三种模式可以在同一个 `consumers` 数组中混用：

```jsonc
{
  "consumers": [
    // 精确指定关键项目（带编译验证）
    {
      "name": "tmom",
      "path": "/Users/dingyuwang/0-X/tmom",
      "buildTarget": "api/TMom.Api/TMom.Api.csproj",
      "autoCommit": false
    },
    // 自动发现其他项目
    {
      "name": "all-others",
      "path": "/Users/dingyuwang/0-X",
      "autoDiscover": true,
      "discoverDepth": 3
    }
  ]
}
```

**执行顺序**：按数组顺序逐个处理。精确指定的项目优先，auto-discover 作为兜底。

**去重机制**：如果 auto-discover 扫描到了已处理的 CPM 文件（如 tmom 的），会自动跳过，避免重复更新。

---

## 完整配置示例

```jsonc
{
  "$schema": "https://raw.githubusercontent.com/qwdingyu/ZL.Pipeline/main/schemas/pipeline-schema.json",
  "version": "1.0",
  "projects": [
    // ... 22 个项目配置
  ],
  "nugetSource": "https://api.nuget.org/v3/index.json",
  "publishTimeout": 120,
  "dryRun": false,
  "consumers": [
    {
      "name": "tmom",
      "path": "/Users/dingyuwang/0-X/tmom",
      "buildTarget": "api/TMom.Api/TMom.Api.csproj",
      "autoCommit": false
    },
    {
      "name": "all-downstream",
      "path": "/Users/dingyuwang/0-X",
      "autoDiscover": true,
      "discoverDepth": 4
    }
  ]
}
```

---

## 标准操作流程

### 发布 + 同步（完整流程）

```bash
cd /Users/dingyuwang/0-X/iot-sdk

# 第 1 步：发布（build → pack → obfuscar → push NuGet）
zl-pipeline publish 1.0.4 --dry-run    # 先验证
zl-pipeline publish 1.0.4               # 正式发布

# 第 2 步：同步下游（dry-run 预览）
zl-pipeline sync-consumers 1.0.4 --dry-run

# 第 3 步：确认无误后执行
zl-pipeline sync-consumers 1.0.4
```

### 仅同步（不重新发布）

```bash
# 适用于：已手动发布到 NuGet，只需更新下游
zl-pipeline sync-consumers 1.0.4 --dry-run
zl-pipeline sync-consumers 1.0.4
```

---

## 输出示例

```
=== 步骤 0: 同步下游消费项目 (version=1.0.4) ===
  [INFO]  更新 tmom: /Users/dingyuwang/0-X/tmom/Directory.Packages.props
  [PASS]    ZL.Dao.IotDevice -> 1.0.4
  [PASS]    ZL.Biz.Execute -> 1.0.4
  [PASS]    ZL.Iot.Interface -> 1.0.4
  [SKIP]    ZL.Collections 未在 tmom 的 CPM 中定义
  ...
  [INFO]  编译验证 tmom...
  [PASS]  tmom 编译通过
  [INFO]  更新 all-downstream-projectA: /path/to/projectA/Directory.Packages.props
  [PASS]    ZL.Connection -> 1.0.4
  [INFO]  跳过 all-downstream-tmom: CPM 文件已被处理

============================================================
  同步完成
  消费项目: 5
  更新包数: 12
============================================================
```

---

## 常见问题

### Q: dry-run 显示 [SKIP] 很多包
A: 正常。SKIP 表示该包在消费项目的 CPM 中没有定义（消费项目没用这个包），不影响其他包的更新。

### Q: auto-discover 扫描太慢
A: 减小 `discoverDepth` 值，或缩小 `path` 范围。

### Q: auto-discover 扫描到了不想更新的项目
A: 在 `consumers` 数组前面加精确指定的项目，auto-discover 会自动跳过已处理的 CPM 文件。或者缩小 `path` 范围。

### Q: 编译验证失败怎么办？
A: 说明版本升级引入了破坏性变更。先修复代码，再重新发布。编译验证失败不会阻止其他项目的同步。

### Q: autoCommit 设为 true 后 push 失败？
A: 检查 git remote 地址和凭证。push 失败不影响版本更新（文件已修改，只是没推到远程）。

### Q: 如何添加新的消费项目？
A: 如果使用 auto-discover，无需手动添加——新项目的 `Directory.Packages.props` 会被自动发现。如果使用精确模式，在 `consumers` 数组中添加配置项。

---

*最后更新：2026-06-07*
