---
name: publish-ispackable-false-package
description: 发布 IsPackable=false 的 .NET 项目到 NuGet 本地 feed 的标准流程（临时改 true → pack → 恢复 false）。
source: auto-skill
extracted_at: '2026-06-14T07:45:00.000Z'
---

## 场景

某些 .NET 项目（如模板库、工具库）在 SDK 源码中作为**项目引用**存在（`IsPackable=false`），但消费方可能需要通过 NuGet 引用。此时需要将其打包到 local-feed。

典型项目：`ZL.Iot.Runner.Templates`（嵌入 .scriban 模板的 DLL）

## 错误做法

```bash
# ❌ 直接 pack：IsPackable=false 会被 dotnet pack 跳过
dotnet pack src/app/ZL.SomeLib/ZL.SomeLib.csproj -c Release \
    --output ~/.nuget/local-feed
# 结果：nupkg 未生成
```

## 正确流程

### 1. 临时启用 IsPackable

```bash
# 读取原始内容确认
grep "IsPackable" src/app/ZL.SomeLib/ZL.SomeLib.csproj

# 改为 true
sed -i '' 's/<IsPackable>false<\/IsPackable>/<IsPackable>true<\/IsPackable>/g' \
    src/app/ZL.SomeLib/ZL.SomeLib.csproj
```

### 2. 编译 + 打包（使用 pipeline 指定的版本号）

```bash
cd /path/to/sdk && \
    dotnet build src/app/ZL.SomeLib/ZL.SomeLib.csproj \
        -c Release -p:Version=1.1.0 && \
    dotnet pack src/app/ZL.SomeLib/ZL.SomeLib.csproj \
        -c Release --no-build -p:Version=1.1.0 \
        --output ~/.nuget/local-feed
```

**关键**：必须用 `-p:Version=X.X.X` 传入版本号。不用 `dotnet pack` 默认版本号（来自 csproj，可能不一致）。

### 3. 恢复 IsPackable=false

```bash
sed -i '' 's/<IsPackable>true<\/IsPackable>/<IsPackable>false<\/IsPackable>/g' \
    src/app/ZL.SomeLib/ZL.SomeLib.csproj
```

### 4. 验证

```bash
ls -lh ~/.nuget/local-feed/ZL.SomeLib.1.1.0.nupkg
unzip -l ~/.nuget/local-feed/ZL.SomeLib.1.1.0.nupkg
```

## 验证检查清单

- ✅ IsPackable=false 的项目不会自动生成 nupkg，必须临时改 true
- ✅ 必须用 pipeline 指定的版本号（`-p:Version=X.X.X`），不是 csproj 默认版本
- ✅ pack 完成后必须恢复 IsPackable=false，避免影响 pipeline.json 的 build/pack 流程
- ✅ 恢复后再验证一次 csproj 内容，确认改回来了

## 一句话原则

> 临时开关 IsPackable，用 pipeline 版本号 pack，完成后立即恢复。
