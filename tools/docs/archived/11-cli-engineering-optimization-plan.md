# CLI 工程化优化实施方案

## 目标
将当前经验型发布脚本改造为可维护、可局部重跑、可快速排错的工程化 CLI。
不追求一次性重写，先建立稳定行为契约与可观测性。

---

## 第一阶段：稳定行为契约（必须）

### 1. 命令语义重构
```bash
zl-pipeline plan <version>
zl-pipeline verify <version>
zl-pipeline publish <version>
zl-pipeline local-pack [version]
zl-pipeline sync-consumers <version>
zl-pipeline clean
```

#### 建议定义
| 命令 | 作用 | 是否真实执行 | 是否推送 |
|---|---|---|---|
| `plan` | 只展示将执行的 step/project/命令 | 否 | 否 |
| `verify` | 真实 build/pack/obfuscate/compare | 是 | 否 |
| `publish` | 先 verify，再 push | 是 | 是 |
| `--dry-run` | 只展示，不做真实副作用 | 否 | 否 |

### 2. 必须支持的排错选项
```bash
zl-pipeline verify 2.3.1 --only ZL.IotHub
zl-pipeline verify 2.3.1 --from-step obfuscate
zl-pipeline verify 2.3.1 --skip-build
zl-pipeline verify 2.3.1 --resume
```

### 3. 固定步骤名
建议统一：
```text
build
pack
fix-nuspec
publish-deps
obfuscate
replace-nupkg
api-compare
push
```

---

## 第二阶段：最小工程化改造

### 1. 引入 step runner
当前问题：
- `cmd_publish` 把所有 step 线性堆在一起
- 没有统一错误封装
- 没有 log 落盘

建议先不拆多文件，先在单文件内抽取 runner：

```python
STEPS = [
    ("build", step_build),
    ("pack", step_pack),
    ("fix-nuspec", step_fix_nuspec),
    ("publish-deps", step_publish_deps),
    ("obfuscate", step_obfuscate),
    ("replace-nupkg", step_replace_nupkg),
    ("api-compare", step_api_compare),
    ("push", step_push),
]
```

每个 step 函数统一签名：

```python
def step_build(ctx: PipelineContext, project: dict) -> StepResult
```

### 2. 引入上下文对象
```python
@dataclass
class PipelineContext:
    version: str
    config: dict
    proj_dir: Path
    artifacts_dir: Path
    obfuscated_dir: Path
    only_projects: set[str] | None
    from_step: str | None
    skip_build: bool
    resume: bool
    dry_run: bool
```

### 3. 引入 StepResult
```python
@dataclass
class StepResult:
    step: str
    project: str
    ok: bool
    duration: float
    command: list[str]
    exit_code: int | None
    stdout_tail: str
    stderr_tail: str
    log_file: Path | None
    resume_hint: str | None
```

---

## 第三阶段：日志与状态落盘

### 1. 目录结构
```text
artifacts/
  logs/<version>/<step>-<project>.log
  .pipeline-state/<version>/<project>/<step>.json
```

### 2. state 文件内容
```json
{
  "step": "pack",
  "project": "ZL.IotHub",
  "status": "passed",
  "exitCode": 0,
  "startedAt": "...",
  "finishedAt": "...",
  "durationSec": 43.2,
  "command": ["dotnet", "pack", "..."],
  "log": "artifacts/logs/2.3.1/pack-ZL.IotHub.log"
}
```

### 3. resume 逻辑
```text
if resume and state.status == passed:
    skip
```

---

## 第四阶段：修复关键语义

### 1. `api-compare` 必须真实失败
当前代码问题：
```python
return 0
```

建议改成：
- 无差异：exit 0
- 有差异：exit 2
- 脚本异常：exit 1

并在 CLI 中显式映射：
```python
if result.returncode == 2:
    mark_api_compare_failed(...)
```

### 2. `verify` 不应是 dry-run 别名
当前：
```python
def cmd_verify(args):
    args.dry_run = True
    cmd_publish(args)
```

必须改成独立真实执行流程。

### 3. 消除 ZL.PlcBase 硬编码
当前：
```python
plcbase_dir = Path(proj_dir).parent / "ZL.PlcBase"
```

改成配置：
```json
{
  "upstreamPackages": [
    {
      "from": "../ZL.PlcBase/artifacts",
      "glob": "*.nupkg"
    }
  ]
}
```

---

## 第五阶段：结构拆分

等行为稳定后再拆。

### 推荐结构
```text
ZL.Pipeline.Cli/
  zl_pipeline/
    __main__.py
    main.py
    context.py
    config.py
    runner.py
    report.py
    dotnet.py
    nuget.py
    steps/
      build.py
      pack.py
      fix_nuspec.py
      publish_deps.py
      obfuscate.py
      replace_nupkg.py
      api_compare.py
      push.py
  scripts/
    replace-nupkg-dll.py
    api-compare-tool/
```

---

## 第六阶段：性能优化

### 1. 减少重复编译
```bash
dotnet build
dotnet pack --no-build
dotnet publish --no-build
```

### 2. API compare 工具缓存
不要每次临时 build：
```text
~/.cache/zl-pipeline/api-compare/<hash>/ApiCompare
```

### 3. 按项目并行
当项目独立时：
- pack
- obfuscate
- replace
- api-compare
可并行。

---

## 建议实施顺序

### Sprint 1（最重要）
1. 新增 `plan/verify/publish` 语义
2. 增加 `--only/--from-step/--resume/--skip-build`
3. `api-compare` 退出码修正
4. 失败日志落盘到 `artifacts/logs/<version>/`

### Sprint 2
1. step runner + StepResult
2. pipeline state 文件
3. verify 真实化
4. upstreamPackages 配置化

### Sprint 3
1. `--no-build` 优化
2. API compare 工具缓存
3. shell 脚本降级为 wrapper
4. pytest 覆盖核心逻辑

---

## 验收标准

### 可快速排错
```bash
zl-pipeline verify 2.3.1 --only ZL.IotHub --from-step obfuscate
```
应能：
- 只跑指定项目
- 只跑指定步骤
- 输出对应日志路径
- 输出 resume 命令

### 可验证语义正确
```bash
zl-pipeline verify 2.3.1
```
必须真实构建并检查产物，不能靠 dry-run 跳过。

### 可工程化维护
新增功能时：
- 只改对应 step
- 不影响其他 step
- 有单测覆盖

---

## 最终建议
不要先做“全面重写”。
正确顺序是：
1. 先稳定命令与失败语义
2. 再加 resume/log/state
3. 最后才做拆包与并行优化
