from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

BG = "#f4f2ee"
PANEL = "#fffdfa"
TEXT = "#25211e"
MUTED = "#655d55"
ACCENT = "#bd3e21"

STYLES = """
QWidget { color: #25211e; font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px; }
QMainWindow, QDialog, #canvas, QScrollArea { background: #f4f2ee; }
QFrame#panel, QFrame#inputPanel, QFrame#transferPanel {
    background: #fffdfa; border: 1px solid #e3ddd5; border-radius: 16px;
}
QFrame#transferPanel { background: #faf8f4; border-radius: 12px; }
QFrame#folderWell { background: #f7f4ef; border: 1px solid #eee8df; border-radius: 9px; }
QLabel { background: transparent; }
QLabel[role="brand"] { font-size: 16px; font-weight: 700; }
QLabel[role="hero"] { font-size: 33px; font-weight: 700; }
QLabel[role="section"] { font-size: 15px; font-weight: 700; }
QLabel[role="title"] { font-size: 19px; font-weight: 700; }
QLabel[role="caption"] { font-size: 12px; color: #655d55; }
QLabel[role="field"] { font-size: 12px; font-weight: 600; color: #4d453e; }
QLabel[role="eyebrow"] { font-size: 11px; color: #8d402a; font-weight: 700; }
QLabel[role="status"] { font-size: 12px; color: #3d5949; font-weight: 600; }
QLabel[role="error"] { font-size: 12px; color: #a92923; font-weight: 600; }
QLabel[role="step"] {
    border-radius: 7px; background: #f9e8df; color: #943c24;
    font: 700 11px "Segoe UI";
}
QLabel[role="badge"] {
    background: #f0ede8; color: #5b544d; border-radius: 7px;
    padding: 0 8px; font-size: 11px;
}
QLabel#qrTile { background: #ffffff; color: #58483d; border: 1px solid #e3ddd5; border-radius: 14px; }
QLineEdit, QComboBox {
    min-height: 36px; color: #25211e; background: #ffffff; border: 1px solid #d9d0c6;
    padding: 0 11px; border-radius: 8px; selection-background-color: #a93820;
}
QLineEdit#link { min-height: 43px; padding: 0 13px; font-size: 14px; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #a93820; }
QComboBox::drop-down { width: 30px; border: 0px; }
QComboBox::down-arrow { image: none; }
QComboBox { padding-right: 30px; }
QComboBox QAbstractItemView {
    background: #fffdfa; color: #25211e; border: 1px solid #d9d0c6;
    selection-background-color: #f6e1d8; selection-color: #762c19; padding: 4px;
}
QPushButton {
    min-height: 34px; padding: 0 12px; border-radius: 8px;
    background: #fffdfa; border: 1px solid #ded7cf; color: #3b322b; font-weight: 600;
}
QPushButton:hover { background: #f6f0ea; border-color: #cdbdb0; }
QPushButton:pressed { background: #efe5db; }
QPushButton:focus { border: 1px solid #a93820; }
QPushButton[role="primary"] {
    min-height: 42px; background: #bd3e21; color: #ffffff; border: 1px solid #bd3e21;
    font-size: 14px; font-weight: 700;
}
QPushButton[role="primary"]:hover { background: #a93820; border-color: #a93820; }
QPushButton[role="primary"]:pressed { background: #8d301b; }
QPushButton[role="primary"]:focus { border: 2px solid #622a1d; }
QPushButton[role="choice"] { min-height: 39px; background: #f7f4ef; }
QPushButton[role="choice"]:hover { background: #f5eae2; }
QPushButton[role="choice"]:checked { color: #85341f; background: #fae9e0; border-color: #c86e51; }
QPushButton[role="ghost"] { background: transparent; border-color: transparent; color: #85341f; }
QPushButton[role="ghost"]:hover { background: #f7e9df; }
QPushButton[role="ghost"]:focus { border-color: #a93820; }
QPushButton:disabled, QPushButton[role="primary"]:disabled, QPushButton[role="choice"]:disabled,
QPushButton[role="ghost"]:disabled, QComboBox:disabled, QLineEdit:disabled {
    color: #766e66; background: #f2efea; border-color: #e4ded7;
}
QProgressBar {
    background: #eae3d9; border: 0; border-radius: 3px; min-height: 6px; max-height: 6px;
}
QProgressBar::chunk { background: #bd3e21; border-radius: 3px; }
QMenu { color: #25211e; background: #fffdfa; border: 1px solid #d9d0c6; padding: 5px; }
QMenu::item { padding: 8px 19px; }
QMenu::item:selected { background: #fae9e0; }
QToolTip { background: #fffdfa; color: #25211e; border: 1px solid #d9d0c6; padding: 5px; }
QScrollArea { border: 0; }
"""


def apply_theme(app):
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    app.setStyle("Fusion")
    palette = app.palette()
    for role, color in {
        QPalette.ColorRole.Window: BG,
        QPalette.ColorRole.Base: PANEL,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.PlaceholderText: MUTED,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#ffffff",
    }.items():
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(STYLES)
