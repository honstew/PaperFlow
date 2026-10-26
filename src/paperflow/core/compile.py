from __future__ import annotations

import logging
import os
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(slots=True)
class CompileResult:
    ok: bool
    pdf_path: Path | None
    log_tail: str
    duration_s: float
    command: str = ""


def compile_tex(project_dir: Path, tex_path: Path, *, timeout_s: int = 120) -> CompileResult:
    project_dir = project_dir.resolve()
    tex_path = tex_path.resolve()
    xelatex = shutil.which("xelatex")
    if not xelatex:
        return CompileResult(
            False,
            None,
            "未找到 xelatex。请先完成 XeLaTeX 环境检测或安装 TeX Live。",
            0.0,
        )
    output = tex_path.parent
    build_dir = output / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    # Biber/PAR breaks when TMP/TEMP points into a non-ASCII project path.
    # Keep compiler scratch files in a short ASCII system temp directory.
    temp_parent = _compiler_temp_parent()
    try:
        temp_dir = Path(
            tempfile.mkdtemp(prefix="paperflow-build-", dir=str(temp_parent))
        )
    except OSError as exc:
        return CompileResult(
            False,
            None,
            f"无法创建编译临时目录：{exc}",
            0.0,
        )
    env = os.environ.copy()
    for name in ("TMP", "TEMP", "TMPDIR", "PAR_GLOBAL_TMPDIR"):
        env[name] = str(temp_dir)
    started = time.perf_counter()
    commands: list[str] = []

    def run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        commands.append(" ".join(command))
        console = build_dir / "console.log"
        with console.open("w", encoding="utf-8", errors="replace") as handle:
            return subprocess.run(
                command,
                cwd=str(output),
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=CREATE_NO_WINDOW,
            )

    try:
        first = run(
            [
                xelatex,
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-file-line-error",
                "-output-directory=build",
                tex_path.name,
            ],
            timeout_s,
        )
        if first.returncode != 0:
            return _failed(output, build_dir, started, commands, first)
        bcf = build_dir / "main.bcf"
        if bcf.is_file():
            biber = shutil.which("biber")
            if not biber:
                return CompileResult(
                    False,
                    None,
                    "文档包含参考文献，但没有找到 biber。请完成环境检测或安装 TeX Live。",
                    time.perf_counter() - started,
                    " ".join(commands),
                )
            biber_result = run([biber, "build/main"], timeout_s)
            if biber_result.returncode != 0:
                return _failed(
                    output,
                    build_dir,
                    started,
                    commands,
                    biber_result,
                    extra_log=build_dir / "main.blg",
                )
        second = run(
            [
                xelatex,
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-file-line-error",
                "-output-directory=build",
                tex_path.name,
            ],
            timeout_s,
        )
        if second.returncode != 0:
            return _failed(output, build_dir, started, commands, second)
        third = run(
            [
                xelatex,
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-file-line-error",
                "-output-directory=build",
                tex_path.name,
            ],
            timeout_s,
        )
        if third.returncode != 0:
            return _failed(output, build_dir, started, commands, third)
    except subprocess.TimeoutExpired:
        return CompileResult(
            False,
            None,
            f"编译超时（>{timeout_s}s）。请检查是否有交互式提示或宏包缺失。",
            time.perf_counter() - started,
            " ".join(commands),
        )
    except OSError as exc:
        return CompileResult(False, None, f"无法启动编译进程：{exc}", 0.0, " ".join(commands))
    finally:
        _remove_tree(temp_dir)

    pdf = build_dir / "main.pdf"
    log_tail = _tail(build_dir / "main.log")
    if not pdf.is_file():
        return CompileResult(
            False,
            None,
            log_tail or "编译完成但没有生成 PDF。",
            time.perf_counter() - started,
            " ".join(commands),
        )
    return CompileResult(True, pdf, log_tail, time.perf_counter() - started, " ".join(commands))


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return

    def fix(func, item, exc_info):
        try:
            os.chmod(item, stat.S_IWRITE)
            func(item)
        except OSError:
            logger.debug("Failed to remove compiler temp file: %s", item, exc_info=True)

    shutil.rmtree(path, onexc=fix)


def _compiler_temp_parent() -> Path:
    candidates: list[Path] = []
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        candidates.append(Path(local) / "Temp" / "PaperFlow" / "build")
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        candidates.append(Path(appdata) / "PaperFlow" / "build-tmp")
    paperflow_home = os.environ.get("PAPERFLOW_HOME", "").strip()
    if paperflow_home:
        candidates.append(Path(paperflow_home) / "build-tmp")
    system_root = os.environ.get("SYSTEMROOT", "C:\\Windows")
    candidates.append(Path(system_root) / "Temp" / "PaperFlow" / "build")
    candidates.append(Path.cwd() / ".paperflow-build-tmp")
    for target in candidates:
        if any(ord(char) > 127 for char in str(target)):
            continue
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".write-test"
            probe.write_text("ok", encoding="ascii")
            probe.unlink()
            return target
        except OSError:
            continue
    fallback = Path(tempfile.gettempdir())
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _failed(
    output: Path,
    build_dir: Path,
    started: float,
    commands: list[str],
    completed: subprocess.CompletedProcess[str],
    *,
    extra_log: Path | None = None,
) -> CompileResult:
    tail = _tail(build_dir / "main.log")
    if extra_log is not None:
        extra = _tail(extra_log)
        if extra:
            tail = (tail + "\n\n" + extra)[-6000:]
    console = _tail(build_dir / "console.log")
    if console:
        tail = (tail + "\n\n--- console ---\n" + console)[-6000:]
    if not tail:
        tail = "编译失败，但没有可读日志。"
    return CompileResult(
        False,
        None,
        tail or "编译失败，但没有可读日志。",
        time.perf_counter() - started,
        " ".join(commands),
    )


def _tail(path: Path, limit: int = 6000) -> str:
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:]