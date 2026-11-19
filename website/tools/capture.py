"""Capture the real desktop widgets with isolated, offline showcase data."""

from contextlib import closing
import math
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QBuffer, QIODevice, QPointF
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication

WEBSITE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEBSITE.parent / "src"))

from medialink.models import Formats, Output, Part, Quality, Source, Track, Video
from medialink.storage import Storage
from medialink.tasks import Request, SavedMedia, State
from medialink.ui.theme import apply_theme
from medialink.ui.widgets import app_icon
from medialink.ui.window import MainWindow


def cover_bytes():
    """Draw original terrain lines for the preview's example cover."""
    width, height = 780, 440
    cover = QImage(width, height, QImage.Format.Format_RGB32)
    painter = QPainter(cover)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0, QColor("#101412"))
    gradient.setColorAt(1, QColor("#30372B"))
    painter.fillRect(cover.rect(), gradient)
    for row in range(58):
        baseline = 45 + row * 7.9
        path = QPainterPath()
        for x in range(0, width + 1, 4):
            ridge = 105 * math.exp(-((x - 490 + row * 3) / 195) ** 2)
            y = baseline - ridge + 24 * math.sin(x / 100 + row / 17)
            if x == 0:
                path.moveTo(QPointF(x, y))
            else:
                path.lineTo(QPointF(x, y))
        color = QColor("#C3D1AA")
        color.setAlpha(36 + int(125 * math.sin(row / 19) ** 2))
        painter.setPen(QPen(color, 1.0))
        painter.drawPath(path)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    cover.save(buffer, "PNG")
    return bytes(buffer.data())


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    assets = WEBSITE / "assets"
    assets.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="medialink-site-") as directory, closing(
        MainWindow(Storage(Path(directory)))
    ) as window:
        window.resize(1140, 840)
        window.folder = Path("C:/MediaLink/Examples")
        window.folder_name.set_full(str(window.folder))

        part = Part(1, 1, "地表回声", 38)
        video = Video("0000000000000000000", part.name, "MediaLink 演示素材", "", (part,), Source.DOUYIN)
        track = Track((), "avc1", 2400000, 1920, 1080)
        window.video, window.part = video, part
        audio = Track((), "mp4a", 128000)
        window.formats = Formats((Quality(1080, "1080P", track),), audio)
        window.cover = cover_bytes()
        window.url.setText("https://www.douyin.com/video/0000000000000000000")
        window.parsed_link = window.url.text()
        window._render_video()

        def request(title, source, output):
            return Request("demo-" + title, 1, title, title, None, output, window.folder,
                           source=source, is_note=output is Output.ASSETS)

        window.queue.paused = True
        for title, source, output, state, label in [
            ("地表回声", Source.DOUYIN, Output.VIDEO, State.DONE, "1080P"),
            ("城市声景", Source.BILIBILI, Output.AUDIO, State.DONE, ""),
            ("未完成的取景", Source.BILIBILI, Output.VIDEO, State.FAILED, ""),
        ]:
            # Seed the history before queue entries are added.
            window.store.enqueue([request(title, source, output)])
            task = window.store.claim()
            files = (window.folder / f"{title}.{output.value.lower()}",) if state is State.DONE else ()
            window.store.finish(task.id, state, SavedMedia(files, label=label), "")
        window.store.enqueue([
            request("纸上微光", Source.BILIBILI, Output.BOTH),
            request("远岸手记", Source.DOUYIN, Output.ASSETS),
        ])
        window._update_tasks()
        window.show()

        for index, name in enumerate(("capture", "queue", "history")):
            window.tabs.setCurrentIndex(index)
            app.processEvents()
            screenshot = window.grab()
            if not screenshot.save(str(assets / f"{name}.webp"), "WEBP", 92):
                raise RuntimeError(f"Could not save {name}.webp")
    if not app_icon().pixmap(128, 128).save(str(assets / "medialink.png")):
        raise RuntimeError("Could not save the desktop icon")


if __name__ == "__main__":
    main()
