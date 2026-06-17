"""单元测试: config 模块"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from zl_pipeline.config import (
    PipelineConfig,
    ProjectConfig,
    ConsumerConfig,
    _detect_csproj,
    _parse_external_deps,
    detect_tfm,
    get_package_id,
    init_config,
    load_config,
)


def _write_csproj(tmp: Path, name: str, content: str) -> Path:
    """写入一个 csproj 文件"""
    p = tmp / f"{name}.csproj"
    p.write_text(content, encoding="utf-8")
    return p


class TestDetectCsproj:
    def test_detect_library_csproj(self, tmp_path: Path) -> None:
        _write_csproj(tmp_path, "MyLib", '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework><OutputType>Library</OutputType></PropertyGroup></Project>')
        result = _detect_csproj(tmp_path)
        assert len(result) == 1
        assert result[0]["name"] == "MyLib"

    def test_exclude_test_project(self, tmp_path: Path) -> None:
        _write_csproj(tmp_path, "MyLib.Tests", '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework><OutputType>Library</OutputType></PropertyGroup></Project>')
        result = _detect_csproj(tmp_path)
        assert len(result) == 0

    def test_exclude_console_app(self, tmp_path: Path) -> None:
        _write_csproj(tmp_path, "MyApp", '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup></Project>')
        result = _detect_csproj(tmp_path)
        assert len(result) == 0


class TestGetPackageId:
    def test_from_csproj(self, tmp_path: Path) -> None:
        _write_csproj(tmp_path, "MyLib", '<Project><PackageId>MyCustomId</PackageId></Project>')
        result = get_package_id(tmp_path, "MyLib.csproj")
        assert result == "MyCustomId"

    def test_fallback_to_stem(self, tmp_path: Path) -> None:
        _write_csproj(tmp_path, "MyLib", '<Project></Project>')
        result = get_package_id(tmp_path, "MyLib.csproj")
        assert result == "MyLib"

    def test_nonexistent_csproj(self, tmp_path: Path) -> None:
        result = get_package_id(tmp_path, "nonexistent.csproj")
        assert result == "nonexistent"


class TestDetectTfm:
    def test_single_tf(self, tmp_path: Path) -> None:
        p = _write_csproj(tmp_path, "MyLib", '<Project><TargetFramework>net6.0</TargetFramework></Project>')
        assert detect_tfm(p) == "net6.0"

    def test_multi_tf(self, tmp_path: Path) -> None:
        p = _write_csproj(tmp_path, "MyLib", '<Project><TargetFrameworks>net6.0;net8.0</TargetFrameworks></Project>')
        assert detect_tfm(p) == "net8.0"

    def test_default(self, tmp_path: Path) -> None:
        p = _write_csproj(tmp_path, "MyLib", '<Project></Project>')
        assert detect_tfm(p) == "net8.0"


class TestLoadConfig:
    def test_load_valid_config(self, tmp_path: Path) -> None:
        config = {
            "version": "1.0",
            "projects": [
                {"name": "MyLib", "csproj": "src/MyLib.csproj"},
            ],
        }
        (tmp_path / "pipeline.json").write_text(json.dumps(config), encoding="utf-8")
        result = load_config(config_path=str(tmp_path / "pipeline.json"))
        assert isinstance(result, PipelineConfig)
        assert len(result.projects) == 1
        assert result.projects[0].name == "MyLib"

    def test_missing_config(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_config(config_path=str(tmp_path / "nonexistent.json"))

    def test_init_config(self, tmp_path: Path) -> None:
        p = _write_csproj(tmp_path, "MyLib", '<Project><TargetFramework>net8.0</TargetFramework></Project>')
        result = init_config(tmp_path)
        assert result.exists()
        data = json.loads(result.read_text())
        assert len(data["projects"]) == 1

    def test_init_existing_raises(self, tmp_path: Path) -> None:
        (tmp_path / "pipeline.json").write_text("{}", encoding="utf-8")
        with pytest.raises(FileExistsError):
            init_config(tmp_path)


class TestDataclasses:
    def test_obfuscate_projects_filter(self) -> None:
        config = PipelineConfig(
            version="1.0",
            projects=[
                ProjectConfig(name="A", csproj="a.csproj", obfuscate=True),
                ProjectConfig(name="B", csproj="b.csproj", obfuscate=False),
            ],
        )
        assert len(config.obfuscate_projects) == 1
        assert config.obfuscate_projects[0].name == "A"

    def test_frozen(self) -> None:
        config = PipelineConfig(version="1.0", projects=[])
        with pytest.raises(Exception):
            config.version = "2.0"
