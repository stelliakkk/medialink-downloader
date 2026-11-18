from threading import Event

from PySide6.QtCore import QThread, Signal

from .models import Cancelled, UserError
from .diagnostics import unexpected_error


class Worker(QThread):
    ready = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(str, object, str)
    qr = Signal(str)
    status = Signal(str)
    account_expired = Signal()

    def __init__(self, operation, parent, *, context: str = "后台操作"):
        super().__init__(parent)
        self.operation = operation
        self.cancel = Event()
        self.context = context

    def run(self):
        try:
            result = self.operation(self)
        except Cancelled:
            self.cancelled.emit()
        except UserError as error:
            self.failed.emit(str(error))
        except OSError:
            self.failed.emit("无法读写本地文件。请检查保存位置、磁盘空间和文件权限。")
        except Exception as error:
            self.failed.emit(unexpected_error(error, self.context))
        else:
            self.ready.emit(result)
