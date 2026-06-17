"""StepRunner — Pipeline 步骤执行引擎。

编排步骤执行、状态管理、错误处理。是整个系统的核心。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from zl_pipeline.context import PipelineContext
from zl_pipeline.result import StepResult
from zl_pipeline.state import StateStore

# 步骤函数签名
StepFn = Callable[[PipelineContext, dict[str, Any]], StepResult]

# 步骤注册表：(步骤名, 步骤函数)
STEP_REGISTRY: list[tuple[str, StepFn]] = []


def register_step(name: str) -> Callable[[StepFn], StepFn]:
    """装饰器：注册步骤到 STEP_REGISTRY"""
    def decorator(fn: StepFn) -> StepFn:
        STEP_REGISTRY.append((name, fn))
        return fn
    return decorator


@dataclass
class ExecutionPlan:
    """执行计划（plan 命令使用）"""
    project: str
    step: str
    command_preview: str  # 简要描述将执行什么


class StepRunner:
    """步骤执行引擎。

    用法:
        runner = StepRunner(context)
        results = runner.run_all()
    """

    def __init__(self, context: PipelineContext) -> None:
        self.ctx = context
        self.state = StateStore(context.version, context.proj_dir)
        self.results: list[StepResult] = []
        self._log_file_dir = context.artifacts_dir / "logs" / context.version
        self._log_file_dir.mkdir(parents=True, exist_ok=True)

    def _build_log_file(self, project: str, step: str) -> Path:
        """构建日志文件路径"""
        return self._log_file_dir / f"{step}-{project}.log"

    def _log(self, msg: str, project: str | None = None) -> None:
        """打印日志（带步骤标记）"""
        prefix = f"[{project}] " if project else ""
        print(f"  {prefix}{msg}")

    def plan(self) -> list[ExecutionPlan]:
        """生成执行计划（不实际执行）"""
        plan: list[ExecutionPlan] = []
        for project_cfg in self._iter_projects():
            for step_name, _ in STEP_REGISTRY:
                plan.append(ExecutionPlan(
                    project=project_cfg["name"],
                    step=step_name,
                    command_preview=f"[plan] {step_name}",
                ))
        return plan

    def run_all(self) -> list[StepResult]:
        """编排所有项目的执行。

        Returns:
            所有步骤的执行结果。
        """
        all_results: list[StepResult] = []

        for project_cfg in self._iter_projects():
            all_results.extend(self._run_project(project_cfg))

        return all_results

    def _iter_projects(self) -> list[dict[str, Any]]:
        """迭代项目列表，应用 only_projects 过滤"""
        projects = []
        for p in self.ctx.config.projects:
            if self.ctx.only_projects and p.name not in self.ctx.only_projects:
                continue
            projects.append({
                "name": p.name,
                "csproj": p.csproj,
                "obfuscate": p.obfuscate,
            })
        return projects

    def _run_project(self, project_cfg: dict[str, Any]) -> list[StepResult]:
        """运行单个项目的所有步骤"""
        project_name = project_cfg["name"]
        results: list[StepResult] = []

        # 获取可跳过的步骤
        skippable = self.state.get_skippable(project_name, self.ctx.from_step)

        for step_name, step_fn in STEP_REGISTRY:
            # 跳过已完成/已完成的步骤
            if project_name in skippable:
                self._log(f"[SKIP] {step_name} (已完成)", project_name)
                results.append(StepResult.skipped(step_name, project_name, "state:passed"))
                continue

            # 跳过编译
            if self.ctx.skip_build and step_name == "build":
                self._log(f"[SKIP] build (--skip-build)", project_name)
                results.append(StepResult.skipped(step_name, project_name, "--skip-build"))
                continue

            # 执行步骤
            result = self._execute_step(step_fn, project_cfg, step_name)
            results.append(result)

            # 非 resume 模式且失败，停止后续步骤
            if not result.ok and not self.ctx.resume:
                self._log(f"[ABORT] 步骤 {step_name} 失败，停止后续步骤", project_name)
                break

        return results

    def _execute_step(
        self,
        step_fn: StepFn,
        project_cfg: dict[str, Any],
        step_name: str,
    ) -> StepResult:
        """执行单个步骤"""
        project_name = project_cfg["name"]
        log_file = self._build_log_file(project_name, step_name)

        # 检查 resume 状态
        existing = self.state.get(project_name, step_name)
        if self.ctx.resume and existing and existing.status == "passed":
            self._log(f"[RESUME] {step_name} (从状态文件恢复)", project_name)
            return StepResult(
                step=step_name,
                project=project_name,
                ok=True,
                duration=existing.duration_sec or 0.0,
                command=existing.command or [],
                exit_code=existing.exit_code,
                error_detail=f"resume: {existing.status}",
                log_file=log_file,
            )

        # 标记 running
        self.state.mark_running(project_name, step_name, ["step:" + step_name])

        # 执行
        start = time.monotonic()
        try:
            result = step_fn(self.ctx, project_cfg)
            result = StepResult(
                step=result.step,
                project=result.project,
                ok=result.ok,
                duration=time.monotonic() - start,
                command=result.command,
                exit_code=result.exit_code,
                stdout_tail=result.stdout_tail,
                stderr_tail=result.stderr_tail,
                log_file=log_file,
                error_detail=result.error_detail,
            )

            if result.ok:
                self.state.mark_passed(project_name, step_name, result)
                self._log(f"[PASS] {step_name} ({result.duration:.1f}s)", project_name)
            else:
                self.state.mark_failed(project_name, step_name, result)
                self._log(f"[FAIL] {step_name}: {result.error_detail}", project_name)

            return result

        except Exception as e:
            result = StepResult(
                step=step_name,
                project=project_name,
                ok=False,
                duration=time.monotonic() - start,
                command=[],
                exit_code=1,
                stderr_tail=str(e),
                log_file=log_file,
                error_detail=str(e),
            )
            self.state.mark_failed(project_name, step_name, result)
            self._log(f"[ERROR] {step_name}: {e}", project_name)
            return result
