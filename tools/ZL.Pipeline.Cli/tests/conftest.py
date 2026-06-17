"""pytest 配置 — 确保步骤注册表在测试前被填充"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def _register_steps() -> None:
    """在所有测试运行前注册步骤"""
    import zl_pipeline.steps  # noqa: F401
