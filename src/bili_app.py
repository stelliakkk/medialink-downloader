import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from bili_downloader.storage import Storage
from bili_downloader.ui.theme import apply_theme
from bili_downloader.ui.window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Bili 下载器")
    app.setApplicationDisplayName("Bili 下载器")
    apply_theme(app)
    window = MainWindow(Storage())
    window.show()
    if "--smoke-test" in sys.argv:
        QTimer.singleShot(450, window.close)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
