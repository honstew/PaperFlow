from __future__ import annotations

import logging
from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from paperflow.core.api import ConnectionResult, test_connection
from paperflow.core.config import KNOWN_MODELS, AppSettings, SettingsStore
from paperflow.core.env import EnvDetector, EnvReport, EnvStatus
from paperflow.core.secrets import SecretStore, mask_key
from paperflow.ui.widgets import (
    Banner,
    Card,
    StatusRow,
    field_label,
    hint_label,
    make_button,
    make_chip,
)
from paperflow.ui.workers import FunctionThread

logger = logging.getLogger(__name__)

MIKTEX_URL = "https://miktex.org/download"
TEXLIVE_URL = "https://tug.org/texlive/windows.html"
TEXLIVE_TUNA_URL = "https://mirrors.tuna.tsinghua.edu.cn/CTAN/systems/texlive/Images/"
MIKTEX_WINGET = "winget install --id MiKTeX.MiKTeX -e"


class SetupPage(QWidget):
    """M1 setup: API credentials, connection test and TeX environment check."""

    connection_result = Signal(object)
    env_report_ready = Signal(object)
    settings_saved = Signal(object)
    status_message = Signal(str)
    scroll_to_install = Signal()

    def __init__(
        self,
        settings: AppSettings,
        settings_store: SettingsStore,
        secret_store: SecretStore,
        *,
        auto_detect: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._settings_store = settings_store
        self._secret_store = secret_store
        self._env_report: EnvReport | None = None
        self._connection_result: ConnectionResult | None = None
        self._api_busy = False
        self._env_busy = False
        self._env_thread: FunctionThread | None = None
        self._api_thread: FunctionThread | None = None
        self._auto_detect = auto_detect

        stored_key = secret_store.get_key()
        self._saved_key = stored_key if settings.remember_api_key else None
        self._session_key = ""
        if stored_key and not settings.remember_api_key:
            secret_store.delete_key()

        self._build_ui()
        self._apply_settings(settings)
        self._refresh_key_hint()

        if auto_detect:
            QTimer.singleShot(300, self.run_env_check)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 22)
        root.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(12)
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        title = QLabel("环境与 API")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "配置 OpenAI 兼容接口，并检查本机 XeLaTeX 环境。两步都通过后，才能生成 PDF。"
        )
        subtitle.setObjectName("PageSub")
        subtitle.setWordWrap(True)
        text_layout.addWidget(title)
        text_layout.addWidget(subtitle)
        header.addLayout(text_layout, 1)
        self.recheck_button = make_button("重新检测", kind="default")
        self.recheck_button.clicked.connect(self.run_env_check)
        header.addWidget(self.recheck_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        cards = QHBoxLayout()
        cards.setSpacing(14)
        cards.setAlignment(Qt.AlignmentFlag.AlignTop)
        api_card = self._build_api_card()
        env_card = self._build_env_card()
        api_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        env_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        cards.addWidget(api_card, 1)
        cards.addWidget(env_card, 1)
        root.addLayout(cards)

        root.addWidget(self._build_install_card())
        root.addWidget(
            Banner(
                "M1 范围",
                "本版本完成环境与 API 配置。论文导入、结构校对、图表与 LaTeX 编译将在 M2–M5 逐步开放。",
                "info",
            )
        )
        root.addStretch(1)

    def _build_api_card(self) -> Card:
        card = Card(
            "大模型配置",
            "OpenAI 兼容格式 · 默认 DeepSeek",
            right_widget=make_chip("推荐"),
        )
        body = card.body

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://api.deepseek.com")
        self.base_url_edit.setClearButtonEnabled(True)
        body.addWidget(self._field("Base URL", self.base_url_edit, "只填写服务根地址，不要包含 /chat/completions"))

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        self.api_key_edit.setClearButtonEnabled(True)
        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        key_row.addWidget(self.api_key_edit, 1)
        self.show_key_check = QCheckBox("显示")
        self.show_key_check.toggled.connect(self._toggle_key_visibility)
        key_row.addWidget(self.show_key_check, 0, Qt.AlignmentFlag.AlignVCenter)
        key_widget = QWidget()
        key_widget.setLayout(key_row)
        key_block = self._field("API Key", key_widget, "")
        body.addWidget(key_block)
        self.key_hint = hint_label("")
        body.addWidget(self.key_hint)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.model_combo.addItems(KNOWN_MODELS)
        choose_model_hint = hint_label("默认 deepseek-flash；可填写其他 OpenAI 兼容模型。")
        body.addWidget(self._field("模型", self.model_combo, ""))
        body.addWidget(choose_model_hint)

        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("可选，例如 http://127.0.0.1:7890")
        body.addWidget(self._field("网络代理", self.proxy_edit, "留空则使用系统默认网络设置。"))

        self.remember_check = QCheckBox("保存到 Windows 凭据管理器")
        self.remember_check.toggled.connect(self._refresh_key_hint)
        body.addWidget(self.remember_check)

        self.api_banner = Banner(
            "尚未测试",
            "填写 Key 后点击测试连接。测试会发送一次极小的请求，可能产生少量调用费用。",
            "info",
        )
        body.addWidget(self.api_banner)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.save_button = make_button("保存配置")
        self.save_button.clicked.connect(lambda: self.persist_settings(notify=True))
        self.test_button = make_button("测试连接", kind="primary")
        self.test_button.clicked.connect(self.test_api)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.test_button)
        body.addLayout(buttons)
        return card

    def _build_env_card(self) -> Card:
        self.env_badge = make_chip("待检测", fg="#667085", bg="#f2f4f7", border="#e4e7ec")
        card = Card(
            "排版环境",
            "逐项检测，不只判断“是否安装过”",
            right_widget=self.env_badge,
        )
        body = card.body

        self.env_rows: dict[str, StatusRow] = {}
        for item_id, label in (
            ("xelatex", "XeLaTeX"),
            ("latexmk", "latexmk"),
            ("packages", "中文宏包与模板依赖"),
            ("fonts", "中文与西文字体"),
            ("biber", "biber 参考文献"),
            ("compile", "最小中文编译"),
        ):
            row = StatusRow(label=label)
            self.env_rows[item_id] = row
            body.addWidget(row)

        self.env_banner = Banner(
            "尚未检测",
            "点击“重新检测”检查 XeLaTeX、宏包、字体、biber 并做一次最小中文编译。",
            "info",
        )
        body.addWidget(self.env_banner)

        buttons = QHBoxLayout()
        buttons.setSpacing(7)
        self.env_install_button = make_button("安装引导", kind="soft")
        self.env_install_button.clicked.connect(self._scroll_to_install_guide)
        self.choose_xelatex_button = make_button("选择 xelatex.exe")
        self.choose_xelatex_button.clicked.connect(self.choose_xelatex)
        self.detect_button = make_button("重新检测", kind="ghost")
        self.detect_button.clicked.connect(self.run_env_check)
        buttons.addWidget(self.env_install_button)
        buttons.addWidget(self.choose_xelatex_button)
        buttons.addStretch(1)
        buttons.addWidget(self.detect_button)
        body.addLayout(buttons)
        return card

    def _build_install_card(self) -> Card:
        self.install_card = Card(
            "安装引导",
            "不会静默安装，也不会自行提权。安装完成后回到本页重新检测。",
            right_widget=make_chip("缺失时使用", fg="#b54708", bg="#fffaeb", border="#fedf89"),
        )
        options = QHBoxLayout()
        options.setSpacing(10)
        options.addWidget(
            self._install_option(
                "方案 A · TeX Live（推荐）",
                "完整、稳定，宏包和字体齐全，推荐用于论文排版。下载体积较大；可使用清华镜像加速。",
                [
                    ("打开官网", lambda: self._open_url(TEXLIVE_URL)),
                    ("清华镜像", lambda: self._open_url(TEXLIVE_TUNA_URL)),
                ],
            ),
            1,
        )
        options.addWidget(
            self._install_option(
                "方案 B · MiKTeX",
                "体积较小，按需下载宏包；适合个人电脑。首次补装中文宏包时需要联网。",
                [
                    ("复制 winget 命令", self._copy_miktex_command),
                    ("打开官网", lambda: self._open_url(MIKTEX_URL)),
                ],
            ),
            1,
        )
        options.addWidget(
            self._install_option(
                "已有安装",
                "适用于便携版、自定义目录，或未加入 PATH 的安装。",
                [("选择 xelatex.exe", self.choose_xelatex)],
            ),
            1,
        )
        self.install_card.body.addLayout(options)
        self.install_card.body.addWidget(
            hint_label(
                "提示：安装 TeX 发行版可能需要管理员权限和较长下载时间。PaperFlow 只负责检测和引导，不会替你执行系统级安装。"
            )
        )
        return self.install_card

    def _install_option(
        self,
        title: str,
        text: str,
        actions: list[tuple[str, object]],
    ) -> QFrame:
        frame = QFrame()
        frame.setObjectName("InstallOption")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(11, 9, 11, 10)
        layout.setSpacing(5)
        title_label = QLabel(title)
        title_label.setObjectName("InstallTitle")
        text_label = QLabel(text)
        text_label.setObjectName("InstallText")
        text_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(text_label)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        for label, handler in actions:
            button = make_button(label, kind="link")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(handler)  # type: ignore[arg-type]
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return frame

    def _field(self, label: str, widget: QWidget, hint: str) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(field_label(label))
        layout.addWidget(widget)
        if hint:
            layout.addWidget(hint_label(hint))
        return container

    # ------------------------------------------------------------------
    # Settings and API key handling
    # ------------------------------------------------------------------
    def _apply_settings(self, settings: AppSettings) -> None:
        self.base_url_edit.setText(settings.base_url)
        self.model_combo.setCurrentText(settings.model)
        self.proxy_edit.setText(settings.proxy)
        self.remember_check.setChecked(settings.remember_api_key)

    def current_settings(self) -> AppSettings:
        return self._collect_settings()

    def current_api_key(self) -> str:
        return self._resolve_key()

    def _collect_settings(self) -> AppSettings:
        return AppSettings(
            base_url=self.base_url_edit.text(),
            model=self.model_combo.currentText(),
            proxy=self.proxy_edit.text(),
            timeout_s=self._settings.timeout_s,
            xelatex_path=self._settings.xelatex_path,
            remember_api_key=self.remember_check.isChecked(),
        )

    def _resolve_key(self) -> str:
        entered = self.api_key_edit.text().strip()
        if entered:
            return entered
        if self.remember_check.isChecked():
            return self._saved_key or self._session_key
        return self._session_key

    def _refresh_key_hint(self) -> None:
        if not self.remember_check.isChecked():
            self.api_key_edit.setPlaceholderText("仅本次会话使用，不写入系统凭据")
            self.key_hint.setText("Key 只在当前进程内保存；关闭软件后需要重新输入。")
            return
        if self._secret_store.backend_available:
            if self._saved_key:
                self.api_key_edit.setPlaceholderText("已保存；留空则沿用")
                self.key_hint.setText(
                    f"已保存到 Windows 凭据管理器（{mask_key(self._saved_key)}）；留空则沿用。"
                )
            else:
                self.api_key_edit.setPlaceholderText("sk-...")
                self.key_hint.setText("保存到 Windows 凭据管理器，不写入项目、日志或导出包。")
        else:
            self.api_key_edit.setPlaceholderText("凭据管理器不可用；仅本次会话")
            self.key_hint.setText(
                "当前系统凭据管理器不可用，Key 只会保存在内存中，关闭软件后失效。"
            )

    def _toggle_key_visibility(self, visible: bool) -> None:
        self.api_key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )

    def persist_settings(self, *, notify: bool = True) -> bool:
        try:
            settings = self._collect_settings()
        except (ValidationError, ValueError) as exc:
            self.api_banner.set_state("error", "配置有误", _validation_message(exc))
            return False

        entered_key = self.api_key_edit.text().strip()
        key_to_store = entered_key or self._session_key
        stored_ok = True
        if self.remember_check.isChecked():
            if key_to_store:
                stored_ok = self._secret_store.set_key(key_to_store)
                if stored_ok:
                    self._saved_key = key_to_store
                    self._session_key = ""
            else:
                stored_ok = True
            if not stored_ok:
                self._session_key = key_to_store
                self.api_banner.set_state(
                    "warn",
                    "凭据保存失败",
                    "系统凭据管理器不可用，Key 仅本次会话有效。请检查 Windows 凭据管理器后重试。",
                )
                self.remember_check.setChecked(False)
                settings = settings.model_copy(update={"remember_api_key": False})
        else:
            self._session_key = entered_key or self._session_key or self._saved_key or ""
            self._saved_key = None
            self._secret_store.delete_key()

        try:
            self._settings_store.save(settings)
        except OSError as exc:
            logger.exception("Failed to save settings")
            self.api_banner.set_state("error", "保存失败", f"无法写入配置文件：{exc}")
            return False

        self._settings = settings
        self.settings_saved.emit(settings)
        self._refresh_key_hint()
        if notify:
            self.status_message.emit("配置已保存")
            self.save_button.setText("已保存")
            QTimer.singleShot(1500, lambda: self.save_button.setText("保存配置"))
        return True

    # ------------------------------------------------------------------
    # API connection
    # ------------------------------------------------------------------
    def test_api(self) -> None:
        if self._api_busy:
            return
        try:
            settings = self._collect_settings()
        except (ValidationError, ValueError) as exc:
            self.api_banner.set_state("error", "配置有误", _validation_message(exc))
            return
        key = self._resolve_key()
        if not key:
            self.api_banner.set_state(
                "error",
                "缺少 API Key",
                "请填写 API Key，或确认已保存的 Key 可用。",
            )
            return

        self._api_busy = True
        self.test_button.setEnabled(False)
        self.test_button.setText("测试中…")
        self.api_banner.set_state("info", "正在连接…", f"向 {settings.base_url} 发送一次极小请求。")
        thread = FunctionThread(test_connection, settings, key, parent=self)
        thread.result.connect(self._on_api_result)
        thread.error.connect(self._on_api_error)
        thread.finished.connect(self._on_api_finished)
        thread.finished.connect(thread.deleteLater)
        self._api_thread = thread
        thread.start()

    def _on_api_result(self, result: ConnectionResult) -> None:
        self._connection_result = result
        if result.ok:
            detail = f"{result.model} · {result.latency_ms} ms"
            if result.usage_text:
                detail += f" · {result.usage_text}"
            self.api_banner.set_state("ok", "连接正常", detail)
            self.connection_result.emit(result)
            # A successful probe is a good moment to persist non-secret settings.
            if self.persist_settings(notify=False):
                self.status_message.emit("连接成功，配置已保存")
        else:
            self.api_banner.set_state("error", "连接失败", result.message)
            self.connection_result.emit(result)
            self.status_message.emit("API 连接失败")

    def _on_api_error(self, message: str) -> None:
        self.api_banner.set_state("error", "连接失败", message)
        self.status_message.emit("API 连接失败")

    def _on_api_finished(self) -> None:
        self._api_busy = False
        self._api_thread = None
        self.test_button.setEnabled(True)
        self.test_button.setText("测试连接")

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------
    def run_env_check(self) -> None:
        if self._env_busy:
            return
        self._env_busy = True
        self._set_env_busy(True)
        self._set_env_badge("检测中", "info")
        self.env_banner.set_state(
            "info",
            "正在检测环境…",
            "正在查找 XeLaTeX、检查宏包和字体，并编译一份最小中文测试文档。",
        )
        for row in self.env_rows.values():
            row.set_placeholder()
        detector = EnvDetector(self._settings.xelatex_path)
        thread = FunctionThread(detector.detect, parent=self)
        thread.result.connect(self._on_env_result)
        thread.error.connect(self._on_env_error)
        thread.finished.connect(self._on_env_finished)
        thread.finished.connect(thread.deleteLater)
        self._env_thread = thread
        thread.start()

    def _on_env_result(self, report: EnvReport) -> None:
        self._env_report = report
        for item in report.items:
            row = self.env_rows.get(item.id)
            if row is not None:
                row.set_item(item)
        if report.can_compile and report.references_ready:
            self._set_env_badge("已就绪", "ok")
            self.env_banner.set_state(
                "ok",
                "环境已就绪",
                f"{report.summary}。XeLaTeX、宏包、字体、biber 与最小中文编译均通过，可以进入后续排版流程。",
            )
        elif report.can_compile:
            self._set_env_badge("可编译", "warn")
            self.env_banner.set_state(
                "warn",
                "可以编译，但 B 参考文献缺少 biber",
                "请安装 biber，否则结构化参考文献无法编译。其他环境项已通过。",
            )
        elif report.get("xelatex") and report.get("xelatex").status is EnvStatus.MISSING:
            self._set_env_badge("未安装", "error")
            self.env_banner.set_state(
                "error",
                "未检测到 XeLaTeX",
                "仍可先配置 API。安装 MiKTeX 或 TeX Live 后，点击“重新检测”即可。",
            )
        else:
            self._set_env_badge("需处理", "warn")
            self.env_banner.set_state(
                "error",
                "环境需要处理",
                f"{report.summary}。请查看红色条目，或打开安装引导。",
            )
        self.env_report_ready.emit(report)
        self.status_message.emit(f"环境检测完成：{report.summary}")

    def _on_env_error(self, message: str) -> None:
        self._set_env_badge("检测失败", "error")
        self.env_banner.set_state("error", "环境检测失败", message)
        self.status_message.emit("环境检测失败")

    def _on_env_finished(self) -> None:
        self._env_busy = False
        self._env_thread = None
        self._set_env_busy(False)

    def _set_env_busy(self, busy: bool) -> None:
        self.recheck_button.setEnabled(not busy)
        self.detect_button.setEnabled(not busy)
        self.choose_xelatex_button.setEnabled(not busy)
        self.env_install_button.setEnabled(not busy)
        self.detect_button.setText("检测中…" if busy else "重新检测")

    def _set_env_badge(self, text: str, state: str) -> None:
        colors = {
            "ok": ("#067647", "#ecfdf3", "#abefc6"),
            "warn": ("#b54708", "#fffaeb", "#fedf89"),
            "error": ("#b42318", "#fef3f2", "#fecdca"),
            "info": ("#2563eb", "#eff4ff", "#dbe7ff"),
        }
        fg, bg, border = colors.get(state, colors["info"])
        self.env_badge.setText(text)
        self.env_badge.setStyleSheet(
            f"color:{fg}; background:{bg}; border:1px solid {border}; "
            "border-radius:8px; padding:2px 7px; font-size:9px; font-weight:700;"
        )

    def choose_xelatex(self) -> None:
        start_dir = str(Path(self._settings.xelatex_path).parent) if self._settings.xelatex_path else ""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择 xelatex.exe",
            start_dir,
            "xelatex.exe (xelatex.exe);;可执行文件 (*.exe)",
        )
        if not filename:
            return
        if Path(filename).name.lower() != "xelatex.exe":
            self.env_banner.set_state(
                "error",
                "选择无效",
                "请选择名为 xelatex.exe 的可执行文件。",
            )
            return
        self._settings = self._settings.model_copy(update={"xelatex_path": filename})
        try:
            self._settings_store.save(self._settings)
        except OSError:
            logger.exception("Failed to save selected xelatex path")
        self.status_message.emit("已选择 xelatex.exe，正在重新检测")
        self.run_env_check()

    def _scroll_to_install_guide(self) -> None:
        self.scroll_to_install.emit()

    def _open_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def _copy_miktex_command(self) -> None:
        QGuiApplication.clipboard().setText(MIKTEX_WINGET)
        self.status_message.emit("已复制 MiKTeX winget 命令")
        self.env_banner.set_state(
            "info",
            "已复制安装命令",
            f"请在 PowerShell 中粘贴执行：{MIKTEX_WINGET}。安装完成后点击“重新检测”。",
        )

    # ------------------------------------------------------------------
    # Public state for the shell
    # ------------------------------------------------------------------
    @property
    def env_report(self) -> EnvReport | None:
        return self._env_report

    @property
    def connection(self) -> ConnectionResult | None:
        return self._connection_result

    @property
    def has_key(self) -> bool:
        return bool(self._resolve_key())

    @property
    def key_is_persisted(self) -> bool:
        return bool(self._saved_key and self._secret_store.backend_available)

    def shutdown(self, wait_ms: int = 2000) -> None:
        """Stop background checks when the window is closing."""
        for thread in (self._env_thread, self._api_thread):
            if thread is not None and thread.isRunning():
                thread.requestInterruption()
                if not thread.wait(wait_ms):
                    logger.warning("Terminating background thread on shutdown: %s", thread.objectName())
                    thread.terminate()
                    thread.wait(500)
        self._env_thread = None
        self._api_thread = None


def _validation_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts: list[str] = []
        for error in exc.errors():
            loc = ".".join(str(item) for item in error.get("loc", ()))
            msg = error.get("msg", "")
            parts.append(f"{loc}: {msg}" if loc else msg)
        return "；".join(parts) or "配置不合法"
    return str(exc) or "配置不合法"