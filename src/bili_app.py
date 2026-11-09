import sqlite3
import sys

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from bili_downloader.storage import Storage
from bili_downloader.ui.theme import apply_theme
from bili_downloader.ui.window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Bili 下载器")
    app.setApplicationDisplayName("Bili 下载器")
    apply_theme(app)
    storage = Storage()
    lock = QLockFile(str(storage.directory / "app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.warning(None, "Bili 下载器", "无法锁定本机任务数据。请先关闭已打开的下载器，再试一次。")
        return 1
    try:
        try:
            window = MainWindow(storage)
        except sqlite3.Error:
            QMessageBox.critical(None, "Bili 下载器", "任务数据库无法打开。请检查本机数据目录与磁盘空间。")
            return 1
        window.show()
        if "--smoke-test" in sys.argv:
            QTimer.singleShot(450, window.close)
        return app.exec()
    finally:
        lock.unlock()


if __name__ == "__main__":
    sys.exit(main())
