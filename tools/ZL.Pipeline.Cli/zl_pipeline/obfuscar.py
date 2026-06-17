"""ObfuscarAdapter — Obfuscar 封装。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zl_pipeline.dotnet import _run


@dataclass(frozen=True)
class ObfuscationResult:
    """混淆执行结果"""
    ok: bool
    stdout: str
    stderr: str
    mapping_file: Path | None = None


class ObfuscarAdapter:
    """Obfuscar 适配器"""

    def run(
        self,
        input_dll: Path,
        output_dir: Path,
        config_path: Path | None = None,
        timeout: int = 300,
        dry_run: bool = False,
    ) -> ObfuscationResult:
        """执行混淆。

        Args:
            input_dll:   待混淆的 DLL 路径
            output_dir:  混淆输出目录
            config_path: 自定义 obfuscar XML 配置路径
            timeout:     超时秒数
            dry_run:     仅展示，不执行

        Returns:
            ObfuscationResult
        """
        if not config_path:
            # 动态生成临时 XML
            import tempfile
            xml_content = self._generate_default_xml(input_dll, output_dir)
            tmp = Path(tempfile.mktemp(suffix=".xml"))
            tmp.write_text(xml_content, encoding="utf-8")
            config_path = tmp
            cleanup_tmp = True
        else:
            cleanup_tmp = False

        try:
            cmd = ["obfuscar.console", str(config_path)]
            result = _run(cmd, cwd=str(input_dll.parent), timeout=timeout, dry_run=dry_run)
            ok = result.returncode == 0

            mapping_file = output_dir / "Mapping.txt" if ok else None

            return ObfuscationResult(
                ok=ok,
                stdout=result.stdout,
                stderr=result.stderr,
                mapping_file=mapping_file,
            )
        finally:
            if cleanup_tmp and config_path.exists():
                config_path.unlink(missing_ok=True)

    def _generate_default_xml(self, input_dll: Path, output_dir: Path) -> str:
        return f"""<?xml version='1.0' encoding='utf-8'?>
<Obfuscator>
  <Var name='InPath' value='{input_dll.parent}' />
  <Var name='OutPath' value='{output_dir}' />
  <Var name='KeepPublicApi' value='true' />
  <Var name='HidePrivateApi' value='true' />
  <Var name='UseUnicodeNames' value='true' />
  <Module file='$(InPath)/{input_dll.name}' />
</Obfuscator>"""
