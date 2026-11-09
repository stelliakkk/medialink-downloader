import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from medialink.ui.widgets import app_icon


def main(path: Path) -> None:
    app = QApplication([])
    icon = app_icon()
    sizes = [16, 24, 32, 48, 64, 128]
    chunks = []
    for size in sizes:
        image = icon.pixmap(size, size)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError("Could not encode app icon")
        chunks.append(bytes(buffer.data()))
    offset = 6 + 16 * len(chunks)
    entries = []
    for size, data in zip(sizes, chunks, strict=True):
        entries.append(struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    path.write_bytes(struct.pack("<HHH", 0, 1, len(chunks)) + b"".join(entries + chunks))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
