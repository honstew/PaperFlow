from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paperflow.core.document import Block, ImportResult
from paperflow.core.recent import RecentProject
from paperflow.ingest import import_document
from paperflow.ingest.importer import SUPPORTED_SUFFIXES
from paperflow.ui.widgets import (
    Banner,
    Card,
    Divider,
    KpiCard,
    make_button,
    make_chip,
)
from paperflow.ui.workers import FunctionThread

logger = logging.getLogger(__name__)

KIND_LABELS = {
    "title": "题名",
    "subtitle": "副题",
    "author": "作者",
    "affiliation": "单位",
    "abstract": "摘要",
    "keywords": "关键词",
    "heading": "标题",
    "paragraph": "正文",
    "list": "列表",
    "code": "代码",
    "figure": "图",
    "figure_caption": "图题",
    "table": "表格",
    "table_caption": "表题",
    "equation": "公式",
    "algorithm": "算法",
    "reference": "参考文献",
    "acknowledgement": "致谢",
    "appendix": "附录",
    "unknown": "其他",
}

ASSET_STATUS = {
    "ready": ("已关联", "#067647", "#ecfdf3", "#abefc6"),
    "pending": ("待补充", "#b54708", "#fffaeb", "#fedf89"),
    "missing": ("待上传", "#b54708", "#fffaeb", "#fedf89"),
    "remote": ("远程未下载", "#b54708", "#fffaeb", "#fedf89"),
    "unsupported": ("格式不支持", "#b42318", "#fef3f2", "#fecdca"),
    "unsupported_table": ("需手动处理", "#b42318", "#fef3f2", "#fecdca"),
}


class DropZone(QFrame):
    file_dropped = Signal(str)
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 19, 20, 18)
        layout.setSpacing(5)
        icon = QLabel("⇧")
        icon.setObjectName("DropIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedHeight(30)
        title = QLabel("把论文拖到这里，或点击选择文件")
        title.setObjectName("DropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("支持 TXT / Markdown · 单文件不超过 50 MB · 推荐 Markdown")
        hint.setObjectName("DropHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(hint)
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 5, 0, 0)
        button_row.addStretch(1)
        self.choose_button = make_button("选择文件", kind="primary")
        button_row.addWidget(self.choose_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        self.choose_button.clicked.connect(self.clicked.emit)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._has_supported_file(event):
            event.acceptProposedAction()
            self.setProperty("dragOver", "true")
            self._repolish()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.setProperty("dragOver", "false")
        self._repolish()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self.setProperty("dragOver", "false")
        self._repolish()
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in SUPPORTED_SUFFIXES:
                self.file_dropped.emit(str(path))
                event.acceptProposedAction()
                return
        event.ignore()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    @staticmethod
    def _has_supported_file(event: QDragEnterEvent) -> bool:
        return any(
            Path(url.toLocalFile()).suffix.lower() in SUPPORTED_SUFFIXES
            for url in event.mimeData().urls()
            if url.isLocalFile()
        )

    def _repolish(self) -> None:
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
        self.update()


class ImportPage(QWidget):
    import_completed = Signal(object)
    status_message = Signal(str)
    next_requested = Signal()
    recent_open_requested = Signal(str)

    def __init__(self, projects_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._projects_dir = projects_dir
        self._thread: FunctionThread | None = None
        self._busy = False
        self._last_result: ImportResult | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 24)
        layout.setSpacing(12)

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        title = QLabel("导入论文")
        title.setObjectName("PageTitle")
        sub = QLabel(
            "读取 TXT 或 Markdown，生成带稳定 ID 的内容块。图片和表格先建立占位，"
            "后续按语义定位并由你确认。"
        )
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        header.addWidget(title)
        header.addWidget(sub)
        layout.addLayout(header)

        self.drop_zone = DropZone()
        self.drop_zone.clicked.connect(self.choose_file)
        self.drop_zone.file_dropped.connect(self._start_import)
        layout.addWidget(self.drop_zone)

        note = QLabel(
            "不支持 DOCX/DOC/PDF。Word 文档请先另存为 Markdown 或纯文本；"
            "Markdown 能保留标题、表格和本地图片路径；TXT 建议用空行分段。"
        )
        note.setObjectName("Hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.recent_card = self._build_recent_card()
        self.recent_card.setVisible(False)
        layout.addWidget(self.recent_card)

        self.error_banner = Banner("导入失败", "", "error")
        self.error_banner.setVisible(False)
        layout.addWidget(self.error_banner)

        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedHeight(3)
        self.busy_bar.setVisible(False)
        layout.addWidget(self.busy_bar)

        self.result_card = self._build_result_card()
        self.result_card.setVisible(False)
        layout.addWidget(self.result_card)
        layout.addStretch(1)

    def _build_recent_card(self) -> Card:
        card = Card(
            "最近项目",
            "重新打开已保存的 M2–M5 项目；缺失文件会在打开时提示。",
        )
        self.recent_table = QTableWidget(0, 3)
        self.recent_table.setObjectName("RecentTable")
        self.recent_table.setHorizontalHeaderLabels(["论文", "更新时间", "项目路径"])
        self.recent_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.recent_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.recent_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.recent_table.setShowGrid(False)
        self.recent_table.setAlternatingRowColors(True)
        self.recent_table.verticalHeader().setVisible(False)
        header = self.recent_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.recent_table.setColumnWidth(1, 150)
        self.recent_table.setMaximumHeight(150)
        self.recent_table.itemDoubleClicked.connect(self._open_recent_item)
        card.body.addWidget(self.recent_table)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        self.open_recent_button = make_button("打开选中项目", kind="soft")
        self.open_recent_button.clicked.connect(self._open_selected_recent)
        actions.addWidget(self.open_recent_button)
        actions.addStretch(1)
        card.body.addLayout(actions)
        return card

    def set_recent(self, projects: list[RecentProject]) -> None:
        self.recent_table.setRowCount(len(projects))
        for row, project in enumerate(projects):
            title = project.title or project.source_name or Path(project.root).name
            updated = project.updated_at.replace("T", " ")[:16]
            values = [title, updated, project.root]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, project.root)
                self.recent_table.setItem(row, col, item)
            self.recent_table.setRowHeight(row, 27)
        self.recent_card.setVisible(bool(projects))
        if projects:
            self.recent_table.selectRow(0)

    def _open_selected_recent(self) -> None:
        row = self.recent_table.currentRow()
        if row >= 0:
            item = self.recent_table.item(row, 0)
            if item is not None:
                self.recent_open_requested.emit(item.data(Qt.ItemDataRole.UserRole) or "")

    def _open_recent_item(self, item: QTableWidgetItem) -> None:
        root = item.data(Qt.ItemDataRole.UserRole) if item.column() == 0 else None
        if root:
            self.recent_open_requested.emit(str(root))

    def _build_result_card(self) -> Card:
        self.result_chip = make_chip("解析完成", fg="#067647", bg="#ecfdf3", border="#abefc6")
        card = Card(
            "导入结果",
            "块 ID 用于后续结构识别、图表锚点和覆盖校验。",
            right_widget=self.result_chip,
        )
        body = card.body

        file_row = QHBoxLayout()
        file_row.setSpacing(10)
        self.file_icon = QLabel("TXT")
        self.file_icon.setObjectName("FileIcon")
        self.file_icon.setFixedSize(38, 38)
        self.file_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        file_row.addWidget(self.file_icon)
        file_text = QVBoxLayout()
        file_text.setContentsMargins(0, 0, 0, 0)
        file_text.setSpacing(1)
        self.file_name = QLabel("—")
        self.file_name.setObjectName("FileTitle")
        self.file_meta = QLabel("—")
        self.file_meta.setObjectName("FileMeta")
        self.file_meta.setWordWrap(True)
        file_text.addWidget(self.file_name)
        file_text.addWidget(self.file_meta)
        file_row.addLayout(file_text, 1)
        self.open_project_button = make_button("打开项目目录", kind="ghost")
        self.open_project_button.clicked.connect(self._open_project_dir)
        file_row.addWidget(self.open_project_button)
        body.addLayout(file_row)

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(8)
        self.kpi_blocks = KpiCard("内容块", "—", "#2563eb")
        self.kpi_headings = KpiCard("标题", "—", "#0f9f8f")
        self.kpi_figures = KpiCard("图片占位", "—", "#7a5af8")
        self.kpi_tables = KpiCard("表格", "—", "#b54708")
        for widget in (self.kpi_blocks, self.kpi_headings, self.kpi_figures, self.kpi_tables):
            kpi_row.addWidget(widget, 1)
        body.addLayout(kpi_row)

        self.warning_banner = Banner("解析完成", "", "ok")
        body.addWidget(self.warning_banner)
        warning_actions = QHBoxLayout()
        warning_actions.setContentsMargins(0, 0, 0, 0)
        self.warning_button = make_button("查看全部待处理项", kind="link")
        self.warning_button.clicked.connect(self._show_warnings)
        self.warning_button.setVisible(False)
        warning_actions.addWidget(self.warning_button)
        warning_actions.addStretch(1)
        body.addLayout(warning_actions)

        body.addWidget(Divider())
        preview_head = QHBoxLayout()
        preview_title = QLabel("内容块预览")
        preview_title.setObjectName("SubCardTitle")
        preview_head.addWidget(preview_title)
        preview_head.addStretch(1)
        self.preview_chip = make_chip("带稳定 ID", fg="#475467", bg="#f2f4f7", border="#e4e7ec")
        preview_head.addWidget(self.preview_chip)
        body.addLayout(preview_head)

        self.block_table = QTableWidget(0, 4)
        self.block_table.setObjectName("BlockTable")
        self.block_table.setHorizontalHeaderLabels(["ID", "类型", "文本", "行号"])
        self.block_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.block_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.block_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.block_table.setShowGrid(False)
        self.block_table.setAlternatingRowColors(True)
        self.block_table.verticalHeader().setVisible(False)
        self.block_table.horizontalHeader().setStretchLastSection(False)
        header = self.block_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.block_table.setColumnWidth(0, 72)
        self.block_table.setColumnWidth(1, 82)
        self.block_table.setColumnWidth(3, 58)
        self.block_table.setMinimumHeight(330)
        body.addWidget(self.block_table)

        assets_head = QHBoxLayout()
        assets_title = QLabel("图表占位")
        assets_title.setObjectName("SubCardTitle")
        assets_head.addWidget(assets_title)
        assets_head.addStretch(1)
        self.assets_chip = make_chip("0", fg="#475467", bg="#f2f4f7", border="#e4e7ec")
        assets_head.addWidget(self.assets_chip)
        body.addLayout(assets_head)

        self.asset_table = QTableWidget(0, 4)
        self.asset_table.setObjectName("AssetTable")
        self.asset_table.setHorizontalHeaderLabels(["类型", "编号", "题注 / 说明", "状态"])
        self.asset_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.asset_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.asset_table.setShowGrid(False)
        self.asset_table.setAlternatingRowColors(True)
        self.asset_table.verticalHeader().setVisible(False)
        asset_header = self.asset_table.horizontalHeader()
        asset_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        asset_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        asset_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        asset_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.asset_table.setColumnWidth(0, 64)
        self.asset_table.setColumnWidth(1, 64)
        self.asset_table.setColumnWidth(3, 92)
        self.asset_table.setMaximumHeight(170)
        body.addWidget(self.asset_table)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        self.reimport_button = make_button("重新选择文件", kind="ghost")
        self.reimport_button.clicked.connect(self.choose_file)
        self.next_button = make_button("下一步：结构校对", kind="primary")
        self.next_button.setEnabled(False)
        self.next_button.setToolTip("导入完成后可进入 M3")
        self.next_button.clicked.connect(self.next_requested.emit)
        actions.addWidget(self.reimport_button)
        actions.addStretch(1)
        actions.addWidget(self.next_button)
        body.addLayout(actions)
        return card

    # ------------------------------------------------------------------
    # File selection and import
    # ------------------------------------------------------------------
    def choose_file(self) -> None:
        if self._busy:
            return
        start = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择论文文件",
            start or str(Path.home()),
            "论文文本 (*.txt *.md *.markdown);;TXT (*.txt);;Markdown (*.md *.markdown)",
        )
        if path:
            self._start_import(path)

    def _start_import(self, path: str | Path) -> None:
        if self._busy:
            return
        source = Path(path)
        if source.suffix.lower() not in SUPPORTED_SUFFIXES:
            self._show_error("仅支持 .txt、.md、.markdown；不支持 DOCX/DOC/PDF。")
            return
        if not source.is_file():
            self._show_error("文件不存在或不可读。")
            return
        self._set_busy(True)
        self.error_banner.setVisible(False)
        self.status_message.emit(f"正在解析 {source.name} …")
        self._thread = FunctionThread(
            import_document,
            source,
            projects_dir=self._projects_dir,
            parent=self,
        )
        self._thread.result.connect(self._on_imported)
        self._thread.error.connect(self._on_import_failed)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_imported(self, result: ImportResult) -> None:
        self._last_result = result
        self._set_busy(False)
        self._populate(result)
        self.result_card.setVisible(True)
        self.next_button.setEnabled(True)
        self.next_button.setToolTip("进入 M3 结构校对")
        self.status_message.emit(
            f"导入完成 · {result.summary.block_count} 个内容块 · "
            f"{result.summary.figure_count} 图 · {result.summary.table_count} 表"
        )
        self.import_completed.emit(result)

    def _on_import_failed(self, message: str) -> None:
        self._set_busy(False)
        self._show_error(message or "解析失败，请检查文件编码或 Markdown 语法。")
        self.status_message.emit("导入失败")

    def _on_thread_finished(self) -> None:
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.deleteLater()
        self._set_busy(False)

    def _populate(self, result: ImportResult) -> None:
        document = result.document
        summary = result.summary
        self.file_icon.setText("MD" if document.format == "markdown" else "TXT")
        self.file_name.setText(document.source_name or "—")
        self.file_meta.setText(
            f"{summary.format} · {summary.encoding} · {summary.block_count} 块 · "
            f"{summary.heading_count} 个标题 · {summary.figure_count} 图 · "
            f"{summary.table_count} 表"
        )
        self.file_meta.setToolTip(result.project_dir)
        self.kpi_blocks.set_value(summary.block_count)
        self.kpi_headings.set_value(summary.heading_count)
        self.kpi_figures.set_value(summary.figure_count)
        self.kpi_tables.set_value(summary.table_count)

        if summary.warning_count:
            self.warning_banner.set_state(
                "warn",
                f"有 {summary.warning_count} 个待处理项",
                document.warnings[0].message
                if document.warnings
                else "请查看详情并确认。",
            )
            self.warning_button.setVisible(True)
            self._rechip(self.result_chip, "有警告", "#b54708", "#fffaeb", "#fedf89")
        else:
            self.warning_banner.set_state(
                "ok",
                "解析完成",
                "未发现结构性问题；图片和表格可在图表管理页继续补充。",
            )
            self.warning_button.setVisible(False)
            self._rechip(self.result_chip, "解析完成", "#067647", "#ecfdf3", "#abefc6")

        self._populate_blocks(document.blocks)
        self._populate_assets(result)

    def _populate_blocks(self, blocks: list[Block]) -> None:
        preview = blocks[:600]
        self.block_table.setRowCount(len(preview))
        for row, block in enumerate(preview):
            kind = KIND_LABELS.get(block.kind, block.kind)
            if block.heading_level:
                kind = f"{kind} H{block.heading_level}"
            text = block.text.replace("\n", " ").strip()
            display = text[:180] + ("…" if len(text) > 180 else "")
            values = [
                block.id,
                kind,
                display,
                f"{block.source.line_start}–{block.source.line_end}"
                if block.source.line_end != block.source.line_start
                else str(block.source.line_start),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col in {0, 1, 3}:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                    )
                item.setToolTip(text if col == 2 else value)
                self.block_table.setItem(row, col, item)
            self.block_table.setRowHeight(row, 26)
        if len(blocks) > len(preview):
            self.preview_chip.setText(f"显示前 {len(preview)} / {len(blocks)} 块")
        else:
            self.preview_chip.setText(f"{len(blocks)} 块 · 带稳定 ID")

    def _populate_assets(self, result: ImportResult) -> None:
        assets: list[tuple[str, str, str, str]] = []
        for figure in result.document.figures:
            text, *colors = ASSET_STATUS.get(
                figure.status, ("待处理", "#667085", "#f2f4f7", "#e4e7ec")
            )
            assets.append(("图", figure.label or figure.id, figure.caption or "—", text))
        for table in result.document.tables:
            text, *colors = ASSET_STATUS.get(
                table.status, ("待处理", "#667085", "#f2f4f7", "#e4e7ec")
            )
            assets.append(("表", table.label or table.id, table.caption or "—", text))
        self.asset_table.setRowCount(len(assets))
        self.assets_chip.setText(str(len(assets)))
        for row, (kind, label, caption, status) in enumerate(assets):
            for col, value in enumerate((kind, label, caption, status)):
                item = QTableWidgetItem(value)
                if col == 3:
                    item.setForeground(Qt.GlobalColor.darkYellow if "待" in value else Qt.GlobalColor.darkGreen)
                self.asset_table.setItem(row, col, item)
            self.asset_table.setRowHeight(row, 24)
        self.asset_table.setVisible(bool(assets))

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------
    def _show_error(self, message: str) -> None:
        self.error_banner.set_state("error", "导入失败", message)
        self.error_banner.setVisible(True)
        if self._last_result is None:
            self.result_card.setVisible(False)

    def _show_warnings(self) -> None:
        if self._last_result is None:
            return
        messages = [
            f"• {warning.message}" for warning in self._last_result.document.warnings
        ]
        if not messages:
            messages = ["没有待处理项。"]
        box = QMessageBox(self)
        box.setWindowTitle("待处理项")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("\n".join(messages))
        box.exec()

    def _open_project_dir(self) -> None:
        if self._last_result is None or not self._last_result.project_dir:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_result.project_dir))

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_bar.setVisible(busy)
        self.drop_zone.setEnabled(not busy)
        self.reimport_button.setEnabled(not busy)
        self.next_button.setEnabled(False)
        self.drop_zone.setCursor(
            Qt.CursorShape.ForbiddenCursor if busy else Qt.CursorShape.PointingHandCursor
        )

    def _rechip(self, label: QLabel, text: str, fg: str, bg: str, border: str) -> None:
        label.setText(text)
        label.setStyleSheet(
            f"color:{fg}; background:{bg}; border:1px solid {border}; "
            "border-radius:8px; padding:2px 7px; font-size:9px; font-weight:700;"
        )

    def shutdown(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            if not self._thread.wait(1500):
                self._thread.terminate()
                self._thread.wait(500)
        self._thread = None

    @property
    def last_result(self) -> ImportResult | None:
        return self._last_result