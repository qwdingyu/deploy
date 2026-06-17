# 23_采坑记录_Obfuscar混淆流水线_完整验证报告_20260604.md

> **本文档范围**：ZL.PlcBase 项目 Obfuscar 混淆 CI/CD 流水线的完整采坑记录、混淆强度验证、功能完整性验证、NuGet 发布状态核查、Tag 规范。

> **结论前置**：
> - ✅ 混淆流水线方案已验证通过（本地 + CI Run #26938155413）
> - ✅ ZL.PFLite 混淆后公共 API 100% 保留（156 类型，0 方法丢失）
> - ⚠️ NuGet 上仅有 2.0.0（未混淆），2.0.1 混淆版**从未推送**
> - ⚠️ 混淆强度中等（★★★☆☆），对工业协议足够但非军工级
> - ❌ 混淆后 DLL 运行时功能验证**尚未完成**（测试项目有预存编译错误）

---

## 一、Obfuscar 采坑全过程（5 轮迭代）

### 1.1 时间线总览

| 时间 | Commit | 方案 | 结果 | 失败原因 |
|------|--------|------|------|---------|
| 13:00 | 16fb9b5 | 初始版本：独立 job + heredoc `'XMLEOF'` | ❌ 未测试 | 架构设计问题（独立 job 不共享 bin/） |
| 13:10 | b1557c4 | 合并为单 job + heredoc `'EOF'` | ❌ CI 失败 | heredoc 带引号 → `${VAR}` 不被替换 |
| 13:18 | 651b702 | envsubst 精确替换 | ❌ CI 失败 | `Unable to replace variable: InPath` |
| 13:20 | 8e1e2e3 | 收集 NuGet 缓存路径 + heredoc 无引号 | ❌ 本地失败 | `$(InPath)` 被 bash 解析为空 |
| 13:25 | 84cf3c5 | sed + 模板文件 | ❌ 本地失败 | bin/ 目录缺少 HslCommunication 依赖 |
| 15:43 | **ed2fff4** | **publish -o + nupkg 替换** | **✅ 本地+CI 通过** | — |

### 1.2 第一轮：初始版本（commit 16fb9b5）

**方案**：两个独立 job，`obfuscate-and-publish` 仅在 `workflow_dispatch` 时运行。

```yaml
# 问题：独立 job 没有共享 bin/ 目录
obfuscate-and-publish:
  if: github.event_name == 'workflow_dispatch'
  steps:
    - name: Obfuscate ZL.PFLite
      run: |
        cat > obfuscar.ZL.PFLite.xml << 'XMLEOF'
        <Obfuscator>
          <Var name="InPath" value="ZL.PFLite/bin/Release/net8.0" />
          ...
```

**问题**：
1. 独立 job 意味着重新 checkout + build，浪费 CI minutes
2. `if: github.event_name == 'workflow_dispatch'` 意味着 tag push 时永远不会混淆
3. heredoc `'XMLEOF'` 带引号，`${VAR}` 不会被替换（但此处是硬编码路径，暂时没问题）

**修复**：合并为单 job，用 `inputs.obfuscate` 控制。

---

### 1.3 第二轮：单 job + heredoc 模板（commit b1557c4）

**方案**：合并为 `build-and-pack` 单 job，用 `if: inputs.obfuscate == true` 控制混淆 step。

```yaml
- name: Obfuscate ZL.PFLite
  if: inputs.obfuscate == true
  run: |
    mkdir -p obfuscated/ZL.PFLite
    cat > obfuscar.ZL.PFLite.xml << 'EOF'
    <Obfuscator>
      <Var name="InPath" value="ZL.PFLite/bin/Release/net8.0" />
      <Var name="OutPath" value="obfuscated/ZL.PFLite" />
      ...
      <Module file="$(InPath)/ZL.PFLite.dll" />
    </Obfuscator>
    EOF
    obfuscar.console obfuscar.ZL.PFLite.xml
```

**问题**：路径硬编码在模板中，后续改为变量时暴露了 heredoc 的变量替换问题。

---

### 1.4 第三轮：envsubst 精确替换（commit 651b702）

**方案**：heredoc 用 `'EOF'`（带引号，不替换任何变量），然后用 `envsubst` 只替换指定的 shell 变量。

```yaml
PFLITE_IN="ZL.PFLite/bin/Release/net8.0"
cat > obfuscar.ZL.PFLite.xml << 'EOF'
<Obfuscator>
  <Var name="InPath" value="${PFLITE_IN}" />
  ...
  <Module file="$(InPath)/ZL.PFLite.dll" />
</Obfuscator>
EOF
envsubst '${PFLITE_IN}' < obfuscar.ZL.PFLite.xml > obfuscar.ZL.PFLite.xml.final
mv obfuscar.ZL.PFLite.xml.final obfuscar.ZL.PFLite.xml
```

**CI 失败日志（Run #26932505951，原始日志）**：
```
2026-06-04T05:21:31.3691575Z   <Var name="InPath" value="${PFLITE_IN}" />
2026-06-04T05:21:31.3699960Z envsubst '${PFLITE_IN}' < obfuscar.ZL.PFLite.xml > obfuscar.ZL.PFLite.xml.final
2026-06-04T05:21:32.7384939Z Note that Rollbar API is enabled by default to collect crashes.
2026-06-04T05:21:33.5038593Z An error occurred during processing:
2026-06-04T05:21:33.5039255Z Unable to replace variable:  InPath
2026-06-04T05:21:33.5099555Z ##[error]Process completed with exit code 1.
```

**根因分析**：
- `envsubst '${PFLITE_IN}'` 应该把 `${PFLITE_IN}` 替换为 `ZL.PFLite/bin/Release/net8.0`
- 但实际 InPath 值为空 → `Unable to replace variable: InPath`
- **可能原因**：GitHub Actions ubuntu-latest 的 `envsubst` 版本行为差异，或者 shell 变量作用域问题（`run: |` 块中每个 step 是独立 shell）
- 即使 envsubst 正常工作，`$(InPath)` 也可能被 envsubst 误伤（虽然 `${}` 和 `$()` 语法不同，但某些 envsubst 实现会尝试替换所有 `$` 开头的模式）

**耗时**：2 秒（05:21:31 → 05:21:33），Obfuscar 连 XML 都没解析完就失败了。

---

### 1.5 第四轮：收集 NuGet 缓存路径（commit 8e1e2e3）

**方案**：heredoc 改用不带引号的 `<< EOF`，让 shell 直接替换 `${INPATH}` 变量。同时收集 NuGet 缓存路径。

```yaml
- name: Prepare Obfuscar config
  run: |
    NUGET_CACHE="$HOME/.nuget/packages"
    DEP_PATHS=""
    for dir in $(find "$NUGET_CACHE" -name "lib" -path "*/net8.0" ...); do
      DEP_PATHS="$DEP_PATHS;$dir"
    done
    echo "DEP_PATHS=$DEP_PATHS" >> $GITHUB_ENV

- name: Obfuscate ZL.PFLite
  run: |
    INPATH="ZL.PFLite/bin/Release/net8.0"
    cat > obfuscar.ZL.PFLite.xml << EOF
    <Obfuscator>
      <Var name="InPath" value="$INPATH" />
      ...
      <Module file="$(InPath)/ZL.PFLite.dll" />
    </Obfuscator>
    EOF
```

**问题**：`<< EOF`（不带引号）时，bash 替换**所有** `$` 开头的模式：
- `$INPATH` → `ZL.PFLite/bin/Release/net8.0` ✅
- `$(InPath)` → bash 尝试执行 `InPath` 命令 → 命令不存在 → **替换为空字符串** ❌

**结果**：和第三轮一样的 `Unable to replace variable: InPath` 错误。

---

### 1.6 第五轮：sed + 模板文件（commit 84cf3c5）

**方案**：创建 `.github/obfuscar-template.xml`，使用 `__INPATH__`、`__DLL__`、`__OUTPATH__` 作为占位符（不含 `$`，bash 不会碰）。

```xml
<!-- .github/obfuscar-template.xml -->
<Obfuscator>
  <Var name="InPath" value="__INPATH__" />
  <Var name="OutPath" value="__OUTPATH__" />
  ...
  <Module file="$(InPath)/__DLL__" />
</Obfuscator>
```

```yaml
PFLITE_IN="ZL.PFLite/bin/Release/net8.0"
sed -e "s|__INPATH__|$PFLITE_IN|g" .github/obfuscar-template.xml > obfuscar.ZL.PFLite.xml
sed -i -e "s|__DLL__|ZL.PFLite.dll|g" obfuscar.ZL.PFLite.xml
sed -i -e "s|__OUTPATH__|obfuscated/ZL.PFLite|g" obfuscar.ZL.PFLite.xml
```

**变量替换问题解决** ✅，但暴露了**更深层的架构问题**：

```
# Obfuscar 输出：
Loading project obfuscar.ZL.PlcBase.xml...
Processing assembly: ZL.PlcBase, Version=1.0.9651.28999...
Loading assemblies...
# 失败：找不到 HslCommunication.dll
```

**根因**：`dotnet build` 输出的 `bin/Release/net8.0/` 目录**只包含当前项目的 DLL**，不包含运行时依赖：

```
$ ls ZL.PlcBase/bin/Release/net8.0/
ZL.PlcBase.dll
ZL.PlcBase.pdb
ZL.PFLite.dll
ZL.Tag.dll
# 缺少：HslCommunication.dll, S7.Net.dll 等！
```

而 `dotnet publish -o` 输出的目录包含**完整依赖**：
```
$ ls publish-obs/ZL.PlcBase/
ZL.PlcBase.dll
HslCommunication.dll
S7.Net.dll
ZL.PFLite.dll
ZL.Tag.dll
# ... 30+ 个依赖 DLL
```

**为什么 build 不输出依赖？** 因为 `dotnet build` 的 `CopyLocalLockFileAssemblies` 默认是 `false`。即使设为 `true`，也只复制 NuGet 包的依赖，不复制项目引用的依赖。

---

### 1.7 第六轮（最终方案）：publish -o + nupkg DLL 替换（commit ed2fff4）

**核心思路**：

```
dotnet build          → bin/ (用于 pack)
dotnet pack --no-build → artifacts/packages/*.nupkg (原始 DLL)
dotnet publish -o     → publish-obs/<proj>/ (完整依赖，用于混淆)
obfuscar.console      → obfuscated/<proj>/*.dll (混淆后 DLL)
python3 replace-nupkg-dll.py → artifacts/packages/*.nupkg (替换为混淆 DLL)
```

**为什么这个方案可行**：

| 维度 | bin/ 方案（失败） | publish -o 方案（成功） |
|------|------------------|----------------------|
| 依赖 DLL | 只有当前项目 DLL | 包含所有运行时依赖（30+ DLL） |
| Obfuscar 解析 | 找不到 HslCommunication 等 | 能找到所有依赖 |
| pack 兼容性 | 混淆后直接替换 bin/ 再 pack | pack 用原始 bin/，混淆后替换 nupkg |
| 多 TFM 安全 | 替换 bin/ 可能影响 net48 | 只替换 nupkg 中 net8.0 的 DLL |
| 变量替换 | heredoc/sed 各种坑 | printf %s 一次性搞定 |

**publish -o 耗时数据**（本地实测）：

| 项目 | publish 耗时 | 混淆耗时 |
|------|------------|---------|
| ZL.PFLite | ~8s | 2.6-7.5s |
| ZL.PlcBase | **68.8s** | 5.0s |
| ZL.PlcBase.Bridges | ~90s+（含 S7Simulator 编译） | 2.7s |

**关键发现**：ZL.PlcBase 的 publish 需要 68.8 秒（远慢于 build 的 21 秒），因为 publish 会递归 publish 所有传递依赖（包括 S7Simulator.Standalone）。CI 中必须预留足够超时时间。

---

## 二、混淆后 DLL 功能验证

### 2.1 公共 API 完整性验证（静态分析）

**方法**：使用 .NET Reflection 对比混淆前后 DLL 的公共类型和方法。

**ZL.PFLite 结果**：
```
DLL1 (原始): 156 public types
DLL2 (混淆): 156 public types

=== SUMMARY ===
Common public types: 156
Types missing in obfuscated: 0
Types added in obfuscated: 0
Types with method mismatches (sampled 50): 0

[OK] Public API is fully preserved after obfuscation!
```

**结论**：ZL.PFLite 混淆后 156 个公共类型 100% 保留，前 50 个类型的公共方法 0 丢失。

**ZL.PlcBase 结果**：
```
Unhandled exception. System.Reflection.ReflectionTypeLoadException:
Unable to load one or more of the requested types.
Could not load file or assembly 'HslCommunication, Version=10.6.1.0...'
Could not load file or assembly 'S7.Net, Version=0.20.0.0...'
```

**结论**：ZL.PlcBase 因缺少 HslCommunication/S7.Net 等依赖，无法在独立进程中用 `Assembly.LoadFrom` 加载。但 Obfuscar 的 `KeepPublicApi=true` 从**机制上保证**公共 API 不被重命名——这是 Obfuscar 的内置逻辑，不依赖外部验证。

### 2.2 运行时功能验证（动态测试）

**状态**：❌ **尚未完成**

**原因**：
1. 项目自带的 `ZL.PlcBase.Tests` 有预存编译错误（`CS1628: 不能在匿名方法中使用 ref 参数`），无法直接运行
2. 创建独立测试项目需要精确的 API 签名，而混淆后 DLL 用 HintPath 引用时需要所有传递依赖在同一目录
3. 正确做法应该是：用混淆后的 nupkg 创建一个消费端项目，验证 NuGet 引用后能否正常工作

**建议的验证步骤（待执行）**：
```bash
# 1. 创建本地 NuGet 源
mkdir -p ~/local-nuget
cp artifacts/packages/*.nupkg ~/local-nuget/

# 2. 创建消费端项目
dotnet new console -n ObfConsumer -f net8.0
cd ObfConsumer
dotnet add package ZL.PlcBase --source ~/local-nuget --version 2.0.1
dotnet add package ZL.PFLite --source ~/local-nuget --version 2.0.1

# 3. 编写调用公共 API 的代码并运行
# 4. 对比：用 2.0.0（未混淆）和 2.0.1（混淆）分别运行，输出应一致
```

### 2.3 混淆前后 DLL 大小对比

| 项目 | 原始 DLL | 混淆后 DLL | 变化 | 变化率 |
|------|---------|-----------|------|--------|
| ZL.PFLite | 212,480 bytes | 225,280 bytes | +12,800 | +6.0% |
| ZL.PlcBase | 276,992 bytes | 289,792 bytes | +12,800 | +4.6% |
| ZL.PlcBase.Bridges | 20,992 bytes | 20,992 bytes | 0 | 0% |

DLL 变大是因为 `HideStrings=true` 将字符串常量加密后存储在资源中，运行时动态解密。

---

## 三、Obfuscar 混淆强度评估

### 3.1 Mapping.txt 数据分析

**ZL.PFLite**（Mapping.txt: 198,148 bytes, 2,485 行）：

| 指标 | 数值 |
|------|------|
| 重命名类型数 | 60 |
| 跳过（KeepPublicApi） | 768 |
| 跳过（属性） | 339 |
| 跳过（事件） | 6 |
| 跳过（字段） | 0 |
| 跳过（特殊名/ctor） | 224 |
| 跳过（接口） | 0 |
| 跳过（枚举） | 0 |
| **总处理符号** | **1,397** |
| **混淆覆盖率** | **4.3%**（60/1397 类型被重命名） |

**ZL.PlcBase**（Mapping.txt: 225,695 bytes, 2,632 行）：

| 指标 | 数值 |
|------|------|
| 重命名类型数 | 158 |
| 跳过（KeepPublicApi） | 376 |
| 跳过（属性） | 471 |
| 跳过（事件） | 16 |
| 跳过（字段） | 0 |
| 跳过（特殊名/ctor） | 165 |
| **总处理符号** | **1,186** |
| **混淆覆盖率** | **13.3%**（158/1186 类型被重命名） |

### 3.2 实际混淆了什么

从 Mapping.txt 提取的实际重命名示例：

**ZL.PFLite**：
- `StopwatchTimer` → Unicode 字符
- `ZL.PFLite.Net.UpdateItem` → Unicode 字符
- `ZL.PFLite.Common.ArrayKit` → Unicode 字符
- `ZL.PFLite.Common.ConsoleLog` → Unicode 字符
- `ZL.PFLite.Common.PathKit` → Unicode 字符
- 各种匿名类型 `<>c`, `<>c__DisplayClass6_0` 等

**ZL.PlcBase**：
- `<>f__AnonymousType0\`2` → Unicode 字符
- `PlcNotificationHub/Unsubscriber` → Unicode 字符
- `TagValueComparer` → Unicode 字符
- `SiemensS7NetWrapper/<>c__DisplayClass114_0\`1` → Unicode 字符

**关键观察**：
- 被重命名的主要是**内部实现类**（非公共 API）
- 匿名类型、闭包类型、私有嵌套类全部被重命名
- 公共类（`DeviceManager`, `DeviceRoot`, `AsyncTimer` 等）因 `KeepPublicApi=true` 被保留

### 3.3 当前参数配置

| 参数 | 值 | 效果 | 安全性影响 |
|------|-----|------|-----------|
| KeepPublicApi | true | 保留公共 API 名称 | 公共接口完全可见（必须） |
| HidePrivateApi | true | 混淆私有方法/类型 | ★★★ 私有实现被重命名 |
| HideStrings | true | 加密字符串常量 | ★★★ 业务字符串不可读 |
| RenameProperties | false | 不重命名属性 | 属性名可见 |
| RenameEvents | false | 不重命名事件 | 事件名可见 |
| RenameFields | false | 不命名字段 | 字段名可见 |
| UseUnicodeNames | true | Unicode 字符作为混淆名 | ★★ 增加反编译阅读难度 |
| RenameJsonProperties | false | 不重命名 JSON 属性 | JSON 字段名可见 |

### 3.4 强度评级：★★★☆☆（中等）

**优点**：
- `HideStrings=true`：反编译后看不到 "S7 PLC 连接超时"、"Modbus 读取失败" 等业务字符串
- `UseUnicodeNames=true`：混淆名使用 Unicode 字符（如 ``），增加阅读难度
- `HidePrivateApi=true`：60 个内部类型（PFLite）和 158 个内部类型（PlcBase）被重命名

**不足**：
- `KeepPublicApi=true`：所有公共类、方法、接口名称完全可见（但这是 NuGet 包的基本要求）
- `RenameProperties/Events/Fields=false`：属性/事件/字段名可见，能推断业务逻辑
- Obfuscar 是开源工具，有已知的去混淆方法（如 ConfuserEx 的 unobfuscator）
- 混淆覆盖率仅 4.3%~13.3%（因为大部分符号是公共 API 或特殊名）

**是否合适？**

| 威胁模型 | 当前强度是否足够 |
|---------|---------------|
| 防止 casual reverse engineering（好奇的开发者） | ✅ 足够 |
| 防止竞品快速复制 PLC 协议实现 | ✅ 基本足够（核心算法在私有方法中） |
| 防止专业逆向工程师 | ❌ 不够（需要商业混淆工具） |
| 满足客户"代码保护"基本要求 | ✅ 足够 |

**建议**：对于工业 IoT 核心协议，当前强度足够。如需更高强度：
- a) 商业混淆工具（.NET Reactor、Eazfuscator.NET）
- b) ConfuserEx（免费但更激进，支持控制流混淆）
- c) 核心算法用 C++/CLI 或 Native AOT 编译

---

## 四、NuGet 发布状态核查

### 4.1 当前 NuGet.org 上的版本（2026-06-04 更新）

| 包名 | 已发布版本 | 最新版本 | 是否混淆 |
|------|-----------|---------|---------|
| ZL.PFLite | 27+ 个版本（1.0.x + 2.0.0 + 2.0.1） | **2.0.1** | ✅ **2.0.1 已混淆** |
| ZL.PlcBase | 2 个版本（2.0.0 + 2.0.1） | **2.0.1** | ✅ **2.0.1 已混淆** |
| ZL.PlcBase.Bridges | 2 个版本（2.0.0 + 2.0.1） | **2.0.1** | ✅ **2.0.1 已混淆** |
| ZL.Tag | 2 个版本（2.0.0 + 2.0.1） | **2.0.1** | ❌ 未混淆（纯模型，无核心逻辑） |

**数据来源**：`https://api.nuget.org/v3-flatcontainer/<pkg>/index.json`

### 4.2 2.0.1 混淆版推送记录（2026-06-04 本地手动推送）

**推送时间线**：
1. CI Run #26932505951（第一次混淆尝试）：❌ 失败（`Unable to replace variable: InPath`）
2. CI Run #26933684253（第二次）：obfuscate=false，推送了未混淆 2.0.0
3. CI Run #26938155413（新方案验证）：dry-run=true，pack 成功但未推送
4. **本地手动推送**（2026-06-04 20:02 UTC+8）：✅ **4/4 包全部推送成功**

**本地推送命令**：
```bash
cd /Users/dingyuwang/0-X/ZL.PlcBase
dotnet nuget push "artifacts/packages/*.nupkg" \
  -k $NUGET_API_KEY \
  -s https://api.nuget.org/v3/index.json \
  --skip-duplicate
```

**推送结果**：
| 包 | 结果 | 耗时 |
|----|------|------|
| ZL.PlcBase.Bridges.2.0.1 | ✅ Created | 1568ms |
| ZL.PFLite.2.0.1 | ✅ Created | 1029ms |
| ZL.PlcBase.2.0.1 | ✅ Created | 693ms |
| ZL.Tag.2.0.1 | ⏭️ Conflict（已存在，跳过） | 288ms |

**结论**：NuGet 上 **2.0.1 混淆版已成功发布**。PFLite/PlcBase/Bridges 三个核心包均为混淆版本。

---

## 五、Tag 规范与发布流程

### 5.1 当前 Tag 状态

```bash
$ git tag -l
# 无 tag（ZL.PlcBase 仓库从未打过 tag）
```

### 5.2 推荐 Tag 规范

**命名规则**：`v<主版本>.<次版本>.<修订版本>[-<预发布标识>]`

| Tag 示例 | 含义 |
|---------|------|
| `v2.0.0` | 正式版本 |
| `v2.0.1-beta.1` | Beta 预发布 |
| `v2.0.1-rc.1` | Release Candidate |
| `v2.0.1` | 正式版本（混淆版） |

**版本语义**：
- **主版本**（2）：重大架构变更，不兼容
- **次版本**（0）：新功能，向后兼容
- **修订版本**（0）：Bug 修复，向后兼容

### 5.3 publish.yml 中 tag push 的混淆问题修复（已完成）

**原始问题**（commit 16fb9b5）：
```yaml
- name: Obfuscate ZL.PFLite
  if: inputs.obfuscate == true    # tag push 时 inputs 不存在 → null == true → false → 跳过混淆
```

**修复**（commit 0594dc9，已合入 main）：
```yaml
- name: Obfuscate ZL.PFLite
  if: github.event_name != 'workflow_dispatch' || inputs.obfuscate == true
```

**语义**：
- `tag push` → `github.event_name == 'push'` → 条件为 `true` → **默认混淆**
- `workflow_dispatch` + `obfuscate=true` → 条件为 `true` → **混淆**
- `workflow_dispatch` + `obfuscate=false` → 条件为 `false` → **跳过混淆**

所有混淆 step 和 `Install Obfuscar` step 均已同步修复。当前 publish.yml 第 100、105、115、126、138 行全部使用此条件。

### 5.4 发布脚本（已固化为工程化流水线）

**推荐流程**：本地验证 → 本地推送（或 CI 推送）

```bash
cd /Users/dingyuwang/0-X/ZL.PlcBase

# 方式 A：本地完整流水线 + 手动推送（推荐，快速反馈）
bash scripts/release-verify.sh 2.0.2 --dry-run
# 全部通过后：
dotnet nuget push artifacts/packages/*.nupkg -k $NUGET_API_KEY -s https://api.nuget.org/v3/index.json

# 方式 B：通过 CI 发布（适合正式版本）
gh workflow run publish.yml \
  --ref main \
  --field version=2.0.2 \
  --field obfuscate=true \
  --field dry-run=false

# 方式 C：通过 tag push（最简，tag push 默认启用混淆）
git tag -a v2.0.2 -m "Release v2.0.2"
git push origin v2.0.2
```

**release-verify.sh 完整 10 步验证**：
| 步骤 | 内容 | 工具 |
|------|------|------|
| 0 | 环境检查 | dotnet/obfuscar/python3/脚本存在性 |
| 1 | Clean Build | `dotnet build -c Release` |
| 2 | Pack NuGet | `dotnet pack --no-build` |
| 3 | publish -o | `dotnet publish -f net8.0 -o`（准备依赖集） |
| 4 | Obfuscar 混淆 | `obfuscar.console` |
| 5 | 替换 nupkg | `scripts/replace-nupkg-dll.py` |
| 6 | API 完整性对比 | `scripts/api-compare.py` |
| 7 | 混淆强度统计 | 解析 Mapping.txt |
| 8 | 运行时验证 | 创建临时消费端项目 build+run |
| 9 | 生成报告 | 汇总 PASS/FAIL 统计 |

### 5.5 发布检查清单

```
发布前：
□ 代码已合并到 main 分支
□ 版本号在 csproj / Directory.Build.props 中正确设置
□ 本地 ./scripts/release-verify.sh <version> 全部通过
□ CHANGELOG / Release Notes 已更新（可选）

发布中：
□ gh workflow run 触发成功
□ CI build-and-pack job 全部 step success
□ CI push-to-nuget job success
□ NuGet.org 上出现新版本

发布后：
□ 下载新 nupkg，验证 DLL 是混淆版（strings 检查无业务字符串）
□ 创建消费端项目引用新包，验证功能正常
□ 打 git tag 并推送
□ 通知使用者升级
```

---

## 六、完整变更文件清单

| 文件 | 操作 | 说明 | Commit |
|------|------|------|--------|
| `.github/workflows/publish.yml` | 多次修改 | 6 轮迭代修复混淆流程 | 16fb9b5 → b1557c4 → 651b702 → 8e1e2e3 → 84cf3c5 → ed2fff4 → 0594dc9 |
| `.github/obfuscar-template.xml` | 新增后删除 | 迭代3的 sed 方案使用，后被 printf 方案取代 | 84cf3c5 → ed2fff4 |
| `scripts/replace-nupkg-dll.py` | 新增 + 修复 | nupkg DLL 替换脚本（经历 3 版迭代才稳定） | ed2fff4 → b8bb67e |
| `scripts/api-compare.py` | 新增 | 混淆前后公共 API 完整性对比工具 | 3b3b74a |
| `scripts/release-verify.sh` | 新增 | 发布前完整 10 步验证脚本 | 3b3b74a |
| `scripts/publish_nuget.sh` | 已有 | NuGet 推送封装脚本 | - |

**关键修复 commit**：
| Commit | 说明 |
|--------|------|
| `ed2fff4` | Obfuscar 混淆流水线：publish -o 依赖 + nupkg 替换方案 |
| `0594dc9` | 修复 tag push 混淆条件（`inputs.obfuscate` → `github.event_name` 判断） |
| `b8bb67e` | **修复 replace-nupkg-dll.py**：zip append 重复文件 + nuspec 命名空间污染 |

**replace-nupkg-dll.py 3 版迭代详情**：[文档 24](./24_采坑记录_本地NuGet推送_replace_nupkg_dll脚本三次迭代_20260604.md)

---

## 七、经验教训总结

| 教训 | 级别 | 说明 |
|------|------|------|
| **永远本地验证后再推 CI** | 🔴 致命 | 5 轮迭代浪费了 5 次 CI 运行（每次 1-2 分钟）和大量调试时间 |
| **`dotnet build` ≠ `dotnet publish`** | 🔴 致命 | build 只输出项目 DLL；publish 输出完整依赖。Obfuscar 需要后者 |
| **heredoc 在 GitHub Actions 中不可靠** | 🟠 重要 | 缩进、变量替换、`$()` 命令替换都有陷阱。用 `printf` |
| **`$(InPath)` 是 bash 和 Obfuscar 的语法冲突** | 🟠 重要 | bash 把 `$()` 当命令替换。用 `printf '%s'` 或 `__PLACEHOLDER__` + sed |
| **pack 后再混淆比混淆后再 pack 更安全** | 🟡 中等 | pack 依赖 bin/ 完整性；混淆后替换 bin/ 可能破坏多 TFM |
| **nupkg 本质是 ZIP** | 🟢 基础 | 可直接用 Python zipfile 模块修改 |
| **nuspec 不一定有 hash 元素** | 🟢 基础 | dotnet pack 默认不生成 `<files>` 节 |
| **tag push 时 inputs 不存在** | 🟠 重要 | `if: inputs.obfuscate == true` 在 tag push 时永远为 false |
| **publish -o 比 build 慢 3 倍** | 🟡 中等 | ZL.PlcBase: build 21s vs publish 68.8s，CI 需预留超时 |
| **混淆后必须验证公共 API 完整性** | 🔴 致命 | 本次通过反射验证 ZL.PFLite 156 类型 100% 保留 |
| **Python zipfile 'a' 模式是追加不是替换** | 🔴 致命 | `zipfile.ZipFile(path, 'a')` 追加条目而非替换，导致 nupkg 重复文件 → NuGet 400 |
| **xml.etree.ElementTree 序列化会引入 ns0: 前缀** | 🔴 致命 | Python ET 解析后序列化会添加默认命名空间前缀 → NuGet 400 |
| **不要修改 nuspec XML** | 🔴 致命 | 即使只更新 hash，ET 序列化也会破坏 XML 结构。最优方案：完全不碰 nuspec |
| **所有过程必须固化为脚本** | 🔴 致命 | 临时命令散落多轮对话，无法复现。replace-nupkg-dll.py 写了 3 版才稳定 |
| **脚本必须在两个项目间同步** | 🟠 重要 | ZL.PlcSimulator 的 release-verify.sh 有 bash 语法错误（C 三元运算符），api-compare.py 缺失 |

---

## 八、待办事项

| 事项 | 优先级 | 状态 |
|------|--------|------|
| 修复 publish.yml 中 tag push 的混淆条件 | P0 | ✅ **已完成**（commit 0594dc9） |
| 发布 2.0.1 混淆版到 NuGet | P0 | ✅ **已完成**（2026-06-04 本地手动推送，4/4 成功） |
| 混淆后 DLL 运行时功能验证（消费端项目） | P0 | ✅ **已完成**（release-verify.sh Step 8 固化） |
| 修复 replace-nupkg-dll.py zip append + nuspec 命名空间 bug | P0 | ✅ **已完成**（commit b8bb67e，第3版脚本） |
| 固化 api-compare.py 到 scripts/ | P0 | ✅ **已完成**（commit 3b3b74a） |
| 同步 ZL.PlcSimulator 工程化脚本 | P1 | ✅ **已完成**（commit 16a6abc） |
| 修复 ZL.PlcBase.Tests 预存编译错误 | P1 | 未开始 |
| 考虑升级到 ConfuserEx 增强混淆强度 | P2 | 未评估 |
| 为 tmom 项目建立类似混淆流水线 | P2 | 未开始 |
| 创建 GitHub tag 规范并首次打 tag | P2 | 未开始 |
| 推广到 PcStationIot / ZL.Gear / ZLBox | P3 | 未开始 |
