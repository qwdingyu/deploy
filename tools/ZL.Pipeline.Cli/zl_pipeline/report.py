"""报告模块 — 彩色终端输出 + 汇总报告"""

from __future__ import annotations

from pathlib import Path

from zl_pipeline.result import StepResult

_GREEN = "\033[0;32m"
_RED = "\033[0;31m"
_YELLOW = "\033[1;33m"
_CYAN = "\033[0;36m"
_NC = "\033[0m"


def print_report(results: list[StepResult], obfuscated: bool = False) -> None:
    """打印最终报告"""
    total = len(results)
    passed = sum(1 for r in results if r.ok)
    failed = sum(1 for r in results if not r.ok)

    print(f"\n{'=' * 60}")
    print(f"  发布报告")
    print(f"{'=' * 60}")
    print()
    print(f"  总步骤: {total}")
    print(f"  {_GREEN}通过: {passed}{_NC}")
    print(f"  {_RED}失败: {failed}{_NC}")
    print(f"  混淆: {'已启用' if obfuscated else '未启用'}")
    print()

    # 列出失败的步骤
    failures = [r for r in results if not r.ok]
    if failures:
        print(f"  {_RED}失败详情:{_NC}")
        for r in failures:
            reason = r.error_detail or f"exit {r.exit_code}"
            print(f"    - {r.project}/{r.step}: {reason}")
        print()

    if failed == 0:
        print(f"  {_GREEN}✅ 所有步骤通过{_NC}")
    else:
        print(f"  {_RED}❌ 存在失败项，请修复后重试{_NC}")

    print(f"{'=' * 60}\n")


def print_plan(plan: list["ExecutionPlan"]) -> None:
    """打印执行计划"""
    total = len(plan)
    projects = set(e.project for e in plan)
    steps = set(e.step for e in plan)

    print(f"  {_CYAN}计划详情:{_NC}")
    print(f"    项目数: {len(projects)}")
    print(f"    步骤数: {total}")
    print(f"    每项目: {len(steps)} 步")
    print()


def get_obfuscated_projects(results: list[StepResult]) -> bool:
    """判断是否有混淆步骤通过"""
    obfuscate_results = [r for r in results if r.step == "obfuscate"]
    if not obfuscate_results:
        return False
    return any(r.ok for r in obfuscate_results)
