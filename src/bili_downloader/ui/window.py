from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLineEdit,
    QMainWindow, QMenu, QProgressBar, QScrollArea, QVBoxLayout, QWidget,
)

from .. import __version__
from ..download import save_media
from ..models import Output, check_cancelled
from ..platform import Bilibili
from ..workers import Worker
from .login_dialog import LoginDialog
from .widgets import ComboBox, FitLabel, Poster, app_icon, button, label, set_role


def row(*items, gap=8):
    layout = QHBoxLayout()
    layout.setSpacing(gap)
    for item in items:
        if item is None:
            layout.addStretch()
        else:
            layout.addWidget(item)
    return layout


def panel(name="panel", margin=20, gap=12):
    frame = QFrame()
    frame.setObjectName(name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(gap)
    return frame, layout


def duration(seconds):
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class MainWindow(QMainWindow):
    def __init__(self, storage):
        super().__init__()
        self.storage = storage
        self.folder = storage.download_folder()
        self.cookies = storage.load_cookies()
        self.account = None
        self.video = self.part = self.formats = None
        self.cover = b""
        self.parsed_link = ""
        self.worker = None
        self.closing = False
        self.files = ()
        self.setWindowTitle("Bili 下载器")
        self.setWindowIcon(app_icon())
        self.resize(1140, 792)
        self.setMinimumSize(920, 630)
        self._build()
        self._update_controls()
        if self.cookies:
            self._check_account()

    def _build(self):
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setCentralWidget(scroller)
        canvas = QWidget()
        canvas.setObjectName("canvas")
        scroller.setWidget(canvas)
        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(32, 20, 32, 16)
        layout.setSpacing(14)

        icon = label("")
        icon.setPixmap(self.windowIcon().pixmap(34, 34))
        self.account_button = button("扫码登录")
        self.account_button.clicked.connect(self._account_menu)
        self.account_state = FitLabel("游客模式", "status")
        self.account_state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.account_state.setFixedWidth(168)
        top = row(icon, label("Bili 下载器", "brand"), label("桌面版", "badge"),
                  None, self.account_state, self.account_button, gap=10)
        layout.addLayout(top)

        intro = QVBoxLayout()
        intro.setSpacing(4)
        intro.addWidget(label("下载视频", "hero"))
        intro.addWidget(label("粘贴哔哩哔哩分享链接，保存视频或音频。", "caption"))
        layout.addLayout(intro)

        entry, entry_layout = panel("inputPanel", 16, 10)
        entry_layout.addLayout(row(label("01", "step"), label("视频链接", "section"), None))
        self.url = QLineEdit()
        self.url.setObjectName("link")
        self.url.setPlaceholderText("https://www.bilibili.com/video/BV…  或  https://b23.tv/…")
        self.url.setAccessibleName("哔哩哔哩视频链接")
        self.url.setClearButtonEnabled(True)
        self.url.textChanged.connect(self._link_changed)
        self.url.returnPressed.connect(self._resolve)
        self.paste = button("粘贴")
        self.paste.setFixedWidth(76)
        self.paste.setMinimumHeight(43)
        self.paste.clicked.connect(self._paste)
        self.resolve_button = button("解析链接", "primary")
        self.resolve_button.setMinimumSize(116, 43)
        self.resolve_button.clicked.connect(self._resolve)
        entry_layout.addLayout(row(self.url, self.paste, self.resolve_button, gap=10))
        layout.addWidget(entry)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self._preview_panel(), 12)
        body.addWidget(self._options_panel(), 10)
        layout.addLayout(body, 1)
        layout.addWidget(self._transfer_panel())
        layout.addLayout(row(label("普通投稿 · 本地处理", "caption"),
                             None, label(f"版本 {__version__}", "caption")))
        self.url.setFocus()

    def _preview_panel(self):
        frame, layout = panel(gap=9)
        self.preview_badge = label("待解析", "badge")
        layout.addLayout(row(label("02", "step"), label("视频预览", "section"), None, self.preview_badge))
        self.poster = Poster()
        layout.addWidget(self.poster, 1)
        self.video_title = FitLabel("等待视频链接", "title")
        self.video_info = FitLabel("解析后在这里查看封面、作者和时长。", "caption")
        layout.addWidget(self.video_title)
        layout.addWidget(self.video_info)
        self.parts = ComboBox()
        self.parts.setAccessibleName("分 P")
        self.parts.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.parts.addItem("解析后可选分 P")
        self.parts.currentIndexChanged.connect(self._part_changed)
        part_row = row(label("分 P", "field"), self.parts, gap=12)
        part_row.setStretch(1, 1)
        layout.addLayout(part_row)
        return frame

    def _options_panel(self):
        frame, layout = panel(gap=7)
        layout.addLayout(row(label("03", "step"), label("保存设置", "section"), None))
        layout.addSpacing(3)
        layout.addWidget(label("视频画质", "field"))
        self.quality = ComboBox()
        self.quality.setAccessibleName("视频画质")
        self.quality.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.quality.addItem("解析后显示可用画质")
        self.quality.currentIndexChanged.connect(self._update_controls)
        layout.addWidget(self.quality)
        self.quality_note = FitLabel("按视频和账号实际可用的画质显示", "caption")
        layout.addWidget(self.quality_note)
        layout.addSpacing(4)
        layout.addWidget(label("输出格式", "field"))
        self.output_choices = QButtonGroup(self)
        options_row = QHBoxLayout()
        options_row.setSpacing(7)
        for index, (mode, title) in enumerate(zip(Output, ("视频 MP4", "仅音频 MP3", "MP4 + MP3"), strict=True)):
            option = button(title, "choice")
            option.setCheckable(True)
            option.setChecked(index == 0)
            self.output_choices.addButton(option, index)
            options_row.addWidget(option, 1)
        self.output_choices.idClicked.connect(self._output_changed)
        layout.addLayout(options_row)

        layout.addSpacing(4)
        layout.addWidget(label("保存位置", "field"))
        self.folder_name = FitLabel(str(self.folder), "caption")
        self.folder_name.setMinimumHeight(30)
        self.folder_button = button("更改", "ghost")
        self.folder_button.clicked.connect(self._pick_folder)
        folder_well = QFrame()
        folder_well.setObjectName("folderWell")
        folder_row = row(self.folder_name, self.folder_button)
        folder_row.setContentsMargins(10, 3, 4, 3)
        folder_row.setStretch(0, 1)
        folder_well.setLayout(folder_row)
        layout.addWidget(folder_well)
        layout.addStretch()
        self.output_note = FitLabel("直接封装原始画面与音轨", "caption")
        layout.addWidget(self.output_note)
        self.download_button = button("开始下载", "primary")
        self.download_button.clicked.connect(self._download)
        layout.addWidget(self.download_button)
        return frame

    def _transfer_panel(self):
        frame, layout = panel("transferPanel", 12, 6)
        self.phase = FitLabel("准备就绪", "status")
        self.phase.setFixedWidth(100)
        self.detail = FitLabel("等待视频链接", "caption")
        self.percent = label("—", "field")
        self.cancel_button = button("取消", "ghost")
        self.cancel_button.setMinimumHeight(25)
        self.cancel_button.clicked.connect(self._cancel)
        self.cancel_button.hide()
        self.open_button = button("打开位置", "ghost")
        self.open_button.setMinimumHeight(25)
        self.open_button.clicked.connect(self._show_files)
        self.open_button.hide()
        info = row(self.phase, self.detail, self.percent, self.cancel_button, self.open_button)
        info.setStretch(1, 1)
        layout.addLayout(info)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setAccessibleName("任务进度")
        layout.addWidget(self.bar)
        return frame

    def _update_controls(self):
        idle = self.worker is None
        parsed = self.formats is not None and self.url.text().strip() == self.parsed_link
        audio_only = self.output_choices.checkedId() == 1
        self.url.setEnabled(idle)
        self.paste.setEnabled(idle)
        self.resolve_button.setEnabled(idle and bool(self.url.text().strip()))
        self.account_button.setEnabled(idle)
        self.parts.setEnabled(idle and self.video is not None and len(self.video.parts) > 1
                              and self.url.text().strip() == self.parsed_link)
        self.folder_button.setEnabled(idle)
        for option in self.output_choices.buttons():
            option.setEnabled(idle)
        has_video = self.quality.currentIndex() >= 0 and self.quality.count() > 0 and self.quality.itemData(0) is not None
        self.quality.setEnabled(idle and parsed and has_video and not audio_only)
        self.download_button.setEnabled(idle and parsed and (audio_only or has_video))

    def _output_changed(self):
        choice = self.output_choices.checkedId()
        self.download_button.setText("导出 MP3" if choice == 1 else "开始下载")
        self.output_note.set_full((
            "直接封装原始画面与音轨",
            "从视频音轨导出 320 kbps MP3",
            "保存视频，并用同一音轨导出 MP3",
        )[choice])
        self._update_controls()

    def _link_changed(self):
        self._update_controls()
        if self.worker is None and self.url.text().strip() != self.parsed_link:
            self._progress("准备就绪", 0, "按 Enter 或点击「解析链接」" if self.url.text().strip() else "等待视频链接")

    def _paste(self):
        self.url.setText(QApplication.clipboard().text().strip().replace("\n", " "))
        self.url.setFocus()

    def _pick_folder(self):
        selected = QFileDialog.getExistingDirectory(self, "选择保存目录", str(self.folder))
        if selected:
            self.folder = Path(selected)
            self.folder_name.set_full(str(self.folder))
            try:
                self.storage.save_folder(self.folder)
            except OSError:
                self._error("本次可使用所选目录，但无法保存目录偏好。")

    def _progress(self, phase, value, detail):
        set_role(self.phase, "status")
        self.phase.set_full(phase)
        self.detail.set_full(detail)
        if value is None:
            self.bar.setRange(0, 0)
            self.percent.setText("…")
        else:
            self.bar.setRange(0, 100)
            self.bar.setValue(value)
            self.percent.setText(f"{value}%" if value else "—")

    def _error(self, message):
        self._progress("操作未完成", 0, message)
        set_role(self.phase, "error")
        self.phase.set_full("操作未完成")

    def _cancel(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self._progress("正在取消", None, "等待当前网络或文件操作结束")

    def _start(self, operation, receive):
        self.worker = Worker(operation, self)
        self.worker.ready.connect(receive)
        self.worker.failed.connect(self._error)
        self.worker.cancelled.connect(lambda: self._progress("已取消", 0, "可以重新开始当前操作"))
        self.worker.progress.connect(self._worker_progress)
        self.worker.finished.connect(self._end)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self._update_controls()
        self.worker.start()

    def _worker_progress(self, phase, value, detail):
        if self.worker and not self.worker.cancel.is_set():
            self._progress(phase, value, detail)

    def _end(self):
        previous, self.worker = self.worker, None
        previous.deleteLater()
        self.cancel_button.hide()
        self._update_controls()
        if self.closing:
            self.close()

    def _resolve(self):
        text = self.url.text().strip()
        if self.worker or not text:
            return
        self.formats = None
        self._progress("正在解析", None, "正在获取视频信息和可用画质")
        cookies = self.cookies.copy()

        def operation(task):
            with Bilibili(cookies) as api:
                account_expired = bool(cookies) and api.account() is None
                if account_expired:
                    api.session.cookies.clear()
                video, part = api.resolve(text)
                check_cancelled(task.cancel)
                formats = api.formats(video, part)
                check_cancelled(task.cancel)
                cover = api.cover(video)
                check_cancelled(task.cancel)
                return video, part, formats, cover, account_expired

        def receive(payload):
            if self.worker.cancel.is_set():
                return
            self.video, self.part, self.formats, self.cover, expired = payload
            self.parsed_link = text
            if expired:
                self.cookies = {}
                self.account = None
                self._account_display()
                try:
                    self.storage.clear_cookies()
                except OSError:
                    pass
            self._render_video()
            if expired:
                self.detail.set_full("登录已过期，已按游客可用画质解析")

        self._start(operation, receive)

    def _render_video(self):
        video, part = self.video, self.part
        self.preview_badge.setText(video.bvid)
        self.poster.update_cover(self.cover, duration(part.seconds))
        self.video_title.set_full(video.title)
        self.video_info.set_full(f"UP 主  {video.author}   ·   {len(video.parts)} 个分 P")
        self.parts.blockSignals(True)
        self.parts.clear()
        for index, item in enumerate(video.parts):
            self.parts.addItem(f"P{item.number:02d}  {item.name}  ·  {duration(item.seconds)}", item)
            if item == part:
                self.parts.setCurrentIndex(index)
        self.parts.blockSignals(False)
        self._render_formats()

    def _render_formats(self):
        formats = self.formats
        available = [quality for quality in formats.qualities if quality.track]
        unavailable = [quality.label for quality in formats.qualities if quality.track is None]
        self.quality.blockSignals(True)
        self.quality.clear()
        if available:
            self.quality.addItem(f"最高可用 · {available[0].label}", "best")
        for quality in available:
            track = quality.track
            self.quality.addItem(f"{quality.label}  ·  {track.width} × {track.height}", quality.code)
        if not available:
            self.quality.addItem("当前只有音频可用")
        self.quality.blockSignals(False)
        self.quality_note.set_full(
            "当前不可用：" + "、".join(unavailable) if unavailable else "已获取当前可用的画质档位"
        )
        self._progress("解析完成", 0, f"已获取 {len(available)} 个视频档位，可以开始下载")

    def _part_changed(self):
        part = self.parts.currentData()
        if not self.video or not part or self.worker or (part == self.part and self.formats is not None):
            return
        self.formats = None
        self.quality.clear()
        self.quality.addItem("正在查询分 P 画质")
        self._progress("正在解析分 P", None, f"P{part.number:02d}  {part.name}")
        video, cookies = self.video, self.cookies.copy()

        def operation(task):
            with Bilibili(cookies) as api:
                formats = api.formats(video, part)
            check_cancelled(task.cancel)
            return formats

        def receive(formats):
            if not self.worker.cancel.is_set():
                self.part, self.formats = part, formats
                self.poster.update_cover(self.cover, duration(part.seconds))
                self._render_formats()

        self._start(operation, receive)

    def _download(self):
        if not self.download_button.isEnabled():
            return
        selected = self.quality.currentData()
        quality = self.formats.select(None).code if selected == "best" else selected
        output = list(Output)[self.output_choices.checkedId()]
        cookies, video, part, folder = self.cookies.copy(), self.video, self.part, self.folder
        self.files = ()
        self.open_button.hide()
        self._progress("正在准备下载", None, "正在确认目标画质与保存位置")

        def operation(task):
            return save_media(cookies, video, part, quality, output, folder, task.cancel, task.progress.emit)

        def receive(files):
            self.files = files
            self.open_button.show()
            self._progress("下载完成", 100, f"{len(files)} 个文件已保存到 {folder}")

        self._start(operation, receive)

    def _show_files(self):
        if self.files:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.files[0].parent)))

    def _check_account(self):
        self.account_state.set_full("正在检查登录")
        self._progress("正在检查登录", None, "正在验证本机 B 站会话")
        cookies = self.cookies.copy()

        def operation(task):
            with Bilibili(cookies) as api:
                account = api.account()
            check_cancelled(task.cancel)
            return account

        def receive(account):
            if not self.worker.cancel.is_set():
                self.account = account
                if account is None:
                    try:
                        self.storage.clear_cookies()
                    except OSError:
                        pass
                    self.cookies = {}
                self._account_display()
                self._progress("准备就绪", 0, "登录已恢复" if account else "登录已过期，已切换到游客模式")

        self._start(operation, receive)
        self.worker.failed.connect(lambda _: self.account_state.set_full("登录待验证"))
        self.worker.cancelled.connect(lambda: self.account_state.set_full("登录待验证"))

    def _account_display(self):
        if self.account:
            self.account_state.set_full(("大会员 · " if self.account.vip else "已登录 · ") + self.account.name)
            self.account_button.setText("账号")
        else:
            self.account_state.set_full("游客模式")
            self.account_button.setText("扫码登录")

    def _account_menu(self):
        if not self.account and not self.cookies:
            self._login()
            return
        menu = QMenu(self)
        relog = menu.addAction("重新扫码登录")
        logout = menu.addAction("退出本机登录")
        chosen = menu.exec(self.account_button.mapToGlobal(self.account_button.rect().bottomLeft()))
        if chosen == relog:
            self._login()
        elif chosen == logout:
            try:
                self.storage.clear_cookies()
            except OSError:
                self._error("无法移除本机登录状态，请检查数据目录权限。")
                return
            self.account = None
            self.cookies = {}
            self._account_display()
            if self.url.text().strip():
                self._resolve()

    def _login(self):
        dialog = LoginDialog(self.storage, self)
        dialog.start()
        if dialog.exec() and dialog.result_account:
            self.cookies = self.storage.load_cookies()
            self.account = dialog.result_account
            self._account_display()
            if self.url.text().strip():
                self._resolve()
            else:
                self._progress("登录成功", 0, "可以解析视频并查看账号可用的画质")
        dialog.deleteLater()

    def closeEvent(self, event):
        if self.worker:
            self.closing = True
            self._cancel()
            event.ignore()
            return
        super().closeEvent(event)
