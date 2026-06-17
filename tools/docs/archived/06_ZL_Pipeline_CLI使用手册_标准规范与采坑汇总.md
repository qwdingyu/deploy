# ZL.Pipeline.Cli 使用手册

## 总览

`zl-pipeline` 是一个通用的 .NET NuGet 发布流水线 CLI 工具，集中管理以下流程：

```
build → pack → publish(依赖集) → obfuscate → replace-dll → api-compare → verify-nuget → push
  1       2          3               4             5             6            7        8
```

非 PLC 专属，**任何 .NET 库项目的 NuGet 发布都可以使用**。

---

## 安装

### 方式一：本地安装（推荐）

```bash
# 从 tools 目录安装
cd tmom/tools/ZL.Pipeline.Cli
bash install.sh

# 或指定安装位置
bash install.sh --prefix /usr/local/bin
```

默认安装到 `~/.local/bin/zl-pipeline`。

### 方式二：直接运行

```bash
python3 /path/to/tools/ZL.Pipeline.Cli/zl-pipeline.py --help
```

### 方式三：后续通过 NuGet global tool

```bash
dotnet tool install -g ZL.Pipeline.Cli
```

### 依赖项

| 工具 | 用途 | 检查命令 |
|------|------|----------|
| dotnet SDK | 编译 .NET 项目 | `dotnet --version` |
| python3 | 运行核心脚本 | `python3 --version` |
| obfuscar.console | 代码混淆（可选） | `which obfuscar.console` |

---

## 快速开始

```bash
# 1. 进入你的 .NET 项目目录
cd /path/to/your-project

# 2. 初始化发布配置（自动扫描 csproj）
zl-pipeline init

# 3. 检查生成的 pipeline.json，调整配置
vim pipeline.json

# 4. 先 dry-run 验证（不推送）
zl-pipeline publish 1.0.0 --dry-run

# 5. 全部通过后正式发布
export NUGET_API_KEY=<your-nuget-api-key>
zl-pipeline publish 1.0.0
```

---

## 命令参考

### `zl-pipeline init`

在当前目录生成 `pipeline.json`。自动扫描所有 `.csproj` 文件，排除测试/性能/示例项目。

```bash
zl-pipeline init
```

**注意**：
- 生成后**必须检查**，有时会自动包含不应发布的 demo/bench 项目
- 如果项目根目录不在当前目录，需要手动编辑 csproj 路径
- Console 应用（OutputType=Exe）会被自动排除

### `zl-pipeline publish <version>`

完整发布流水线。

```bash
# 标准发布
zl-pipeline publish 1.0.1

# 仅验证不推送
zl-pipeline publish 1.0.1 --dry-run

# 指定配置文件
zl-pipeline publish 1.0.1 --config ./config/pipeline.json

# 错误立即停止（默认继续执行但标记失败）
zl-pipeline publish 1.0.1 --stop-on-error
```

**版本号**必须符合 NuGet 规范：`主版本.次版本.修订号`（如 `2.0.1`）。

**pipeline.json 中的 `dryRun: true`** 控制全局 dry-run 模式。

### `zl-pipeline verify <version>`

等价于 `zl-pipeline publish <version> --dry-run`。需要传入版本号。

```bash
zl-pipeline verify 1.0.1   # 验证 v1.0.1 全部流程
```
### `zl-pipeline check <包名> <版本号>`

验证已发布的 NuGet 包是否包含混淆后的 DLL。

```bash
# 验证已发布的 PlcSimulator.Core v1.0.1
zl-pipeline check PlcSimulator.Core 1.0.1

# 指定目标框架
zl-pipeline check PlcSimulator.Core 1.0.1 --tfm net8.0
```

验证过程：
1. 从 nuget.org 下载 `.nupkg`
2. 解压提取 DLL
3. 对比本地 `obfuscated/<包名>/<包名>.dll` 的 SHA256
4. 如果相等 → 混淆版已发布 ✅
5. 如果不相等 → 发布的是未混淆版 ❌

**注意**：NuGet CDN 可能有 1-5 分钟传播延迟，刚推送后验证可能失败（下载到的是 HTML 页面而非 ZIP）。

### `zl-pipeline list-config`

列出所有可配置项。

---

## pipeline.json 配置详解

```json
{
  "$schema": "https://raw.githubusercontent.com/.../pipeline-schema.json",
  "version": "1.0",
  "projects": [
    {
      "name": "MyLibrary",              // NuGet 包名
      "csproj": "src/MyLibrary.csproj", // 相对项目根目录的路径
      "obfuscate": true,                // 是否混淆（默认 true）
      "obfuscarConfig": "obfuscar.xml", // 自定义混淆配置（可选）
      "includeDependencies": []         // 额外依赖 DLL（可选）
    }
  ],
  "obfuscarConfig": "obfuscar.xml",    // 全局默认混淆配置
  "nugetSource": "https://api.nuget.org/v3/index.json",
  "publishTimeout": 120,
  "dryRun": false
}
```

### 字段说明

| 字段 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `version` | ✅ | - | 配置版本号，当前为 "1.0" |
| `projects` | ✅ | - | 要发布的库项目数组，至少一个 |
| `projects[].name` | ✅ | - | 包名，同时也是 DLL 名，必须与 csproj 的 AssemblyName 一致 |
| `projects[].csproj` | ✅ | - | csproj 路径，相对于项目根目录 |
| `projects[].obfuscate` | ❌ | true | 是否对此项目执行混淆 |
| `projects[].obfuscarConfig` | ❌ | 全局值 | 自定义 Obfuscar 配置，覆盖全局 |
| `projects[].includeDependencies` | ❌ | [] | Obfuscar 需要包含的依赖 DLL 列表 |
| `obfuscarConfig` | ❌ | "obfuscar.xml" | 全局 Obfuscar 配置文件路径 |
| `nugetSource` | ❌ | "https://api.nuget.org/v3/index.json" | NuGet 推送源 |
| `publishTimeout` | ❌ | 120 | 推送超时秒数 |
| `dryRun` | ❌ | false | 全局 dry-run 模式 |

### 环境变量

| 变量 | 用途 | 是否必填 |
|------|------|---------|
| `NUGET_API_KEY` | NuGet.org API Key | 发布时必须 |
| `OBFUSCAR_PATH` | obfuscar.console 路径（默认从 PATH 查找） | 可选 |

---

## 完整流水线详解

### 步骤 0：环境检查

检查 dotnet、python3、obfuscar.console 和核心脚本是否存在。

### 步骤 1：Clean Build

对所有配置的 csproj 执行 `dotnet build -c Release`。

### 步骤 2：Pack NuGet

对所有项目执行 `dotnet pack -c Release -p:PackageVersion=<version>`。
生成的 `.nupkg` 放在 `artifacts/` 目录。

### 步骤 3：dotnet publish -o（准备依赖集）

对需要混淆的项目执行 `dotnet publish -c Release -o obfuscated/<name>/publish`。
这一步将项目的所有依赖 DLL 拉到一起，Obfuscar 需要完整的依赖集才能正确工作。

### 步骤 4：Obfuscar 混淆

每个项目动态生成 `obfuscar.<name>.xml`：

```xml
<Obfuscator>
  <Var name="InPath" value="obfuscated/<name>/publish" />
  <Var name="OutPath" value="obfuscated/<name>" />
  <Var name="KeepPublicApi" value="true" />
  <Var name="HidePrivateApi" value="true" />
  <Var name="UseUnicodeNames" value="true" />
  <Module file="$(InPath)/<name>.dll" />
</Obfuscator>
```

- `KeepPublicApi=true`：保留所有 `public` 类型和方法，确保 NuGet 使用者不受影响
- `HidePrivateApi=true`：混淆 `private`/`internal` 成员
- `UseUnicodeNames=true`：使用 Unicode 编码混淆名，增加逆向难度

### 步骤 5：替换 nupkg 中的 DLL

用混淆后的 DLL 替换 `artifacts/<name>.<version>.nupkg` 中原始 DLL。

**注意**：使用 read/write 模式直接覆盖 zip 内的文件，不能使用 append 模式——append 会导致压缩包中出现重复文件，推送时会 400 Bad Request。

### 步骤 6：API 完整性对比

用 `api-compare.py` 对比原始 DLL 和混淆 DLL 的 public API：

- 提取原始 DLL（来自 nupkg）的所有 public 类型
- 提取混淆后 DLL 的所有 public 类型
- 对比：类型名、方法名（public 部分不改变）
- 100% 匹配 → 通过

### 步骤 7：混淆强度统计

读取 `obfuscated/<name>/Mapping.txt`，统计混淆的私有成员数量。

### 步骤 8：推送 NuGet

对所有 `artifacts/*.<version>.nupkg` 执行 `dotnet nuget push --skip-duplicate`。

---

## Dry-Run 模式

`--dry-run` 或 `pipeline.json` 中的 `"dryRun": true` 启用：

- 不实际执行 dotnet build/pack（只打印命令）
- 不执行 obfuscar.console（只打印命令）
- 不推送 NuGet
- 但会检查环境、配置、已有 Mapping.txt（如果有）
- 所有跳过的步骤显示 `[DRYRUN]` 或 `[INFO] ... (dry-run, 跳过)`

**始终先 dry-run**：确认环境、配置、混淆配置都正确后再正式发布。

---

## 验证已发布的包

```bash
# 方式 1：使用 CLI
zl-pipeline check MyLibrary 1.0.1

# 方式 2：直接运行验证脚本
bash tools/ZL.Pipeline.Cli/scripts/verify-nuget-obfuscation.sh MyLibrary 1.0.1
```

验证逻辑：
1. SHA256 对比 → 确认二进制完全一致
2. 检查 Unicode 混淆名字 → 确认混淆已生效

---

## 项目接入步骤

```bash
# 0. 安装 CLI（一次安装，全局可用）
bash tmom/tools/ZL.Pipeline.Cli/install.sh

# 1. 创建 Obfuscar 配置文件（如果使用混淆）
cat > obfuscar.xml << 'EOF'
<Obfuscator>
  <Var name="KeepPublicApi" value="true" />
  <Var name="HidePrivateApi" value="true" />
  <Var name="UseUnicodeNames" value="true" />
  <Module file="$(InPath)/MyLibrary.dll" />
</Obfuscator>
EOF

# 2. 初始化 pipeline.json
zl-pipeline init

# 3. 编辑 pipeline.json，确认项目列表正确
vim pipeline.json

# 4. dry-run 验证
zl-pipeline publish 1.0.0 --dry-run

# 5. 正式发布
export NUGET_API_KEY=oy2i5vtsqu2yzqes4wbq2vgyzeb52jve3onie4ol2os75m
zl-pipeline publish 1.0.0

# 6. 事后验证
zl-pipeline check MyLibrary 1.0.0
```

---

## 采坑记录与最佳实践

### 1. Obfuscar XML 不要写死配置

**错误做法**：在 obfuscar.xml 中硬编码 `<Module file="Debug/MyLibrary.dll" />`

**正确做法**：使用变量 `<Module file="$(InPath)/MyLibrary.dll" />`，CLI 工具会自动设置 InPath/OutPath。

### 2. replace-nupkg-dll.py 必须使用 read/write 模式

**问题**：Python `zipfile` 的 `"a"`（append）模式不会替换同名文件，只会追加。
**结果**：nupkg 中出现两个相同路径的 DLL，NuGet 推送返回 `400 Bad Request`。
**修复**：使用 `"r"` 模式读取，在内存中替换后再写回。

### 3. Obfuscar 需要完整依赖集

**问题**：只传主 DLL 给 Obfuscar 会报错 `Could not load file or assembly ...`
**原因**：Obfuscar 需要解析所有依赖的类型信息。
**解决**：先用 `dotnet publish -o` 把项目发布到临时目录，Obfuscar 的 InPath 指向这个目录。

### 4. obfuscar.console 版本兼容性

- 当前使用的版本：**2.9.1**
- Mono 版本：**6.12.0**
- .NET 版本：**6.0+**（Obfuscar 本身基于 .NET 6）
- 推荐使用 `dotnet tool install -g Obfuscar.GlobalTool` 安装最新版

### 5. NuGet CDN 传播延迟

推送成功后立即验证可能失败，因为 CDN 需要 1-5 分钟同步。
`verify-nuget-obfuscation.sh` 会自动检测并提示重试。

### 6. 版本号必须通过 CLI 参数传递

不要修改 csproj 中的 `<Version>` 字段。CLI 通过 `-p:PackageVersion=<version>` 传入版本号。
如果同时修改 csproj 的 Version，会导致混淆/替换步骤中的文件名不匹配。

### 7. KeepPublicApi=true 的必要性

Obfuscar 的 `KeepPublicApi=true` 保留所有 public 类型和方法名。
如果不设置：
- NuGet 使用者将无法调用 public API
- API 对比会失败（因为 public 方法名变了）

### 8. pipeline.json 必须加入版本控制

`pipeline.json` 应按提交到 Git 仓库。这样：
- CI/CD 可以读取它
- 团队成员使用一致配置
- 发布历史可追溯

### 9. 不要手动绕过

**禁止**：
```bash
dotnet build
dotnet pack
dotnet nuget push   # ❌ 没有混淆、没有验证
```

**必须**：
```bash
zl-pipeline publish 1.0.0   # ✅ 完整流程
zl-pipeline publish --dry-run  # ✅ 先验证
```

### 10. 多个子项目的发布顺序

CLI 自动顺序处理所有项目，无需指定顺序。但注意：
- 项目间的依赖关系：如果 A 依赖 B，B 必须先发布
- 建议：如果项目间有依赖，在 pipeline.json 中按依赖顺序排列

### 11. MSBuild 节点崩溃（MSB4166）— 必须禁用节点重用

**问题**：运行 5+ 个项目的顺序发布时，`dotnet build/pack` 报错 `MSB4166: 子节点"3"过早退出`。

**根因**：MSBuild 默认缓存子节点进程。顺序编译 10 个项目时，累积的子节点耗尽系统资源/文件句柄，导致崩溃。

**固化解决**：pipeline 已自动在 `check_env()` 和 `cmd_publish()` 中设置：
```python
os.environ["MSBUILDDISABLENODEREUSE"] = "1"
```
手动调用时也需要设置：
```bash
export MSBUILDDISABLENODEREUSE=1
zl-pipeline publish 1.0.0
```

### 12. 所有 subprocess 调用必须带超时保护（反复踩坑，必须固化！）

**问题**：流水线运行到一半突然卡死无输出，进程被终端杀掉（`Operation timed out` / `zsh: terminated`）。这个坑出现**至少 5 次以上**。

**根因**：
- `dotnet build/pack/publish` 单步可能执行 30-90s，多项目累积 15+ 分钟
- `obfuscar.console` 处理大 DLL 时可能卡住
- 终端（如 VSCode Terminal、SSH）如果 90~180s 无 stdout 输出，**自动杀掉进程**
- 开发者每次遇到都临时手动解决，没有从代码层面固化

**历史教训**（反复出现）：
| 次数 | 场景 | 结果 |
|------|------|------|
| 1 | build 超时 → 进程被终端杀掉 | 手动重跑 |
| 2 | pack 超时 → zsh: terminated | 手动重跑 |
| 3 | publish 超时 | 手动加 `timeout` 命令 |
| 4 | obfuscar 卡住 3 分钟 | 手动 `Ctrl+C` 重跑 |
| 5 | replace-nupkg-dll 卡住 | 手动重跑 |
| 6 | verify-nuget-obfuscation 下载超时 | 手动重跑 |

**固化解决**：pipeline 的 `run()` 函数已内置全栈保护：
```python
def run(cmd, **kwargs):
    timeout = kwargs.pop("timeout", 300)  # 每步默认 5 分钟
    retry = kwargs.pop("retry", 0)       # 自动重试
    for attempt in range(retry + 1):
        try:
            result = subprocess.run(cmd, timeout=timeout, **kwargs)
        except subprocess.TimeoutExpired:
            print(f"[TIMEOUT] 超时 ({timeout}s)，已优雅终止")
            return FailedResult()  # 返回 -1，不崩溃
```

**每个步骤的 timeout/retry 配置**（2026-06-04 全面审计后固化）：

| 步骤 | 命令 | timeout | retry | 说明 |
|------|------|---------|-------|------|
| 步骤 1 | `dotnet build` | 300s | 1 | 首次编译 |
| 步骤 2 | `dotnet pack` | 600s | 2 | 打包耗时长，重试 2 次 |
| 步骤 3 | `dotnet publish -o` | 300s | 1 | 准备依赖集 |
| 步骤 4 | `obfuscar.console` | 300s | 1 | 混淆大 DLL 可能卡住 |
| 步骤 5 | `replace-nupkg-dll.py` | 120s | 1 | zip 解压/压缩 |
| 步骤 6 | `api-compare.py` | 120s | 1 | nupkg 解压+反编译 |
| 步骤 7 | (文件读取，无 subprocess) | - | - | - |
| 步骤 8 | `dotnet nuget push` | 120s | 1 | 网络推送 |
| cmd_check | `verify-nuget-obfuscation.sh` | 120s | 1 | 下载+解压+分析 |
| check_env | `dotnet --version` | 15s | 0 | 瞬间命令 |
| check_obfuscar | `which obfuscar.console` | 15s | 0 | 瞬间命令 |

**⚠️ 严禁**：任何新增 subprocess 调用不带 `timeout` 参数。pipeline 代码审查的第一条规则。

### 13. PackageId 与 AssemblyName 不一致的处理

**问题**：某些项目（如 `ZL.Iot.Runner`）的 `PackageId` 不等于项目文件名。pipeline 用项目名 `ZL.Iot.Runner` 查找 `ZL.Iot.Runner.{version}.nupkg`，但实际生成的是 `ZL.Iot.Runner.Lib.{version}.nupkg`，导致替换/推送步骤提示 "nupkg 不存在"。

**固化解决**：pipeline 已自动检测 csproj 中的 `<PackageId>`：
```python
def get_package_id(proj_dir, proj):
    # 优先使用 csproj 中的 <PackageId>，无则回退到项目名
```

### 14. replace-nupkg-dll.py 需要 TFM 参数

**问题**：`replace-nupkg-dll.py` 需要第 3 个参数 `<tfm>`（如 `netstandard2.1`、`net8.0`），但 deploy 版 pipeline 只传了 2 个参数。

**根因**：不同版本的脚本签名不一致（tmom 版 3 参数，deploy 版也 3 参数，但 pipeline 调用代码未同步更新）。

**固化解决**：pipeline 已自动从 csproj 的 `<TargetFramework>` 标签检测 TFM：
```python
m = re.search(r'<TargetFramework[^>]*>(.*?)</TargetFramework>', content)
tfm = m.group(1).strip() if m else "net8.0"
```

---
## 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| `Obfuscar 配置文件不存在` | 未创建 obfuscar.xml | `zl-pipeline init` 自动生成 |
| `nupkg 不存在` | pack 步骤失败 | 检查 build 错误 |
| `NUGET_API_KEY 未设置` | 环境变量缺失 | `export NUGET_API_KEY=...` |
| `NuGet 推送 400` | nupkg 损坏或有重复文件 | 重新运行 `zl-pipeline publish` |
| `SHA256 不匹配` | NuGet 包不是混淆版 | 检查 pipeline.json 配置 |
| `API 对比失败` | 混淆配置不正确 | 检查 obfuscar.xml 的 KeepPublicApi |
| `obfuscar.console 未安装` | 缺少全局工具 | `dotnet tool install -g Obfuscar.GlobalTool` |
| `publish 超时 / zsh: terminated` | 终端 90s 无输出自动杀进程 | pipeline 已固化 timeout+retry；手动设置 `MSBUILDDISABLENODEREUSE=1` |
| `MSB4166: 子节点崩溃` | MSBuild 节点重用耗尽资源 | pipeline 已自动设置 `MSBUILDDISABLENODEREUSE=1` |

---

## 项目引用关系

```
tmom/
├── tools/ZL.Pipeline.Cli/       ← 核心工具链（唯一维护点）
│   ├── zl-pipeline.py            ← CLI 入口
│   ├── scripts/
│   │   ├── replace-nupkg-dll.py  ← 共享脚本
│   │   ├── api-compare.py        ← 共享脚本
│   │   └── verify-nuget-obfuscation.sh
│   ├── schemas/pipeline-schema.json
│   └── install.sh
│
├── docs/                        ← 所有项目的集中文档目录
│   ├── z-plcbase/               ← ZL.PlcBase 的历史文档（只读归档）
│   ├── z-plcsim/                ← ZL.PlcSimulator 的历史文档（只读归档）
│   ├── 23_*                     ← 发布流水线采坑记录
│   ├── 24_*                     ← nupkg 脚本迭代记录
│   ├── 25_*                     ← 完整复盘
│   ├── 26_*                     ← 工具链方案文档
│   └── 27_*                     ← 本使用手册
│
├── ZL.PlcBase/pipeline.json     ← 各项目的配置文件
├── ZL.PlcSimulator/pipeline.json
└── (其他项目)/pipeline.json
```

**接入新项目**：只需 `zl-pipeline init` → 生成 pipeline.json → `zl-pipeline publish`。

**文档索引**：如需查看历史采坑记录，访问 `docs/z-plcbase/` 或 `docs/z-plcsim/` 目录，
或搜索 `docs/` 下的 `*采坑*` 文件。
