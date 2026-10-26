from __future__ import annotations

import csv
import io
import json
import logging
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paperflow.core.document import Figure, ImportResult, Table
from paperflow.core.metadata import M4State
from paperflow.core.structure import StructureResult
from paperflow.ui.widgets import Banner, Card, make_button

logger = logging.getLogger(__name__)

FIGURE_STATUS = {
    "ready": ("已关联", "#067647"),
    "missing": ("待上传", "#b54708"),
    "pending": ("待处理", "#b54708"),
    "remote": ("远程未下载", "#b54708"),
    "unsupported": ("格式不支持", "#b42318"),
}


class AssetsPage(QWidget):
    assets_saved = Signal(object)
    status_message = Signal(str)
    next_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._import_result: ImportResult | None = None
        self._structure: StructureResult | None = None
        self._state: M4State | None = None
        self._current_id: str | None = None
        self._loading = False
        self._dirty = False
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
        title = QLabel("图表管理")
        title.setObjectName("PageTitle")
        sub = QLabel(
            "上传或替换图片、编辑表格，并确认插入锚点。图片会复制到项目 assets/figures/。"
        )
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        header.addWidget(title)
        header.addWidget(sub)
        layout.addLayout(header)

        self.info_banner = Banner(
            "素材管理",
            "Markdown 已关联的图片可直接预览；TXT 中缺失的图片请在这里上传。",
            "info",
        )
        layout.addWidget(self.info_banner)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)
        body.setHandleWidth(10)
        body.addWidget(self._build_asset_list())
        body.addWidget(self._build_editor())
        body.setStretchFactor(1, 1)
        body.setSizes([260, 850])
        layout.addWidget(body, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 2, 0, 0)
        self.save_hint = QLabel("")
        self.save_hint.setObjectName("Hint")
        footer.addWidget(self.save_hint)
        footer.addStretch(1)
        self.save_button = make_button("保存图表设置", kind="primary")
        self.save_button.clicked.connect(self.save_assets)
        self.next_button = make_button("下一步：作者信息", kind="primary")
        self.next_button.setEnabled(False)
        self.next_button.setToolTip("保存图表设置后进入作者信息")
        self.next_button.clicked.connect(self.next_requested.emit)
        footer.addWidget(self.save_button)
        footer.addWidget(self.next_button)
        layout.addLayout(footer)

    def _build_asset_list(self) -> Card:
        card = Card("图表清单", "选择要编辑的图表。")
        self.asset_list = QListWidget()
        self.asset_list.setObjectName("AssetList")
        self.asset_list.setMinimumWidth(220)
        self.asset_list.currentItemChanged.connect(self._on_asset_changed)
        card.body.addWidget(self.asset_list)
        self.asset_count = QLabel("0 个")
        self.asset_count.setObjectName("Hint")
        card.body.addWidget(self.asset_count)
        return card

    def _build_editor(self) -> Card:
        card = Card("素材编辑", "图片和表格分别编辑；切换图表时会保留当前修改。")
        self.editor_stack = QStackedWidget()
        self.editor_stack.setObjectName("AssetEditorStack")
        self.editor_stack.setMinimumWidth(0)

        self.empty_editor = QLabel("尚未导入图表。")
        self.empty_editor.setObjectName("EmptyEditor")
        self.empty_editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.editor_stack.addWidget(self.empty_editor)
        self.editor_stack.addWidget(self._build_figure_editor())
        self.editor_stack.addWidget(self._build_table_editor())
        card.body.addWidget(self.editor_stack)
        return card

    def _build_figure_editor(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        top = QHBoxLayout()
        top.setSpacing(12)
        self.figure_preview = QLabel("暂无图片")
        self.figure_preview.setObjectName("FigurePreview")
        self.figure_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.figure_preview.setMinimumSize(260, 170)
        self.figure_preview.setMaximumHeight(230)
        top.addWidget(self.figure_preview, 1)

        actions = QVBoxLayout()
        actions.setSpacing(6)
        self.upload_button = make_button("上传 / 替换图片", kind="soft")
        self.upload_button.clicked.connect(self.upload_figure)
        self.remove_button = make_button("移除图片", kind="ghost")
        self.remove_button.clicked.connect(self.remove_figure)
        self.figure_status = QLabel("—")
        self.figure_status.setObjectName("Hint")
        actions.addWidget(self.upload_button)
        actions.addWidget(self.remove_button)
        actions.addWidget(self.figure_status)
        actions.addStretch(1)
        top.addLayout(actions)
        layout.addLayout(top)

        self.figure_caption = QLineEdit()
        self.figure_caption.setPlaceholderText("中文图题，例如：研究流程图")
        self.figure_caption.textChanged.connect(self._mark_dirty)
        self.figure_caption_en = QLineEdit()
        self.figure_caption_en.setPlaceholderText("英文图题（可选）")
        self.figure_caption_en.textChanged.connect(self._mark_dirty)
        self.figure_note = QLineEdit()
        self.figure_note.setPlaceholderText("图注 / 来源备注（可选）")
        self.figure_note.textChanged.connect(self._mark_dirty)
        for label, widget in (
            ("中文图题", self.figure_caption),
            ("英文图题", self.figure_caption_en),
            ("图注 / 来源", self.figure_note),
        ):
            layout.addWidget(self._field_label(label))
            layout.addWidget(widget)

        options = QHBoxLayout()
        options.setSpacing(12)
        width_box = QVBoxLayout()
        width_box.addWidget(self._field_label("宽度比例"))
        width_row = QHBoxLayout()
        self.width_slider = QSlider(Qt.Orientation.Horizontal)
        self.width_slider.setRange(25, 100)
        self.width_slider.setValue(80)
        self.width_slider.valueChanged.connect(self._mark_dirty)
        self.width_label = QLabel("80%")
        self.width_label.setObjectName("Hint")
        self.width_slider.valueChanged.connect(
            lambda value: self.width_label.setText(f"{value}%")
        )
        width_row.addWidget(self.width_slider, 1)
        width_row.addWidget(self.width_label)
        width_box.addLayout(width_row)
        options.addLayout(width_box, 1)
        self.span_check = QCheckBox("跨双栏")
        self.span_check.toggled.connect(self._mark_dirty)
        options.addWidget(self.span_check, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(options)

        layout.addWidget(self._field_label("插入锚点"))
        self.anchor_combo = QComboBox()
        self.anchor_combo.setObjectName("AnchorCombo")
        self._configure_anchor_combo(self.anchor_combo)
        self.anchor_combo.currentIndexChanged.connect(self._mark_dirty)
        layout.addWidget(self.anchor_combo)
        layout.addStretch(1)
        return page

    def _build_table_editor(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.table_caption = QLineEdit()
        self.table_caption.setPlaceholderText("中文表题")
        self.table_caption.textChanged.connect(self._mark_dirty)
        self.table_caption_en = QLineEdit()
        self.table_caption_en.setPlaceholderText("英文表题（可选）")
        self.table_caption_en.textChanged.connect(self._mark_dirty)
        self.table_note = QLineEdit()
        self.table_note.setPlaceholderText("表注 / 单位（可选）")
        self.table_note.textChanged.connect(self._mark_dirty)
        for label, widget in (
            ("中文表题", self.table_caption),
            ("英文表题", self.table_caption_en),
            ("表注 / 单位", self.table_note),
        ):
            layout.addWidget(self._field_label(label))
            layout.addWidget(widget)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        add_row = make_button("+ 行", kind="soft")
        add_row.clicked.connect(self.add_table_row)
        add_col = make_button("+ 列", kind="soft")
        add_col.clicked.connect(self.add_table_column)
        del_row = make_button("删除行", kind="ghost")
        del_row.clicked.connect(self.delete_table_row)
        del_col = make_button("删除列", kind="ghost")
        del_col.clicked.connect(self.delete_table_column)
        paste = make_button("粘贴 CSV / Excel", kind="ghost")
        paste.clicked.connect(self.paste_table)
        toolbar.addWidget(add_row)
        toolbar.addWidget(add_col)
        toolbar.addWidget(del_row)
        toolbar.addWidget(del_col)
        toolbar.addStretch(1)
        toolbar.addWidget(paste)
        layout.addLayout(toolbar)

        self.table_editor = QTableWidget(1, 2)
        self.table_editor.setObjectName("TableEditor")
        self.table_editor.setHorizontalHeaderLabels(["列 1", "列 2"])
        self.table_editor.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table_editor.verticalHeader().setVisible(True)
        self.table_editor.setMinimumHeight(260)
        self.table_editor.itemChanged.connect(self._mark_dirty)
        layout.addWidget(self.table_editor, 1)

        options = QHBoxLayout()
        self.table_span = QCheckBox("跨双栏")
        self.table_span.toggled.connect(self._mark_dirty)
        options.addWidget(self.table_span)
        options.addWidget(self._field_label("插入锚点"))
        self.table_anchor = QComboBox()
        self.table_anchor.setObjectName("AnchorCombo")
        self._configure_anchor_combo(self.table_anchor)
        self.table_anchor.currentIndexChanged.connect(self._mark_dirty)
        options.addWidget(self.table_anchor, 1)
        layout.addLayout(options)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------
    def set_context(
        self,
        imported: ImportResult,
        structure: StructureResult,
        state: M4State,
    ) -> None:
        self._import_result = imported
        self._structure = structure
        self._state = state
        self._current_id = None
        self._dirty = False
        self._populate_anchor_combo()
        self._populate_list()
        self.save_hint.setText("未保存")

    def _populate_list(self) -> None:
        self.asset_list.clear()
        if self._state is None:
            self.asset_count.setText("0 个")
            self.editor_stack.setCurrentWidget(self.empty_editor)
            return
        for figure in self._state.figures:
            item = QListWidgetItem(f"图 · {figure.label or figure.id}  {figure.caption[:24]}")
            item.setData(Qt.ItemDataRole.UserRole, ("figure", figure.id))
            self.asset_list.addItem(item)
        for table in self._state.tables:
            item = QListWidgetItem(f"表 · {table.label or table.id}  {table.caption[:24]}")
            item.setData(Qt.ItemDataRole.UserRole, ("table", table.id))
            self.asset_list.addItem(item)
        self.asset_count.setText(
            f"{len(self._state.figures)} 图 · {len(self._state.tables)} 表"
        )
        if self.asset_list.count():
            self.asset_list.setCurrentRow(0)
        else:
            self.editor_stack.setCurrentWidget(self.empty_editor)
        self.next_button.setEnabled(False)

    # ------------------------------------------------------------------
    # Selection and editors
    # ------------------------------------------------------------------
    def _on_asset_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None or self._loading:
            return
        self._commit_current()
        data = current.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, asset_id = data
        self._current_id = asset_id
        self._loading = True
        try:
            if kind == "figure":
                figure = self._find_figure(asset_id)
                if figure is not None:
                    self._load_figure(figure)
                    self.editor_stack.setCurrentIndex(1)
            else:
                table = self._find_table(asset_id)
                if table is not None:
                    self._load_table(table)
                    self.editor_stack.setCurrentIndex(2)
        finally:
            self._loading = False

    def _load_figure(self, figure: Figure) -> None:
        self.figure_caption.setText(figure.caption)
        self.figure_caption_en.setText(figure.caption_en)
        self.figure_note.setText(figure.note)
        self.width_slider.setValue(int(round(figure.width_ratio * 100)))
        self.span_check.setChecked(figure.span_columns)
        self._set_anchor(self.anchor_combo, figure.anchor_after_block)
        self._set_preview(figure)
        self._update_figure_status(figure)
        self.upload_button.setEnabled(True)

    def _load_table(self, table: Table) -> None:
        self.table_caption.setText(table.caption)
        self.table_caption_en.setText(table.caption_en)
        self.table_note.setText(table.note)
        self.table_span.setChecked(table.span_columns)
        self._set_anchor(self.table_anchor, table.anchor_after_block)
        rows = table.rows or [["", ""]]
        cols = max(len(row) for row in rows)
        self.table_editor.setRowCount(len(rows))
        self.table_editor.setColumnCount(max(1, cols))
        for row_index, row in enumerate(rows):
            for col_index in range(self.table_editor.columnCount()):
                value = row[col_index] if col_index < len(row) else ""
                self.table_editor.setItem(row_index, col_index, QTableWidgetItem(value))
        self._rename_table_headers()
        self.table_editor.resizeRowsToContents()

    def _commit_current(self) -> None:
        if self._loading or self._state is None or self._current_id is None:
            return
        if self.editor_stack.currentIndex() == 1:
            figure = self._find_figure(self._current_id)
            if figure is not None:
                figure.caption = self.figure_caption.text().strip()
                figure.caption_en = self.figure_caption_en.text().strip()
                figure.note = self.figure_note.text().strip()
                figure.width_ratio = self.width_slider.value() / 100.0
                figure.span_columns = self.span_check.isChecked()
                figure.anchor_after_block = self.anchor_combo.currentData()
        elif self.editor_stack.currentIndex() == 2:
            table = self._find_table(self._current_id)
            if table is not None:
                table.caption = self.table_caption.text().strip()
                table.caption_en = self.table_caption_en.text().strip()
                table.note = self.table_note.text().strip()
                table.span_columns = self.table_span.isChecked()
                table.anchor_after_block = self.table_anchor.currentData()
                table.rows = self._table_rows()
                table.status = "ready" if any(any(cell for cell in row) for row in table.rows) else "pending"
                table.warnings = [] if table.status == "ready" else ["表格数据待补充"]

    # ------------------------------------------------------------------
    # Figure actions
    # ------------------------------------------------------------------
    def upload_figure(self) -> None:
        if self._state is None or self._current_id is None:
            return
        figure = self._find_figure(self._current_id)
        if figure is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片",
            str(Path.home()),
            "图片 (*.png *.jpg *.jpeg)",
        )
        if not path:
            return
        source = Path(path)
        suffix = source.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg"}:
            self.info_banner.set_state("error", "图片格式不支持", "请选择 PNG / JPG / JPEG 图片。")
            return
        pixmap = QPixmap(str(source))
        if pixmap.isNull():
            self.info_banner.set_state("error", "图片无法读取", "文件可能已损坏或不是有效图片。")
            return
        project_dir = Path(self._import_result.project_dir) if self._import_result else None
        if project_dir is None:
            return
        target = project_dir / "assets" / "figures" / f"{figure.id.lower()}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
        except OSError as exc:
            self.info_banner.set_state("error", "复制失败", str(exc))
            return
        figure.path = str(target.relative_to(project_dir)).replace("\\", "/")
        figure.source_path = str(source)
        figure.status = "ready"
        figure.warnings = []
        self._set_preview(figure)
        self._update_figure_status(figure)
        self._mark_dirty()
        self._refresh_current_item()

    def remove_figure(self) -> None:
        if self._state is None or self._current_id is None:
            return
        figure = self._find_figure(self._current_id)
        if figure is None:
            return
        figure.path = ""
        figure.status = "missing"
        figure.warnings = ["尚未提供图片素材"]
        self._set_preview(figure)
        self._update_figure_status(figure)
        self._mark_dirty()
        self._refresh_current_item()

    def _set_preview(self, figure: Figure) -> None:
        project_dir = Path(self._import_result.project_dir) if self._import_result else None
        if not figure.path or project_dir is None:
            self.figure_preview.setText("暂无图片")
            self.figure_preview.setPixmap(QPixmap())
            return
        path = project_dir / figure.path
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.figure_preview.setText("图片无法预览")
            self.figure_preview.setPixmap(QPixmap())
            return
        self.figure_preview.setPixmap(
            pixmap.scaled(
                430,
                200,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _update_figure_status(self, figure: Figure) -> None:
        text, color = FIGURE_STATUS.get(figure.status, ("待处理", "#b54708"))
        self.figure_status.setText(f"状态：{text}")
        self.figure_status.setStyleSheet(f"color:{color};")

    # ------------------------------------------------------------------
    # Table actions
    # ------------------------------------------------------------------
    def add_table_row(self) -> None:
        self.table_editor.insertRow(self.table_editor.rowCount())
        for col in range(self.table_editor.columnCount()):
            self.table_editor.setItem(
                self.table_editor.rowCount() - 1, col, QTableWidgetItem("")
            )
        self._mark_dirty()

    def add_table_column(self) -> None:
        count = self.table_editor.columnCount()
        self.table_editor.insertColumn(count)
        for row in range(self.table_editor.rowCount()):
            self.table_editor.setItem(row, count, QTableWidgetItem(""))
        self._rename_table_headers()
        self._mark_dirty()

    def delete_table_row(self) -> None:
        row = self.table_editor.currentRow()
        if row >= 0 and self.table_editor.rowCount() > 1:
            self.table_editor.removeRow(row)
            self._mark_dirty()

    def delete_table_column(self) -> None:
        col = self.table_editor.currentColumn()
        if col >= 0 and self.table_editor.columnCount() > 1:
            self.table_editor.removeColumn(col)
            self._rename_table_headers()
            self._mark_dirty()

    def paste_table(self) -> None:
        text = QApplication.clipboard().text()
        if not text.strip():
            self.info_banner.set_state("warn", "剪贴板为空", "请先复制 CSV 或 Excel 单元格。")
            return
        delimiter = "\t" if "\t" in text else ","
        try:
            rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        except csv.Error as exc:
            self.info_banner.set_state("error", "粘贴失败", str(exc))
            return
        rows = [row for row in rows if any(cell.strip() for cell in row)]
        if not rows:
            return
        cols = max(len(row) for row in rows)
        self.table_editor.setRowCount(len(rows))
        self.table_editor.setColumnCount(cols)
        for row_index, row in enumerate(rows):
            for col_index in range(cols):
                value = row[col_index] if col_index < len(row) else ""
                self.table_editor.setItem(row_index, col_index, QTableWidgetItem(value))
        self._rename_table_headers()
        self._mark_dirty()

    def _rename_table_headers(self) -> None:
        self.table_editor.setHorizontalHeaderLabels(
            [f"列 {index + 1}" for index in range(self.table_editor.columnCount())]
        )

    def _table_rows(self) -> list[list[str]]:
        rows: list[list[str]] = []
        for row in range(self.table_editor.rowCount()):
            values: list[str] = []
            for col in range(self.table_editor.columnCount()):
                item = self.table_editor.item(row, col)
                values.append(item.text().strip() if item else "")
            rows.append(values)
        return rows

    # ------------------------------------------------------------------
    # Anchors and save
    # ------------------------------------------------------------------
    def _populate_anchor_combo(self) -> None:
        self.anchor_combo.clear()
        self.table_anchor.clear()
        self.anchor_combo.addItem("不指定", None)
        self.table_anchor.addItem("不指定", None)
        if self._structure is None:
            return
        for block in self._structure.document.blocks:
            text = block.text.replace("\n", " ").strip()
            label = f"{block.id} · {text[:42]}"
            self.anchor_combo.addItem(label, block.id)
            self.table_anchor.addItem(label, block.id)

    def _set_anchor(self, combo: QComboBox, block_id: str | None) -> None:
        index = combo.findData(block_id)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def save_assets(self) -> None:
        if self._state is None or self._import_result is None:
            return
        self._commit_current()
        content = Path(self._import_result.project_dir) / "content"
        content.mkdir(parents=True, exist_ok=True)
        payload = {
            "figures": [item.model_dump() for item in self._state.figures],
            "tables": [item.model_dump() for item in self._state.tables],
        }
        (content / "assets.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._dirty = False
        self.save_hint.setText("图表设置已保存")
        self.next_button.setEnabled(True)
        self.info_banner.set_state(
            "ok",
            "图表设置已保存",
            f"{len(self._state.figures)} 图 · {len(self._state.tables)} 表；已写入 content/assets.json。",
        )
        self.assets_saved.emit(self._state)
        self.status_message.emit("M4 · 图表设置已保存")

    def _mark_dirty(self, *_args, silent: bool = False) -> None:
        if self._loading:
            return
        self._dirty = True
        if not silent:
            self.save_hint.setText("有未保存修改")
        self.next_button.setEnabled(False)

    def _refresh_current_item(self) -> None:
        item = self.asset_list.currentItem()
        if item is None or self._state is None or self._current_id is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, asset_id = data
        if kind == "figure":
            figure = self._find_figure(asset_id)
            if figure is not None:
                item.setText(f"图 · {figure.label or figure.id}  {figure.caption[:24]}")
        else:
            table = self._find_table(asset_id)
            if table is not None:
                item.setText(f"表 · {table.label or table.id}  {table.caption[:24]}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _find_figure(self, figure_id: str) -> Figure | None:
        if self._state is None:
            return None
        return next((item for item in self._state.figures if item.id == figure_id), None)

    def _find_table(self, table_id: str) -> Table | None:
        if self._state is None:
            return None
        return next((item for item in self._state.tables if item.id == table_id), None)

    @staticmethod
    def _configure_anchor_combo(combo: QComboBox) -> None:
        combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        combo.setMinimumContentsLength(18)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    @property
    def state(self) -> M4State | None:
        return self._state