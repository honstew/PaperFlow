from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from paperflow import __version__
from paperflow.core.api import ConnectionResult
from paperflow.core.config import AppSettings, SettingsStore
from paperflow.core.document import ImportResult
from paperflow.core.env import EnvReport
from paperflow.core.fixes import RenderOverrides
from paperflow.core.layout import LayoutSettings
from paperflow.core.metadata import M4State, build_m4_state
from paperflow.core.project import ProjectLoadError, load_project
from paperflow.core.recent import RecentProjectsStore
from paperflow.core.references import ReferenceState, parse_references
from paperflow.core.secrets import SecretStore
from paperflow.core.structure import StructureResult
from paperflow.ui.assets_page import AssetsPage
from paperflow.ui.build_page import BuildPage
from paperflow.ui.import_page import ImportPage
from paperflow.ui.layout_page import LayoutPage
from paperflow.ui.metadata_page import MetadataPage
from paperflow.ui.references_page import ReferencesPage
from paperflow.ui.setup_page import SetupPage
from paperflow.ui.structure_page import StructurePage
from paperflow.ui.widgets import NavStep, make_button, make_chip

logger = logging.getLogger(__name__)

NAV_ITEMS = (
    ("setup", 1, "环境与 API", "连接与编译环境", True),
    ("import", 2, "导入论文", "TXT / Markdown", True),
    ("structure", 3, "结构校对", "AI 识别与人工确认", False),
    ("assets", 4, "图表管理", "图片、表格与锚点", False),
    ("metadata", 5, "作者信息", "单位、简介、基金", False),
    ("references", 6, "参考文献", "结构、逐条确认", False),
    ("layout", 7, "版式设置", "模板、单双栏、参数", False),
    ("build", 8, "生成导出", "TEX / PDF / ZIP", False),
)


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: AppSettings,
        settings_store: SettingsStore,
        secret_store: SecretStore,
        *,
        log_dir: Path,
        projects_dir: Path,
        auto_detect: bool = True,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._settings_store = settings_store
        self._secret_store = secret_store
        self._log_dir = log_dir
        self._projects_dir = projects_dir
        self._recent_store = RecentProjectsStore(projects_dir.parent / "recent-projects.json")
        self._last_import: ImportResult | None = None
        self._last_structure: StructureResult | None = None
        self._m4_state: M4State | None = None
        self._m4_saved = False
        self._references: ReferenceState | None = None
        self._layout: LayoutSettings | None = None
        self._overrides = RenderOverrides()
        self._check_states = {"api": False, "tex": False, "refs": False, "key": False}
        self._default_status = "M1 · 环境配置"
        self._status_reset_timer = QTimer(self)
        self._status_reset_timer.setSingleShot(True)
        self._status_reset_timer.timeout.connect(self._reset_status)

        self.setWindowTitle("PaperFlow · 智能论文排版")
        self.setWindowIcon(make_app_icon())
        self.resize(1460, 960)
        self.setMinimumSize(1280, 800)
        self._build_ui(auto_detect=auto_detect)
        self._update_key_check()
        self._update_completion()
        logger.info("Main window created")

    # ------------------------------------------------------------------
    # Shell construction
    # ------------------------------------------------------------------
    def _build_ui(self, *, auto_detect: bool) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())

        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self._build_topbar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.setup_page = SetupPage(
            self._settings,
            self._settings_store,
            self._secret_store,
            auto_detect=auto_detect,
        )
        self.setup_page.connection_result.connect(self._on_connection)
        self.setup_page.env_report_ready.connect(self._on_env_report)
        self.setup_page.settings_saved.connect(self._on_settings_saved)
        self.setup_page.status_message.connect(self._set_status)
        self.setup_page.scroll_to_install.connect(self._scroll_to_install)
        self.setup_scroll = self._wrap_scroll(self.setup_page)

        self.import_page = ImportPage(self._projects_dir)
        self.import_page.import_completed.connect(self._on_import_completed)
        self.import_page.status_message.connect(self._set_status)
        self.import_page.next_requested.connect(lambda: self._on_nav_clicked("structure"))
        self.import_page.recent_open_requested.connect(self._open_project)
        self.import_scroll = self._wrap_scroll(self.import_page)
        self.import_page.set_recent(self._recent_store.prune_missing())

        self.structure_page = StructurePage(
            lambda: self.setup_page.current_settings(),
            self.setup_page.current_api_key,
        )
        self.structure_page.structure_ready.connect(self._on_structure_ready)
        self.structure_page.status_message.connect(self._set_status)
        self.structure_page.next_requested.connect(lambda: self._on_nav_clicked("assets"))
        self.structure_scroll = self._wrap_scroll(self.structure_page)

        self.assets_page = AssetsPage()
        self.assets_page.assets_saved.connect(self._on_assets_saved)
        self.assets_page.status_message.connect(self._set_status)
        self.assets_page.next_requested.connect(lambda: self._on_nav_clicked("metadata"))
        self.assets_scroll = self._wrap_scroll(self.assets_page)

        self.metadata_page = MetadataPage()
        self.metadata_page.metadata_saved.connect(self._on_metadata_saved)
        self.metadata_page.status_message.connect(self._set_status)
        self.metadata_page.next_requested.connect(
            lambda: self._on_nav_clicked("references")
        )
        self.metadata_scroll = self._wrap_scroll(self.metadata_page)

        self.references_page = ReferencesPage()
        self.references_page.references_saved.connect(self._on_references_saved)
        self.references_page.status_message.connect(self._set_status)
        self.references_page.next_requested.connect(lambda: self._on_nav_clicked("layout"))
        self.references_scroll = self._wrap_scroll(self.references_page)

        self.layout_page = LayoutPage()
        self.layout_page.layout_saved.connect(self._on_layout_saved)
        self.layout_page.status_message.connect(self._set_status)
        self.layout_page.next_requested.connect(lambda: self._on_nav_clicked("build"))
        self.layout_scroll = self._wrap_scroll(self.layout_page)

        self.build_page = BuildPage()
        self.build_page.status_message.connect(self._set_status)
        self.build_page.compiled.connect(self._on_build_compiled)
        self.build_page.overrides_changed.connect(self._on_overrides_changed)
        self.build_scroll = self._wrap_scroll(self.build_page)

        for page in (self.references_page, self.build_page):
            page.set_ai_context(self._settings, self._api_key_text)
        self.setup_page.api_key_edit.textChanged.connect(self._refresh_ai_actions)

        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("PageStack")
        self.page_stack.addWidget(self.setup_scroll)
        self.page_stack.addWidget(self.import_scroll)
        self.page_stack.addWidget(self.structure_scroll)
        self.page_stack.addWidget(self.assets_scroll)
        self.page_stack.addWidget(self.metadata_scroll)
        self.page_stack.addWidget(self.references_scroll)
        self.page_stack.addWidget(self.layout_scroll)
        self.page_stack.addWidget(self.build_scroll)
        body.addWidget(self.page_stack, 1)
        self.right_stack = self._build_right_stack()
        body.addWidget(self.right_stack)
        main_layout.addLayout(body, 1)
        main_layout.addWidget(self._build_statusbar())
        layout.addWidget(main, 1)
        self._show_page("setup")

    def _wrap_scroll(self, widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("ContentScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(widget)
        return scroll

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(264)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(12)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        mark = QLabel("P")
        mark.setObjectName("BrandMark")
        mark.setFixedSize(38, 38)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.addWidget(mark)
        brand_text = QVBoxLayout()
        brand_text.setContentsMargins(0, 0, 0, 0)
        brand_text.setSpacing(1)
        name = QLabel("PaperFlow")
        name.setObjectName("BrandName")
        sub = QLabel("INTELLIGENT TYPESET")
        sub.setObjectName("BrandSub")
        brand_text.addWidget(name)
        brand_text.addWidget(sub)
        brand.addLayout(brand_text, 1)
        brand_widget = QWidget()
        brand_widget.setLayout(brand)
        layout.addWidget(brand_widget)

        project = QFrame()
        project.setObjectName("ProjectPill")
        project_layout = QHBoxLayout(project)
        project_layout.setContentsMargins(10, 9, 10, 9)
        project_layout.setSpacing(8)
        self.project_icon = QLabel("M1")
        self.project_icon.setObjectName("ProjectIcon")
        self.project_icon.setFixedSize(30, 30)
        self.project_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        project_layout.addWidget(self.project_icon)
        project_text = QVBoxLayout()
        project_text.setContentsMargins(0, 0, 0, 0)
        project_text.setSpacing(0)
        self.project_name = QLabel("环境与 API")
        self.project_name.setObjectName("ProjectName")
        self.project_name.setMaximumWidth(160)
        self.project_name.setWordWrap(False)
        self.project_meta = QLabel("尚未创建论文项目")
        self.project_meta.setObjectName("ProjectMeta")
        project_text.addWidget(self.project_name)
        project_text.addWidget(self.project_meta)
        project_layout.addLayout(project_text, 1)
        layout.addWidget(project)

        nav = QVBoxLayout()
        nav.setContentsMargins(0, 2, 0, 0)
        nav.setSpacing(3)
        self.nav_steps: dict[str, NavStep] = {}
        for key, number, title, hint, available in NAV_ITEMS:
            step = NavStep(key, number, title, hint, available=available)
            step.clicked.connect(self._on_nav_clicked)
            if not available:
                step.setToolTip("M3 起逐步开放")
            self.nav_steps[key] = step
            nav.addWidget(step)
        self.nav_steps["setup"].set_active(True)
        self.nav_steps["import"].setToolTip("M2：TXT / Markdown 导入")
        layout.addLayout(nav)
        layout.addStretch(1)

        footer = QFrame()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(2, 10, 2, 0)
        footer_layout.setSpacing(4)
        local = QLabel("●  本地处理，不上传项目")
        local.setObjectName("SideFooterStrong")
        note = QLabel("只有你点击“识别结构”时，正文才会发送至你配置的 API。")
        note.setObjectName("SideFooter")
        note.setWordWrap(True)
        version = QLabel(f"v{__version__}  ·  M6 / Windows")
        version.setObjectName("SideFooter")
        footer_layout.addWidget(local)
        footer_layout.addWidget(note)
        footer_layout.addWidget(version)
        layout.addWidget(footer)
        return sidebar

    def _build_topbar(self) -> QFrame:
        top = QFrame()
        top.setObjectName("TopBar")
        top.setFixedHeight(66)
        layout = QHBoxLayout(top)
        layout.setContentsMargins(24, 7, 24, 7)
        layout.setSpacing(12)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        self.crumb = QLabel("PaperFlow   /   M1 环境配置")
        self.crumb.setObjectName("Crumb")
        self.top_title = QLabel("环境与 API")
        self.top_title.setObjectName("TopTitle")
        self.top_sub = QLabel("配置接口与编译环境，完成后进入论文导入")
        self.top_sub.setObjectName("TopSub")
        text.addWidget(self.crumb)
        text.addWidget(self.top_title)
        text.addWidget(self.top_sub)
        layout.addLayout(text, 1)

        saved = QFrame()
        saved.setObjectName("SavePill")
        saved_layout = QHBoxLayout(saved)
        saved_layout.setContentsMargins(8, 3, 9, 3)
        saved_layout.setSpacing(4)
        saved_dot = QLabel("●")
        saved_dot.setObjectName("SaveDot")
        self.saved_text = QLabel("本地配置")
        self.saved_text.setObjectName("SaveText")
        saved_layout.addWidget(saved_dot)
        saved_layout.addWidget(self.saved_text)
        layout.addWidget(saved, 0, Qt.AlignmentFlag.AlignVCenter)

        self.mode_chip = make_chip("M1 预览版")
        layout.addWidget(self.mode_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        logs = make_button("打开日志", kind="ghost")
        logs.clicked.connect(self._open_log_dir)
        layout.addWidget(logs, 0, Qt.AlignmentFlag.AlignVCenter)
        return top

    def _build_right_stack(self) -> QStackedWidget:
        stack = QStackedWidget()
        stack.setObjectName("RightStack")
        stack.setFixedWidth(350)
        stack.addWidget(self._build_m1_right_panel())
        stack.addWidget(self._build_m2_right_panel())
        stack.addWidget(self._build_m3_right_panel())
        stack.addWidget(self._build_m4_right_panel())
        stack.addWidget(self._build_m5_right_panel())
        return stack

    def _build_m1_right_panel(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("RightPanel")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 18, 20, 18)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel("M1 验收")
        title.setObjectName("RightTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.completion_chip = make_chip("0 / 4", fg="#667085", bg="#f2f4f7", border="#e4e7ec")
        head.addWidget(self.completion_chip)
        layout.addLayout(head)
        subtitle = QLabel("四项完成后，M1 即可验收并进入 M2。")
        subtitle.setObjectName("RightText")
        layout.addWidget(subtitle)

        check_card = QFrame()
        check_card.setObjectName("RightCard")
        check_layout = QVBoxLayout(check_card)
        check_layout.setContentsMargins(14, 12, 14, 13)
        check_layout.setSpacing(7)
        self.check_labels: dict[str, QLabel] = {}
        for key, text in (
            ("api", "API 可连接"),
            ("tex", "XeLaTeX 可编译"),
            ("refs", "biber 可用"),
            ("key", "API Key 安全存储"),
        ):
            label = QLabel("○  " + text)
            label.setObjectName("CheckItem")
            label.setStyleSheet("color:#667085;")
            self.check_labels[key] = label
            check_layout.addWidget(label)
        layout.addWidget(check_card)

        next_title = QLabel("后续流程")
        next_title.setObjectName("RightTitle")
        layout.addWidget(next_title)
        next_card = QFrame()
        next_card.setObjectName("RightCard")
        next_layout = QVBoxLayout(next_card)
        next_layout.setContentsMargins(14, 11, 14, 12)
        next_layout.setSpacing(6)
        for text in (
            "M2   导入论文与内容块",
            "M3   AI 结构识别与校对",
            "M4   图表、作者与基金",
            "M5   参考文献、模板与编译",
            "M6   打包、测试与验收",
        ):
            item = QLabel(text)
            item.setObjectName("RightText")
            next_layout.addWidget(item)
        layout.addWidget(next_card)

        local_title = QLabel("本地处理")
        local_title.setObjectName("RightTitle")
        layout.addWidget(local_title)
        local_card = QFrame()
        local_card.setObjectName("RightCard")
        local_layout = QVBoxLayout(local_card)
        local_layout.setContentsMargins(14, 11, 14, 12)
        local_layout.setSpacing(5)
        local_text = QLabel(
            "项目内容保存在本机。只有你点击“识别结构”时，正文才会发送至你配置的 API 服务。"
        )
        local_text.setObjectName("RightText")
        local_text.setWordWrap(True)
        local_layout.addWidget(local_text)
        layout.addWidget(local_card)
        layout.addStretch(1)
        return wrapper

    def _build_m2_right_panel(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("RightPanel")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 18, 20, 18)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel("M2 导入")
        title.setObjectName("RightTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.m2_chip = make_chip("未导入", fg="#667085", bg="#f2f4f7", border="#e4e7ec")
        head.addWidget(self.m2_chip)
        layout.addLayout(head)
        subtitle = QLabel("TXT / Markdown 解析为带稳定 ID 的内容块。")
        subtitle.setObjectName("RightText")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        summary_card = QFrame()
        summary_card.setObjectName("RightCard")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(14, 12, 14, 13)
        summary_layout.setSpacing(7)
        self.m2_values: dict[str, QLabel] = {}
        for key, text in (
            ("blocks", "内容块"),
            ("headings", "标题"),
            ("figures", "图片占位"),
            ("tables", "表格"),
            ("warnings", "待处理项"),
        ):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            label = QLabel(text)
            label.setObjectName("CheckItem")
            value = QLabel("—")
            value.setObjectName("RightValue")
            value.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            row.addWidget(label)
            row.addStretch(1)
            row.addWidget(value)
            self.m2_values[key] = value
            summary_layout.addLayout(row)
        layout.addWidget(summary_card)

        next_title = QLabel("下一步")
        next_title.setObjectName("RightTitle")
        layout.addWidget(next_title)
        next_card = QFrame()
        next_card.setObjectName("RightCard")
        next_layout = QVBoxLayout(next_card)
        next_layout.setContentsMargins(14, 11, 14, 12)
        next_layout.setSpacing(6)
        for text in (
            "M3   结构识别与校对",
            "M4   图片上传、表格编辑",
            "M4   作者、单位与基金",
            "M5   参考文献、模板与编译",
        ):
            item = QLabel(text)
            item.setObjectName("RightText")
            next_layout.addWidget(item)
        layout.addWidget(next_card)

        local_card = QFrame()
        local_card.setObjectName("RightCard")
        local_layout = QVBoxLayout(local_card)
        local_layout.setContentsMargins(14, 11, 14, 12)
        local_layout.setSpacing(5)
        local_text = QLabel(
            "解析在本机完成。M3 只有你点击“识别结构”时，正文才会发送至你配置的 API。"
        )
        local_text.setObjectName("RightText")
        local_text.setWordWrap(True)
        local_layout.addWidget(local_text)
        layout.addWidget(local_card)
        layout.addStretch(1)
        return wrapper

    def _build_m3_right_panel(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("RightPanel")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 18, 20, 18)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel("M3 校对")
        title.setObjectName("RightTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.m3_chip = make_chip("待识别", fg="#667085", bg="#f2f4f7", border="#e4e7ec")
        head.addWidget(self.m3_chip)
        layout.addLayout(head)
        subtitle = QLabel("AI 只分配角色和章节层级，不改写正文。")
        subtitle.setObjectName("RightText")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        summary_card = QFrame()
        summary_card.setObjectName("RightCard")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(14, 12, 14, 13)
        summary_layout.setSpacing(7)
        self.m3_values: dict[str, QLabel] = {}
        for key, text in (
            ("sections", "章节"),
            ("headings", "标题块"),
            ("references", "参考文献"),
            ("issues", "待确认"),
        ):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            label = QLabel(text)
            label.setObjectName("CheckItem")
            value = QLabel("—")
            value.setObjectName("RightValue")
            value.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            row.addWidget(label)
            row.addStretch(1)
            row.addWidget(value)
            self.m3_values[key] = value
            summary_layout.addLayout(row)
        layout.addWidget(summary_card)

        next_title = QLabel("下一步")
        next_title.setObjectName("RightTitle")
        layout.addWidget(next_title)
        next_card = QFrame()
        next_card.setObjectName("RightCard")
        next_layout = QVBoxLayout(next_card)
        next_layout.setContentsMargins(14, 11, 14, 12)
        next_layout.setSpacing(6)
        for text in (
            "M4   图片上传、表格编辑",
            "M4   作者、单位与基金",
            "M5   参考文献、模板与编译",
        ):
            item = QLabel(text)
            item.setObjectName("RightText")
            next_layout.addWidget(item)
        layout.addWidget(next_card)

        local_card = QFrame()
        local_card.setObjectName("RightCard")
        local_layout = QVBoxLayout(local_card)
        local_layout.setContentsMargins(14, 11, 14, 12)
        local_layout.setSpacing(5)
        local_text = QLabel(
            "本地规则不联网；AI 识别会把内容块发送到当前配置的 API。"
        )
        local_text.setObjectName("RightText")
        local_text.setWordWrap(True)
        local_layout.addWidget(local_text)
        layout.addWidget(local_card)
        layout.addStretch(1)
        return wrapper

    def _build_m4_right_panel(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("RightPanel")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 18, 20, 18)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel("M4 素材与作者")
        title.setObjectName("RightTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.m4_chip = make_chip("待编辑", fg="#667085", bg="#f2f4f7", border="#e4e7ec")
        head.addWidget(self.m4_chip)
        layout.addLayout(head)
        subtitle = QLabel("图片、表格、作者与基金；正文冲突在这里确认。")
        subtitle.setObjectName("RightText")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        summary_card = QFrame()
        summary_card.setObjectName("RightCard")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(14, 12, 14, 13)
        summary_layout.setSpacing(7)
        self.m4_values: dict[str, QLabel] = {}
        for key, text in (
            ("figures", "图片就绪"),
            ("tables", "表格"),
            ("authors", "作者"),
            ("funds", "基金"),
            ("conflicts", "冲突"),
        ):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            label = QLabel(text)
            label.setObjectName("CheckItem")
            value = QLabel("—")
            value.setObjectName("RightValue")
            value.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            row.addWidget(label)
            row.addStretch(1)
            row.addWidget(value)
            self.m4_values[key] = value
            summary_layout.addLayout(row)
        layout.addWidget(summary_card)

        next_title = QLabel("下一步")
        next_title.setObjectName("RightTitle")
        layout.addWidget(next_title)
        next_card = QFrame()
        next_card.setObjectName("RightCard")
        next_layout = QVBoxLayout(next_card)
        next_layout.setContentsMargins(14, 11, 14, 12)
        next_layout.setSpacing(6)
        for text in (
            "M5   参考文献逐条确认",
            "M5   模板、编译与 PDF",
            "M6   打包与验收",
        ):
            item = QLabel(text)
            item.setObjectName("RightText")
            next_layout.addWidget(item)
        layout.addWidget(next_card)

        local_card = QFrame()
        local_card.setObjectName("RightCard")
        local_layout = QVBoxLayout(local_card)
        local_layout.setContentsMargins(14, 11, 14, 12)
        local_layout.setSpacing(5)
        local_text = QLabel(
            "图片会复制到项目 assets/figures/；正文中已吸收的作者、单位、基金块不会重复输出。"
        )
        local_text.setObjectName("RightText")
        local_text.setWordWrap(True)
        local_layout.addWidget(local_text)
        layout.addWidget(local_card)
        layout.addStretch(1)
        return wrapper

    def _build_m5_right_panel(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("RightPanel")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 18, 20, 18)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel("M5 编译")
        title.setObjectName("RightTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.m5_chip = make_chip("待生成", fg="#667085", bg="#f2f4f7", border="#e4e7ec")
        head.addWidget(self.m5_chip)
        layout.addLayout(head)
        subtitle = QLabel("模板渲染 + XeLaTeX + biber；AI 不直接生成最终 .tex。")
        subtitle.setObjectName("RightText")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        summary_card = QFrame()
        summary_card.setObjectName("RightCard")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(14, 12, 14, 13)
        summary_layout.setSpacing(7)
        self.m5_values: dict[str, QLabel] = {}
        for key, text in (
            ("references", "参考文献"),
            ("columns", "栏数"),
            ("pdf", "PDF"),
        ):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            label = QLabel(text)
            label.setObjectName("CheckItem")
            value = QLabel("—")
            value.setObjectName("RightValue")
            value.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            row.addWidget(label)
            row.addStretch(1)
            row.addWidget(value)
            self.m5_values[key] = value
            summary_layout.addLayout(row)
        layout.addWidget(summary_card)

        self.m5_next_title = QLabel("下一步")
        self.m5_next_title.setObjectName("RightTitle")
        layout.addWidget(self.m5_next_title)
        self.m5_next_card = QFrame()
        self.m5_next_card.setObjectName("RightCard")
        next_card = self.m5_next_card
        next_layout = QVBoxLayout(next_card)
        next_layout.setContentsMargins(14, 11, 14, 12)
        next_layout.setSpacing(6)
        for text in (
            "M6   打包与安装包",
            "M6   干净机验收",
            "M6   示例项目与文档",
        ):
            item = QLabel(text)
            item.setObjectName("RightText")
            next_layout.addWidget(item)
        layout.addWidget(next_card)

        local_card = QFrame()
        local_card.setObjectName("RightCard")
        local_layout = QVBoxLayout(local_card)
        local_layout.setContentsMargins(14, 11, 14, 12)
        local_layout.setSpacing(5)
        local_text = QLabel(
            "编译在本机进行；不会把生成的 LaTeX 或 PDF 发送到 API。"
        )
        local_text.setObjectName("RightText")
        local_text.setWordWrap(True)
        local_layout.addWidget(local_text)
        layout.addWidget(local_card)
        layout.addStretch(1)
        return wrapper

    def _build_statusbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(34)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(14)
        self.status_msg = QLabel("M1 · 环境配置")
        self.status_msg.setObjectName("StatusBarText")
        layout.addWidget(self.status_msg)
        self.status_api = QLabel("●  API 未测试")
        self.status_api.setObjectName("StatusBarWarn")
        layout.addWidget(self.status_api)
        self.status_tex = QLabel("●  TeX 未检测")
        self.status_tex.setObjectName("StatusBarWarn")
        layout.addWidget(self.status_tex)
        self.status_doc = QLabel("●  文档未导入")
        self.status_doc.setObjectName("StatusBarText")
        layout.addWidget(self.status_doc)
        self.status_structure = QLabel("●  结构未识别")
        self.status_structure.setObjectName("StatusBarText")
        layout.addWidget(self.status_structure)
        layout.addStretch(1)
        self.status_key = QLabel("Key 未配置")
        self.status_key.setObjectName("StatusBarText")
        layout.addWidget(self.status_key)
        version = QLabel(f"v{__version__}  ·  M6")
        version.setObjectName("StatusBarText")
        layout.addWidget(version)
        return bar

    # ------------------------------------------------------------------
    # Signals and state
    # ------------------------------------------------------------------
    def _on_nav_clicked(self, key: str) -> None:
        if key in {
            "setup",
            "import",
            "structure",
            "assets",
            "metadata",
            "references",
            "layout",
            "build",
        }:
            self._show_page(key)
            return
        self._set_status("该步骤将在后续里程碑开放")

    def _show_page(self, key: str) -> None:
        if key == "setup":
            self.page_stack.setCurrentWidget(self.setup_scroll)
            self.right_stack.setCurrentIndex(0)
            self.crumb.setText("PaperFlow   /   M1 环境配置")
            self.top_title.setText("环境与 API")
            self.top_sub.setText("配置接口与编译环境，完成后进入论文导入")
            self._rechip(self.mode_chip, "M1 预览版", "#2563eb", "#eff4ff", "#dbe7ff")
            self._default_status = "M1 · 环境配置"
            if self._last_import is None:
                self.project_icon.setText("M1")
                self.project_name.setText("环境与 API")
                self.project_meta.setText("尚未创建论文项目")
            else:
                self._update_project_pill(self._last_import)
            self.setup_scroll.verticalScrollBar().setValue(0)
        elif key == "import":
            self.page_stack.setCurrentWidget(self.import_scroll)
            self.right_stack.setCurrentIndex(1)
            self.crumb.setText("PaperFlow   /   M2 导入论文")
            self.top_title.setText("导入论文")
            self.top_sub.setText("读取 TXT / Markdown，检查内容块、图片占位和表格")
            self._rechip(self.mode_chip, "M2 预览版", "#0f9f8f", "#effcf9", "#b7ebe2")
            self._default_status = "M2 · 导入论文"
            if self._last_import is None:
                self.project_icon.setText("M2")
                self.project_name.setText("导入论文")
                self.project_meta.setText("等待选择 TXT / Markdown")
            else:
                self._update_project_pill(self._last_import)
            self.import_scroll.verticalScrollBar().setValue(0)
        elif key == "structure":
            self.page_stack.setCurrentWidget(self.structure_scroll)
            self.right_stack.setCurrentIndex(2)
            self.crumb.setText("PaperFlow   /   M3 结构校对")
            self.top_title.setText("结构校对")
            self.top_sub.setText("AI 识别标题、摘要、章节与参考文献，人工确认后保存")
            self._rechip(self.mode_chip, "M3 预览版", "#7a5af8", "#f4f0ff", "#d9ccff")
            self._default_status = "M3 · 结构校对"
            if self._last_import is None:
                self.project_icon.setText("M3")
                self.project_name.setText("结构校对")
                self.project_meta.setText("请先导入论文")
            else:
                self._update_project_pill(self._last_import)
            self.structure_scroll.verticalScrollBar().setValue(0)
        elif key == "assets":
            self.page_stack.setCurrentWidget(self.assets_scroll)
            self.right_stack.setCurrentIndex(3)
            self.crumb.setText("PaperFlow   /   M4 图表管理")
            self.top_title.setText("图表管理")
            self.top_sub.setText("上传图片、编辑表格，确认插入锚点")
            self._rechip(self.mode_chip, "M4 预览版", "#b54708", "#fffaeb", "#fedf89")
            self._default_status = "M4 · 图表管理"
            self.assets_scroll.verticalScrollBar().setValue(0)
        elif key == "metadata":
            self.page_stack.setCurrentWidget(self.metadata_scroll)
            self.right_stack.setCurrentIndex(3)
            self.crumb.setText("PaperFlow   /   M4 作者与基金")
            self.top_title.setText("作者与基金")
            self.top_sub.setText("正文候选自动预填；表单是生成源，冲突需确认")
            self._rechip(self.mode_chip, "M4 预览版", "#b54708", "#fffaeb", "#fedf89")
            self._default_status = "M4 · 作者与基金"
            self.metadata_scroll.verticalScrollBar().setValue(0)
        elif key == "references":
            self.page_stack.setCurrentWidget(self.references_scroll)
            self.right_stack.setCurrentIndex(4)
            self.crumb.setText("PaperFlow   /   M5 参考文献")
            self.top_title.setText("参考文献")
            self.top_sub.setText("解析已有条目、逐条确认，生成 refs.bib")
            self._rechip(self.mode_chip, "M5 预览版", "#0f9f8f", "#effcf9", "#b7ebe2")
            self._default_status = "M5 · 参考文献"
            self.references_scroll.verticalScrollBar().setValue(0)
        elif key == "layout":
            self.page_stack.setCurrentWidget(self.layout_scroll)
            self.right_stack.setCurrentIndex(4)
            self.crumb.setText("PaperFlow   /   M5 版式设置")
            self.top_title.setText("版式设置")
            self.top_sub.setText("模板、单双栏、页边距与字号")
            self._rechip(self.mode_chip, "M5 预览版", "#0f9f8f", "#effcf9", "#b7ebe2")
            self._default_status = "M5 · 版式设置"
            self.layout_scroll.verticalScrollBar().setValue(0)
        elif key == "build":
            self.page_stack.setCurrentWidget(self.build_scroll)
            self.right_stack.setCurrentIndex(4)
            self.crumb.setText("PaperFlow   /   M5 生成导出")
            self.top_title.setText("生成与导出")
            self.top_sub.setText("模板渲染、XeLaTeX + biber 编译与 PDF 预览")
            self._rechip(self.mode_chip, "M5 预览版", "#0f9f8f", "#effcf9", "#b7ebe2")
            self._default_status = "M5 · 生成导出"
            self.build_scroll.verticalScrollBar().setValue(0)
        if hasattr(self, "m5_next_title"):
            show_next = key != "build"
            self.m5_next_title.setVisible(show_next)
            self.m5_next_card.setVisible(show_next)
        for step_key, step in self.nav_steps.items():
            step.set_active(step_key == key)
        self.status_msg.setText(self._default_status)

    def _on_import_completed(self, result: ImportResult) -> None:
        self._last_import = result
        self._last_structure = None
        self._m4_state = None
        self._m4_saved = False
        self._references = None
        self._layout = None
        self._overrides = RenderOverrides()
        self.nav_steps["assets"].set_available(False)
        self.nav_steps["metadata"].set_available(False)
        self.nav_steps["references"].set_available(False)
        self.nav_steps["layout"].set_available(False)
        self.nav_steps["build"].set_available(False)
        self._update_m5_right()
        summary = result.summary
        self.structure_page.set_import_result(result)
        self.nav_steps["structure"].set_available(True)
        self.nav_steps["structure"].setToolTip("M3：结构识别与校对")
        self._update_project_pill(result)
        self.m2_values["blocks"].setText(str(summary.block_count))
        self.m2_values["headings"].setText(str(summary.heading_count))
        self.m2_values["figures"].setText(str(summary.figure_count))
        self.m2_values["tables"].setText(str(summary.table_count))
        self.m2_values["warnings"].setText(str(summary.warning_count))
        self.m2_values["warnings"].setStyleSheet(
            "color:#b54708;" if summary.warning_count else "color:#067647;"
        )
        self._rechip(
            self.m2_chip,
            "已完成" if not summary.warning_count else "有警告",
            "#067647" if not summary.warning_count else "#b54708",
            "#ecfdf3" if not summary.warning_count else "#fffaeb",
            "#abefc6" if not summary.warning_count else "#fedf89",
        )
        self.status_doc.setText("●  文档已导入")
        self.status_doc.setStyleSheet("color:#067647;")
        self._default_status = "M2 · 导入完成"
        self._set_status(
            f"M2 · {result.document.title[:36]} · {summary.block_count} 块"
        )
        self._record_recent(result)

    def _record_recent(self, result: ImportResult) -> None:
        if not result.project_dir:
            return
        try:
            projects = self._recent_store.add(
                Path(result.project_dir),
                title=result.document.title,
                source_name=result.summary.source_name,
                format_name=result.document.format,
            )
        except OSError:
            logger.exception("Failed to update recent projects")
            return
        self.import_page.set_recent(projects)

    def _open_project(self, root: str) -> None:
        try:
            loaded = load_project(Path(root))
        except (ProjectLoadError, OSError) as exc:
            QMessageBox.warning(self, "无法打开项目", str(exc))
            self.import_page.set_recent(self._recent_store.remove(Path(root)))
            return
        self._on_import_completed(loaded.imported)
        if loaded.structure is not None:
            self.structure_page.restore_structure(loaded.structure)
        if loaded.m4 is not None and loaded.structure is not None:
            self._m4_state = loaded.m4
            self._m4_saved = True
            self.assets_page.set_context(
                loaded.imported, loaded.structure, loaded.m4
            )
            self.metadata_page.set_context(
                loaded.imported, loaded.structure, loaded.m4
            )
            self.nav_steps["assets"].set_available(True)
            self.nav_steps["metadata"].set_available(True)
            self._update_m4_right()
        if loaded.references is not None and loaded.structure is not None:
            self._references = loaded.references
            self.references_page.set_context(
                loaded.imported, loaded.structure, loaded.references
            )
            self.nav_steps["references"].set_available(True)
        if loaded.layout is not None:
            self._layout = loaded.layout
            self.layout_page.set_context(
                Path(loaded.imported.project_dir), loaded.layout
            )
            self.nav_steps["layout"].set_available(True)
        self._overrides = loaded.overrides or RenderOverrides()
        self._refresh_build_page()
        if (
            loaded.structure is not None
            and loaded.m4 is not None
            and loaded.references is not None
            and loaded.layout is not None
        ):
            self.nav_steps["build"].set_available(True)
            self._on_nav_clicked("build")
        elif loaded.m4 is not None:
            self._on_nav_clicked("metadata")
        elif loaded.structure is not None:
            self._on_nav_clicked("structure")
        self._update_m5_right()
        self._set_status("M6 · 项目已重新打开")
        self.import_page.set_recent(self._recent_store.prune_missing())

    def _on_structure_ready(self, result: StructureResult) -> None:
        structure = result
        headings = sum(1 for item in structure.blocks if item.role == "heading")
        references = sum(1 for item in structure.blocks if item.role == "reference")
        sections = headings
        issues = len(structure.issues)
        self.m3_values["sections"].setText(str(sections))
        self.m3_values["headings"].setText(str(headings))
        self.m3_values["references"].setText(str(references))
        self.m3_values["issues"].setText(str(issues))
        self.m3_values["issues"].setStyleSheet(
            "color:#b54708;" if issues else "color:#067647;"
        )
        if structure.source == "ai":
            label, fg, bg, border = "AI 已识别", "#067647", "#ecfdf3", "#abefc6"
            self.status_structure.setText("●  结构已识别")
            self.status_structure.setStyleSheet("color:#067647;")
        elif structure.source == "manual":
            label, fg, bg, border = "已保存", "#067647", "#ecfdf3", "#abefc6"
            self.status_structure.setText("●  结构已保存")
            self.status_structure.setStyleSheet("color:#067647;")
        else:
            label, fg, bg, border = "本地规则", "#b54708", "#fffaeb", "#fedf89"
            self.status_structure.setText("●  结构本地规则")
            self.status_structure.setStyleSheet("color:#b54708;")
        if issues:
            label, fg, bg, border = "待确认", "#b54708", "#fffaeb", "#fedf89"
        self._rechip(self.m3_chip, label, fg, bg, border)
        self._default_status = "M3 · 结构校对"
        self._set_status(f"M3 · {label} · {sections} 章节 · {references} 条文献")

        self._last_structure = structure
        if self._last_import is not None:
            if self._m4_state is None or (structure.source == "ai" and not self._m4_saved):
                self._m4_state = build_m4_state(self._last_import, structure)
                self._m4_saved = False
                self.assets_page.set_context(
                    self._last_import, structure, self._m4_state
                )
                self.metadata_page.set_context(
                    self._last_import, structure, self._m4_state
                )
            self.nav_steps["assets"].set_available(True)
            self.nav_steps["metadata"].set_available(True)
            self.nav_steps["assets"].setToolTip("M4：图片上传、表格编辑")
            self.nav_steps["metadata"].setToolTip("M4：作者、单位、基金")
            self._update_m4_right()

    def _on_assets_saved(self, state: M4State) -> None:
        self._m4_state = state
        self._m4_saved = True
        self._update_m4_right()
        self._default_status = "M4 · 图表设置"
        self._set_status("M4 · 图表设置已保存")

    def _on_metadata_saved(self, state: M4State) -> None:
        self._m4_state = state
        self._m4_saved = True
        self._update_m4_right()
        self._default_status = "M4 · 作者与基金"
        self._set_status("M4 · 元数据已保存")
        if self._last_import is None or self._last_structure is None:
            return
        if self._references is None:
            self._references = parse_references(
                self._last_structure.document, self._last_structure
            )
        self.references_page.set_context(
            self._last_import, self._last_structure, self._references
        )
        self.nav_steps["references"].set_available(True)
        self.nav_steps["references"].setToolTip("M5：参考文献逐条确认")
        self._update_m5_right()
        self._refresh_build_page()

    def _on_references_saved(self, state: ReferenceState) -> None:
        self._references = state
        self._update_m5_right()
        self.nav_steps["layout"].set_available(True)
        self.nav_steps["layout"].setToolTip("M5：模板与版式参数")
        if self._last_import is not None:
            self.layout_page.set_context(
                Path(self._last_import.project_dir),
                self._layout or LayoutSettings(),
            )
        self._refresh_build_page()
        self._set_status("M5 · 参考文献已保存")

    def _on_layout_saved(self, settings: LayoutSettings) -> None:
        self._layout = settings
        self._update_m5_right()
        self.nav_steps["build"].set_available(True)
        self.nav_steps["build"].setToolTip("M5：生成 TEX 与编译 PDF")
        if (
            self._last_import is not None
            and self._last_structure is not None
            and self._m4_state is not None
            and self._references is not None
        ):
            self.build_page.set_context(
                self._last_import,
                self._last_structure,
                self._m4_state,
                self._references,
                settings,
                self._overrides,
            )
        self._set_status("M5 · 版式已保存")

    def _refresh_build_page(self) -> None:
        if (
            self._last_import is not None
            and self._last_structure is not None
            and self._m4_state is not None
            and self._references is not None
            and self._layout is not None
        ):
            self.build_page.set_context(
                self._last_import,
                self._last_structure,
                self._m4_state,
                self._references,
                self._layout,
                self._overrides,
            )

    def _on_overrides_changed(self, overrides: RenderOverrides) -> None:
        self._overrides = overrides

    def _on_build_compiled(self, ok: bool) -> None:
        if self.m5_values.get("pdf") is not None:
            self.m5_values["pdf"].setText("已生成" if ok else "失败")
            self.m5_values["pdf"].setStyleSheet(
                "color:#067647;" if ok else "color:#b42318;"
            )
        self._rechip(
            self.m5_chip,
            "PDF 已生成" if ok else "编译失败",
            "#067647" if ok else "#b42318",
            "#ecfdf3" if ok else "#fef3f2",
            "#abefc6" if ok else "#fecdca",
        )

    def _update_m5_right(self) -> None:
        refs = len(self._references.entries) if self._references else 0
        self.m5_values["references"].setText(str(refs))
        self.m5_values["columns"].setText(
            "双栏" if self._layout and self._layout.columns == 2 else ("单栏" if self._layout else "—")
        )
        self.m5_values["pdf"].setText("待生成")
        self.m5_values["pdf"].setStyleSheet("color:#667085;")
        if self._layout is not None:
            self._rechip(self.m5_chip, "待生成", "#2563eb", "#eff4ff", "#dbe7ff")
        elif self._references is not None:
            self._rechip(self.m5_chip, "待版式", "#b54708", "#fffaeb", "#fedf89")
        else:
            self._rechip(self.m5_chip, "待解析", "#667085", "#f2f4f7", "#e4e7ec")

    def _update_m4_right(self) -> None:
        if self._m4_state is None:
            for value in self.m4_values.values():
                value.setText("—")
            self._rechip(self.m4_chip, "待编辑", "#667085", "#f2f4f7", "#e4e7ec")
            return
        figures = self._m4_state.figures
        ready = sum(1 for figure in figures if figure.status == "ready")
        conflicts = len(self._m4_state.metadata.unresolved_conflicts)
        self.m4_values["figures"].setText(f"{ready} / {len(figures)}")
        self.m4_values["tables"].setText(str(len(self._m4_state.tables)))
        self.m4_values["authors"].setText(str(len(self._m4_state.metadata.authors)))
        self.m4_values["funds"].setText(str(len(self._m4_state.metadata.funds)))
        self.m4_values["conflicts"].setText(str(conflicts))
        self.m4_values["conflicts"].setStyleSheet(
            "color:#b54708;" if conflicts else "color:#067647;"
        )
        if conflicts:
            self._rechip(self.m4_chip, "待确认", "#b54708", "#fffaeb", "#fedf89")
        elif self._m4_saved:
            self._rechip(self.m4_chip, "已保存", "#067647", "#ecfdf3", "#abefc6")
        else:
            self._rechip(self.m4_chip, "待编辑", "#2563eb", "#eff4ff", "#dbe7ff")

    def _update_project_pill(self, result: ImportResult) -> None:
        summary = result.summary
        title = result.document.title.strip() or result.document.source_name
        self.project_icon.setText("MD" if result.document.format == "markdown" else "TXT")
        elided = self.project_name.fontMetrics().elidedText(
            title, Qt.TextElideMode.ElideRight, 154
        )
        self.project_name.setText(elided)
        self.project_name.setToolTip(title)
        self.project_meta.setText(
            f"{summary.block_count} 块 · {summary.figure_count} 图 · "
            f"{summary.table_count} 表"
        )

    def _reset_status(self) -> None:
        self.status_msg.setText(self._default_status)

    def _on_connection(self, result: ConnectionResult | None) -> None:
        if result is None:
            self._set_check("api", "○", "API 未测试", "#667085")
            self.status_api.setText("●  API 未测试")
            self.status_api.setObjectName("StatusBarWarn")
            self._repolish(self.status_api)
            return
        if result.ok:
            self._set_check("api", "✓", f"API 可连接 · {result.latency_ms} ms", "#067647")
            self.status_api.setText("●  API 已连接")
            self.status_api.setObjectName("StatusBarOk")
            self.status_api.setStyleSheet("color:#067647;")
        else:
            self._set_check("api", "!", "API 连接失败", "#b42318")
            self.status_api.setText("●  API 连接失败")
            self.status_api.setObjectName("StatusBarWarn")
            self.status_api.setStyleSheet("color:#b42318;")
        self._repolish(self.status_api)
        self._update_completion()

    def _on_env_report(self, report: EnvReport) -> None:
        if report.can_compile:
            self._set_check("tex", "✓", "XeLaTeX 可编译", "#067647")
            self.status_tex.setText("●  TeX 已就绪")
            self.status_tex.setObjectName("StatusBarOk")
            self.status_tex.setStyleSheet("color:#067647;")
        else:
            missing = report.get("xelatex")
            if missing is not None and missing.status.value == "missing":
                self._set_check("tex", "×", "XeLaTeX 未安装", "#b42318")
                self.status_tex.setText("●  TeX 未安装")
                self.status_tex.setStyleSheet("color:#b42318;")
            else:
                self._set_check("tex", "!", "XeLaTeX 需处理", "#b54708")
                self.status_tex.setText("●  TeX 需处理")
                self.status_tex.setStyleSheet("color:#b54708;")
            self.status_tex.setObjectName("StatusBarWarn")
        if report.references_ready:
            self._set_check("refs", "✓", "biber 可用", "#067647")
        else:
            self._set_check("refs", "!", "biber 需安装", "#b54708")
        self._repolish(self.status_tex)
        self._update_completion()

    def _on_settings_saved(self, settings: AppSettings) -> None:
        self._settings = settings
        now = datetime.now().strftime("%H:%M")
        self.saved_text.setText(f"已保存 · {now}")
        self._update_key_check()
        self._update_completion()

    def _api_key_text(self) -> str:
        page = getattr(self, "setup_page", None)
        if page is None:
            return ""
        try:
            return page.current_api_key()
        except Exception:
            return page.api_key_edit.text()

    def _refresh_ai_actions(self) -> None:
        for page in (getattr(self, "references_page", None), getattr(self, "build_page", None)):
            if page is not None and hasattr(page, "refresh_ai_state"):
                page.refresh_ai_state()

    def _update_key_check(self) -> None:
        page = getattr(self, "setup_page", None)
        if page is None:
            return
        if page.key_is_persisted:
            self._set_check("key", "✓", "API Key 已保存", "#067647")
            self.status_key.setText("Key 已安全保存")
            self.status_key.setStyleSheet("color:#067647;")
        elif page.has_key:
            self._set_check("key", "!", "Key 仅本次会话", "#b54708")
            self.status_key.setText("Key 仅本次会话")
            self.status_key.setStyleSheet("color:#b54708;")
        else:
            self._set_check("key", "○", "API Key 未配置", "#667085")
            self.status_key.setText("Key 未配置")
            self.status_key.setStyleSheet("color:#667085;")
        self._update_completion()

    def _set_check(self, key: str, symbol: str, text: str, color: str) -> None:
        label = self.check_labels[key]
        label.setText(f"{symbol}  {text}")
        label.setStyleSheet(f"color:{color};")
        self._check_states[key] = symbol == "✓"

    def _update_completion(self) -> None:
        count = sum(1 for state in self._check_states.values() if state)
        self.completion_chip.setText(f"{count} / 4")
        if count == 4:
            self._rechip(self.completion_chip, "M1 完成", "#067647", "#ecfdf3", "#abefc6")
        else:
            self._rechip(self.completion_chip, f"{count} / 4", "#667085", "#f2f4f7", "#e4e7ec")

    def _rechip(self, label: QLabel, text: str, fg: str, bg: str, border: str) -> None:
        label.setText(text)
        label.setStyleSheet(
            f"color:{fg}; background:{bg}; border:1px solid {border}; "
            "border-radius:8px; padding:2px 7px; font-size:9px; font-weight:700;"
        )

    def _set_status(self, message: str) -> None:
        self.status_msg.setText(message)
        self._status_reset_timer.start(6000)

    def _scroll_to_install(self) -> None:
        self.setup_scroll.ensureWidgetVisible(self.setup_page.install_card, 0, 30)

    def _open_log_dir(self) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._log_dir)))

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)
        widget.update()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API)
        try:
            self.build_page.shutdown()
            self.references_page.shutdown()
            self.structure_page.shutdown()
            self.import_page.shutdown()
            self.setup_page.shutdown()
            self.setup_page.persist_settings(notify=False)
        except Exception:
            logger.exception("Failed to persist settings on close")
        super().closeEvent(event)


def make_app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, 64, 64)
    gradient.setColorAt(0.0, QColor("#60a5fa"))
    gradient.setColorAt(0.55, QColor("#2563eb"))
    gradient.setColorAt(1.0, QColor("#0f9f8f"))
    painter.setBrush(gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(3, 3, 58, 58, 14, 14)
    painter.setPen(QColor("#ffffff"))
    font = QFont("Segoe UI", 28, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "P")
    painter.end()
    return QIcon(pixmap)