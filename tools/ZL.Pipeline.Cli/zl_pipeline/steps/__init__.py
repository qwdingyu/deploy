"""steps 包初始化 — 导入所有步骤以注册它们"""

from __future__ import annotations

# 按顺序导入所有步骤（确保 STEP_REGISTRY 顺序正确）
import zl_pipeline.steps.build       # noqa: F401
import zl_pipeline.steps.pack        # noqa: F401
import zl_pipeline.steps.fix_nuspec  # noqa: F401
import zl_pipeline.steps.publish_deps  # noqa: F401
import zl_pipeline.steps.obfuscate   # noqa: F401
import zl_pipeline.steps.replace_nupkg  # noqa: F401
import zl_pipeline.steps.api_compare  # noqa: F401
import zl_pipeline.steps.push        # noqa: F401
