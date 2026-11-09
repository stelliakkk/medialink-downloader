from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QSizePolicy, QWidget


def label(text: str, role: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setProperty("role", role)
    if role == "badge":
        widget.setFixedHeight(24)
    elif role == "step":
        widget.setFixedSize(29, 27)
        widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return widget


def button(text: str, role: str = "") -> QPushButton:
    widget = QPushButton(text)
    widget.setProperty("role", role)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


def set_role(widget: QWidget, role: str) -> None:
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class FitLabel(QLabel):
    def __init__(self, text: str, role: str):
        super().__init__()
        self.setProperty("role", role)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_full(text)

    def set_full(self, text: str) -> None:
        self.full_text = text
        self.setToolTip(text)
        self._elide()

    def _elide(self) -> None:
        self.setText(self.fontMetrics().elidedText(self.full_text, Qt.TextElideMode.ElideRight, self.width()))

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self):
        return QSize(94, super().sizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def showEvent(self, event):
        super().showEvent(event)
        self._elide()


class ComboBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#65554a" if self.isEnabled() else "#8c8278"), 1.6))
        x, y = self.width() - 16, self.height() / 2
        painter.drawPolyline(QPolygonF([QPointF(x - 4, y - 2), QPointF(x, y + 2), QPointF(x + 4, y - 2)]))


def _triangle(painter: QPainter, x: float, y: float, size: float, color: str):
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPolygon(QPolygonF([
        QPointF(x - size * 0.30, y - size / 2),
        QPointF(x + size * 0.60, y),
        QPointF(x - size * 0.30, y + size / 2),
    ]))


def app_icon() -> QIcon:
    pixmap = QPixmap(128, 128)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(5, 5, 123, 123)
    gradient.setColorAt(0, QColor("#e06b48"))
    gradient.setColorAt(1, QColor("#ab371d"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(QRectF(5, 5, 118, 118), 29, 29)
    painter.setPen(QPen(QColor("#fff8ed"), 7, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(28, 32, 72, 64), 12, 12)
    painter.drawLine(64, 47, 64, 77)
    painter.drawPolyline(QPolygonF([QPointF(51, 65), QPointF(64, 78), QPointF(77, 65)]))
    painter.end()
    return QIcon(pixmap)


class Poster(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(166)
        self.setMaximumHeight(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("视频封面")
        self.image = QPixmap()
        self.duration = ""

    def update_cover(self, image: bytes = b"", duration: str = ""):
        self.image = QPixmap()
        self.image.loadFromData(image)
        self.duration = duration
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        width, height = self.width(), self.height()
        bounds = QRectF(0, 0, width, height)
        clip = QPainterPath()
        clip.addRoundedRect(bounds, 11, 11)
        p.setClipPath(clip)
        target = bounds
        if not self.image.isNull():
            p.fillRect(bounds, QColor("#f1ece4"))
            image_width, image_height = self.image.width(), self.image.height()
            ratio = min(width / image_width, height / image_height)
            picture_width, picture_height = image_width * ratio, image_height * ratio
            target = QRectF((width - picture_width) / 2, (height - picture_height) / 2,
                            picture_width, picture_height)
            p.drawPixmap(target, self.image, QRectF(0, 0, image_width, image_height))
        else:
            self._placeholder(p, width, height)
        if self.duration:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(37, 33, 30, 218))
            badge = QRectF(target.right() - 64, target.bottom() - 32, 54, 22)
            p.drawRoundedRect(badge, 6, 6)
            p.setPen(QColor("#fffdfa"))
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, self.duration)

    @staticmethod
    def _placeholder(p: QPainter, width: int, height: int) -> None:
        gradient = QLinearGradient(0, 0, width, height)
        gradient.setColorAt(0, QColor("#f8ece2"))
        gradient.setColorAt(1, QColor("#efddcf"))
        p.fillRect(0, 0, width, height, gradient)
        p.translate(width / 2, height / 2)
        p.scale(height / 228, height / 228)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f3d8c5"))
        p.drawEllipse(QPointF(3, 3), 93, 93)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#dcbda9"), 1))
        p.drawEllipse(QPointF(3, 3), 106, 106)
        p.save()
        p.rotate(-12)
        p.setPen(QPen(QColor("#d19e84"), 1))
        p.setBrush(QColor("#f5c3a9"))
        p.drawRoundedRect(QRectF(-85, -51, 132, 90), 12, 12)
        p.restore()
        p.save()
        p.rotate(7)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(117, 68, 44, 29))
        p.drawRoundedRect(QRectF(-52, -33, 132, 88), 12, 12)
        p.setPen(QPen(QColor("#e5bba4"), 1))
        p.setBrush(QColor("#fff7ef"))
        p.drawRoundedRect(QRectF(-55, -41, 132, 88), 12, 12)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f6dfd0"))
        p.drawEllipse(QPointF(11, 3), 25, 25)
        _triangle(p, 10, 3, 23, "#bd3e21")
        p.restore()
        p.setBrush(QColor("#c67453"))
        p.drawEllipse(QPointF(102, -52), 3, 3)
        p.setBrush(QColor("#c3957a"))
        p.drawEllipse(QPointF(-111, 39), 4, 4)
