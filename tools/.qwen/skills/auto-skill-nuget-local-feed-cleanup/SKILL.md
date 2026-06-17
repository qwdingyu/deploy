---
name: nuget-local-feed-cleanup
description: 清理本地 NuGet feed 时必须先确认包之间的依赖关系，禁止仅凭"消费方未直接引用"就删除包。
source: auto-skill
extracted_at: '2026-06-14T07:30:00.000Z'
---

## 核心规则

**禁止仅凭"消费方未直接引用"就删除 local-feed 中的包。** 一个包可能被另一个 SDK 项目的传递依赖引用，删除会导致下游项目 restore/build 失败。

## 错误案例

```
# ❌ 错误做法
# 发现 UseThink.Iot 的 csproj 中没有直接引用 ZL.Iot.Runner
# 于是直接删除 ZL.Iot.Runner.1.1.0.nupkg

# 后果：ZL.Iot.Runner 是 iot-sdk 自己的运行时项目（src/application/ZL.Iot.Runner/）
# 它的 nupkg 是给 iot-sdk 后续开发用的，删除后需要重新 pack
# 而且 dotnet pack 默认版本号来自 csproj（1.0.0），不是 pipeline 传入的版本（1.1.0）
# 导致恢复的包内容与原版不一致
```

## 正确流程

### 1. 确认包的用途

```bash
# 查找包在项目中的引用
grep -rn "ZL.Iot.Runner[^.]" /path/to/consumer --include="*.csproj" --include="*.props"

# 查找包在 SDK 源码中的项目
find /path/to/sdk -name "*.csproj" | xargs grep -l "ZL.Iot.Runner"

# 查看包内容
unzip -l ~/.nuget/local-feed/ZL.Iot.Runner.1.1.0.nupkg
```

### 2. 确认是否有其他项目依赖

```bash
# 检查传递依赖：哪些项目间接引用了这个包
dotnet list /path/to/project package --include-transitive | grep "ZL.Iot.Runner"
```

### 3. 决策树

```
是否需要删除？
├── 是，且是过期废弃版本（如 1.1.0-test）
│   └── 可以删除，但先确认无项目引用
├── 是，且是正式版本（如 1.1.0）
│   ├── 确认没有任何项目引用（直接+传递）
│   │   └── 可以删除
│   └── 不确定 → 保留，不做手术
└── 否
    └── 保留
```

### 4. 如果必须删除

```bash
# 步骤 1: 确认无引用后再删除
grep -r "ZL.SomePackage" /path/to/all/consumers --include="*.csproj"

# 步骤 2: 删除
rm -f ~/.nuget/local-feed/ZL.SomePackage.*.nupkg

# 步骤 3: 验证所有消费者仍能 build
dotnet build /path/to/all/consumers
```

### 5. 如果需要恢复被误删的包

```bash
# 错误：直接用 dotnet pack（版本号来自 csproj，不是 pipeline 传入的版本）
dotnet pack src/app/ZL.SomePackage/ZL.SomePackage.csproj -c Release \
    --output ~/.nuget/local-feed
# 结果：ZL.SomePackage.1.0.0.nupkg（错误版本号）

# 正确：用 pipeline 指定的版本号重新 pack
cd /path/to/sdk && CLOUDFLARE_API_TOKEN="" \
    dotnet build src/app/ZL.SomePackage/ZL.SomePackage.csproj \
    -c Release --no-incremental -p:Version=1.1.0 && \
    dotnet pack src/app/ZL.SomePackage/ZL.SomePackage.csproj \
    -c Release --no-build -p:Version=1.1.0 \
    --output ~/.nuget/local-feed
# 结果：ZL.SomePackage.1.1.0.nupkg（正确版本号）
```

## 验证检查清单

- ✅ 删除前确认包的使用范围（直接引用 + 传递依赖）
- ✅ 删除前确认是过期版本（-test）还是正式版本
- ✅ 删除后验证所有消费者项目 build 通过
- ✅ 恢复包时使用 pipeline 指定的版本号，不用 dotnet pack 默认版本
- ✅ 删除前最好先备份到某个临时目录

## 一句话原则

> 宁可多查一步依赖关系，也不要误删一个包导致下游项目 restore 失败。
