from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

REQUIRED_PACKAGES: tuple[tuple[str, str], ...] = (
    ("ctex.sty", "ctex"),
    ("fontspec.sty", "fontspec"),
    ("xeCJK.sty", "xeCJK"),
    ("geometry.sty", "geometry"),
    ("fancyhdr.sty", "fancyhdr"),
    ("booktabs.sty", "booktabs"),
    ("tabularx.sty", "tabularx"),
    ("longtable.sty", "longtable"),
    ("caption.sty", "caption"),
    ("float.sty", "float"),
    ("enumitem.sty", "enumitem"),
    ("hyperref.sty", "hyperref"),
    ("xcolor.sty", "xcolor"),
    ("amsmath.sty", "amsmath"),
    ("amssymb.sty", "amssymb"),
    ("graphicx.sty", "graphicx"),
    ("array.sty", "array"),
    ("multirow.sty", "multirow"),
    ("algorithm.sty", "algorithm"),
    ("algorithmic.sty", "algorithmic"),
    ("biblatex.sty", "biblatex"),
    ("gb7714-2015.bbx", "biblatex-gb7714-2015"),
)

REQUIRED_FONT_FILES: tuple[tuple[str, str], ...] = (
    ("simsun.ttc", "宋体 SimSun"),
    ("simhei.ttf", "黑体 SimHei"),
    ("simfang.ttf", "仿宋 FangSong"),
    ("simkai.ttf", "楷体 KaiTi"),
    ("times.ttf", "Times New Roman"),
)


class EnvStatus(StrEnum):
    OK = "ok"
    WARN = "warn"
    MISSING = "missing"
    SKIPPED = "skipped"


@dataclass(slots=True)
class EnvItem:
    id: str
    label: str
    status: EnvStatus
    detail: str
    version: str = ""
    path: str = ""
    fix_hint: str = ""


@dataclass(slots=True)
class EnvReport:
    items: list[EnvItem] = field(default_factory=list)
    xelatex_path: str = ""
    tex_bin_dir: str = ""
    checked_at: str = ""

    def get(self, item_id: str) -> EnvItem | None:
        return next((item for item in self.items if item.id == item_id), None)

    @property
    def missing(self) -> list[EnvItem]:
        return [item for item in self.items if item.status is EnvStatus.MISSING]

    @property
    def warnings(self) -> list[EnvItem]:
        return [item for item in self.items if item.status is EnvStatus.WARN]

    @property
    def can_compile(self) -> bool:
        required = ("xelatex", "packages", "fonts", "compile")
        return all(
            (item := self.get(item_id)) is not None and item.status is EnvStatus.OK
            for item_id in required
        )

    @property
    def references_ready(self) -> bool:
        biber = self.get("biber")
        packages = self.get("packages")
        return bool(
            biber
            and biber.status is EnvStatus.OK
            and packages
            and packages.status is EnvStatus.OK
        )

    @property
    def summary(self) -> str:
        ok = sum(1 for item in self.items if item.status is EnvStatus.OK)
        warn = len(self.warnings)
        missing = len(self.missing)
        return f"{ok} 项通过 · {warn} 项警告 · {missing} 项缺失"


@dataclass(slots=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


class EnvDetector:
    """Detect the actual XeLaTeX toolchain on Windows.

    Detection is deliberately non-invasive: it never installs software, never
    elevates, and only writes a temporary probe document under %TEMP%.
    """

    def __init__(self, xelatex_override: str = "") -> None:
        self.xelatex_override = xelatex_override.strip()

    def detect(self) -> EnvReport:
        started = time.perf_counter()
        items: list[EnvItem] = []
        xelatex = self._find_xelatex()
        tex_bin_dir = xelatex.parent if xelatex else None
        path_env = self._path_with(tex_bin_dir)

        if xelatex is None:
            items.append(
                EnvItem(
                    id="xelatex",
                    label="XeLaTeX",
                    status=EnvStatus.MISSING,
                    detail="未找到 xelatex.exe",
                    fix_hint="安装 MiKTeX 或 TeX Live，或手动选择 xelatex.exe",
                )
            )
        else:
            result = self._run([str(xelatex), "--version"], path_env=path_env, timeout=20)
            version = _first_line(result.stdout or result.stderr) or "版本未知"
            items.append(
                EnvItem(
                    id="xelatex",
                    label="XeLaTeX",
                    status=EnvStatus.OK if result.exit_code == 0 else EnvStatus.WARN,
                    detail=version,
                    version=version,
                    path=str(xelatex),
                    fix_hint="" if result.exit_code == 0 else "xelatex 存在但无法正常执行",
                )
            )

        latexmk = self._find_tool("latexmk", tex_bin_dir)
        if latexmk:
            result = self._run([str(latexmk), "--version"], path_env=path_env, timeout=20)
            first = _version_line(result.stdout or result.stderr, "Latexmk") or "可用"
            items.append(
                EnvItem(
                    id="latexmk",
                    label="latexmk",
                    status=EnvStatus.OK if result.exit_code == 0 else EnvStatus.WARN,
                    detail=first,
                    path=str(latexmk),
                    fix_hint="" if result.exit_code == 0 else "latexmk 存在但无法执行",
                )
            )
        else:
            items.append(
                EnvItem(
                    id="latexmk",
                    label="latexmk",
                    status=EnvStatus.WARN,
                    detail="未找到；编译时可回退为直接调用 xelatex",
                    fix_hint="可在 TeX 发行版中安装 latexmk，或保留 xelatex 回退模式",
                )
            )

        kpsewhich = self._find_tool("kpsewhich", tex_bin_dir)
        if kpsewhich is None:
            items.append(
                EnvItem(
                    id="packages",
                    label="中文宏包与模板依赖",
                    status=EnvStatus.MISSING,
                    detail="未找到 kpsewhich，无法检查宏包",
                    fix_hint="修复 TeX 发行版安装，确保 kpsewhich 在 bin 目录中",
                )
            )
        else:
            items.append(self._check_packages(kpsewhich, path_env))

        items.append(self._check_fonts())
        items.append(self._check_biber(tex_bin_dir, path_env))

        # biber is required by the confirmed B reference strategy, but a
        # document without references can still compile. It is therefore a
        # warning-level capability rather than a hard compile gate.
        compile_item = self._probe_compile(xelatex, path_env)
        items.append(compile_item)

        report = EnvReport(
            items=items,
            xelatex_path=str(xelatex) if xelatex else "",
            tex_bin_dir=str(tex_bin_dir) if tex_bin_dir else "",
            checked_at=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        )
        logger.info(
            "Environment check finished in %.2fs: %s",
            time.perf_counter() - started,
            report.summary,
        )
        return report

    def _find_xelatex(self) -> Path | None:
        if self.xelatex_override:
            override = Path(self.xelatex_override).expanduser()
            if override.is_file():
                return override
            logger.warning("Configured xelatex path does not exist: %s", override)
        return self._find_tool("xelatex", None)

    def _find_tool(self, name: str, tex_bin_dir: Path | None) -> Path | None:
        candidates: list[Path] = []
        if name == "xelatex" and self.xelatex_override:
            candidates.append(Path(self.xelatex_override).expanduser())
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
        if tex_bin_dir:
            candidates.append(tex_bin_dir / f"{name}.exe")
        for bin_dir in self._common_bin_dirs():
            candidates.append(bin_dir / f"{name}.exe")
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
        return None

    def _common_bin_dirs(self) -> list[Path]:
        dirs: list[Path] = []
        env = os.environ
        for root in (
            Path(env.get("ProgramFiles", r"C:\Program Files")),
            Path(env.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
            Path(env.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))),
        ):
            for pattern in (
                "MiKTeX/miktex/bin/x64",
                "MiKTeX/miktex/bin",
                "Programs/MiKTeX/miktex/bin/x64",
                "Programs/MiKTeX/miktex/bin",
            ):
                candidate = root / pattern
                if candidate.is_dir():
                    dirs.append(candidate)
        for texlive in (Path(r"C:\texlive"), Path(env.get("USERPROFILE", "")) / "texlive"):
            if texlive.is_dir():
                for child in texlive.iterdir():
                    candidate = child / "bin" / "windows"
                    if candidate.is_dir():
                        dirs.append(candidate)
        # Preserve order while removing duplicates.
        return list(dict.fromkeys(dirs))

    def _path_with(self, tex_bin_dir: Path | None) -> dict[str, str]:
        env = os.environ.copy()
        if tex_bin_dir:
            env["PATH"] = str(tex_bin_dir) + os.pathsep + env.get("PATH", "")
        env.setdefault("max_print_line", "10000")
        return env

    def _check_packages(self, kpsewhich: Path, path_env: dict[str, str]) -> EnvItem:
        def check_one(pair: tuple[str, str]) -> tuple[str, bool]:
            file_name, display = pair
            result = self._run([str(kpsewhich), file_name], path_env=path_env, timeout=20)
            return display, result.exit_code == 0 and bool(result.stdout.strip())

        # Each kpsewhich call starts a TeX directory lookup.  Running the
        # independent lookups concurrently cuts a cold check from ~6s to
        # roughly 1s on a typical Windows machine.
        workers = min(8, max(1, len(REQUIRED_PACKAGES)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="kpse") as pool:
            results = list(pool.map(check_one, REQUIRED_PACKAGES))
        missing = [display for display, ok in results if not ok]
        total = len(REQUIRED_PACKAGES)
        if not missing:
            return EnvItem(
                id="packages",
                label="中文宏包与模板依赖",
                status=EnvStatus.OK,
                detail=f"{total}/{total} 可用 · ctex / xeCJK / biblatex-gb7714-2015",
                path=str(kpsewhich),
            )
        return EnvItem(
            id="packages",
            label="中文宏包与模板依赖",
            status=EnvStatus.MISSING,
            detail=f"缺少 {len(missing)} 项：{', '.join(missing)}",
            path=str(kpsewhich),
            fix_hint="在 TeX 发行版中安装缺失宏包；TeX Live 可用 tlmgr，MiKTeX 通常自动按需安装",
        )

    def _check_fonts(self) -> EnvItem:
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        font_dir = windir / "Fonts"
        missing: list[str] = []
        for file_name, display in REQUIRED_FONT_FILES:
            if not (font_dir / file_name).is_file():
                missing.append(display)
        if not missing:
            return EnvItem(
                id="fonts",
                label="中文与西文字体",
                status=EnvStatus.OK,
                detail="宋体 / 黑体 / 仿宋 / 楷体 / Times New Roman 全部存在",
                path=str(font_dir),
            )
        return EnvItem(
            id="fonts",
            label="中文与西文字体",
            status=EnvStatus.MISSING,
            detail=f"缺少：{', '.join(missing)}",
            path=str(font_dir),
            fix_hint="安装缺失的 Windows 字体，或在模板中切换到可用字体",
        )

    def _check_biber(self, tex_bin_dir: Path | None, path_env: dict[str, str]) -> EnvItem:
        biber = self._find_tool("biber", tex_bin_dir)
        if biber is None:
            return EnvItem(
                id="biber",
                label="biber 参考文献",
                status=EnvStatus.WARN,
                detail="未找到 biber；B 参考文献方案无法编译",
                fix_hint="安装 biber（TeX Live 通常随发行版提供）",
            )
        biber_tmp = Path(tempfile.gettempdir()) / ".paperflow-biber-cache"
        try:
            biber_tmp.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return EnvItem(
                id="biber",
                label="biber 参考文献",
                status=EnvStatus.WARN,
                detail=f"无法创建 biber 临时目录：{exc}",
                fix_hint="检查当前用户的临时目录权限",
            )
        biber_env = path_env.copy()
        biber_env["PAR_GLOBAL_TMPDIR"] = str(biber_tmp)
        biber_env["TMP"] = str(biber_tmp)
        biber_env["TEMP"] = str(biber_tmp)
        biber_env["TMPDIR"] = str(biber_tmp)
        result = self._run([str(biber), "--version"], path_env=biber_env, timeout=20)
        version = _first_line(result.stdout or result.stderr) or "版本未知"
        return EnvItem(
            id="biber",
            label="biber 参考文献",
            status=EnvStatus.OK if result.exit_code == 0 else EnvStatus.WARN,
            detail=version,
            path=str(biber),
            fix_hint="" if result.exit_code == 0 else "biber 存在但无法执行",
        )

    def _probe_compile(self, xelatex: Path | None, path_env: dict[str, str]) -> EnvItem:
        if xelatex is None:
            return EnvItem(
                id="compile",
                label="最小中文编译",
                status=EnvStatus.SKIPPED,
                detail="未找到 XeLaTeX，已跳过",
                fix_hint="先安装或选择 XeLaTeX",
            )
        tex = r"""\documentclass[UTF8,fontset=windows,a4paper]{ctexart}
\usepackage{geometry}
\geometry{margin=25mm}
\usepackage{booktabs}
\begin{document}
\section*{环境检测}
中文排版环境测试。表~\ref{tab:probe}。
\begin{table}[h]
\centering
\caption{测试表}\label{tab:probe}
\begin{tabular}{cc}
\toprule
项目 & 结果 \\
\midrule
中文 & 通过 \\
\bottomrule
\end{tabular}
\end{table}
\end{document}
"""
        started = time.perf_counter()
        try:
            with tempfile.TemporaryDirectory(prefix="paperflow-env-") as temp:
                work = Path(temp)
                (work / "probe.tex").write_text(tex, encoding="utf-8")
                probe_env = path_env.copy()
                # xdvipdfmx (a child of xelatex) needs a writable temp dir.
                # Keeping TMP/TEMP inside the isolated probe directory also
                # avoids polluting the user's global temp directory.
                probe_env["TMP"] = str(work)
                probe_env["TEMP"] = str(work)
                probe_env["TMPDIR"] = str(work)
                result = self._run(
                    [
                        str(xelatex),
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        "-file-line-error",
                        "probe.tex",
                    ],
                    path_env=probe_env,
                    timeout=90,
                    cwd=work,
                )
                pdf = work / "probe.pdf"
                duration = int((time.perf_counter() - started) * 1000)
                if result.exit_code == 0 and pdf.is_file() and pdf.stat().st_size > 0:
                    return EnvItem(
                        id="compile",
                        label="最小中文编译",
                        status=EnvStatus.OK,
                        detail=f"PDF 已生成 · {duration / 1000:.2f} s",
                    )
                tail = _error_tail(result.stdout, result.stderr)
                return EnvItem(
                    id="compile",
                    label="最小中文编译",
                    status=EnvStatus.MISSING,
                    detail=f"编译失败：{tail or '未知错误'}",
                    fix_hint="查看日志中的字体或宏包错误；可尝试重新安装 TeX 发行版",
                )
        except Exception as exc:
            logger.exception("Minimal compile probe failed")
            return EnvItem(
                id="compile",
                label="最小中文编译",
                status=EnvStatus.MISSING,
                detail=f"无法执行测试编译：{exc}",
                fix_hint="检查 XeLaTeX 安装是否完整",
            )

    def _run(
        self,
        command: list[str],
        *,
        path_env: dict[str, str],
        timeout: int,
        cwd: Path | None = None,
    ) -> CommandResult:
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd) if cwd else None,
                env=path_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                creationflags=CREATE_NO_WINDOW,
            )
            return CommandResult(
                exit_code=completed.returncode,
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                exit_code=124,
                stdout="",
                stderr=f"命令超时（{timeout}s）",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except OSError as exc:
            return CommandResult(
                exit_code=127,
                stdout="",
                stderr=str(exc),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )


def _first_line(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned
    return ""


def _version_line(text: str, needle: str) -> str:
    needle_lower = needle.lower()
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned and needle_lower in cleaned.lower():
            return cleaned
    return ""


def _error_tail(stdout: str, stderr: str) -> str:
    lines = [line.strip() for line in (stdout + "\n" + stderr).splitlines() if line.strip()]
    interesting = [
        line
        for line in lines
        if any(
            marker in line
            for marker in ("! ", "Error", "error", "not found", "Font", "fatal", "Fatal")
        )
    ]
    selected = interesting[-3:] if interesting else lines[-3:]
    return " | ".join(selected)[:320]


def format_env_report(report: EnvReport) -> str:
    return "\n".join(
        f"[{item.status.value.upper():7}] {item.label}: {item.detail}" for item in report.items
    )


def iter_missing_fixes(report: EnvReport) -> Iterable[str]:
    for item in report.missing:
        if item.fix_hint:
            yield f"{item.label}: {item.fix_hint}"