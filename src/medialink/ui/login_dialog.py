import qrcode
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout

from ..platforms.bili_auth import login
from ..workers import Worker
from .widgets import button, label, set_role


def qr_pixmap(url: str) -> QPixmap:
    code = qrcode.QRCode(border=4)
    code.add_data(url)
    code.make(fit=True)
    matrix = code.get_matrix()
    scale = max(3, 210 // len(matrix))
    pixmap = QPixmap(len(matrix) * scale, len(matrix) * scale)
    pixmap.fill(QColor("#ffffff"))
    painter = QPainter(pixmap)
    for row, modules in enumerate(matrix):
        for column, black in enumerate(modules):
            if black:
                painter.fillRect(column * scale, row * scale, scale, QColor("#25211e"))
    painter.end()
    return pixmap


class LoginDialog(QDialog):
    def __init__(self, storage, parent):
        super().__init__(parent)
        self.storage = storage
        self.worker = None
        self.result_account = None
        self._finish_code = None
        self.setWindowTitle("登录哔哩哔哩")
        self.setFixedWidth(404)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 23, 26, 23)
        layout.setSpacing(13)
        layout.addWidget(label("哔哩哔哩账号", "eyebrow"))
        layout.addWidget(label("手机扫码登录", "title"))
        layout.addWidget(label("打开哔哩哔哩 App，扫码后在手机上确认。", "caption"))
        self.tile = label("正在获取二维码")
        self.tile.setObjectName("qrTile")
        self.tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tile.setFixedSize(224, 224)
        layout.addWidget(self.tile, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.state = label("正在联系 B 站…", "status")
        self.state.setWordWrap(True)
        self.state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.state)
        note = label("登录状态由 Windows 加密保存在本机。", "caption")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(note)
        actions = QHBoxLayout()
        actions.addStretch()
        self.refresh = button("刷新二维码")
        self.refresh.clicked.connect(self.restart)
        close = button("关闭", "ghost")
        close.clicked.connect(self.reject)
        actions.addWidget(self.refresh)
        actions.addWidget(close)
        layout.addLayout(actions)

    def start(self):
        self.tile.setText("正在获取二维码")
        self._status("正在联系 B 站…")
        self.refresh.setEnabled(True)
        self.worker = Worker(lambda task: login(task.cancel, task.qr.emit, task.status.emit), self)
        self.worker.qr.connect(self._show_qr)
        self.worker.status.connect(self._status)
        self.worker.ready.connect(self._success)
        self.worker.failed.connect(self._failure)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _show_qr(self, url):
        if not self.worker.cancel.is_set():
            self.tile.setPixmap(qr_pixmap(url))

    def _status(self, message):
        if not self.worker or not self.worker.cancel.is_set():
            set_role(self.state, "status")
            self.state.setText(message)

    def _failure(self, message):
        if not self.worker.cancel.is_set():
            self.tile.setText("二维码已失效")
            set_role(self.state, "error")
            self.state.setText(message)

    def _success(self, payload):
        if self.worker.cancel.is_set():
            return
        account, cookies = payload
        try:
            self.storage.save_cookies(cookies)
        except OSError:
            self._failure("无法保存本机登录状态，请检查程序目录权限。")
            return
        self.result_account = account
        self._finish_code = QDialog.DialogCode.Accepted

    def restart(self):
        if self.worker is None:
            self.start()
        else:
            self._finish_code = "restart"
            self.refresh.setEnabled(False)
            self.worker.cancel.set()
            self.tile.setText("正在刷新二维码")

    def _finished(self):
        previous, self.worker = self.worker, None
        previous.deleteLater()
        action, self._finish_code = self._finish_code, None
        if action == "restart":
            self.start()
        elif action is not None:
            super().done(action)

    def reject(self):
        if self.worker is not None:
            self._finish_code = QDialog.DialogCode.Rejected
            self.worker.cancel.set()
            self.refresh.setEnabled(False)
            self.tile.setText("正在关闭")
        else:
            super().reject()
