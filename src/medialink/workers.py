from threading import Event

from PySide6.QtCore import QThread, Signal

from .models import Cancelled, UserError


class Worker(QThread):
    ready = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(str, object, str)
    qr = Signal(str)
    status = Signal(str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.cancel = Event()

    def run(self):
        try:
            result = self.operation(self)
        except Cancelled:
            self.cancelled.emit()
        except UserError as error:
            self.failed.emit(str(error))
        except OSError:
            self.failed.emit("无法读写本地文件。请检查保存位置、磁盘空间和文件权限。")
        except Exception:
            # Requests and process details may contain signed URLs. Keep them out of UI and logs.
            self.failed.emit("没有完成这次操作，请重试。若持续失败，B 站接口可能已变化。")
        else:
            self.ready.emit(result)
