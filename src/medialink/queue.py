"""One active download worker, with database transitions on the UI thread."""

from collections.abc import Callable
import sqlite3

from PySide6.QtCore import QObject, QTimer, Signal

from .download import save_media
from .models import UserError, check_cancelled
from .sources import open_source
from .tasks import Enqueued, Request, SavedMedia, State, TaskStore
from .workers import Worker

RECORD_ERROR = "文件操作已结束，但写入历史失败。请检查磁盘后继续队列。"


def execute_request(request: Request, cookies: dict[str, str], task: Worker) -> SavedMedia:
    check_cancelled(task.cancel)
    with open_source(request.source, cookies, task.cancel) as api:
        video, part = api.resolve(request.url)
        check_cancelled(task.cancel)
        if request.cid is not None and part.cid != request.cid:
            raise UserError("这条视频的分 P 已调整。请重新解析并添加任务。")
        return save_media(api.formats, video, part, request.quality, request.output,
                          request.folder, task.cancel, task.progress.emit)


class DownloadQueue(QObject):
    updated = Signal()
    progress = Signal(str, object, str)
    error = Signal(str)
    idle = Signal()

    def __init__(self, store: TaskStore, cookies: Callable[[], dict[str, str]], parent=None,
                 *, execute=execute_request):
        super().__init__(parent)
        self.store = store
        self.cookies = cookies
        self.execute = execute
        self.worker: Worker | None = None
        self.active_id: int | None = None
        self._result: tuple[State, SavedMedia, str] | None = None
        self.closing = False
        store.recover()
        self.paused = bool(store.active())

    def enqueue(self, requests: list[Request]) -> Enqueued | None:
        try:
            result = self.store.enqueue(requests)
        except sqlite3.Error:
            self.error.emit("无法保存队列，请检查磁盘空间和数据目录权限。")
            return None
        self.updated.emit()
        self._schedule()
        return result

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        recorded = paused or self.worker is not None or self._record()
        self.updated.emit()
        if not recorded:
            self.error.emit(RECORD_ERROR)
        self._schedule()

    def remove(self, task_id: int) -> None:
        try:
            self.store.remove_waiting(task_id)
        except sqlite3.Error:
            self.error.emit("无法移除等待任务，请检查本机数据目录。")
        self.updated.emit()

    def cancel(self) -> None:
        if self.worker and not self.worker.cancel.is_set():
            self.worker.cancel.set()
            self.progress.emit("正在取消", None, "等待当前网络或文件操作结束")
            self.updated.emit()

    def shutdown(self) -> None:
        self.closing = True
        self.cancel()

    def _schedule(self) -> None:
        QTimer.singleShot(0, self, self._advance)

    def _advance(self) -> None:
        if self.closing or self.paused or self.worker or self._result is not None:
            return
        try:
            task = self.store.claim()
        except sqlite3.Error:
            self.paused = True
            self.updated.emit()
            self.error.emit("无法读取下一个任务，队列已暂停。")
            return
        if task is None:
            return
        cookies = self.cookies()
        self.active_id = task.id
        self.worker = Worker(lambda worker: self.execute(task.request, cookies, worker), self)
        self.worker.ready.connect(self._succeeded)
        self.worker.failed.connect(self._failed)
        self.worker.cancelled.connect(self._cancelled)
        self.worker.progress.connect(self._progress)
        self.worker.finished.connect(self._finished)
        self.progress.emit("正在准备", None, task.request.display)
        self.updated.emit()
        self.worker.start()

    def _succeeded(self, media: SavedMedia) -> None:
        self._result = (State.DONE, media, "")

    def _failed(self, message: str) -> None:
        self._result = (State.FAILED, SavedMedia(()), message)

    def _cancelled(self) -> None:
        self._result = (State.CANCELLED, SavedMedia(()), "下载已取消。")

    def _progress(self, stage, value, detail) -> None:
        if self.worker and not self.worker.cancel.is_set():
            self.progress.emit(stage, value, detail)

    def _record(self) -> bool:
        if self.active_id is None or self._result is None:
            return True
        try:
            self.store.finish(self.active_id, *self._result)
        except sqlite3.Error:
            self.paused = True
            return False
        self.active_id = None
        self._result = None
        return True

    def _finished(self) -> None:
        previous, self.worker = self.worker, None
        previous.deleteLater()
        if self._result is None:
            self._failed("下载任务意外结束。")
        recorded = self._record()
        self.updated.emit()
        if not recorded:
            self.error.emit(RECORD_ERROR)
        self.idle.emit()
        self._schedule()
