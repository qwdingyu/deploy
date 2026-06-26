---
name: dotnet-pipeline-cli
description: 审查与改进 .NET NuGet 发布流水线 CLI（zl-pipeline），包含模块化架构（Config/Context/Steps/Runner）、多仓库统一版本治理策略、消费者 CPM 同步门禁机制。
source: auto-skill
extracted_at: '2026-06-14T03:07:36.011Z'
updated_at: '2026-06-26T03:30:00.000Z'
---

## 已落地架构（参考）

项目已完成从单文件脚本到分层架构的重构，文件布局如下：

```
ZL.Pipeline.Cli/
├── pyproject.toml          # 包定义，zl-pipeline 入口，依赖 jsonschema
├── schemas/pipeline-schema.json  # JSON Schema 校验
└── zl_pipeline/
    ├── __init__.py         # __version__ = "1.0.0"
    ├── __main__.py         # entry: python -m zl_pipeline
    ├── main.py             # CLI 入口 (plan/verify/publish/check/sync-consumers/align-versions/clean/list-config/init)
    ├── config.py           # PipelineConfig frozen dataclass + load_config() + init_config() + schema 校验
    ├── context.py          # PipelineContext frozen dataclass（不可变运行上下文）
    ├── result.py           # StepResult frozen dataclass
    ├── state.py            # StepState + StateStore（JSON 持久化，断点续跑，原子写入）
    ├── runner.py           # StepRunner + STEP_REGISTRY + @register_step 装饰器
    ├── report.py           # 彩色终端报告
    ├── dotnet.py           # DotnetAdapter（build/pack/publish/restore，subprocess.Popen 流式读取防超时杀进程）
    ├── obfuscar.py         # ObfuscarAdapter（run，默认 XML 自动生成）
    └── steps/
        ├── __init__.py     # 导入所有 step 触发注册
        ├── build.py        # 步骤 1: 编译（MSBUILDDISABLENODEREUSE=1）
        ├── pack.py         # 步骤 2: 打包 NuGet
        ├── fix_nuspec.py   # 步骤 3: 修复 nupkg 内 nuspec 依赖版本
        ├── publish_deps.py # 步骤 4: 发布依赖集（为 obfuscate 准备）
        ├── obfuscate.py    # 步骤 5: Obfuscar 混淆
        ├── replace_nupkg.py# 步骤 6: 替换 nupkg dll（read/write 模式，非 append）
        ├── api_compare.py  # 步骤 7: API 对比（0=一致, 2=差异视为失败, 1=异常）
        └── push.py         # 步骤 8: 推送到 NuGet.org
```

## 使用时机

当需要审查或改进以下场景时使用本 skill：

- `.NET` 库发布流水线 CLI
- `build -> pack -> fix_nuspec -> publish_deps -> obfuscate -> replace_nupkg -> api_compare -> push`
- `pipeline.json` 配置驱动的 NuGet 发布工具
- 混淆发布、API 完整性检查、消费者版本同步
- 用户反馈"编译太慢""排错太久""工具链混乱"

## 目标

确保流水线 CLI 满足以下标准：

优先顺序必须是：

1. **先修发布正确性** — 文件存在性检查、dry-run 兼容性、API 对比正确性
2. **再降低排错时间** — per-step 日志 + 结构化失败 summary + 断点续跑
3. **再治理工具结构混乱** — 分层架构 + 配置驱动 + schema 校验
4. **最后优化性能与工程化体验** — fingerprint 缓存 + 并行

## 核心审查清单

审查这类 CLI 时，必须逐项检查：

### 架构层
- 是否符合分层架构：Config → Context → Adapters → Steps → Runner → CLI → Report
- 是否使用 `@register_step` 装饰器注册步骤
- StepResult 是否为 frozen dataclass
- PipelineContext 是否为 frozen dataclass
- StateStore 是否持久化到 JSON 文件，是否使用原子写入（先 .tmp 再 rename）
- 依赖项是否声明（`jsonschema`）

### 语义层

**关键区分（易错点）：**

| 命令 | 执行行为 | 推送 | 备注 |
|------|---------|------|------|
| `plan <version>` | 仅展示计划，不执行任何步骤 | N/A | 纯展示 |
| `verify <version>` | 执行完整流水线，但 dry-run 模式 | ❌ 不推送 | 文件不存在时步骤返回 ok=True 并跳过 |
| `publish <version>` | 执行完整流水线，真实构建 | ✅ 本地缓存必做，远程推送可选 | push 步骤永远不阻断流水线（本地成功即通过） |
| `check <package> <version>` | 检查已发布的包是否存在 | N/A | 需要 pipeline.json 存在 |

**push 步骤行为（2026-06-13 修订）：**
- push 步骤 **永远不阻断流水线** — 先本地缓存（复制到 `~/.nuget/local-feed`），再根据 `NUGET_API_KEY` 决定是否远程推送
- 无 API key：本地缓存成功即返回 `ok=True`，error_detail 显示保存路径
- 有有效 API key：本地缓存 + 远程推送，远程失败不阻断
- 有无效 API key：本地缓存成功即返回 `ok=True`，error_detail 包含远程失败信息
- 本地缓存路径可通过环境变量 `NUGET_LOCAL_FEED` 自定义，默认 `~/.nuget/local-feed`

> ⚠️ **重要警示：远程失败被静默吞掉**
> 由于 `ok=True  # 本地成功即为通过，远程失败不阻断`，**即使 NUGET_API_KEY 已失效/过期（403），流水线仍然显示成功**。
> 用户可能长期以为远程推送正常，但实际上并未推送到 nuget.org。
> 排查方法：观察终端输出或 StateStore 中 push 步骤的 `error_detail`，包含 `"本地: OK | 远程: ..."` 字样。
> 独立验证脚本：用 `test-nuget-push.sh`（见 tools 目录）针对单个包名做隔离测试，排除流水线逻辑干扰。

**dry-run 兼容性规则（已固化）：**
每个步骤在检查文件/依赖存在性时，必须检查 `ctx.dry_run`：
```python
if not nupkg_path.exists():
    if ctx.dry_run:
        return StepResult(ok=True, error_detail="dry-run 模式，跳过...")
    return StepResult(ok=False, ...)
```

### 执行层
- 是否支持 `--only <project>`（仅处理指定项目）
- 是否支持 `--from-step <step>`（从指定步骤开始）
- 是否支持 `--resume` 断点续跑（从 StateStore 恢复）
- 是否支持 `--skip-build`（跳过编译步骤）
- API compare 返回码语义：0=一致✅, 1=脚本异常, 2=差异（视为失败❌）

### 日志层
- 每 step 每 project 是否有独立日志文件（`artifacts/logs/<version>/<step>-<project>.log`）
- 失败时是否输出结构化 summary（StepResult 包含 step/project/command/exit_code/stderr_tail/error_detail）
- summary 是否包含：step, project, command, exit code, duration, log file, stderr tail

### 超时与稳定性
- 所有 subprocess 调用必须有 `timeout` 参数
- dotnet build: timeout=300s, retry=1（MSBUILDDISABLENODEREUSE=1）
- dotnet pack: timeout=600s, retry=2
- dotnet publish: timeout=300s, retry=1
- obfuscar: timeout=300s, retry=1
- replace_nupkg/api_compare: timeout=120s, retry=1
- 使用 `subprocess.Popen` 流式读取 stdout/stderr，防止长时间无输出被终端杀掉

## 新增步骤开发指南

新增步骤需完成以下三步：

### 1. 创建步骤文件
```python
# zl_pipeline/steps/my_step.py
from __future__ import annotations
from zl_pipeline.runner import register_step
from zl_pipeline.context import PipelineContext
from zl_pipeline.result import StepResult

@register_step("my_step")
def my_step(context: PipelineContext, project_cfg: dict) -> StepResult:
    # ⚠️ 必须检查 dry-run 兼容性：如果依赖物理文件存在，
    # 当 ctx.dry_run=True 且文件不存在时，返回 ok=True 并跳过
    if not some_file.exists():
        if context.dry_run:
            return StepResult(
                step="my_step",
                project=project_cfg["name"],
                ok=True,
                error_detail="dry-run 模式，跳过",
            )

    # 执行逻辑...
    return StepResult(
        step="my_step",
        project=project_cfg["name"],
        ok=True,  # 或 False
        duration=0.5,
        command=["my-command"],
        exit_code=0,
        error_detail="",
    )
```

### 2. 注册到执行顺序
编辑 `zl_pipeline/steps/__init__.py`，添加导入：
```python
from zl_pipeline.steps import build, pack, my_step  # noqa: F401
```

### 3. 更新执行计划
`plan()` 命令会自动遍历 `STEP_REGISTRY`，无需额外配置。

## Python 字节码缓存陷阱（重要）

**症状**：代码修改（如新增 `obfuscate` 检查）在重启后不生效，老版本逻辑仍在运行。

**根因**：`pip install -e .`（可编辑安装）或有 `.pth` 文件时，Python 从 `.pyc` 缓存加载模块。如果 `__pycache__` 中的字节码比 `.py` 源文件旧，但 Python 判断 mtime 匹配未触发重新编译，则修改不生效。

**排查流程**：
1. 确认模块实际加载路径：`import zl_pipeline.steps.replace_nupkg as rn; print(rn.__file__)`
2. 确认加载的源码包含修改：`import inspect; print(inspect.getsource(rn.step_replace_nupkg))`
3. 检查 `.pyc` 与 `.py` 的 mtime 对比
4. **修复**：删除所有 `__pycache__` 目录，重新运行
   ```bash
   find <project_root> -name "__pycache__" -type d -exec rm -rf {} +
   ```

**注意**：可编辑安装（`pip install -e .`）创建的 `__editable__.*.pth` 文件使用自定义 MetaPathFinder，其缓存行为与标准 import 略有不同。遇到"代码修改不生效"时，应始终先清理 `__pycache__`。

**实操验证**：每次修改 zl_pipeline 代码后，运行 `publish <version> --only <single_project>` 确认修改生效，不要只依赖 `grep` 确认源码已改。

## 常见步骤实现陷阱

### push 步骤的 stderr 与 stdout 行为差异
- 其他步骤使用 `DotnetAdapter`（Popen 流式读取），stdout 会实时打印到终端
- push 步骤使用 `subprocess.run(capture_output=True)`，stdout/stderr 被捕获，**不会**流式打印
- 因此 push 的 `error_detail` 不能用 `result.stderr[:500]` 直接显示（会包含多行推送过程日志）
- 应实现 `_extract_first_line(text)` 函数：遍历 stderr 行，匹配包含 `Forbidden/NotFound/Unauthorized/403/401/404/timeout/expired` 关键词的行返回；兜底返回最后一行

```python
def _extract_first_line(text: str) -> str:
    """提取 push 步骤 stderr 中的关键错误行"""
    if not text:
        return ""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    for line in lines:
        if any(kw in line for kw in ("Forbidden", "NotFound", "Unauthorized", "403", "401", "404", "timeout", "expired")):
            return line[:200]
    return lines[-1][:200] if lines else ""
```

### pack/publish 参数拼接 bug
- ❌ `cmd.extend(["-p:PackageVersion=", package_version])` 将参数拆成两个，导致 "1.1.0-test" 被当作项目名
- ✅ `cmd.append(f"-p:PackageVersion={package_version}")` 合并为一个参数
- 所有 `-p:` 参数必须用 `f"-p:{key}={value}"` 拼接

## 审查输出模板

审查后应输出：

- 当前是否符合分层架构：`是 / 否`
- 核心问题：`P0 / P1 / P2`
- 止血项：`最多 5 项`
- 改造顺序：`分阶段`
- 风险项：`向后兼容 / 配置迁移 / 现有脚本影响`
- dry-run 兼容性：`全部 / 部分 / 缺失`（是否每个步骤都处理了 ctx.dry_run）

## 代码审查与清理标准流程

当需要对 zl_pipeline 代码库进行质量审查时，遵循以下系统化流程：

### 步骤 1：读取所有 Python 文件

必须逐一读取 `zl_pipeline/` 下每个 `.py` 文件（包括 `steps/` 子目录），不能只看目录列表。重点关注：
- 模块级 `import` 语句（未使用的导入）
- 函数体内的 `import` 语句（冗余重复导入）
- 数据类的 docstring 是否缺失
- 公开方法的 docstring 是否缺失

### 步骤 2：分类问题

将发现的问题分为四类：
1. **未使用导入** — 模块级或函数体内的 `import` 从未被使用
2. **冗余导入** — 同一模块在顶层和函数体内重复导入
3. **缺失 docstring** — 公开类/方法/数据类缺少文档字符串
4. **逻辑错误** — 运行时错误（如参数拆分、错误提取）

### 步骤 3：批量修复

按优先级批量修复：
1. 未使用导入 → 直接删除
2. 冗余导入 → 合并为单次导入
3. 缺失 docstring → 为公开 API 补充简短 docstring
4. 逻辑错误 → 修复代码 + 补充测试/验证

### 步骤 4：端到端验证

修复完成后必须清理 `__pycache__`（防止旧字节码干扰），然后运行完整的端到端流程：

```bash
# ⚠️ 必须清理缓存，否则修改可能不生效
find <project_root> -name "__pycache__" -type d -exec rm -rf {} +

# 快速验证
cd /path/to/project && zl-pipeline publish <version> --only <single_project>
```
用单个项目快速验证，确认所有步骤行为正常（build/pack/fix_nuspec/publish_deps/obfuscate/replace_nupkg/api_compare/push）。

### 已知的代码质量问题清单（持续更新）

| 文件 | 问题 | 修复方式 |
|------|------|---------|
| `dotnet.py` | `import os` 未使用 | 删除 |
| `report.py` | `from datetime import datetime, timezone` 未使用 | 删除 |
| `config.py` | `_update_cpm_version` 内 `import re as re2` | 改为复用顶层 `re` |
| `main.py` | `_cmd_check` 内 `import json` | 删除（顶层已有） |
| `main.py` | `_cmd_align_versions` 内 `import re as re2` | 改为复用外层 `import re` |

### 端到端验证检查清单

运行 `publish <version> --only <single_project>` 后，确认：
- ✅ `__pycache__` 已清理（旧缓存可能导致修改不生效）
- ✅ 环境检查输出正常（dotnet/python/MSBUILDDISABLENODEREUSE/obfuscar/scripts）
- ✅ 每个步骤显示 `[PASS]` 或预期的 `[FAIL]`
- ✅ `[FAIL]` 的 error_detail 简洁（不超过一行，关键信息在前）
- ✅ 流程结束时显示 `[ABORT]` 或所有步骤完成
- ✅ 报告输出正常（总步骤/通过/失败/混淆状态）

- **dry-run 与 verify 混用**：verify 执行 dry-run，但需要物理文件的步骤必须跳过而非失败
- **新增步骤未处理 dry-run**：导致 verify 在文件不存在时报 FAIL，掩盖了 dry-run 验证能力
- `api compare` 打印 warning 却返回 0（实际 exit 2 应视为失败）
- pack/publish 再次触发隐式 build（应使用 `--skip-build`）
- 每次临时 build C# 校验工具
- shell 与 CLI 各自维护一套发布逻辑（zl_pipeline 是统一入口）
- schema 文件存在但未接入运行时校验
- 全局 `PASS/FAIL` 计数代替结构化结果
- 新增步骤忘记在 `steps/__init__.py` 中注册
- replace_nupkg 使用 append 模式（应使用 read/write 模式，否则 nupkg 内出现重复文件导致 400）
- `obfuscar.xml` 中写死路径（应使用 `$(InPath)` 变量）
- 每次 subprocess 调用不带 timeout（导致终端 90s 无输出时进程被杀）
- push 步骤的 error_detail 未过滤多行日志（stderr 包含推送过程信息，直接用 `[:500]` 会暴露不相关行）
- pack/publish 的 `-p:` 参数用 `extend` 拆成两个参数（应 `append` 合并为 `f"-p:{key}={value}"`）

## 一句话原则

> 先让每次失败 5 分钟内可定位、可重跑，再让 dry-run 验证真正可用，最后让工具链结构长期可维护。

---

## 版本治理：跨仓库统一版本策略

### 问题场景

多个 .NET 仓库（PlcBase + iot-sdk）发布系列 NuGet 包，多个消费者项目（UseThink.Iot、tmom）通过 CPM（Central Package Management）引用。版本漂移的四种根因：

| # | 漂移路径 | 危害 |
|---|---------|------|
| 1 | 手动编辑消费者 CPM 中的版本号 | 一个消费者变高/变低，其他不同步 |
| 2 | `align-versions` 查询 NuGet.org 返回旧版本（1.1.0） | 消费者被"降级"回旧版本 |
| 3 | 只构建了一边（只跑 PlcBase 没跑 iot-sdk） | 部分包有新版，部分没有 |
| 4 | 构建部分失败，包缺失 | 消费者 restore 到混合版本 |

### 三职责分离原则

三个工具各管各的——这是整个设计的核心：

| 工具 | 职责 | 适用场景 |
|------|------|---------|
| **`sync-consumers <version>`** | **设置版本** — 把所有 ZL 包都设成同一个版本 | 统一版本模式（日常） |
| **`version-check <version>`** (NEW) | **验证版本** — 检查消费者是否一致 | 发布前门禁 |
| **`align-versions --source <mode>`** | **查询版本** — 从包源获取每个包的最新版 | 独立版本模式（未来用） |

### version-check 实现模式

```python
def cmd_version_check(args):
    cfg = load_config(args.config)
    version = args.version
    consumers = cfg.get("consumers", [])

    # 关键：只检查组管道实际构建的包（来自 pipeline.json projects 列表）
    projects = cfg.get("projects", [])
    pipeline_packages = set()
    for proj in projects:
        pkg_id = get_package_id(proj_dir, proj)
        pipeline_packages.add(pkg_id)

    for consumer in consumers:
        for entry in _expand_consumer_paths(consumer, proj_dir):
            cpm_file = _find_cpm_file(Path(entry["path"]))
            content = cpm_file.read_text(encoding="utf-8")
            for pkg_id in sorted(pipeline_packages):
                pattern = rf'PackageVersion\s+Include="{re.escape(pkg_id)}"\s+Version="([^"]+)"'
                m = re.search(pattern, content)
                if m and m.group(1) != version:
                    fail(...)  # 版本不一致
```

⚠️ **陷阱**：不要用硬编码的正则（如 `ZL\.|ProtocolGateway`）匹配包名。必须从 pipeline.json 的 `projects` 列表动态读取——消费者 CPM 中的 `ProtocolGateway`（第三方包，无 ZL 前缀）与流水线构建的 `ZL.ProtocolGateway` 不同包，硬编码正则会导致误报。

### align-versions --source 策略

```python
--source auto   → 优先查 local-feed，没有才查 NuGet.org（默认）
--source nuget  → 只查 NuGet.org（兼容旧行为）
--source local  → 只查 local-feed（离线模式）
```

新增 `_get_latest_local_version()` 扫描 `~/.nuget/local-feed/` 目录中的 nupkg 文件：

```python
def _get_latest_local_version(package_id: str) -> str | None:
    local_feed = Path.home() / ".nuget" / "local-feed"
    local_pattern = re.compile(
        rf"^{re.escape(package_id)}\.(\d+\.\d+\.\d+(?:\.\d+)?)(?:-[^\.]+)?\.nupkg$",
        re.IGNORECASE)
    versions = [m.group(1) for f in local_feed.iterdir()
                if f.is_file() and (m := local_pattern.match(f.name))]
    if versions:
        versions.sort(key=lambda v: [int(x) for x in v.split(".") if x.isdigit()])
        return versions[-1]
    return None
```

### deploy-fast.sh 集成模式

日常开发的标准入口，构建完成后自动：

```
1. sync-consumers <version>    ← 更新消费者 CPM
2. version-check <version>     ← 门禁验证
3. 任一项失败 → 整体报错退出
```

### 部署入口：deploy-fast.sh

`deploy-fast.sh` 设计为介于单项目 `local-pack` 和正式 `publish` 之间的**日常开发标准入口**，固定调用流水线并强制同步+门禁：

```bash
# 构建 → pack → nuspec修复 → local-feed复制
python3 "$PIPELINE" publish --local "$VERSION"

# 同步消费者 CPM
python3 "$PIPELINE" sync-consumers "$VERSION"

# 版本一致性门禁
python3 "$PIPELINE" version-check "$VERSION"
```

> ⚠️ `deploy-fast.sh` 同时对 PlcBase 和 iot-sdk 执行上述流程。**PlcBase pipeline.json 也必须有 consumers 配置**，否则 PlcBase 产的包（ZL.IotHub、ZL.IotHub.Bridges、ZL.Tag）不会被同步到消费者 CPM。

### 单体版 `zl-pipeline.py` 的 `--local` 模式

`zl-pipeline.py`（旧单体版）添加了 `--local / -l` 标志，用于快速本地发布：

```python
# 用法
python3 zl-pipeline.py --config pipeline.json publish --local 2.2.0

# 效果：build → pack → nuspec-fix → 复制到 ~/.nuget/local-feed/（跳过混淆+推送）
```

实现：在 `cmd_publish()` 的 nuspec 修复步骤之后、混淆检查之前插入：

```python
if getattr(args, 'local', False):
    copied = _copy_to_local_feed(artifacts_dir, version)
    print_report(len(projects), obfuscated=False)
    return
```

### `_copy_to_local_feed` 函数

```python
def _copy_to_local_feed(artifacts_dir: Path, version: str) -> int:
    """将 nupkg 复制到 ~/.nuget/local-feed/"""
    import shutil
    local_feed = Path.home() / ".nuget" / "local-feed"
    local_feed.mkdir(parents=True, exist_ok=True)
    nupkg_files = sorted(artifacts_dir.glob(f"*.{version}.nupkg"))
    count = 0
    for nupkg in nupkg_files:
        dest = local_feed / nupkg.name
        shutil.copy2(str(nupkg), str(dest))
        count += 1
    return count
```

### `_get_latest_local_version` 函数

用于 `align-versions --source local` 从 local-feed 查询包最新版本：

```python
def _get_latest_local_version(package_id: str) -> str | None:
    local_feed = Path.home() / ".nuget" / "local-feed"
    if not local_feed.exists():
        return None
    local_pattern = re.compile(
        rf"^{re.escape(package_id)}\.(\d+\.\d+\.\d+(?:\.\d+)?)(?:-[^\.]+)?\.nupkg$",
        re.IGNORECASE)
    versions: list[str] = []
    for f in local_feed.iterdir():
        if f.is_file():
            m = local_pattern.match(f.name)
            if m:
                versions.append(m.group(1))
    if versions:
        versions.sort(key=lambda v: [int(x) for x in v.split(".") if x.isdigit()])
        return versions[-1]
    return None
```

### `external_deps` 修复

单体版 `zl-pipeline.py` 的 nuspec 修复步骤引用 `external_deps` 但未定义，导致 `NameError`。修复方式：

```python
import zipfile, shutil, tempfile
external_deps: set[str] = set()
# 从 csproj 解析 ExternalPackageReference 列表
for proj in projects:
    csproj_path = Path(proj_dir) / proj["csproj"]
    if csproj_path.exists():
        try:
            csproj_text = csproj_path.read_text(encoding="utf-8")
            for m in re.finditer(r"<ExternalPackageReference\s+Include=\"([^\"]+)\"", csproj_text):
                external_deps.add(m.group(1))
        except Exception:
            pass
```

### `print_report` 的混淆状态修复

`print_report()` 不能因为 `--local` 模式而误报"obfuscar.console 未安装"。修复方式：动态检测 obfuscar 是否实际可用：

```python
def print_report(total, obfuscated=False):
    if obfuscated:
        obf_status = "已启用"
    elif check_obfuscar():
        obf_status = "已跳过 (--local 模式)"
    else:
        obf_status = "未启用 (obfuscar.console 未安装)"
    ...
```

### PlcBase pipeline.json consumers 配置

PlcBase pipeline.json 必须配置 consumers（与 iot-sdk 保持一致），否则 `deploy-fast.sh` 的双 repo sync 只会同步 iot-sdk 的包，遗漏 PlcBase 的包（ZL.IotHub、ZL.IotHub.Bridges、ZL.Tag）。

```jsonc
// ZL.PlcBase/pipeline.json
{
  "consumers": [
    {
      "name": "UseThink.Iot",
      "path": "/Users/dingyuwang/0-X/UseThink.Iot/api",
      "cpmFile": "Directory.Packages.props",
      "autoCommit": false
    },
    {
      "name": "tmom",
      "path": "/Users/dingyuwang/0-X/tmom",
      "cpmFile": "Directory.Packages.props",
      "autoCommit": false
    }
  ]
}
```

> 未配置 consumers 时，`sync-consumers` 报 `pipeline.json 中未配置 consumers`，但 exit 0，容易被忽略。

### 全量版本一致性检查清单

升级版本（如 2.2.0 → 2.2.1）后，必须逐一确认以下 8 项全部对齐：

| # | 检查项 | 验证命令 |
|---|--------|---------|
| 1 | PlcBase/Directory.Build.props `<Version>` | `grep '<Version>' ZL.PlcBase/Directory.Build.props` |
| 2 | iot-sdk/Directory.Packages.props 所有 ZL 包 | `grep 'PackageVersion Include="(ZL\.\|ProtocolGateway)' iot-sdk/Directory.Packages.props \| grep -o 'Version="[^"]*"' \| sort \| uniq -c` — 应只有 1 个版本 |
| 3 | UseThink.Iot CPM 所有 ZL 包 | `grep 'PackageVersion Include="ZL\.' UseThink.Iot/api/Directory.Packages.props` |
| 4 | tmom CPM 所有 ZL 包 | `grep 'PackageVersion Include="ZL\.' tmom/Directory.Packages.props` |
| 5 | deploy-fast.sh 默认版本 | `grep 'VERSION=' deploy/tools/deploy-fast.sh` |
| 6 | version-check 通过（iot-sdk） | `python3 zl-pipeline.py --config iot-sdk/pipeline.json version-check <version>` |
| 7 | version-check 通过（PlcBase） | `python3 zl-pipeline.py --config ZL.PlcBase/pipeline.json version-check <version>` |
| 8 | 版本治理文档（03_版本治理规范） | 确认当前版本号已更新 |

> ⚠️ 常见遗漏：iot-sdk/Directory.Packages.props（生产者自身 CPM）容易漏更新。deploy-fast.sh 和 version-check 只保证消费者 CPM 一致，不保证生产者 CPM 版本。必须手动检查第 2 项。

---

## 未来演进：Trusted Publishing 迁移

### 背景

nuget.org 正在推行 **Trusted Publishing**（基于 GitHub Actions OIDC 的短期令牌机制），替代长期 API Key。详见：[Microsoft Learn - Trusted Publishing](https://learn.microsoft.com/zh-cn/nuget/nuget-org/trusted-publishing)

当前状态（2026-06）：
- ✅ API Key 仍然可用，**无强制停用时间表**
- ✅ Trusted Publishing 已上线，当前仅支持 **GitHub Actions**
- ⚠️ 官方推荐迁移，强调"不再需要管理长期 API 密钥"

### 项目现状

本流水线涉及的 Git 仓库结构（均为本地 git，未上 GitHub）：

| Git 仓库 | 产出 NuGet 包数 | 候选 GitHub 仓库名 |
|----------|---------------|-------------------|
| `ZL.PlcBase` | 4 个 | `ZL.PlcBase` |
| `iot-sdk` | 23 个 | `iot-sdk` |
| `ZL.PlcSimulator` | 2 个 | `ZL.PlcSimulator` |
| `tmom` | 若干 | `tmom` |

**关键理解**：Trusted Publishing 策略绑定的是 **GitHub 仓库 + workflow 文件**，不是单个 NuGet 包。一个仓库产出 N 个包，只需 **一条策略** 即可覆盖全部。

### push.py 需要适配的改动

当前代码（基于 API Key）：

```python
api_key = os.environ.get("NUGET_API_KEY")
cmd = ["dotnet", "nuget", "push", str(nupkg_path),
       "-k", api_key, "-s", ctx.config.nuget_source, "--skip-duplicate"]
```

迁移后（基于 Trusted Publishing）：

```python
# 方案 A：优先使用 NUGET_TEMP_API_KEY（由 NuGet/login@v1 action 注入）
# 回退到传统的 NUGET_API_KEY（本地开发/手动测试）
api_key = os.environ.get("NUGET_TEMP_API_KEY") or os.environ.get("NUGET_API_KEY")
if not api_key:
    ...  # 仅本地缓存
cmd = ["dotnet", "nuget", "push", str(nupkg_path),
       "-k", api_key, "-s", ctx.config.nuget_source, "--skip-duplicate"]
```

### 迁移路线图

```
第 1 步：将 4 个本地 git 仓库推上 GitHub（私有仓库）
  - 每个仓库建一个私有 GitHub 仓库
  - 不影响本地开发流程（git remote add origin + git push）

第 2 步：每条 repo 的 pipeline 配置添加 publish.yml 工作流
  - 使用 NuGet/login@v1 获取临时 API Key
  - 调用 zl-pipeline publish 时传入 NUGET_TEMP_API_KEY

第 3 步：在 nuget.org 创建 Trusted Publishing 策略
  - 每个 GitHub 仓库 + workflow 文件配一条策略
  - 不需要每个包单独配

第 4 步：旧 API Key 保留为本地回退
  - push.py 修改为"先读 NUGET_TEMP_API_KEY，再回退 NUGET_API_KEY"
  - 本地手动测试仍可用旧 key
```

### `test-nuget-push.sh` — 独立验证脚本

当需要**隔离测试**远程推送是否正常（排除流水线逻辑干扰）时，使用 `tools/test-nuget-push.sh`：

```bash
# 验证 API Key 是否有效
export NUGET_API_KEY=oy2...
bash tools/test-nuget-push.sh ZL.PFLite
# → 403 = key 失效，成功 = key 有效

# 脚本逻辑：
# 1. mktemp 创建工作目录
# 2. 创建极简 csproj（netstandard2.0, version 0.0.1-test）
# 3. dotnet pack → dotnet nuget push --skip-duplicate
# 4. exit 自动清理临时目录
```
