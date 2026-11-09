from datetime import datetime
import sqlite3

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QProgressBar,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..models import Output
from ..platform import QUALITY_NAMES
from ..tasks import State
from .widgets import ComboBox, FitLabel, button, label


STATE_LABELS = {
    State.WAITING: "等待", State.RUNNING: "下载中", State.DONE: "已完成",
    State.FAILED: "失败", State.CANCELLED: "已取消", State.INTERRUPTED: "已中断",
}
PAGE_SIZE = 50


def quality_label(task):
    code = task.request.quality
    if task.request.output is Output.AUDIO:
        return "音频"
    return task.media.label or (QUALITY_NAMES.get(code, f"档位 {code}") if code else "最高可用")


class TaskTable(QTableWidget):
    def __init__(self, columns):
        super().__init__(0, len(columns))
        self.tasks = ()
        self.setHorizontalHeaderLabels(columns)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(36)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)

    def selected(self):
        selected = self.selectedIndexes()
        return self.tasks[selected[0].row()] if selected else None

    def render(self, tasks, extra_columns):
        previous = self.selected()
        previous_id = previous.id if previous else None
        self.blockSignals(True)
        self.clearSelection()
        self.tasks = tuple(tasks)
        self.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            values = [task.request.display, quality_label(task), task.request.output.value,
                      STATE_LABELS[task.state], *extra_columns(task)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.setItem(row, column, item)
            if task.id == previous_id:
                self.selectRow(row)
        self.blockSignals(False)


class QueuePage(QWidget):
    def __init__(self, queue):
        super().__init__()
        self.queue = queue
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(12)
        layout.addWidget(label("下载队列", "hero"))
        layout.addWidget(label("任务按顺序执行。暂停会让当前任务完成，下一条等待继续。", "caption"))
        actions = QHBoxLayout()
        self.pause = button("暂停队列")
        self.pause.clicked.connect(lambda: queue.set_paused(not queue.paused))
        self.cancel = button("取消当前")
        self.cancel.clicked.connect(queue.cancel)
        self.remove = button("移除所选")
        self.remove.clicked.connect(self._remove)
        self.count = label("", "caption")
        for control in (self.pause, self.cancel, self.remove):
            actions.addWidget(control)
        actions.addStretch()
        actions.addWidget(self.count)
        layout.addLayout(actions)
        self.batch_note = FitLabel("", "caption")
        self.batch_note.hide()
        layout.addWidget(self.batch_note)
        self.table = TaskTable(("视频 / 分 P", "画质", "输出", "状态"))
        self.table.setAccessibleName("下载队列")
        self.table.itemSelectionChanged.connect(self._selection)
        layout.addWidget(self.table, 1)
        self.detail = FitLabel("没有正在下载的任务", "caption")
        layout.addWidget(self.detail)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setAccessibleName("当前下载任务进度")
        layout.addWidget(self.bar)

    def _selection(self):
        selected = self.table.selected()
        self.remove.setEnabled(selected is not None and selected.state is State.WAITING)

    def _remove(self):
        selected = self.table.selected()
        if selected:
            self.queue.remove(selected.id)

    def render(self, tasks):
        self.table.render(tasks, lambda _: [])
        waiting = sum(task.state is State.WAITING for task in tasks)
        self.count.setText(f"{waiting} 项等待" if tasks else "队列为空")
        self.pause.setText("继续队列" if self.queue.paused else "暂停队列")
        self.pause.setEnabled(bool(tasks))
        worker = self.queue.worker
        self.cancel.setEnabled(worker is not None and not worker.cancel.is_set())
        self._selection()
        if worker is None:
            self.bar.setRange(0, 100)
            self.bar.setValue(0)
            self.detail.set_full("队列已暂停" if self.queue.paused and tasks else "没有正在下载的任务")

    def progress(self, stage, value, detail):
        self.detail.set_full(f"{stage}  ·  {detail}")
        self.bar.setRange(0, 0 if value is None else 100)
        if value is not None:
            self.bar.setValue(value)

    def report_batch(self, message, errors):
        self.batch_note.set_full(message)
        self.batch_note.setToolTip("\n".join((message, *errors)))
        self.batch_note.show()


class HistoryPage(QWidget):
    def __init__(self, store, enqueue):
        super().__init__()
        self.store = store
        self.enqueue = enqueue
        self.page = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(12)
        layout.addWidget(label("下载历史", "hero"))
        layout.addWidget(label("查看已保存的文件、失败原因和上次下载结果。", "caption"))
        actions = QHBoxLayout()
        self.filter = ComboBox()
        self.filter.setAccessibleName("按状态筛选历史")
        self.filter.addItem("全部状态", None)
        for state in (State.DONE, State.FAILED, State.CANCELLED, State.INTERRUPTED):
            self.filter.addItem(STATE_LABELS[state], state)
        self.filter.currentIndexChanged.connect(self._reset_page)
        self.retry = button("重新入队", "primary")
        self.retry.clicked.connect(self._retry)
        self.open_file = button("打开文件")
        self.open_file.clicked.connect(lambda: self._open(False))
        self.open_folder = button("打开目录")
        self.open_folder.clicked.connect(lambda: self._open(True))
        actions.addWidget(self.filter)
        actions.addStretch()
        for control in (self.open_file, self.open_folder, self.retry):
            actions.addWidget(control)
        layout.addLayout(actions)
        self.table = TaskTable(("视频 / 分 P", "画质", "输出", "结果", "结束时间"))
        self.table.setAccessibleName("下载历史")
        self.table.itemSelectionChanged.connect(self.refresh_actions)
        layout.addWidget(self.table, 1)
        self.detail = FitLabel("还没有下载记录", "caption")
        footer = QHBoxLayout()
        footer.addWidget(self.detail, 1)
        self.previous = button("上一页", "ghost")
        self.previous.clicked.connect(lambda: self._turn(-1))
        self.page_label = label("第 1 页", "caption")
        self.next = button("下一页", "ghost")
        self.next.clicked.connect(lambda: self._turn(1))
        for control in (self.previous, self.page_label, self.next):
            footer.addWidget(control)
        layout.addLayout(footer)

    def _reset_page(self):
        self.page = 0
        self.refresh()

    def _turn(self, delta):
        self.page += delta
        self.refresh()

    def refresh(self):
        state = self.filter.currentData()
        try:
            tasks = self.store.history(state, limit=PAGE_SIZE + 1, offset=self.page * PAGE_SIZE)
        except sqlite3.Error:
            self.detail.set_full("无法读取历史记录，请检查数据目录。")
            return
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(len(tasks) > PAGE_SIZE)
        self.page_label.setText(f"第 {self.page + 1} 页")
        self.table.render(tasks[:PAGE_SIZE], lambda task: [
            datetime.fromisoformat(task.finished).astimezone().strftime("%Y-%m-%d %H:%M") if task.finished else "—",
        ])
        self.refresh_actions()

    def refresh_actions(self):
        task = self.table.selected()
        self.retry.setEnabled(bool(task and task.can_retry))
        files = self._files(task)
        self.open_file.setEnabled(bool(files))
        self.open_folder.setEnabled(bool(task and task.request.folder.is_dir()))
        if task:
            paths = "  ·  ".join(str(path) for path in task.media.files)
            missing = "部分或全部文件已缺失。 " if task.media.files and not task.media.exists else ""
            self.detail.set_full(task.message or missing + paths or str(task.request.folder))
        else:
            self.detail.set_full("选择一条记录查看详情" if self.table.tasks else "没有匹配的下载记录")

    @staticmethod
    def _files(task):
        return [path for path in task.media.files
                if path.suffix.lower() in (".mp4", ".mp3") and path.is_absolute() and path.is_file()] if task else []

    def _open(self, folder):
        task = self.table.selected()
        if not task:
            return
        files = self._files(task)
        path = task.request.folder if folder and task.request.folder.is_dir() else (
            files[0] if not folder and files else None
        )
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        self.refresh_actions()

    def _retry(self):
        task = self.table.selected()
        if task and task.can_retry:
            self.enqueue([task.request])
