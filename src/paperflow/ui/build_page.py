from __future__ import annotations

import logging
import shutil
import zipfile
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from paperflow.core.compile import CompileResult, compile_tex
from paperflow.core.config import AppSettings
from paperflow.core.document import ImportResult
from paperflow.core.fixes import FixPlan, RenderOverrides, apply_fix_plan, build_fix_plan
from paperflow.core.layout import LayoutSettings
from paperflow.core.metadata import M4State
from paperflow.core.references import ReferenceState
from paperflow.core.render import RenderResult, render_project
from paperflow.core.structure import StructureResult
from paperflow.llm.compile_ai import (
    CompileAIError,
    CompileFixResult,
    analyze_compile_failure,
    apply_compile_patches,
)
from paperflow.llm.review_ai import AIReviewResult, ReviewFinding, review_pdf_with_ai
from paperflow.ui.ai_review_dialog import AIReviewDialog
from paperflow.ui.compile_fix_dialog import CompileFixDialog
from paperflow.ui.fix_compare_dialog import FixCompareDialog
from paperflow.ui.pdf_preview import PdfPreview
from paperflow.ui.widgets import Banner, Card, make_button, make_chip
from paperflow.ui.workers import FunctionThread

logger = logging.getLogger(__name__)


class BuildPage(QWidget):
    status_message = Signal(str)
    compiled = Signal(bool)
    overrides_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._imported: ImportResult | None = None
        self._structure: StructureResult | None = None
        self._m4: M4State | None = None
        self._references: ReferenceState | None = None
        self._layout: LayoutSettings | None = None
        self._render_result: RenderResult | None = None
        self._compile_result: CompileResult | None = None
        self._thread: FunctionThread | None = None
        self._settings: AppSettings | None = None
        self._key_getter = None
        self._review_thread: FunctionThread | None = None
        self._overrides = RenderOverrides()
        self._fix_pending = False
        self._fix_old_overrides: RenderOverrides | None = None
        self._fix_before_pdf: Path | None = None
        self._fix_before_tex: Path | None = None
        self._fix_plan: FixPlan | None = None
        self._compile_fix_thread: FunctionThread | None = None
        self._compile_fix_pending = False
        self._compile_fix_before_tex: Path | None = None
        self._compile_fix_before_pdf: Path | None = None
        self._compile_fix_result: CompileFixResult | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 24)
        layout.setSpacing(12)

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        title = QLabel("生成与导出")
        title.setObjectName("PageTitle")
        sub = QLabel(
            "程序用固定模板渲染 main.tex，再调用 XeLaTeX + biber 编译。"
            "AI 不直接生成最终 LaTeX。"
        )
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        header.addWidget(title)
        header.addWidget(sub)
        layout.addLayout(header)

        status_row = QHBoxLayout()
        self.state_chip = make_chip("未生成", fg="#667085", bg="#f2f4f7", border="#e4e7ec")
        status_row.addWidget(self.state_chip)
        self.status_text = QLabel("尚未生成 TEX。")
        self.status_text.setObjectName("Hint")
        self.status_text.setWordWrap(True)
        status_row.addWidget(self.status_text, 1)
        layout.addLayout(status_row)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.generate_button = make_button("生成 TEX", kind="soft")
        self.generate_button.clicked.connect(self.generate_tex)
        self.compile_button = make_button("编译 PDF", kind="primary")
        self.compile_button.clicked.connect(self.compile_pdf)
        self.ai_review_button = make_button("AI 审阅 PDF", kind="soft")
        self.ai_review_button.setEnabled(False)
        self.ai_review_button.setToolTip("可选：将 PDF 页面截图发送给模型做版式审阅")
        self.ai_review_button.clicked.connect(self._start_ai_review)
        self.ai_fix_button = make_button("AI 修复编译错误", kind="soft")
        self.ai_fix_button.setEnabled(False)
        self.ai_fix_button.setToolTip("编译失败后可用：把编译日志和 TEX 发给模型分析")
        self.ai_fix_button.clicked.connect(self._start_compile_fix)
        self.open_tex_button = make_button("打开 TEX", kind="ghost")
        self.open_tex_button.setEnabled(False)
        self.open_tex_button.setToolTip("用本机默认程序打开 output/main.tex")
        self.open_tex_button.clicked.connect(self.open_tex)
        self.export_button = make_button("导出 ZIP", kind="ghost")
        self.export_button.clicked.connect(self.export_zip)
        self.open_button = make_button("打开输出目录", kind="ghost")
        self.open_button.clicked.connect(self.open_output)
        toolbar.addWidget(self.generate_button)
        toolbar.addWidget(self.compile_button)
        toolbar.addWidget(self.ai_review_button)
        toolbar.addWidget(self.ai_fix_button)
        toolbar.addWidget(self.open_tex_button)
        toolbar.addWidget(self.export_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.open_button)
        layout.addLayout(toolbar)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.banner = Banner("生成状态", "选择版式参数后，点击“生成 TEX”或“编译 PDF”。", "info")
        layout.addWidget(self.banner)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.addWidget(self._build_log_card())
        splitter.addWidget(self._build_preview_card())
        splitter.setSizes([470, 750])
        layout.addWidget(splitter, 1)

    def _build_log_card(self) -> Card:
        card = Card("编译输出", "先看错误摘要，再看完整日志尾部。")
        self.log_edit = QTextEdit()
        self.log_edit.setObjectName("BuildLog")
        self.log_edit.setReadOnly(True)
        self.log_edit.setMinimumWidth(300)
        self.log_edit.setStyleSheet(
            "font-family: Consolas, 'Cascadia Mono', monospace; font-size: 9px;"
        )
        card.body.addWidget(self.log_edit)
        return card

    def _build_preview_card(self) -> Card:
        card = Card("PDF 预览", "预览用于检查版式；不承诺像素级所见即所得。")
        self.preview = PdfPreview()
        card.body.addWidget(self.preview)
        return card

    def set_context(
        self,
        imported: ImportResult,
        structure: StructureResult,
        m4: M4State,
        references: ReferenceState,
        layout: LayoutSettings,
        overrides: RenderOverrides | None = None,
    ) -> None:
        self._imported = imported
        self._structure = structure
        self._m4 = m4
        self._references = references
        self._layout = layout
        self._overrides = overrides or RenderOverrides()
        self._render_result = None
        self._compile_result = None
        self._fix_pending = False
        self._fix_old_overrides = None
        self._fix_before_pdf = None
        self._fix_before_tex = None
        self._fix_plan = None
        self._compile_fix_pending = False
        self._compile_fix_before_tex = None
        self._compile_fix_before_pdf = None
        self._compile_fix_result = None
        existing_tex = Path(imported.project_dir).resolve() / "output" / "main.tex"
        self.open_tex_button.setEnabled(existing_tex.is_file())
        self.ai_fix_button.setEnabled(False)
        self.preview.close_document()
        self.log_edit.clear()
        self.state_chip.setText("待生成")
        self.state_chip.setStyleSheet(
            "color:#667085; background:#f2f4f7; border:1px solid #e4e7ec; "
            "border-radius:8px; padding:2px 7px; font-size:9px; font-weight:700;"
        )
        self.status_text.setText(
            f"{len(structure.document.blocks)} 块 · {len(m4.figures)} 图 · "
            f"{len(m4.tables)} 表 · {len(references.entries)} 条文献"
        )
        self.export_button.setEnabled(False)
        self.refresh_ai_state()

    def set_ai_context(self, settings: AppSettings, key_getter) -> None:
        self._settings = settings
        self._key_getter = key_getter
        self.refresh_ai_state()

    def refresh_ai_state(self) -> None:
        key = ""
        if callable(self._key_getter):
            try:
                key = self._key_getter() or ""
            except Exception:
                key = ""
        available = (
            bool(key.strip())
            and self._compile_result is not None
            and self._compile_result.ok
            and self._review_thread is None
        )
        self.ai_review_button.setEnabled(available)
        if not available:
            self.ai_review_button.setToolTip("需先配置 Key 并成功编译 PDF")
        else:
            self.ai_review_button.setToolTip("可选：将 PDF 页面截图发送给模型做版式审阅")
        self.refresh_compile_fix_state()

    def _start_ai_review(self) -> None:
        if self._settings is None or not callable(self._key_getter):
            self.banner.set_state("error", "AI 未配置", "请先配置 API Key。")
            return
        key = (self._key_getter() or "").strip()
        if not key or self._compile_result is None or not self._compile_result.ok:
            self.banner.set_state("error", "没有可审阅的 PDF", "请先成功编译 PDF。")
            return
        answer = QMessageBox.question(
            self,
            "AI 审阅 PDF",
            "将把 PDF 页面截图（最多 20 页）和页面文本发送给模型，"
            "用于版式审阅。\n\nAI 只返回建议，不会自动修改 main.tex；"
            "是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.ai_review_button.setEnabled(False)
        self.banner.set_state(
            "info",
            "AI 正在审阅",
            "正在渲染页面并请求视觉审阅；建议可应用白名单修复，不直接改正文。",
        )
        layout_note = ""
        if self._layout is not None:
            layout_note = (
                f"{'双栏' if self._layout.columns == 2 else '单栏'}，"
                f"页边距 {self._layout.margin_mm} mm，"
                f"正文 {self._layout.body_size_pt} pt"
            )
        self._review_thread = FunctionThread(
            review_pdf_with_ai,
            self._settings,
            key,
            self._compile_result.pdf_path,
            layout_note=layout_note,
            target_catalog=self._target_catalog(),
            parent=self,
        )
        self._review_thread.result.connect(self._on_ai_review_result)
        self._review_thread.error.connect(self._on_ai_review_error)
        self._review_thread.finished.connect(self._on_review_finished)
        self._review_thread.start()

    def _target_catalog(self) -> str:
        lines: list[str] = []
        if self._m4 is not None:
            for figure in self._m4.figures:
                lines.append(f"图片 {figure.label or figure.id} -> figure:{figure.id}")
            for table in self._m4.tables:
                lines.append(f"表格 {table.label or table.id} -> table:{table.id}")
        if self._structure is not None:
            for block in self._structure.document.blocks:
                if block.kind == "heading":
                    lines.append(f"标题 {block.text} -> heading:{block.id}")
        return "\n".join(lines[:80])

    def _on_ai_review_result(self, result: AIReviewResult) -> None:
        if result.findings:
            self.banner.set_state(
                "warn",
                "AI 审阅完成",
                f"发现 {len(result.findings)} 条版式问题；可选中应用白名单修复。",
            )
        else:
            self.banner.set_state(
                "ok",
                "AI 审阅完成",
                "没有发现明确的版式问题。",
            )
        self.status_message.emit(f"M5 · AI 审阅完成，{len(result.findings)} 条")
        dialog = AIReviewDialog(result, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_findings:
            self.apply_fixes(dialog.selected_findings)

    def apply_fixes(self, findings: list[ReviewFinding]) -> None:
        if self._m4 is None or self._structure is None:
            return
        plan = build_fix_plan(findings, self._m4, self._structure, self._overrides)
        if not plan.actions:
            detail = "；".join(plan.skipped) or "没有可定位的白名单动作。"
            self.banner.set_state(
                "warn",
                "没有可安全自动修复的项",
                detail + " 请人工处理，或让审阅结果带上 figure/table/heading target。",
            )
            return
        summary = "\n".join(f"· {action.description}" for action in plan.actions)
        answer = QMessageBox.question(
            self,
            "应用白名单修复",
            f"将应用 {len(plan.actions)} 项受控修改并重新编译：\n\n{summary}\n\n"
            "不会改正文；编译后可对比前后 PDF，不保留会回滚。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        project = Path(self._imported.project_dir).resolve()
        build = project / "output" / "build"
        before_pdf = build / "main.before.pdf"
        before_tex = project / "output" / "main.before.tex"
        try:
            if self._compile_result is None or self._compile_result.pdf_path is None:
                raise OSError("当前没有可备份的 PDF")
            shutil.copy2(self._compile_result.pdf_path, before_pdf)
            shutil.copy2(project / "output" / "main.tex", before_tex)
        except OSError as exc:
            self.banner.set_state("error", "无法启动修复", f"备份失败：{exc}")
            return
        self._fix_old_overrides = self._overrides.model_copy(deep=True)
        self._fix_before_pdf = before_pdf
        self._fix_before_tex = before_tex
        self._fix_plan = plan
        self._fix_pending = True
        self._overrides = apply_fix_plan(plan, self._overrides)
        if not self.generate_tex():
            self._fix_pending = False
            self._overrides = self._fix_old_overrides or RenderOverrides()
            self._cleanup_fix_backups(keep_after=False)
            self._write_overrides()
            self.banner.set_state("error", "修复渲染失败", "已撤销，未改变原文件。")
            return
        self.banner.set_state(
            "info",
            "正在应用修复",
            f"已应用 {len(plan.actions)} 项白名单修改，正在重新编译……",
        )
        self._start_compile()

    def _handle_fix_compiled(self, result: CompileResult) -> None:
        if not result.ok or result.pdf_path is None:
            self._rollback_fix()
            self.banner.set_state(
                "error",
                "修复后编译失败，已回滚",
                "原 TeX/PDF 已恢复；错误日志见下方。",
            )
            self._set_log(result.log_tail)
            return
        self._compile_result = result
        dialog = FixCompareDialog(
            self._fix_before_pdf,
            result.pdf_path,
            self._fix_plan,
            self,
        )
        dialog.exec()
        if dialog.keep_changes:
            self._retain_fix()
        else:
            self._rollback_fix()
            self.banner.set_state(
                "warn",
                "已回滚修复",
                "已恢复修改前的 TeX/PDF 和覆盖设置。",
            )

    def _retain_fix(self) -> None:
        self._fix_pending = False
        self._fix_plan = None
        self._fix_old_overrides = None
        self._cleanup_fix_backups(keep_after=False)
        self._write_overrides()
        self.overrides_changed.emit(self._overrides)
        self.export_button.setEnabled(True)
        self.banner.set_state(
            "ok",
            "修复已保留",
            "白名单修改已写入 overrides；PDF 已重新编译。",
        )
        self.status_message.emit("M5 · 白名单修复已保留")
        self.refresh_ai_state()

    def _rollback_fix(self) -> None:
        project = Path(self._imported.project_dir).resolve()
        if self._fix_before_pdf is not None and self._fix_before_pdf.is_file():
            try:
                shutil.copy2(self._fix_before_pdf, project / "output" / "build" / "main.pdf")
            except OSError:
                logger.exception("Failed to restore previous PDF")
        if self._fix_before_tex is not None and self._fix_before_tex.is_file():
            try:
                shutil.copy2(self._fix_before_tex, project / "output" / "main.tex")
            except OSError:
                logger.exception("Failed to restore previous TEX")
        self._overrides = self._fix_old_overrides or RenderOverrides()
        self._fix_pending = False
        self._fix_plan = None
        self._cleanup_fix_backups(keep_after=False)
        self._write_overrides()
        self.overrides_changed.emit(self._overrides)
        pdf = project / "output" / "build" / "main.pdf"
        if pdf.is_file():
            self.preview.load_pdf(pdf)
            self._compile_result = CompileResult(
                True,
                pdf,
                "已回滚到修复前的 PDF。",
                0.0,
            )
            self.export_button.setEnabled(True)
        self.state_chip.setText("已回滚")
        self.status_text.setText("修复已回滚，当前为修改前版本。")
        self.status_message.emit("M5 · 修复已回滚")
        self.refresh_ai_state()

    def _cleanup_fix_backups(self, *, keep_after: bool) -> None:
        if not keep_after:
            for path in (self._fix_before_pdf, self._fix_before_tex):
                if path is not None and path.is_file():
                    try:
                        path.unlink()
                    except OSError:
                        logger.debug("Failed to remove backup", exc_info=True)
        self._fix_before_pdf = None
        self._fix_before_tex = None

    def _write_overrides(self) -> None:
        if self._imported is None:
            return
        content = Path(self._imported.project_dir).resolve() / "content"
        content.mkdir(parents=True, exist_ok=True)
        target = content / "overrides.json"
        if self._overrides.figure_width or self._overrides.figure_span or self._overrides.table_span or self._overrides.page_break_before:
            target.write_text(self._overrides.to_json() + "\n", encoding="utf-8")
        elif target.is_file():
            target.unlink()

    def _on_ai_review_error(self, message: str) -> None:
        self.banner.set_state("error", "AI 审阅失败", message)

    def _on_review_finished(self) -> None:
        thread = self._review_thread
        self._review_thread = None
        if thread is not None:
            thread.deleteLater()
        self.refresh_ai_state()

    def generate_tex(self) -> bool:
        if not self._all_ready():
            return False
        try:
            self._render_result = render_project(
                Path(self._imported.project_dir),
                self._imported,
                self._structure,
                self._m4,
                self._references,
                self._layout,
                self._overrides,
            )
        except Exception as exc:
            logger.exception("Render failed")
            self.banner.set_state("error", "生成 TEX 失败", str(exc))
            return False
        self.state_chip.setText("TEX 已生成")
        self.state_chip.setStyleSheet(
            "color:#2563eb; background:#eff4ff; border:1px solid #dbe7ff; "
            "border-radius:8px; padding:2px 7px; font-size:9px; font-weight:700;"
        )
        self.status_text.setText(f"已写入 {self._render_result.tex_path}")
        self.banner.set_state(
            "ok",
            "TEX 已生成",
            f"main.tex 与 refs.bib 已写入 {self._render_result.tex_path.parent}。",
        )
        self.log_edit.setPlainText(self._render_result.tex[:6000])
        self.open_tex_button.setEnabled(True)
        self.refresh_compile_fix_state()
        self.status_message.emit("M5 · TEX 已生成")
        return True

    def compile_pdf(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        if not self.generate_tex():
            return
        self._start_compile()

    def _start_compile(self) -> None:
        self._set_busy(True)
        self.banner.set_state("info", "正在编译", "XeLaTeX + biber 编译中，请稍候……")
        self.status_text.setText("正在编译 PDF……")
        project_dir = Path(self._imported.project_dir).resolve()
        self._thread = FunctionThread(
            compile_tex,
            project_dir,
            self._render_result.tex_path,
            parent=self,
        )
        self._thread.result.connect(self._on_compiled)
        self._thread.error.connect(self._on_compile_error)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_compiled(self, result: CompileResult) -> None:
        self._set_busy(False)
        if self._compile_fix_pending:
            self._handle_compile_fix_compiled(result)
            return
        if self._fix_pending:
            self._handle_fix_compiled(result)
            return
        self._compile_result = result
        if result.ok and result.pdf_path is not None:
            self.preview.load_pdf(result.pdf_path)
            self.state_chip.setText("PDF 已生成")
            self.state_chip.setStyleSheet(
                "color:#067647; background:#ecfdf3; border:1px solid #abefc6; "
                "border-radius:8px; padding:2px 7px; font-size:9px; font-weight:700;"
            )
            self.status_text.setText(
                f"编译成功 · {result.duration_s:.2f}s · {result.pdf_path}"
            )
            self.banner.set_state(
                "ok",
                "编译成功",
                f"PDF 已生成：{result.pdf_path.name}；可翻页预览或导出 ZIP。",
            )
            self.export_button.setEnabled(True)
            self._set_log(result.log_tail or "编译完成，无日志尾部。")
            self.compiled.emit(True)
            self.status_message.emit("M5 · PDF 编译成功")
        else:
            self.state_chip.setText("编译失败")
            self.state_chip.setStyleSheet(
                "color:#b42318; background:#fef3f2; border:1px solid #fecdca; "
                "border-radius:8px; padding:2px 7px; font-size:9px; font-weight:700;"
            )
            self.status_text.setText("编译失败；请查看日志并修改。")
            self.banner.set_state("error", "编译失败", "LaTeX 返回错误，详见下方日志。")
            self._set_log(result.log_tail)
            self.export_button.setEnabled(False)
            self.compiled.emit(False)
            self.status_message.emit("M5 · 编译失败")
        self.refresh_ai_state()

    def _on_compile_error(self, message: str) -> None:
        self._set_busy(False)
        if self._compile_fix_pending:
            self._rollback_compile_fix()
            self.banner.set_state(
                "error",
                "AI 修复编译进程失败，已回滚",
                message,
            )
            self._set_log(message)
            return
        if self._fix_pending:
            self._rollback_fix()
            self.banner.set_state(
                "error",
                "修复编译进程失败，已回滚",
                message,
            )
            self._set_log(message)
            return
        self.state_chip.setText("编译失败")
        self.banner.set_state("error", "编译进程失败", message)
        self._set_log(message)
        self.refresh_ai_state()

    def _on_thread_finished(self) -> None:
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.deleteLater()
        self._set_busy(False)

    def export_zip(self) -> None:
        if self._imported is None or self._compile_result is None or not self._compile_result.ok:
            return
        project = Path(self._imported.project_dir).resolve()
        pdf = self._compile_result.pdf_path
        if pdf is None or not pdf.is_file():
            return
        target = project / "output" / "paperflow-export.zip"
        try:
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for file in (
                    project / "output" / "main.tex",
                    project / "output" / "refs.bib",
                    pdf,
                    project / "content" / "metadata.json",
                    project / "content" / "structure.json",
                    project / "content" / "references.json",
                    project / "content" / "layout.json",
                ):
                    if file.is_file():
                        archive.write(file, file.relative_to(project))
                for folder in (project / "assets" / "figures", project / "assets" / "tables"):
                    if folder.is_dir():
                        for file in folder.rglob("*"):
                            if file.is_file():
                                archive.write(file, file.relative_to(project))
        except OSError as exc:
            self.banner.set_state("error", "导出失败", str(exc))
            return
        self.banner.set_state("ok", "ZIP 已导出", str(target))
        self.status_message.emit("M5 · ZIP 已导出")

    def open_output(self) -> None:
        if self._imported is None:
            return
        path = Path(self._imported.project_dir).resolve() / "output"
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _set_log(self, text: str) -> None:
        self.log_edit.setPlainText(text)
        self.log_edit.moveCursor(QTextCursor.MoveOperation.End)

    def open_tex(self) -> None:
        tex = self._render_result.tex_path if self._render_result is not None else None
        if tex is None and self._imported is not None:
            candidate = Path(self._imported.project_dir).resolve() / "output" / "main.tex"
            tex = candidate if candidate.is_file() else None
        if tex is None or not tex.is_file():
            self.banner.set_state("warn", "没有 TEX", "请先生成 main.tex。")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(tex))):
            self.banner.set_state(
                "warn",
                "无法打开 TEX",
                f"没有找到 .tex 的默认程序；文件位置：{tex}",
            )
            return
        self.status_message.emit("M5 · 已用本机程序打开 main.tex")

    def refresh_compile_fix_state(self) -> None:
        key = ""
        if callable(self._key_getter):
            try:
                key = self._key_getter() or ""
            except Exception:
                key = ""
        failed = (
            self._compile_result is not None
            and not self._compile_result.ok
            and self._render_result is not None
        )
        available = bool(key.strip()) and failed and self._compile_fix_thread is None
        self.ai_fix_button.setEnabled(available)
        self.ai_fix_button.setToolTip(
            "编译失败后可用：把编译日志和 TEX 发给模型分析"
            if not available
            else "可选：把编译日志和 main.tex 发送给模型，生成最小 patch"
        )

    def _start_compile_fix(self) -> None:
        if self._settings is None or not callable(self._key_getter):
            self.banner.set_state("error", "AI 未配置", "请先配置 API Key。")
            return
        key = (self._key_getter() or "").strip()
        if not key:
            self.banner.set_state("error", "缺少 API Key", "请先配置 API Key。")
            return
        if self._compile_result is None or self._compile_result.ok:
            self.banner.set_state("warn", "当前不是编译失败", "请先执行编译并确认失败。")
            return
        if self._render_result is None or not self._render_result.tex_path.is_file():
            self.banner.set_state("warn", "没有 TEX", "请先生成 main.tex。")
            return
        answer = QMessageBox.question(
            self,
            "AI 修复编译错误",
            "将把编译日志和 main.tex 文本发送给模型，用于分析编译错误。\n\n"
            "不上传 PDF；AI 只返回最小 patch，应用前会备份，失败自动回滚。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        tex = self._render_result.tex_path.read_text(encoding="utf-8")
        log = self._compile_result.log_tail
        self.ai_fix_button.setEnabled(False)
        self.banner.set_state("info", "AI 正在分析编译错误", "正在请求最小修改片段……")
        self._compile_fix_thread = FunctionThread(
            analyze_compile_failure,
            self._settings,
            key,
            log,
            tex,
            parent=self,
        )
        self._compile_fix_thread.result.connect(self._on_compile_fix_result)
        self._compile_fix_thread.error.connect(self._on_compile_fix_error)
        self._compile_fix_thread.finished.connect(self._on_compile_fix_finished)
        self._compile_fix_thread.start()

    def _on_compile_fix_result(self, result: CompileFixResult) -> None:
        self._compile_fix_result = result
        if not result.patches:
            self.banner.set_state(
                "warn",
                "AI 没有给出安全 patch",
                result.diagnosis or "请查看诊断并人工修改。",
            )
            return
        dialog = CompileFixDialog(result, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._apply_compile_fix(result)

    def _on_compile_fix_error(self, message: str) -> None:
        self.banner.set_state("error", "AI 编译修复分析失败", message)

    def _on_compile_fix_finished(self) -> None:
        thread = self._compile_fix_thread
        self._compile_fix_thread = None
        if thread is not None:
            thread.deleteLater()
        self.refresh_compile_fix_state()

    def _apply_compile_fix(self, result: CompileFixResult) -> None:
        if self._render_result is None:
            return
        tex_path = self._render_result.tex_path
        try:
            original = tex_path.read_text(encoding="utf-8")
            patched, _applied = apply_compile_patches(original, result.patches)
        except CompileAIError as exc:
            self.banner.set_state("error", "无法应用 AI 修改", str(exc))
            return
        project = Path(self._imported.project_dir).resolve()
        build = project / "output" / "build"
        before_tex = project / "output" / "main.before-ai.tex"
        before_pdf = build / "main.before-ai.pdf"
        try:
            shutil.copy2(tex_path, before_tex)
            if self._compile_result is not None and self._compile_result.pdf_path:
                shutil.copy2(self._compile_result.pdf_path, before_pdf)
        except OSError as exc:
            self.banner.set_state("error", "备份失败", str(exc))
            return
        tex_path.write_text(patched, encoding="utf-8")
        self._compile_fix_pending = True
        self._compile_fix_before_tex = before_tex
        self._compile_fix_before_pdf = before_pdf
        self.banner.set_state(
            "info",
            "正在应用 AI 修改",
            f"已应用 {len(result.patches)} 个 patch，正在重新编译……",
        )
        self._start_compile()

    def _handle_compile_fix_compiled(self, result: CompileResult) -> None:
        if result.ok and result.pdf_path is not None:
            self._compile_fix_pending = False
            self._compile_result = result
            self.preview.load_pdf(result.pdf_path)
            self.export_button.setEnabled(True)
            self.state_chip.setText("AI 修复后已生成")
            self.state_chip.setStyleSheet(
                "color:#067647; background:#ecfdf3; border:1px solid #abefc6; "
                "border-radius:8px; padding:2px 7px; font-size:9px; font-weight:700;"
            )
            self.status_text.setText(
                f"AI 修复后编译成功 · {result.duration_s:.2f}s · {result.pdf_path}"
            )
            self.banner.set_state(
                "ok",
                "AI 修复后编译成功",
                "已保留 AI 修改后的 main.tex；可继续预览或导出。",
            )
            self._set_log(result.log_tail or "编译完成，无日志尾部。")
            self._cleanup_compile_fix_backups()
            self.compiled.emit(True)
            self.status_message.emit("M5 · AI 编译修复成功")
            self.refresh_ai_state()
            return
        self._rollback_compile_fix()
        self.banner.set_state(
            "error",
            "AI 修改后仍编译失败，已回滚",
            "已恢复修改前的 main.tex 和 PDF；请查看日志并人工处理。",
        )
        self._set_log(result.log_tail)
        self.compiled.emit(False)
        self.status_message.emit("M5 · AI 编译修复失败")

    def _rollback_compile_fix(self) -> None:
        project = Path(self._imported.project_dir).resolve()
        if self._compile_fix_before_tex is not None and self._compile_fix_before_tex.is_file():
            try:
                shutil.copy2(self._compile_fix_before_tex, project / "output" / "main.tex")
            except OSError:
                logger.exception("Failed to restore TEX after AI fix")
        if self._compile_fix_before_pdf is not None and self._compile_fix_before_pdf.is_file():
            try:
                shutil.copy2(
                    self._compile_fix_before_pdf,
                    project / "output" / "build" / "main.pdf",
                )
            except OSError:
                logger.exception("Failed to restore PDF after AI fix")
        self._compile_fix_pending = False
        self._cleanup_compile_fix_backups()
        self.refresh_compile_fix_state()

    def _cleanup_compile_fix_backups(self) -> None:
        for path in (self._compile_fix_before_tex, self._compile_fix_before_pdf):
            if path is not None and path.is_file():
                try:
                    path.unlink()
                except OSError:
                    logger.debug("Failed to remove AI compile-fix backup", exc_info=True)
        self._compile_fix_before_tex = None
        self._compile_fix_before_pdf = None

    def _all_ready(self) -> bool:
        return all(
            item is not None
            for item in (
                self._imported,
                self._structure,
                self._m4,
                self._references,
                self._layout,
            )
        )

    def _set_busy(self, busy: bool) -> None:
        self.progress.setVisible(busy)
        self.generate_button.setEnabled(not busy)
        self.compile_button.setEnabled(not busy)
        if busy:
            self.ai_review_button.setEnabled(False)
        self.export_button.setEnabled(not busy and self._compile_result is not None and self._compile_result.ok)
        if not busy:
            self.status_text.setText(self.status_text.text())

    def shutdown(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            if not self._thread.wait(1500):
                self._thread.terminate()
                self._thread.wait(500)
        self._thread = None
        if self._review_thread is not None and self._review_thread.isRunning():
            self._review_thread.quit()
            if not self._review_thread.wait(1500):
                self._review_thread.terminate()
                self._review_thread.wait(500)
        self._review_thread = None
        if self._compile_fix_thread is not None and self._compile_fix_thread.isRunning():
            self._compile_fix_thread.quit()
            if not self._compile_fix_thread.wait(1500):
                self._compile_fix_thread.terminate()
                self._compile_fix_thread.wait(500)
        self._compile_fix_thread = None
        self.preview.shutdown()