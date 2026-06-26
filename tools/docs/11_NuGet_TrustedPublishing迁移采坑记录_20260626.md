# NuGet Trusted Publishing 迁移采坑全记录

> 日期：2026-06-26
> 背景：ZL 体系（ZL.PlcBase / iot-sdk / ZL.PlcSimulator / UseThink.Iot）从单个 NUGET_API_KEY 全面迁移到 nuget.org Trusted Publishing

---

## 一、整体迁移涉及的仓库

| 仓库 | GitHub 地址 | 包数 | 迁移方式 | 状态 |
|------|-------------|------|---------|------|
| **ZL.PlcBase** | `qwdingyu/ZL.PlcBase` | 4 | Trusted Publishing | ✅ 完成 |
| **iot-sdk** | `qwdingyu/ZL.Iot.Sdk` | 24 | Trusted Publishing | ✅ 完成 |
| **ZL.PlcSimulator** | `qwdingyu/ZL.PlcSimulator` | 2 | API Key 回退（预留 Trusted Publishing 策略） | ✅ 完成 |
| **UseThink.Iot** | 未推 GitHub | 0（消费者） | 无变更，仅 NuGet.config | ✅ 完成 |

---

## 二、核心坑点

### 坑 1：YAML 中 `on` 被解析为布尔值 True（大坑）

**现象**：`gh workflow run publish.yml` 报错 `Workflow does not have 'workflow_dispatch' trigger`，而 workflow 文件明明有 `workflow_dispatch:`。

**原因**：YAML 规范中 `on`、`yes`、`true` 都是布尔值 `True` 的别名。Python PyYAML 解析时 `data['on']` 为 `True`，GitHub Actions 的 YAML 解析器也有同样问题。

```yaml
# ❌ 错误写法
on:
  push:
    tags: ['v*']
  workflow_dispatch:

# ✅ 正确写法
"on":
  push:
    tags: ['v*']
  workflow_dispatch:
```

> **经验**：所有 YAML 顶层键 `on` **必须加引号**写为 `"on":`。GitHub Actions 的示例模板不写引号是因为 GitHub 的 YAML 解析器做了特殊处理，但并非所有版本的 parser 都可靠。

### 坑 2：API Key 失效但流水线显示成功

**现象**：NUGET_API_KEY 早已过期（403），但 ZL.Pipeline.Cli 的 `push.py` 第 99 行代码吞掉了错误：

```python
ok=True,  # 本地成功即为通过，远程失败不阻断
```

**原因**：本地 feed 复制始终成功，远程推送到 nuget.org 的 403 被上游吞掉，流水线永远显示成功。

**教训**：这种"远程失败不阻断"的设计会导致问题长期不被发现。建议至少加一个 WARNING 级别的日志告警。

### 坑 3：CI 环境没有本地 feed

**现象**：iot-sdk 的 `NuGet.config` 引用了 `/Users/dingyuwang/.nuget/local-feed`，在 GitHub Actions runner（ubuntu-latest）上该路径不存在，导致 `NU1301: The local source doesn't exist`。

**修复**：在 workflow 的 restore 步骤中生成临时 `nuget.config`（只含 nuget.org）：

```yaml
- name: Restore
  run: |
    echo '<?xml version="1.0" encoding="utf-8"?>' > nuget.ci.config
    echo '<configuration><packageSources><clear />' >> nuget.ci.config
    echo '<add key="nuget.org" value="https://api.nuget.org/v3/index.json" />' >> nuget.ci.config
    echo '</packageSources></configuration>' >> nuget.ci.config
    dotnet restore --configfile nuget.ci.config
```

> **注意**：不能用 heredoc 写入 `<?xml`，因为 YAML 的 `run: |` 块中 `<?` 会被解析为 YAML directive。

### 坑 4：项目间硬编码的绝对路径引用

**现象**：`ZL.PlcSimulator/src/PlcSimulator.Core/PlcSimulator.Core.csproj` 中有：

```xml
<ProjectReference Include="/Users/dingyuwang/0-X/iot-sdk/src/platform/ZL.Watchdog/ZL.Watchdog.csproj" />
```

在 CI runner 上该路径不存在，构建失败。

**修复**：改成 NuGet 包引用（版本由 CPM 统一管理）：

```xml
<PackageReference Include="ZL.Watchdog" />
```

**经验**：本地开发用项目引用方便调试和联调，但必须保证 CI 环境下也能正常工作。通常做法是条件编译或统一走 NuGet 包引用。

### 坑 5：secrets 不可在 `if` 条件表达式中使用

**现象**：写回退逻辑时试图在 `if:` 中引用 `secrets.NUGET_API_KEY`：

```yaml
- name: Push (fallback)
  if: steps.login.outcome != 'success' && secrets.NUGET_API_KEY != ''
```

GitHub Actions 报错：`Unrecognized named-value: 'secrets'`

**原因**：GitHub Actions 中 `secrets` 上下文只允许在 `env:` 和 `run:` 中使用，不可在 `if:` 条件中引用。

**修复**：将 secrets 通过 `env:` 注入，在 shell 中判断：

```yaml
- name: Push to NuGet.org
  env:
    NUGET_API_KEY: ${{ steps.login.outputs.NUGET_API_KEY || secrets.NUGET_API_KEY }}
  run: |
    if [[ -z "$NUGET_API_KEY" ]]; then
      echo "::error::No API key available"
      exit 1
    fi
    dotnet nuget push ... -k "$NUGET_API_KEY"
```

### 坑 6：Obfuscar 安装 - 包名不一致

**现象**：`dotnet tool install -g Obfuscar` 报错 `Package obfuscar is not a .NET tool`。

**原因**：正确的 NuGet 工具包名是 `Obfuscar.GlobalTool`（注意区分：包名 `Obfuscar.GlobalTool` vs 命令名 `obfuscar.console`）。

**修复**：
```yaml
- name: Install Obfuscar
  run: dotnet tool install --global Obfuscar.GlobalTool --version 2.2.38
```

### 坑 7：GitHub Actions 暂不支持 .NET 10

**现象**：iot-sdk 部分项目使用 `net10.0` 目标框架，但 GitHub Actions 的 ubuntu-latest 只预装 .NET 8.0 和 .NET 9.0 SDK。

**处理**：
- 构建时 `dotnet build` 可正常编译（项目引用 `net8.0;net10.0` 多目标，CI 只生效 `net8.0` 部分）
- 混淆时需要只对 `net8.0` 做 publish + obfuscation
- `dotnet pack` 产生的 nupkg 中只有 `net8.0` 的输出被混淆，`net10.0` 输出保持原始（非混淆）状态

### 坑 8：NuGet Login 的 `user` 参数必须匹配策略创建者

**现象**：Trusted Publishing 配置错误时出现：
```
Token exchange failed (HTTP 401) ... Make sure you are using the username of the policy creator, not the policy owner
```

**说明**：`NuGet/login@v1` 的 `user:` 参数必须填写 **nuget.org 账号的 username**（即创建 Trusted Publishing 策略的那个账号），不是 GitHub 用户名。

---

## 三、ZL.Pipeline.Cli 的后续定位

**短期结论：并非无用，职责变化了。**

### 以前 ZL.Pipeline.Cli 的职责
1. ✅ 构建 + 打包
2. ✅ 混淆（Obfuscar + DLL 替换）
3. ✅ 推送到本地 feed（开发用）
4. 🟡 推送到 nuget.org（远程）

### 迁移后 ZL.Pipeline.Cli 的职责
1. ✅ 构建 + 打包（本地开发仍需要）
2. ✅ 混淆（本地开发仍需要）
3. ✅ 推送到本地 feed（已删除，但不影响）
4. ❌ 推送到 nuget.org → 已迁移到 GitHub Actions

### 实际受影响的部分

`push.py` 中的远程推送代码已不再需要，但仍可作为 **fallback 逻辑保留**（API Key 仍有过渡期）。

本地开发流程不变：
```bash
# 本地开发 → 本地测试（还是走 ZL.Pipeline.Cli）
zl-pipeline publish --local --version 2.2.1

# 正式发布 → GitHub Actions（自动触发）
git tag v2.3.0 && git push origin v2.3.0
```

### 建议保留 ZL.Pipeline.Cli 的理由

1. **本地开发迭代**：`dotnet pack` + Obfuscar 混淆 + 本地测试的工作流
2. **消费者 CPM 同步**：`zl-pipeline sync-consumers` 仍负责更新 tmom / UseThink.Iot 的版本号
3. **API Key 过渡期**：如果某些仓库（如 PlcSimulator）还未配置 Trusted Publishing，可用 API Key 回退

---

## 四、publish.yml 通用模板（用于未来新仓库）

```yaml
"on":
  push:
    tags: ['v*']
  workflow_dispatch:
    inputs:
      version:
        description: 'Package version'
        required: true
      dry-run:
        description: 'Pack only, no push'
        type: boolean
        default: false

jobs:
  build-and-pack:
    runs-on: ubuntu-latest
    outputs:
      version: ${{ steps.version.outputs.version }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-dotnet@v4
        with:
          dotnet-version: '8.0.x'

      - name: Determine version
        id: version
        run: |
          if [ "${{ github.event_name }}" = "push" ]; then
            echo "version=${GITHUB_REF_NAME#v}" >> $GITHUB_OUTPUT
          else
            echo "version=${{ inputs.version }}" >> $GITHUB_OUTPUT
          fi

      # Restore（CI 环境无需本地 feed，走临时 config）
      - name: Restore
        run: |
          echo '<?xml version="1.0" encoding="utf-8"?>' > nuget.ci.config
          echo '<configuration>' >> nuget.ci.config
          echo '  <packageSources><clear />' >> nuget.ci.config
          echo '    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />' >> nuget.ci.config
          echo '  </packageSources>' >> nuget.ci.config
          echo '</configuration>' >> nuget.ci.config
          dotnet restore --configfile nuget.ci.config

      # Build → Pack → （可选 Obfuscar）

      - uses: actions/upload-artifact@v4
        with:
          path: artifacts/packages/*.nupkg

  push-to-nuget:
    needs: build-and-pack
    runs-on: ubuntu-latest
    if: github.event_name == 'push' || (github.event_name == 'workflow_dispatch' && inputs.dry-run != true)
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
      - uses: actions/setup-dotnet@v4
      - name: NuGet login
        uses: NuGet/login@v1
        id: login
        with:
          user: dingyuw
      - name: Push
        env:
          NUGET_API_KEY: ${{ steps.login.outputs.NUGET_API_KEY }}
        run: |
          for pkg in artifacts/packages/*.nupkg; do
            dotnet nuget push "$pkg" \
              --source https://api.nuget.org/v3/index.json \
              --api-key "$NUGET_API_KEY" \
              --skip-duplicate
          done
```

---

## 五、API Key 回退模式（当 Trusted Publishing 未配置时）

```yaml
- name: NuGet login (OIDC)
  uses: NuGet/login@v1
  id: login
  continue-on-error: true
  with:
    user: dingyuw

- name: Push
  env:
    NUGET_API_KEY: ${{ steps.login.outputs.NUGET_API_KEY || secrets.NUGET_API_KEY }}
  run: |
    dotnet nuget push ... -k "$NUGET_API_KEY"
```

> 注意：`secrets.NUGET_API_KEY` 只在 `env:` 和 `run:` 中可用，**不能在 `if:` 中引用**。

---

## 六、PlcSimulator 部署状态

**已成功部署到 nuget.org**（版本 2.2.1）。

- `PlcSimulator.Core.2.2.1` ✅ 已推送
- `PlcSimulator.Grpc.2.2.1` ✅ 已推送

但 Trusted Publishing **策略未在 nuget.org 上配置**（`Token exchange failed (HTTP 401)`），推送使用了 API Key 回退。如需启用 Trusted Publishing，去 [nuget.org/account/trusted-publishing](https://www.nuget.org/account/trusted-publishing) 配置：

```
Repository Owner: qwdingyu
Repository: ZL.PlcSimulator
Workflow File: publish.yml
```

---

## 七、版本统一治理（ZL 体系专属）

### 当前状态
所有 ZL 包统一版本 **2.2.1**，消费者 CPM 文件已对齐此版本。

### 版本发布流程（简化版）

```
# 1. 本地开发 + 测试
cd ZL.PlcBase && zl-pipeline publish --local --version 2.3.0
cd iot-sdk && zl-pipeline publish --local --version 2.3.0

# 2. 确认无误后，打 tag 推送到 GitHub → 自动发布
cd ZL.PlcBase && git tag v2.3.0 && git push origin v2.3.0
cd iot-sdk && git tag v2.3.0 && git push origin v2.3.0

# 3. 或者手动触发
gh workflow run publish.yml --repo qwdingyu/ZL.PlcBase -f version=2.3.0
gh workflow run publish.yml --repo qwdingyu/ZL.Iot.Sdk -f version=2.3.0
```

---
*文档最后更新：2026-06-26*
