from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from paperflow.core.config import AppSettings
from paperflow.core.document import ImportResult
from paperflow.core.references import (
    ReferenceEntry,
    ReferenceState,
    generate_bib,
    parse_references,
)
from paperflow.core.structure import StructureResult
from paperflow.llm.reference_ai import parse_references_with_ai
from paperflow.ui.widgets import Banner, Card, make_button, make_chip
from paperflow.ui.workers import FunctionThread

logger = logging.getLogger(__name__)

COLUMNS = ["编号", "类型", "作者", "题名", "年份", "期刊 / 出版社", "状态", "缺失字段"]
STATUS_LABELS = {
    "pending": "待确认",
    "confirmed": "已确认",
    "fallback_text": "回退原文",
    "excluded": "不输出",
}


class ReferencesPage(QWidget):
    references_saved = Signal(object)
    status_message = Signal(str)
    next_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._imported: ImportResult | None = None
        self._structure: StructureResult | None = None
        self._state: ReferenceState | None = None
        self._settings: AppSettings | None = None
        self._key_getter = None
        self._ai_thread: FunctionThread | None = None
        self._updating = False
        self._dirty = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 24)
        layout.setSpacing(12)

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        title = QLabel("参考文献")
        title.setObjectName("PageTitle")
        sub = QLabel(
            "采用 B 方案：解析已有条目，逐条确认后生成 refs.bib，由 biblatex-gb7714-2015 重排。"
            "缺失字段不补造。"
        )
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        header.addWidget(title)
        header.addWidget(sub)
        layout.addLayout(header)

        self.info_banner = Banner(
            "参考文献解析",
            "正在读取结构中的 reference 块……",
            "info",
        )
        layout.addWidget(self.info_banner)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.ai_button = make_button("AI 解析条目", kind="soft")
        self.ai_button.setEnabled(False)
        self.ai_button.setToolTip("可选：将参考文献原文发送给模型解析；需先配置 Key")
        self.ai_button.clicked.connect(self._start_ai_parse)
        toolbar.addWidget(self.ai_button)
        self.confirm_all_button = make_button("确认全部", kind="soft")
        self.confirm_all_button.clicked.connect(self.confirm_all)
        self.save_button = make_button("保存并生成 refs.bib", kind="primary")
        self.save_button.clicked.connect(self.save_references)
        self.add_button = make_button("+ 手动条目", kind="ghost")
        self.add_button.clicked.connect(self.add_entry)
        self.remove_button = make_button("删除选中", kind="ghost")
        self.remove_button.clicked.connect(self.remove_entry)
        toolbar.addWidget(self.confirm_all_button)
        toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.remove_button)
        toolbar.addStretch(1)
        self.count_chip = make_chip("0 条", fg="#667085", bg="#f2f4f7", border="#e4e7ec")
        toolbar.addWidget(self.count_chip)
        toolbar.addWidget(self.save_button)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("ReferenceTable")
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        header_view = self.table.horizontalHeader()
        header_view.setStretchLastSection(False)
        for index in (0, 1, 4, 6, 7):
            header_view.setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        for index, width in ((0, 60), (1, 62), (2, 140), (4, 54), (5, 130), (6, 76), (7, 86)):
            self.table.setColumnWidth(index, width)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, 2)

        original_card = Card("原文对照", "模型不补造字段；无法确认时可直接回退原文。")
        self.original_edit = QTextEdit()
        self.original_edit.setReadOnly(True)
        self.original_edit.setMinimumHeight(110)
        original_card.body.addWidget(self.original_edit)
        layout.addWidget(original_card)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 2, 0, 0)
        self.save_hint = QLabel("")
        self.save_hint.setObjectName("Hint")
        footer.addWidget(self.save_hint)
        footer.addStretch(1)
        self.next_button = make_button("下一步：版式设置", kind="primary")
        self.next_button.setEnabled(False)
        self.next_button.clicked.connect(self.next_requested.emit)
        footer.addWidget(self.next_button)
        layout.addLayout(footer)

    def set_context(
        self,
        imported: ImportResult,
        structure: StructureResult,
        state: ReferenceState | None = None,
    ) -> None:
        self._imported = imported
        self._structure = structure
        self._state = state or parse_references(structure.document, structure)
        self._populate()
        self.info_banner.set_state(
            "info",
            "参考文献已解析" if self._state.entries else "没有检测到参考文献",
            (
                f"共 {len(self._state.entries)} 条。逐条确认后保存；"
                "当前为本地规则解析，可在表格中手动修正。"
            ),
        )
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
        available = bool(key.strip()) and self._state is not None and bool(self._state.entries)
        self.ai_button.setEnabled(available and self._ai_thread is None)
        self.ai_button.setToolTip(
            "可选：将参考文献原文发送给模型解析；需先配置 Key"
            if not available
            else "可选：把当前条目的原文发送给模型重新解析"
        )

    def _start_ai_parse(self) -> None:
        if self._settings is None or not callable(self._key_getter):
            self.info_banner.set_state("error", "AI 未配置", "请先配置 API Key。")
            return
        key = (self._key_getter() or "").strip()
        if not key:
            self.info_banner.set_state("error", "缺少 API Key", "请先配置 API Key。")
            return
        if self._state is None or not self._state.entries:
            self.info_banner.set_state("error", "没有条目", "当前没有可解析的参考文献。")
            return
        answer = QMessageBox.question(
            self,
            "AI 解析参考文献",
            f"将把 {len(self._state.entries)} 条参考文献原文发送给模型，"
            "用于结构化字段。\n\n不会上传论文正文或 PDF；AI 不补造字段。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.ai_button.setEnabled(False)
        self.info_banner.set_state(
            "info",
            "AI 正在解析",
            "模型只接收参考文献原文；结果仍需逐条确认后保存。",
        )
        self._ai_thread = FunctionThread(
            parse_references_with_ai,
            self._settings,
            key,
            self._state,
            parent=self,
        )
        self._ai_thread.result.connect(self._on_ai_result)
        self._ai_thread.error.connect(self._on_ai_error)
        self._ai_thread.finished.connect(self._on_ai_finished)
        self._ai_thread.start()

    def _on_ai_result(self, state: ReferenceState) -> None:
        self._state = state
        self._populate()
        self._dirty = True
        self.info_banner.set_state(
            "ok",
            "AI 已解析，尚未保存",
            f"共 {len(state.entries)} 条。AI 只给字段，仍需逐条确认后保存。",
        )
        self.save_hint.setText("AI 已解析，请确认后保存")
        self.status_message.emit("M5 · AI 参考解析完成")

    def _on_ai_error(self, message: str) -> None:
        self.info_banner.set_state("error", "AI 参考解析失败", message)
        self.save_hint.setText("AI 解析失败，本地结果未变")

    def _on_ai_finished(self) -> None:
        thread = self._ai_thread
        self._ai_thread = None
        if thread is not None:
            thread.deleteLater()
        self.refresh_ai_state()

    def shutdown(self) -> None:
        if self._ai_thread is not None and self._ai_thread.isRunning():
            self._ai_thread.quit()
            if not self._ai_thread.wait(1500):
                self._ai_thread.terminate()
                self._ai_thread.wait(500)
        self._ai_thread = None

    def _populate(self) -> None:
        if self._state is None:
            return
        self._updating = True
        try:
            self.table.setRowCount(len(self._state.entries))
            for row, entry in enumerate(self._state.entries):
                values = [
                    entry.id,
                    entry.type,
                    "，".join(entry.authors),
                    entry.title,
                    entry.year,
                    entry.journal or entry.publisher or entry.booktitle,
                    STATUS_LABELS.get(entry.status, entry.status),
                    "，".join(entry.missing_fields),
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if col in {0, 4, 6, 7}:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                        )
                    if col in {0, 7}:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, col, item)
                self.table.setRowHeight(row, 28)
            self.count_chip.setText(f"{len(self._state.entries)} 条")
            self._updating = False
            if self.table.rowCount():
                self.table.selectRow(0)
                self.original_edit.setPlainText(self._state.entries[0].original_text)
            else:
                self.original_edit.clear()
            self.next_button.setEnabled(False)
            self.save_hint.setText("未保存")
        finally:
            self._updating = False
        self.refresh_ai_state()

    def _on_selection_changed(self) -> None:
        if self._updating or self._state is None:
            return
        row = self.table.currentRow()
        if 0 <= row < len(self._state.entries):
            self.original_edit.setPlainText(self._state.entries[row].original_text)

    def _collect(self) -> ReferenceState:
        if self._state is None:
            raise ValueError("没有参考文献数据")
        entries: list[ReferenceEntry] = []
        for row in range(self.table.rowCount()):
            old = self._state.entries[row] if row < len(self._state.entries) else None
            status_text = self._cell(row, 6)
            status = next(
                (key for key, label in STATUS_LABELS.items() if label == status_text),
                "pending",
            )
            ref_type = self._cell(row, 1) or "misc"
            venue = self._cell(row, 5)
            authors = [
                item.strip()
                for item in self._cell(row, 2).replace("，", ",").split(",")
                if item.strip()
            ]
            missing = [
                item.strip()
                for item in self._cell(row, 7).replace("，", ",").split(",")
                if item.strip()
            ]
            if old is not None:
                entry = old.model_copy(
                    update={
                        "type": ref_type,
                        "authors": authors,
                        "title": self._cell(row, 3),
                        "year": self._cell(row, 4),
                        "journal": venue if ref_type == "article" else old.journal,
                        "publisher": venue if ref_type == "book" else old.publisher,
                        "status": status,
                        "missing_fields": missing,
                    }
                )
            else:
                entry = ReferenceEntry(
                    id=f"ref{row + 1:03d}",
                    original_text="",
                    type=ref_type,
                    authors=authors,
                    title=self._cell(row, 3),
                    year=self._cell(row, 4),
                    journal=venue if ref_type == "article" else "",
                    publisher=venue if ref_type == "book" else "",
                    status=status,
                    missing_fields=missing,
                    citation_key=f"ref{row + 1:03d}",
                )
            entries.append(entry)
        return ReferenceState(entries=entries, source="local")

    def confirm_all(self) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 6)
            if item:
                item.setText("已确认")
        self.save_hint.setText("已全部确认，点击保存生成 refs.bib")
        self._dirty = True

    def add_entry(self) -> None:
        if self._state is None:
            return
        entry = ReferenceEntry(
            id=f"ref{len(self._state.entries) + 1:03d}",
            original_text="",
            title="",
            status="pending",
            citation_key=f"ref{len(self._state.entries) + 1:03d}",
        )
        self._state.entries.append(entry)
        self._populate()
        self.table.selectRow(self.table.rowCount() - 1)

    def remove_entry(self) -> None:
        if self._state is None:
            return
        row = self.table.currentRow()
        if 0 <= row < len(self._state.entries):
            del self._state.entries[row]
            self._populate()

    def save_references(self) -> None:
        if self._imported is None:
            return
        try:
            state = self._collect()
        except Exception as exc:
            self.info_banner.set_state("error", "参考文献校验失败", str(exc))
            return
        self._state = state
        project = Path(self._imported.project_dir)
        content = project / "content"
        output = project / "output"
        content.mkdir(parents=True, exist_ok=True)
        output.mkdir(parents=True, exist_ok=True)
        (content / "references.json").write_text(state.to_json() + "\n", encoding="utf-8")
        (output / "refs.bib").write_text(generate_bib(state.entries) + "\n", encoding="utf-8")
        self.info_banner.set_state(
            "ok",
            "参考文献已保存",
            f"已生成 {len(state.entries)} 条 refs.bib；确认 {state.confirmed_count} 条。",
        )
        self.count_chip.setText(f"{len(state.entries)} 条 · 确认 {state.confirmed_count}")
        self.save_hint.setText("参考文献已保存")
        self.next_button.setEnabled(True)
        self._dirty = False
        self.references_saved.emit(state)
        self.status_message.emit("M5 · 参考文献已保存")

    def _cell(self, row: int, col: int) -> str:
        item = self.table.item(row, col)
        return item.text().strip() if item else ""