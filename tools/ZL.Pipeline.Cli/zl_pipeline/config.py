"""Pipeline 配置解析与验证。

从 pipeline.json 读取配置，合并默认值，并通过 JSON Schema 验证结构。
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema  # pip install jsonschema


# ---------------------------------------------------------------------------
# 默认值
# ---------------------------------------------------------------------------
_DEFAULT_CONFIG: dict[str, Any] = {
    "$schema": "https://raw.githubusercontent.com/qwdingyu/ZL.Pipeline/main/schemas/pipeline-schema.json",
    "version": "1.0",
    "projects": [],
    "obfuscarConfig": "obfuscar.xml",
    "nugetSource": "https://api.nuget.org/v3/index.json",
    "publishTimeout": 120,
    "dryRun": False,
}


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ProjectConfig:
    """单个项目的配置"""
    name: str
    csproj: str
    obfuscate: bool = True
    obfuscar_config: str | None = None
    include_dependencies: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConsumerConfig:
    """下游消费者的配置"""
    name: str
    path: str
    cpm_file: str | None = None
    build_target: str | None = None
    auto_commit: bool = False
    auto_discover: bool = False
    discover_depth: int = 5


@dataclass(frozen=True)
class PipelineConfig:
    """完整的 pipeline.json 配置（不可变）"""
    version: str
    projects: list[ProjectConfig]
    obfuscar_config: str = "obfuscar.xml"
    nuget_source: str = "https://api.nuget.org/v3/index.json"
    publish_timeout: int = 120
    dry_run: bool = False
    consumers: list[ConsumerConfig] = field(default_factory=list)

    @property
    def obfuscate_projects(self) -> list[ProjectConfig]:
        """返回需要混淆的项目"""
        return [p for p in self.projects if p.obfuscate]


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _detect_csproj(root: Path) -> list[dict[str, str]]:
    """在 root 目录下探测所有库 csproj 文件"""
    csproj_files = sorted(root.rglob("*.csproj"))
    excluded_keywords = {"test", "perf", "e2e", "bench", "benchmark", "demo", "sample"}
    projects = []
    for csproj in csproj_files:
        name = csproj.stem
        if any(kw in name.lower() for kw in excluded_keywords):
            continue
        try:
            content = csproj.read_text(encoding="utf-8")
            if "<OutputType>Exe</OutputType>" in content or "<OutputType>WinExe</OutputType>" in content:
                continue
        except Exception:
            continue
        projects.append({
            "name": name,
            "csproj": str(csproj.relative_to(root)),
            "obfuscate": True,
            "includeDependencies": [],
        })
    return projects


def _parse_external_deps(csproj_path: Path) -> set[str]:
    """从 csproj 中解析 ExternalPackageReferences 列表"""
    try:
        content = csproj_path.read_text(encoding="utf-8")
    except Exception:
        return set()
    deps: list[str] = []
    for m in re.finditer(r"<ExternalPackageReference\s+Include=\"([^\"]+)\"", content):
        deps.append(m.group(1))
    return set(deps)


def _load_schema(schema_path: Path) -> dict[str, Any]:
    """加载 JSON Schema"""
    try:
        return json.loads(schema_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------
def load_config(config_path: str | None = None, root: Path | None = None) -> PipelineConfig:
    """加载并验证 pipeline.json，返回 PipelineConfig。

    Args:
        config_path: 配置文件路径。None 则从 cwd 或 root 下查找 pipeline.json。
        root: 项目根目录。用于 init 时探测 csproj。

    Returns:
        验证后的 PipelineConfig 实例。
    """
    if config_path:
        path = Path(config_path)
    else:
        base = root or Path.cwd()
        path = base / "pipeline.json"

    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}\n运行 'zl-pipeline init' 生成")

    with open(path) as f:
        raw = json.load(f)

    # 合并默认值
    for k, v in _DEFAULT_CONFIG.items():
        raw.setdefault(k, v)

    # Schema 验证
    schema_path = Path(__file__).parents[1] / "schemas" / "pipeline-schema.json"
    schema = _load_schema(schema_path)
    if schema:
        jsonschema.validate(instance=raw, schema=schema)

    # 转换为数据类
    projects = []
    for p in raw.get("projects", []):
        projects.append(ProjectConfig(
            name=p["name"],
            csproj=p["csproj"],
            obfuscate=p.get("obfuscate", True),
            obfuscar_config=p.get("obfuscarConfig"),
            include_dependencies=p.get("includeDependencies", []),
        ))

    consumers = []
    for c in raw.get("consumers", []):
        consumers.append(ConsumerConfig(
            name=c["name"],
            path=c["path"],
            cpm_file=c.get("cpmFile"),
            build_target=c.get("buildTarget"),
            auto_commit=c.get("autoCommit", False),
            auto_discover=c.get("autoDiscover", False),
            discover_depth=c.get("discoverDepth", 5),
        ))

    return PipelineConfig(
        version=raw.get("version", "1.0"),
        projects=projects,
        obfuscar_config=raw.get("obfuscarConfig", "obfuscar.xml"),
        nuget_source=raw.get("nugetSource", "https://api.nuget.org/v3/index.json"),
        publish_timeout=raw.get("publishTimeout", 120),
        dry_run=raw.get("dryRun", False),
        consumers=consumers,
    )


def init_config(root: Path) -> Path:
    """在 root 下生成 pipeline.json，返回文件路径。"""
    config_path = root / "pipeline.json"
    if config_path.exists():
        raise FileExistsError(f"{config_path} 已存在")

    projects = _detect_csproj(root)
    config = {
        "$schema": _DEFAULT_CONFIG["$schema"],
        "version": "1.0",
        "projects": projects,
        "obfuscarConfig": "obfuscar.xml",
        "nugetSource": "https://api.nuget.org/v3/index.json",
        "publishTimeout": 120,
        "dryRun": False,
    }

    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    return config_path


def get_package_id(proj_dir: Path, csproj_rel: str) -> str:
    """从 csproj 获取 PackageId，如果没有则返回 csproj_rel 的 stem"""
    csproj_path = proj_dir / csproj_rel
    if csproj_path.exists():
        content = csproj_path.read_text(encoding="utf-8")
        m = re.search(r"<PackageId[^>]*>(.*?)</PackageId>", content)
        if m:
            return m.group(1).strip()
    return Path(csproj_rel).stem


def detect_tfm(csproj_path: Path) -> str:
    """从 csproj 检测 TargetFramework，默认返回 net8.0"""
    try:
        content = csproj_path.read_text(encoding="utf-8")
        # 优先项目自身的 TargetFrameworks（排除 Directory.Build.props 继承的）
        m = re.search(r"<TargetFrameworks>([^<]+)</TargetFrameworks>", content)
        if m:
            frameworks = [f.strip() for f in m.group(1).split(";")]
            return "net8.0" if "net8.0" in frameworks else frameworks[0]
        m = re.search(r"<TargetFramework>([^<]+)</TargetFramework>", content)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return "net8.0"


def check_obfuscar_available() -> bool:
    """检查 obfuscar.console 是否可用"""
    result = subprocess.run(
        ["which", "obfuscar.console"],
        capture_output=True, text=True, timeout=15,
    )
    return result.returncode == 0


def check_dotnet_available() -> str | None:
    """检查 dotnet 是否可用，返回版本号字符串或 None"""
    result = subprocess.run(
        ["dotnet", "--version"],
        capture_output=True, text=True, timeout=15,
    )
    return result.stdout.strip() if result.returncode == 0 else None


# ---------------------------------------------------------------------------
# Consumer 辅助函数（用于 sync-consumers / align-versions）
# ---------------------------------------------------------------------------

def _find_cpm_file(consumer_root: Path) -> Path | None:
    """在消费项目根目录及上级目录中查找 Directory.Packages.props"""
    for p in [consumer_root, consumer_root.parent]:
        candidate = p / "Directory.Packages.props"
        if candidate.exists():
            return candidate
    return None


def _update_cpm_version(cpm_path: Path, package_id: str, new_version: str) -> bool:
    """更新 Directory.Packages.props 中指定包的版本号"""
    content = cpm_path.read_text(encoding="utf-8")
    pattern = rf'(PackageVersion Include="{re.escape(package_id)}"\s+Version=")([^"]+)(")'
    match = re.search(pattern, content)
    if not match:
        return False
    old_version = match.group(2)
    if old_version == new_version:
        return True
    new_content = re.sub(pattern, rf'\g<1>{new_version}\3', content)
    cpm_path.write_text(new_content, encoding="utf-8")
    return True


def _discover_cpm_files(root: Path, depth: int = 5) -> list[Path]:
    """递归扫描指定目录，自动发现所有 Directory.Packages.props 文件"""
    found: list[Path] = []
    seen: set[Path] = set()
    for d in root.rglob("*"):
        if d.is_dir():
            rel = d.relative_to(root)
            if rel.parts and len(rel.parts) > depth:
                continue
        cpm = d / "Directory.Packages.props" if d.is_dir() else d
        if str(d).endswith("Directory.Packages.props") and d.exists() and d.is_file():
            real = d.resolve()
            if real not in seen:
                seen.add(real)
                found.append(d)
    return sorted(found)


def _expand_consumer_paths(consumer_cfg: dict, base_path: str) -> list[dict]:
    """展开 consumer 配置，支持 glob 通配符和 auto-discover 模式"""
    results: list[dict] = []
    path = consumer_cfg["path"]

    if consumer_cfg.get("autoDiscover"):
        root = Path(base_path) / path if not Path(path).is_absolute() else Path(path)
        if not root.exists():
            return results
        depth = consumer_cfg.get("discoverDepth", 5)
        cpm_files = _discover_cpm_files(root, depth)
        for cpm in cpm_files:
            rel = cpm.relative_to(root) if str(cpm).startswith(str(root)) else cpm
            results.append({
                "name": str(rel.parent) if str(rel.parent) != "." else root.name,
                "path": str(cpm.parent),
                "cpmFile": str(cpm.name),
                "buildTarget": consumer_cfg.get("buildTarget"),
                "autoCommit": consumer_cfg.get("autoCommit", False),
            })
        return results

    import glob as glob_mod
    matches = sorted(glob_mod.glob(path))
    if matches:
        for m in matches:
            results.append({
                "name": Path(m).name,
                "path": m,
                "cpmFile": consumer_cfg.get("cpmFile"),
                "buildTarget": consumer_cfg.get("buildTarget"),
                "autoCommit": consumer_cfg.get("autoCommit", False),
            })
        return results

    return [consumer_cfg]
