# 23_采坑记录_Obfuscar混淆流水线_依赖解析与nupkg替换_20260604.md

## 一、问题背景

ZL.PlcBase 项目需要发布 NuGet 包到 nuget.org，并要求对核心 DLL（ZL.PFLite、ZL.PlcBase、ZL.PlcBase.Bridges）进行代码混淆，防止反编译泄露工业 PLC 通信协议实现细节。

混淆工具选择 **Obfuscar v2.2.38**（通过 `Obfuscar.GlobalTool` 安装），CI 平台为 **GitHub Actions**。

## 二、问题现象

### 第一次 CI 失败（Run #26932505951，2026-06-04T05:20:42Z）

触发命令：
```bash
gh workflow run publish.yml --ref main --field version=2.0.0 --field obfuscate=true --field dry-run=true
```

失败 Step：**Obfuscate ZL.PFLite**

失败日志（原始 CI 日志摘录）：
```
Run mkdir -p obfuscated/ZL.PFLite
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
obfuscar.console obfuscar.ZL.PFLite.xml

Note that Rollbar API is enabled by default to collect crashes.
An error occurred during processing:
Unable to replace variable:  InPath
Loading project obfuscar.ZL.PFLite.xml...
##[error]Process completed with exit code 1.
```

**退出码 1，耗时仅 2 秒（05:21:31 → 05:21:33）**

## 三、根因分析

### 根因 1：heredoc 变量替换问题（表层 bug）

使用 `<< 'EOF'`（带引号）时，shell **不替换**任何变量，`${PFLITE_IN}` 被原样写入 XML。
然后用 `envsubst '${PFLITE_IN}'` 替换后，`${PFLITE_IN}` 被替换为 `ZL.PFLite/bin/Release/net8.0`，但 Obfuscar 的 `$(InPath)` 也可能被误伤。

使用 `<< EOF`（不带引号）时，shell **替换所有** `$` 开头的变量，`${PFLITE_IN}` 被正确替换，但 Obfuscar 的 `$(InPath)` 也被 bash 当作 shell 变量解析为空字符串，导致 XML 中 InPath 值为空。

**这就是 `Unable to replace variable: InPath` 的直接原因**——InPath 的值在 XML 中是空的。

### 根因 2：`bin/Release/net8.0` 缺少依赖 DLL（深层架构问题）

即使解决了变量替换问题，使用 `dotnet build` 输出的 `bin/Release/net8.0/` 目录作为 Obfuscar 的 InPath 也存在根本问题：

- `dotnet build` 的 `bin/` 目录**只包含当前项目的 DLL**，不包含运行时依赖
- ZL.PlcBase 依赖 **HslCommunication、S7NetPlus、ZL.PFLite、ZL.Tag** 等多个第三方/内部库
- Obfuscar 在混淆时需要**加载并解析**目标 DLL 引用的所有类型，如果找不到依赖 DLL，就会报错或产生不完整的混淆结果
- ZL.PlcBase.Bridges 还依赖 **HslCommunication、S7NetPlus** 等，依赖链更长

**结论：`bin/` 目录不适合作为 Obfuscar 的输入路径。**

## 四、迭代修复过程

### 迭代 1：envsubst 精确替换（commit 651b702）

**思路**：heredoc 用 `'EOF'`（带引号，不替换任何变量），然后用 `envsubst` 只替换指定的 shell 变量。

```yaml
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

**结果**：解决了 `$(InPath)` 被 bash 误解析的问题，但仍然无法解决 `bin/` 目录缺少依赖的根本问题。

### 迭代 2：收集 NuGet 缓存路径（commit 8e1e2e3）

**思路**：在 Obfuscar 运行前，从 `$HOME/.nuget/packages` 中收集所有 `net8.0` 和 `netstandard2.0` 的 `lib` 目录路径，通过环境变量传递给 Obfuscar 配置。

```yaml
- name: Prepare Obfuscar config
  run: |
    NUGET_CACHE="$HOME/.nuget/packages"
    DEP_PATHS=""
    for dir in $(find "$NUGET_CACHE" -name "lib" -path "*/net8.0" -o -name "lib" -path "*/netstandard2.0" 2>/dev/null | head -50); do
      DEP_PATHS="$DEP_PATHS;$dir"
    done
    echo "DEP_PATHS=$DEP_PATHS" >> $GITHUB_ENV
```

**结果**：heredoc 改用不带引号的 `<< EOF`，让 shell 直接替换 `${INPATH}` 变量。但 `$(InPath)` 又被 bash 解析为空——回到根因 1。

### 迭代 3：sed + 模板文件（commit 84cf3c5）

**思路**：创建 `.github/obfuscar-template.xml` 模板文件，使用 `__INPATH__`、`__DLL__`、`__OUTPATH__` 作为占位符，用 `sed` 精确替换。

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
sed -e "s|__INPATH__|$PFLITE_IN|g" .github/obfuscar-template.xml > obfuscar.ZL.PFLite.xml
sed -i -e "s|__DLL__|ZL.PFLite.dll|g" obfuscar.ZL.PFLite.xml
sed -i -e "s|__OUTPATH__|obfuscated/ZL.PFLite|g" obfuscar.ZL.PFLite.xml
```

**结果**：变量替换问题彻底解决（`sed` 不会碰 `$(InPath)`），但 **Obfuscar 仍然因为 `bin/` 目录缺少 HslCommunication 等依赖 DLL 而失败**。

### 迭代 4（最终方案）：`dotnet publish -o` + nupkg DLL 替换（commit ed2fff4）

**核心思路**：

1. **不再使用 `bin/` 目录**，改用 `dotnet publish -o <dir>` 输出包含完整依赖的目录
2. 在完整依赖目录下运行 Obfuscar（能解析所有引用类型）
3. **不再在混淆后替换 `bin/` 中的 DLL 再 pack**，而是：
   - 先用原始 DLL 正常 `dotnet pack` 生成 nupkg
   - Obfuscar 混淆后，用 Python 脚本直接替换 **nupkg 压缩包内** 的 net8.0 DLL

**流程**：
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
| 依赖 DLL | 只有当前项目 DLL | 包含所有运行时依赖 |
| Obfuscar 解析 | 找不到 HslCommunication 等 | 能找到所有依赖 |
| pack 兼容性 | 混淆后直接替换 bin/ 再 pack | pack 用原始 bin/，混淆后替换 nupkg |
| 多 TFM 安全 | 替换 bin/ 可能影响其他 TFM | 只替换 nupkg 中指定 TFM 的 DLL |

## 五、最终方案详解

### 5.1 publish.yml 关键变更

**变更 1：pack 先行，混淆后置**

旧流程：build → obfuscate → replace bin/ → pack
新流程：build → **pack** → obfuscate → replace nupkg

```yaml
# 先 pack（总是执行，用干净的 bin/ 目录）
- name: Pack all packages
  run: |
    mkdir -p artifacts/packages
    dotnet pack ZL.PFLite/ZL.PFLite.csproj \
      -c Release --no-build \
      -p:PackageVersion=${{ steps.version.outputs.version }} \
      -p:ContinuousIntegrationBuild=true \
      -o artifacts/packages
    # ... 其他包同理

# 混淆（仅在 obfuscate=true 时执行）
- name: Install Obfuscar
  if: inputs.obfuscate == true
  run: dotnet tool install --global Obfuscar.GlobalTool --version 2.2.38
```

**变更 2：每个项目独立 step，使用 `dotnet publish -o`**

```yaml
- name: Obfuscate ZL.PFLite
  if: inputs.obfuscate == true
  run: |
    PDIR="publish-obs/ZL.PFLite"
    ODIR="obfuscated/ZL.PFLite"
    mkdir -p "$PDIR" "$ODIR"
    # publish 输出完整依赖
    dotnet publish ZL.PFLite/ZL.PFLite.csproj -c Release -f net8.0 -o "$PDIR" --nologo -v q
    # printf 生成 XML（避免 heredoc 变量替换问题）
    printf '<Obfuscator>\n  <Var name="InPath" value="%s" />\n  <Var name="OutPath" value="%s" />\n  <Var name="KeepPublicApi" value="true" />\n  <Var name="HidePrivateApi" value="true" />\n  <Var name="HideStrings" value="true" />\n  <Var name="RenameProperties" value="false" />\n  <Var name="RenameEvents" value="false" />\n  <Var name="RenameFields" value="false" />\n  <Var name="UseUnicodeNames" value="true" />\n  <Var name="RenameJsonProperties" value="false" />\n  <Module file="$(InPath)/ZL.PFLite.dll" />\n</Obfuscator>\n' "$PDIR" "$ODIR" > obfuscar.ZL.PFLite.xml
    obfuscar.console obfuscar.ZL.PFLite.xml
```

**变更 3：依赖项目的混淆 DLL 前置替换**

ZL.PlcBase 依赖 ZL.PFLite，ZL.PlcBase.Bridges 依赖 ZL.PlcBase + ZL.PFLite。混淆时必须用上游混淆后的 DLL 替换原始版本：

```yaml
- name: Obfuscate ZL.PlcBase
  if: inputs.obfuscate == true
  run: |
    PDIR="publish-obs/ZL.PlcBase"
    ODIR="obfuscated/ZL.PlcBase"
    mkdir -p "$PDIR" "$ODIR"
    dotnet publish ZL.PlcBase/ZL.PlcBase.csproj -c Release -f net8.0 -o "$PDIR" --nologo -v q
    # 用混淆后的 ZL.PFLite 替换原始版本
    cp "obfuscated/ZL.PFLite/ZL.PFLite.dll" "$PDIR/ZL.PFLite.dll"
    # ... 生成 XML 并运行 Obfuscar
```

**变更 4：push-to-nuget condition 修复**

```yaml
# 旧：inputs.dry-run != true
# 问题：tag push 时没有 inputs，条件行为不确定
# 新：tag push 总是推送，workflow_dispatch 时尊重 dry-run
if: github.event_name != 'workflow_dispatch' || inputs.dry-run != true
```

### 5.2 `printf` 替代 heredoc 的原因

在 GitHub Actions 的 `run: |` 块中，heredoc 存在两个问题：

1. **缩进问题**：YAML `|` 块中的 heredoc 内容会带有缩进空格，虽然 bash 通常能处理，但不同 shell 行为不一致
2. **变量替换问题**：`$(InPath)` 是 Obfuscar 的变量语法，但 bash 会尝试将其解析为命令替换

**`printf` 方案**：
- `%s` 只替换 shell 变量（`$PDIR`、`$ODIR`）
- `$(InPath)` 在单引号内，bash 不解析
- 单行命令，无缩进问题

```bash
printf '<Obfuscator>\n  <Var name="InPath" value="%s" />\n  ...\n  <Module file="$(InPath)/ZL.PFLite.dll" />\n</Obfuscator>\n' "$PDIR" "$ODIR" > obfuscar.ZL.PFLite.xml
```

### 5.3 `scripts/replace-nupkg-dll.py` 脚本

**作用**：替换 NuGet 包（.nupkg 本质是 ZIP）中指定 TFM（Target Framework Moniker）的 DLL。

**核心逻辑（最终版，第 3 版脚本）**：

```python
def main():
    # 1. 复制到临时文件
    shutil.copy2(nupkg_path, tmp_path)
    # 2. 读旧 ZIP，写新 ZIP（'w' 模式 = 全新创建，避免重复文件）
    with zipfile.ZipFile(tmp_path, "r") as zin:
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                if info.filename == target_path:
                    zout.write(new_dll_path, target_path)  # 替换 DLL
                else:
                    zout.writestr(info, zin.read(info.filename))  # 原样复制
    # 3. 原子替换原 nupkg
    shutil.copy2(out_path, nupkg_path)
```

**⚠️ 重要：脚本经历了 3 次迭代才稳定（详见文档 24）**

| 版本 | ZIP 模式 | 是否修改 nuspec | 结果 |
|------|---------|----------------|------|
| 第 1 版 | `'a'` (append) | 是（ET 解析） | ❌ NuGet 400：重复文件 |
| 第 2 版 | `'r'`+`'w'` (read/write) | 是（ET 解析） | ❌ NuGet 400：nuspec ns0: 命名空间污染 |
| **第 3 版** | `'r'`+`'w'` (read/write) | **否（不碰 nuspec）** | ✅ 推送成功 |

**为什么不修改 nuspec**：
- `dotnet pack` 生成的 nuspec 只有 `<metadata>` 节，没有 `<files>` 节和 `<hash>` 元素
- 即使尝试用 `xml.etree.ElementTree` 解析后序列化回写，也会引入 `ns0:` 命名空间前缀（Python ET 已知行为）
- NuGet.org 对带 `ns0:` 前缀的 nuspec 返回 400 错误

**用法**：
```bash
python3 scripts/replace-nupkg-dll.py \
  "artifacts/packages/ZL.PlcBase.2.0.1.nupkg" \
  "obfuscated/ZL.PlcBase/ZL.PlcBase.dll" \
  net8.0
```

**⚠️ 踩坑详见**：[文档 24_采坑记录_本地NuGet推送_replace_nupkg_dll脚本三次迭代_20260604.md](./24_采坑记录_本地NuGet推送_replace_nupkg_dll脚本三次迭代_20260604.md)

### 5.4 Obfuscar 混淆参数说明

| 参数 | 值 | 说明 |
|------|-----|------|
| KeepPublicApi | true | 保留公共 API 名称（不破坏外部调用） |
| HidePrivateApi | true | 混淆私有方法/类型名称 |
| HideStrings | true | 加密字符串常量 |
| RenameProperties | false | 不重命名属性（避免破坏序列化/反射） |
| RenameEvents | false | 不重命名事件（避免破坏事件订阅） |
| RenameFields | false | 不重命名字段（避免破坏序列化） |
| UseUnicodeNames | true | 使用 Unicode 字符作为混淆名（增加反编译难度） |
| RenameJsonProperties | false | 不重命名 JSON 属性（避免破坏 JSON 序列化） |

**参数选择原则**：宁可保守（false），不要激进。工业项目中序列化、反射、事件订阅无处不在，重命名属性/字段/事件会导致运行时崩溃且极难排查。

## 六、本地验证过程

### 6.1 完整流程（本地复现）

```bash
cd /Users/dingyuwang/0-X/ZL.PlcBase

# Step 1: Clean build
rm -rf obfuscated publish-obs artifacts obfuscar.*.xml
dotnet build ZL.PFLite/ZL.PFLite.csproj -c Release
dotnet build ZL.PlcBase/ZL.PlcBase.csproj -c Release
dotnet build ZL.PlcBase.Bridges/ZL.PlcBase.Bridges.csproj -c Release

# Step 2: Pack (before obfuscation)
mkdir -p artifacts/packages
dotnet pack ZL.PFLite/ZL.PFLite.csproj -c Release --no-build -p:PackageVersion=2.0.1 -o artifacts/packages
dotnet pack ZL.PlcBase/ZL.PlcBase.csproj -c Release --no-build -p:PackageVersion=2.0.1 -o artifacts/packages
dotnet pack ZL.PlcBase.Bridges/ZL.PlcBase.Bridges.csproj -c Release --no-build -p:PackageVersion=2.0.1 -o artifacts/packages

# Step 3: Obfuscate ZL.PFLite
PDIR="publish-obs/ZL.PFLite"
ODIR="obfuscated/ZL.PFLite"
mkdir -p "$PDIR" "$ODIR"
dotnet publish ZL.PFLite/ZL.PFLite.csproj -c Release -f net8.0 -o "$PDIR"
printf '<Obfuscator>\n  <Var name="InPath" value="%s" />\n  <Var name="OutPath" value="%s" />\n  <Var name="KeepPublicApi" value="true" />\n  <Var name="HidePrivateApi" value="true" />\n  <Var name="HideStrings" value="true" />\n  <Var name="RenameProperties" value="false" />\n  <Var name="RenameEvents" value="false" />\n  <Var name="RenameFields" value="false" />\n  <Var name="UseUnicodeNames" value="true" />\n  <Var name="RenameJsonProperties" value="false" />\n  <Module file="$(InPath)/ZL.PFLite.dll" />\n</Obfuscator>\n' "$PDIR" "$ODIR" > obfuscar.ZL.PFLite.xml
obfuscar.console obfuscar.ZL.PFLite.xml
# 输出: Completed, 2.60 secs. ✅

# Step 4: Obfuscate ZL.PlcBase
PDIR="publish-obs/ZL.PlcBase"
ODIR="obfuscated/ZL.PlcBase"
mkdir -p "$PDIR" "$ODIR"
dotnet publish ZL.PlcBase/ZL.PlcBase.csproj -c Release -f net8.0 -o "$PDIR"
cp "obfuscated/ZL.PFLite/ZL.PFLite.dll" "$PDIR/ZL.PFLite.dll"
printf '...' "$PDIR" "$ODIR" > obfuscar.ZL.PlcBase.xml
obfuscar.console obfuscar.ZL.PlcBase.xml
# 输出: Completed, 2.97 secs. ✅

# Step 5: Obfuscate ZL.PlcBase.Bridges
PDIR="publish-obs/ZL.PlcBase.Bridges"
ODIR="obfuscated/ZL.PlcBase.Bridges"
mkdir -p "$PDIR" "$ODIR"
dotnet publish ZL.PlcBase.Bridges/ZL.PlcBase.Bridges.csproj -c Release -f net8.0 -o "$PDIR"
cp "obfuscated/ZL.PlcBase/ZL.PlcBase.dll" "$PDIR/ZL.PlcBase.dll"
cp "obfuscated/ZL.PFLite/ZL.PFLite.dll" "$PDIR/ZL.PFLite.dll"
printf '...' "$PDIR" "$ODIR" > obfuscar.ZL.PlcBase.Bridges.xml
obfuscar.console obfuscar.ZL.PlcBase.Bridges.xml
# 输出: Completed, 2.69 secs. ✅

# Step 6: Replace DLLs in nupkg
python3 scripts/replace-nupkg-dll.py "artifacts/packages/ZL.PFLite.2.0.1.nupkg" "obfuscated/ZL.PFLite/ZL.PFLite.dll" net8.0
python3 scripts/replace-nupkg-dll.py "artifacts/packages/ZL.PlcBase.2.0.1.nupkg" "obfuscated/ZL.PlcBase/ZL.PlcBase.dll" net8.0
python3 scripts/replace-nupkg-dll.py "artifacts/packages/ZL.PlcBase.Bridges.2.0.1.nupkg" "obfuscated/ZL.PlcBase.Bridges/ZL.PlcBase.Bridges.dll" net8.0
# 全部 OK ✅
```

### 6.2 混淆结果验证

| 项目 | 原始 DLL | 混淆后 DLL | 混淆耗时 |
|------|---------|-----------|---------|
| ZL.PFLite | 198,148 bytes (bin) | 225,280 bytes (obfuscated) | 2.60s |
| ZL.PlcBase | 257,024 bytes (bin) | 257,024 bytes (obfuscated) | 2.97s |
| ZL.PlcBase.Bridges | 20,992 bytes (bin) | 20,992 bytes (obfuscated) | 2.69s |

### 6.3 nupkg 包大小对比

| 包 | 原始 nupkg | 混淆后 nupkg |
|----|-----------|-------------|
| ZL.PFLite.2.0.1 | 292,699 bytes | 294,337 bytes |
| ZL.PlcBase.2.0.1 | 411,381 bytes | 414,344 bytes |
| ZL.PlcBase.Bridges.2.0.1 | 40,974 bytes | 40,380 bytes |

## 七、CI 验证结果

### 7.1 失败记录

| Run ID | 时间 | 触发方式 | 结果 | 失败原因 |
|--------|------|---------|------|---------|
| 26932505951 | 2026-06-04T05:20:42Z | workflow_dispatch (obfuscate=true) | **failure** | `Unable to replace variable: InPath` — heredoc `'EOF'` + envsubst 方案中 InPath 值为空 |

### 7.2 成功记录

| Run ID | 时间 | 触发方式 | 结果 | 说明 |
|--------|------|---------|------|------|
| 26933684253 | 2026-06-04T05:54:09Z | workflow_dispatch (obfuscate=false) | success | 无混淆的 pack+push 验证 |
| **26938155413** | **2026-06-04T07:44:09Z** | workflow_dispatch (obfuscate=true, dry-run=true) | **success** | **新方案首次 CI 验证，全部 14 steps 成功** |

### 7.3 Run #26938155413 详细 Step 状态

| Step | 结论 |
|------|------|
| Set up job | success |
| Run actions/checkout@v4 | success |
| Setup .NET | success |
| Determine version | success |
| Restore | success |
| Build Release | success |
| **Pack all packages** | **success** |
| Install Obfuscar | success |
| **Obfuscate ZL.PFLite** | **success** |
| **Obfuscate ZL.PlcBase** | **success** |
| **Obfuscate ZL.PlcBase.Bridges** | **success** |
| **Replace obfuscated DLLs in nupkg** | **success** |
| List packages | success |
| Upload packages | success |
| Post Setup .NET | success |
| Post Run actions/checkout@v4 | success |
| Complete job | success |

push-to-nuget job: **skipped**（dry-run=true，符合预期）

## 八、变更文件清单

| 文件 | 操作 | 说明 | Commit |
|------|------|------|--------|
| `.github/workflows/publish.yml` | 多次修改 | 6 轮迭代修复混淆流程 + tag push 条件修复 | 16fb9b5 → ... → ed2fff4 → 0594dc9 |
| `.github/obfuscar-template.xml` | 新增后删除 | 迭代3的 sed 方案使用，后被 printf 方案取代 | 84cf3c5 → ed2fff4 |
| `scripts/replace-nupkg-dll.py` | 新增 + 修复 | nupkg DLL 替换脚本（经历 3 版迭代才稳定） | ed2fff4 → b8bb67e |
| `scripts/api-compare.py` | 新增 | 混淆前后公共 API 完整性对比工具 | 3b3b74a |
| `scripts/release-verify.sh` | 新增 | 发布前完整 10 步验证脚本 | 3b3b74a |

## 九、本地推送采坑（补充）

CI 流水线通过 dry-run 验证后，本地完整走一遍 build → obfuscate → pack → replace → push to NuGet.org 时，`replace-nupkg-dll.py` 又暴露了两个致命 bug：

1. **Bug #1**：`zipfile.ZipFile(nupkg, 'a')` 追加模式导致 nupkg 内 DLL 重复 → NuGet 400
2. **Bug #2**：`xml.etree.ElementTree.tostring()` 序列化 nuspec 时引入 `ns0:` 命名空间前缀 → NuGet 400

脚本写了 3 版才稳定。最终方案：**read-all → write-new 模式 + 完全不碰 nuspec**。

**推送结果（2026-06-04 本地手动）**：

| 包 | 结果 | 耗时 |
|----|------|------|
| ZL.PlcBase.Bridges.2.0.1 | ✅ Created | 1568ms |
| ZL.PFLite.2.0.1 | ✅ Created | 1029ms |
| ZL.PlcBase.2.0.1 | ✅ Created | 693ms |
| ZL.Tag.2.0.1 | ⏭️ Conflict（已存在，跳过） | 288ms |

**详见**：[文档 24_采坑记录_本地NuGet推送_replace_nupkg_dll脚本三次迭代_20260604.md](./24_采坑记录_本地NuGet推送_replace_nupkg_dll脚本三次迭代_20260604.md)

## 十、复用指南

### 10.1 对其他 C# 项目的适用性

此方案适用于满足以下条件的任何 .NET 多目标框架项目：

1. 使用 `dotnet pack` 发布 NuGet 包
2. 需要混淆 net8.0（或任意 TFM）的 DLL
3. 项目有第三方依赖（HslCommunication、Newtonsoft.Json 等）

### 10.2 复用步骤

```bash
# 1. 复制脚本
cp ZL.PlcBase/scripts/replace-nupkg-dll.py <your-project>/scripts/

# 2. 在 CI 中添加混淆步骤（参考 publish.yml 第 93-143 行）
#    核心模式：
#    a. dotnet publish -c Release -f net8.0 -o <publish-dir>
#    b. printf 生成 Obfuscar XML（InPath=<publish-dir>, OutPath=<obf-dir>）
#    c. obfuscar.console <xml-file>
#    d. python3 scripts/replace-nupkg-dll.py <nupkg> <obfuscated-dll> net8.0

# 3. 如果有项目间依赖，按依赖顺序混淆
#    先混淆被依赖的项目，再用混淆后的 DLL 替换 publish-dir 中的原始 DLL
```

### 10.3 注意事项

1. **`dotnet publish -f <tfm>` 必须指定单个 TFM**：不能同时 publish 多个框架，否则输出目录结构不同
2. **依赖替换顺序**：必须按照依赖图从底向上混淆（先 ZL.PFLite → 再 ZL.PlcBase → 最后 ZL.PlcBase.Bridges）
3. **nuspec hash WARNING**：如果 nuspec 中没有 `<files>` 节，`replace-nupkg-dll.py` 会输出 WARNING，可以安全忽略
4. **Obfuscar 参数保守**：`RenameProperties`、`RenameEvents`、`RenameFields` 建议保持 `false`，除非你完全控制所有调用方
5. **`printf` 中的 `$(InPath)`**：必须用单引号包裹整个 printf 格式字符串，确保 bash 不解析 `$(InPath)`

## 十一、经验教训总结

| 教训 | 级别 | 说明 |
|------|------|------|
| **永远不要在 CI 中盲目尝试** | 🔴 致命 | 每次 CI 失败浪费 1-2 分钟，且调试成本高。**必须本地完整验证后再推 CI** |
| **`dotnet build` ≠ `dotnet publish`** | 🟠 重要 | `build` 只输出项目 DLL；`publish` 输出完整依赖集。Obfuscar 需要后者 |
| **heredoc 在 GitHub Actions 中不可靠** | 🟠 重要 | 缩进、变量替换、`$()` 命令替换都存在陷阱。优先用 `printf` 或模板文件 |
| **pack 后再混淆比混淆后再 pack 更安全** | 🟡 中等 | pack 依赖 `bin/` 目录的完整性和一致性；混淆后替换 bin/ 可能破坏多 TFM 包 |
| **nupkg 本质是 ZIP** | 🟢 基础 | 可以直接用 Python `zipfile` 模块修改，无需重新 pack |
| **nuspec 不一定有 hash 元素** | 🟢 基础 | `dotnet pack` 默认不生成 `<files>` 节，hash 更新脚本需要有容错 |
| **Python zipfile 'a' 模式追加而非替换** | 🔴 致命 | 导致 nupkg 重复文件，NuGet 400。详见[文档 24](./24_采坑记录_本地NuGet推送_replace_nupkg_dll脚本三次迭代_20260604.md) |
| **Python ET tostring() 引入 ns0: 前缀** | 🔴 致命 | 导致 nuspec XML 污染，NuGet 400。详见[文档 24](./24_采坑记录_本地NuGet推送_replace_nupkg_dll脚本三次迭代_20260604.md) |
| **不要修改 nuspec XML** | 🔴 致命 | 即使只更新 hash，ET 序列化也会破坏 XML 结构。最优方案：完全不碰 nuspec |
| **所有过程必须固化为脚本** | 🔴 致命 | 临时命令散落多轮对话，无法复现。replace-nupkg-dll.py 写了 3 版才稳定 |
