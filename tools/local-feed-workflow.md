# 本地开发 Feed 工作流

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                     开发阶段（本地）                           │
│                                                             │
│  iot-sdk 改代码                                              │
│     │                                                       │
│     ▼                                                       │
│  local-pack.sh  (pack → push local-feed)                    │
│     │                                                       │
│     ▼                                                       │
│  ~/.nuget/local-feed/  ←─── 优先级 1（最高）                  │
│     │                                                       │
│     ▼                                                       │
│  消费者 dotnet restore  (优先命中 local-feed)                 │
│     │                                                       │
│     ▼                                                       │
│  本地编译、测试、调试                                         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     发布阶段                                  │
│                                                             │
│  确认稳定后:                                                 │
│     │                                                       │
│     ▼                                                       │
│  dotnet pack -p:Version=x.x.x                               │
│     │                                                       │
│     ▼                                                       │
│  dotnet nuget push (→ NuGet.org)  ←─── 优先级 2             │
│     │                                                       │
│     ▼                                                       │
│  更新消费者 CPM 版本号                                        │
│     │                                                       │
│     ▼                                                       │
│  CI/CD 构建（仅依赖 NuGet.org）                               │
└─────────────────────────────────────────────────────────────┘
```

## NuGet 源配置

### 全局配置（`~/.nuget/NuGet/NuGet.Config`）

```xml
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <!-- 本地开发 feed：优先使用，用于快速迭代 iot-sdk 本地修改 -->
    <add key="local-feed" value="/Users/dingyuwang/.nuget/local-feed" />
    <!-- NuGet.org：正式发布包源，CI/CD 和线上构建使用 -->
    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" protocolVersion="3" />
  </packageSources>
</configuration>
```

**关键原则**：`local-feed` 排在 `nuget.org` **之前**。NuGet 按声明顺序搜索，找到匹配版本就停止。

### 源优先级行为

| 场景 | local-feed 有 1.1.0 | nuget.org 有 1.1.0 | 结果 |
|------|---------------------|---------------------|------|
| 消费者 CPM 指定 1.1.0 | ✅ | ✅ | 使用 **local-feed**（优先级高） |
| 消费者 CPM 指定 1.1.0 | ❌ | ✅ | 使用 **nuget.org**（fallback） |
| 消费者 CPM 指定 1.2.0 | ❌ | ❌ | **失败** |
| ZL 包不在 local-feed | ❌ | ✅（有 1.1.0） | 使用 **nuget.org** |

**结论**：local-feed 只在有同名版本时拦截，不影响 nuget.org 上的其他包。

## 日常开发工作流

### 场景 1：修改 iot-sdk 代码 → 消费者测试

```bash
# 1. 修改 iot-sdk 代码
#    (编辑 /Users/dingyuwang/0-X/iot-sdk/src/ 中的源码)

# 2. 打包并推送到本地 feed（一行命令）
local-pack.sh

# 3. 消费者 restore（自动命中 local-feed）
cd /Users/dingyuwang/0-X/tmom/api
dotnet restore TMom.Device.Runtime.Host/TMom.Device.Runtime.Host.csproj

# 4. 编译、调试
dotnet build
```

**耗时**：约 10-30 秒（对比之前发 NuGet.org 需要 5-10 分钟）

### 场景 2：只修改单个包

```bash
# 只打包 ZL.Watchdog（不打包全部 23 个）
local-pack.sh -p ZL.Watchdog
```

### 场景 3：使用自定义版本号（dev 标记）

```bash
# 用 1.1.0-dev 版本推送到本地 feed
local-pack.sh -v 1.1.0-dev

# 消费者 CPM 临时改为 1.1.0-dev 来测试
# (修改 Directory.Packages.props 中的版本号)
```

> **注意**：使用 `-v` 指定不同版本号时，消费者 CPM 需要同步修改。
> 如果不指定 `-v`，脚本自动从 iot-sdk 的 CPM 读取当前版本号。

### 场景 4：正式发布到 NuGet.org

```bash
# 1. 使用 pipeline CLI 打包并发布（标准流程）
zl-pipeline.py pack -v 1.1.1
zl-pipeline.py push -v 1.1.1

# 2. 更新所有消费者 CPM 到 1.1.1
zl-pipeline.py update-consumers -v 1.1.1

# 3. 消费者 restore
cd /path/to/consumer
dotnet restore
```

## local-pack.sh 命令参考

```
用法: local-pack.sh [选项]

选项:
  -v, --version VERSION    指定版本号（默认从 iot-sdk CPM 读取）
  -p, --project NAME       只打包指定项目（默认全量 23 个）
  --force                  强制覆盖已存在的包

示例:
  local-pack.sh                      # 全量打包，使用 CPM 版本号
  local-pack.sh -v 1.1.0-dev        # 全量打包，使用指定版本
  local-pack.sh -p ZL.Watchdog      # 只打包 ZL.Watchdog
  local-pack.sh -p ZL.Dao.IotDevice -v 1.2.0  # 指定项目和版本
```

## 注意事项

### 1. local-feed 仅用于本地开发

- `~/.nuget/local-feed/` 是**本地机器专用**的
- 不要提交到 Git
- 不要在其他机器上依赖它

### 2. CI/CD 环境不使用 local-feed

- CI 服务器（GitHub Actions 等）没有 `~/.nuget/local-feed/`
- CI 仅依赖 NuGet.org，保证可重复构建
- 如果 CI 也需要本地 feed，需在 CI 配置中显式添加

### 3. 版本一致性

| 状态 | local-feed | NuGet.org | 消费者 CPM |
|------|-----------|-----------|-----------|
| 开发中 | 1.1.0（含最新修改） | 1.1.0（上次发布） | 1.1.0 |
| 已发布 | 1.1.0 | 1.1.1 | 1.1.1 |

**规则**：local-feed 中的包版本必须与消费者 CPM 一致才能被命中。如果 CPM 指向 1.1.0，local-feed 中必须有 1.1.0。

### 4. 清除 NuGet 缓存（故障排查）

如果 restore 找不到刚推送到 local-feed 的包：

```bash
# 清除 NuGet HTTP 缓存
dotnet nuget locals http-cache -c

# 清除全局包缓存（强制重新下载）
dotnet nuget locals global-packages -c

# 重新 restore
dotnet restore
```

### 5. 本地 feed 维护

```bash
# 查看本地 feed 内容
ls ~/.nuget/local-feed/

# 清理本地 feed（全部清空）
rm ~/.nuget/local-feed/*.nupkg

# 重新填充（从 iot-sdk 打包）
local-pack.sh
```

## 故障排查

### Q: restore 失败，提示找不到 ZL 包

1. 确认 local-feed 中有对应版本：`ls ~/.nuget/local-feed/ZL.*.nupkg`
2. 确认消费者 CPM 版本号与 local-feed 一致
3. 确认全局 NuGet.Config 中 local-feed 排在第一位
4. 清除缓存：`dotnet nuget locals http-cache -c`

### Q: local-pack.sh 打包失败

1. 确认 iot-sdk 能编译：`cd /Users/dingyuwang/0-X/iot-sdk && dotnet build -c Release`
2. 确认版本号格式正确（语义化版本：`1.2.3` 或 `1.2.3-dev`）

### Q: 消费者仍然使用 NuGet.org 的旧版本

1. 确认 local-feed 中有**完全相同的版本号**
2. NuGet 按版本号精确匹配，local-feed 1.1.0 不会拦截 CPM 1.1.1 的请求
3. 清除 HTTP 缓存后重新 restore

## 文件清单

| 文件 | 说明 |
|------|------|
| `~/.nuget/NuGet/NuGet.Config` | 全局 NuGet 源配置（local-feed 优先） |
| `~/.nuget/local-feed/` | 本地 feed 目录（23 个 nupkg） |
| `deploy/tools/local-pack.sh` | 本地打包推送脚本 |
| `deploy/tools/local-feed-workflow.md` | 本文档 |
