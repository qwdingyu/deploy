"""DotnetAdapter — dotnet CLI 封装。

所有 dotnet 命令的统一入口，步骤函数通过此适配器调用 dotnet，
核心逻辑不直接依赖 subprocess。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandResult:
    """命令执行结果"""
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def _run(
    cmd: list[str],
    cwd: Path | None = None,
    timeout: int = 300,
    dry_run: bool = False,
) -> CommandResult:
    """执行命令并返回结果。

    流式输出 stdout/stderr，防止长时间无输出被 kill。
    """
    if dry_run:
        return CommandResult(returncode=0, stdout="", stderr="", timed_out=False)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=cwd,
        )
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        import sys
        for line in iter(proc.stdout.readline, ""):
            if line:
                stdout_lines.append(line)
                print(line, end="", flush=True)

        for line in iter(proc.stderr.readline, ""):
            if line:
                stderr_lines.append(line)
                print(line, end="", flush=True, file=sys.stderr)

        proc.wait(timeout=timeout)
        return CommandResult(
            returncode=proc.returncode,
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        return CommandResult(returncode=-1, stdout="", stderr=f"TIMEOUT: exceeded {timeout}s", timed_out=True)


class DotnetAdapter:
    """dotnet CLI 适配器"""

    def __init__(self, proj_dir: Path) -> None:
        self.proj_dir = proj_dir

    def build(
        self,
        framework: str | None = None,
        no_restore: bool = False,
        configuration: str = "Release",
        timeout: int = 300,
        dry_run: bool = False,
    ) -> CommandResult:
        """执行 dotnet build"""
        cmd = ["dotnet", "build", str(self.proj_dir), "-c", configuration]
        if framework:
            cmd.extend(["-f", framework])
        if no_restore:
            cmd.append("--no-restore")
        cmd.extend(["--nologo", "-v", "q"])
        return _run(cmd, cwd=self.proj_dir, timeout=timeout, dry_run=dry_run)

    def pack(
        self,
        no_build: bool = False,
        configuration: str = "Release",
        package_version: str | None = None,
        output_dir: Path | None = None,
        treat_warnings_as_errors: bool = False,
        timeout: int = 600,
        dry_run: bool = False,
    ) -> CommandResult:
        """执行 dotnet pack"""
        cmd = ["dotnet", "pack", str(self.proj_dir), "-c", configuration, "--nologo", "-v", "q"]
        if no_build:
            cmd.append("--no-build")
        if package_version:
            cmd.append(f"-p:PackageVersion={package_version}")
        if output_dir:
            cmd.extend(["-o", str(output_dir)])
        if not treat_warnings_as_errors:
            cmd.append("-p:TreatWarningsAsErrors=false")
        return _run(cmd, cwd=self.proj_dir, timeout=timeout, dry_run=dry_run)

    def publish(
        self,
        output: Path,
        framework: str | None = None,
        configuration: str = "Release",
        timeout: int = 300,
        dry_run: bool = False,
    ) -> CommandResult:
        """执行 dotnet publish"""
        cmd = ["dotnet", "publish", str(self.proj_dir), "-c", configuration,
               "-o", str(output), "--nologo", "-v", "q"]
        if framework:
            cmd.append(f"-p:TargetFramework={framework}")
        return _run(cmd, cwd=self.proj_dir, timeout=timeout, dry_run=dry_run)

    def restore(
        self,
        timeout: int = 120,
        dry_run: bool = False,
    ) -> CommandResult:
        """执行 dotnet restore"""
        cmd = ["dotnet", "restore", str(self.proj_dir), "--nologo"]
        return _run(cmd, cwd=self.proj_dir, timeout=timeout, dry_run=dry_run)
