from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QPlainTextEdit, QVBoxLayout

from ..platform import share_links
from .widgets import button, label


def _actions(layout, dialog, caption):
    footer = QHBoxLayout()
    footer.addStretch()
    cancel = button("取消", "ghost")
    cancel.clicked.connect(dialog.reject)
    confirm = button(caption, "primary")
    confirm.clicked.connect(dialog.accept)
    footer.addWidget(cancel)
    footer.addWidget(confirm)
    layout.addLayout(footer)


class LinkDialog(QDialog):
    def __init__(self, parent, output, folder):
        super().__init__(parent)
        self.links = []
        self.setWindowTitle("批量添加链接")
        self.resize(550, 390)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(12)
        layout.addWidget(label("批量添加链接", "title"))
        description = label(f"最多 50 条，支持直接粘贴分享文本。每条按最高可用画质保存为 {output.value}。", "caption")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.input = QPlainTextEdit()
        self.input.setAccessibleName("批量视频链接")
        self.input.setPlaceholderText("粘贴多个 B 站视频链接或分享文本")
        layout.addWidget(self.input, 1)
        self.note = label(str(folder), "caption")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        _actions(layout, self, "解析并加入")
        self.input.setFocus()

    def accept(self):
        links = list(dict.fromkeys(share_links(self.input.toPlainText())))
        if not links or len(links) > 50:
            self.note.setText("请粘贴 1–50 条 B 站视频或分享短链。")
            return
        self.links = links
        super().accept()


class PartsDialog(QDialog):
    def __init__(self, parent, video, current, quality, output):
        super().__init__(parent)
        self.chosen = []
        self.setWindowTitle("选择多个分 P")
        self.resize(570, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(12)
        layout.addWidget(label("选择多个分 P", "title"))
        self.note = label(f"{video.title}  ·  {output.value}  ·  {quality}", "caption")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        toolbar = QHBoxLayout()
        for caption, state in (("全选", Qt.CheckState.Checked), ("清空选择", Qt.CheckState.Unchecked)):
            control = button(caption)
            control.clicked.connect(lambda checked=False, value=state: self._select(value))
            toolbar.addWidget(control)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.items = QListWidget()
        self.items.setAccessibleName("视频分 P 列表")
        for part in video.parts:
            item = QListWidgetItem(f"P{part.number:02d}  {part.name}")
            item.setData(Qt.ItemDataRole.UserRole, part)
            item.setCheckState(Qt.CheckState.Checked if part == current else Qt.CheckState.Unchecked)
            self.items.addItem(item)
        layout.addWidget(self.items, 1)
        _actions(layout, self, "加入队列")

    def _select(self, state):
        for index in range(self.items.count()):
            self.items.item(index).setCheckState(state)

    def accept(self):
        self.chosen = [
            item.data(Qt.ItemDataRole.UserRole)
            for index in range(self.items.count())
            if (item := self.items.item(index)).checkState() == Qt.CheckState.Checked
        ]
        if self.chosen:
            super().accept()
        else:
            self.note.setText("至少勾选一个分 P。")
