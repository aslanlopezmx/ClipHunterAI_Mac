"""
Tema visual de ClipHunter AI (paleta oscura, tipografía y estilos de botón).

Se aplica una sola vez al arrancar la app con `apply_theme(app)`. Los widgets
que necesitan un aspecto especial (botón principal, peligro, etc.) lo piden
con `set_role(widget, "primary")` o similar, después de crearlos.
"""

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

# -------------------------------------------------------------------
# Paleta (tema oscuro)
# -------------------------------------------------------------------
BG = "#1e1e1e"              # fondo general
BG_PANEL = "#252526"        # paneles, cabeceras
BG_INPUT = "#2d2d30"        # inputs, listas, tablas
FG = "#e6e6e6"              # texto principal
FG_MUTED = "#a8a8a8"        # texto secundario (hints)
BORDER = "#3e3e42"          # bordes
ACCENT = "#0a84ff"          # azul principal
ACCENT_HOVER = "#339dff"
SUCCESS = "#2e7d32"         # verde (aprobar)
SUCCESS_HOVER = "#388e3c"
DANGER = "#c62828"          # rojo (rechazar, cancelar, eliminar)
DANGER_HOVER = "#d32f2f"

BASE_FONT_POINT_SIZE = 10

# -------------------------------------------------------------------
# Hoja de estilos global (QSS). Se construye reemplazando @VAR@ por su
# valor para evitar problemas con las llaves de CSS en f-strings.
# -------------------------------------------------------------------
_QSS_RAW = """
QWidget {
    background-color: @BG@;
    color: @FG@;
    font-size: @FONT_SIZE@pt;
}
QMainWindow { background-color: @BG@; }
QLabel { background: transparent; }
QLabel[role="title"] { font-size: 16pt; font-weight: bold; color: @FG@; }
QLabel[role="hint"] { color: @FG_MUTED@; }
QLabel[role="step_active"] { font-weight: bold; color: @FG@; }
QLabel[role="step_done"] { color: #4caf50; }
QLabel[role="step_failed"] { color: #ef5350; }
QLabel[role="step_pending"] { color: @FG_MUTED@; }

QPushButton {
    background-color: @BG_INPUT@;
    color: @FG@;
    border: 1px solid @BORDER@;
    border-radius: 4px;
    padding: 6px 12px;
    min-height: 20px;
}
QPushButton:hover:!disabled { background-color: #3a3a3d; }
QPushButton:pressed:!disabled { background-color: #2a2a2d; }
QPushButton:disabled { color: #6b6b6b; background-color: #2a2a2d; border-color: #333333; }

QPushButton[role="primary"] {
    background-color: @ACCENT@; color: white; font-weight: bold; border: 1px solid @ACCENT@;
}
QPushButton[role="primary"]:hover:!disabled { background-color: @ACCENT_HOVER@; }
QPushButton[role="primary"]:disabled { background-color: #1e3a5c; color: #a0b8cc; border-color: #1e3a5c; }

QPushButton[role="success"] {
    background-color: @SUCCESS@; color: white; font-weight: bold; border: 1px solid @SUCCESS@;
}
QPushButton[role="success"]:hover:!disabled { background-color: @SUCCESS_HOVER@; }

QPushButton[role="danger"] {
    background-color: @DANGER@; color: white; font-weight: bold; border: 1px solid @DANGER@;
}
QPushButton[role="danger"]:hover:!disabled { background-color: @DANGER_HOVER@; }

QListWidget, QTextEdit, QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QTableWidget {
    background-color: @BG_INPUT@;
    color: @FG@;
    border: 1px solid @BORDER@;
    border-radius: 3px;
    padding: 3px;
    selection-background-color: @ACCENT@;
    selection-color: white;
}
QListWidget::item { padding: 4px 2px; }
QListWidget::item:selected, QTableWidget::item:selected { background-color: @ACCENT@; color: white; }
QListWidget::item:hover { background-color: #333338; }

QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: @BG_INPUT@; color: @FG@;
    selection-background-color: @ACCENT@; selection-color: white;
}

QCheckBox { color: @FG@; spacing: 6px; }
QCheckBox::indicator { width: 16px; height: 16px; }

QProgressBar {
    background-color: @BG_INPUT@; border: 1px solid @BORDER@;
    border-radius: 3px; text-align: center; color: @FG@;
}
QProgressBar::chunk { background-color: @ACCENT@; border-radius: 2px; }

QToolButton { background: transparent; color: @FG@; border: none; padding: 4px; }
QToolButton:hover { color: @ACCENT_HOVER@; }

QSplitter::handle { background: @BORDER@; }

QHeaderView::section {
    background-color: @BG_PANEL@; color: @FG@;
    padding: 4px; border: none;
}

QToolTip {
    background-color: @BG_PANEL@; color: @FG@;
    border: 1px solid @BORDER@; padding: 3px;
}

QScrollBar:vertical, QScrollBar:horizontal { background: transparent; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: @BORDER@; border-radius: 3px; min-height: 20px; min-width: 20px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: #555555;
}
"""

_QSS = (_QSS_RAW
    .replace("@BG_PANEL@", BG_PANEL)
    .replace("@BG_INPUT@", BG_INPUT)
    .replace("@BG@", BG)
    .replace("@FG_MUTED@", FG_MUTED)
    .replace("@FG@", FG)
    .replace("@ACCENT_HOVER@", ACCENT_HOVER)
    .replace("@ACCENT@", ACCENT)
    .replace("@SUCCESS_HOVER@", SUCCESS_HOVER)
    .replace("@SUCCESS@", SUCCESS)
    .replace("@DANGER_HOVER@", DANGER_HOVER)
    .replace("@DANGER@", DANGER)
    .replace("@BORDER@", BORDER)
    .replace("@FONT_SIZE@", str(BASE_FONT_POINT_SIZE))
)


def apply_theme(app: QApplication):
    """Aplica el estilo Fusion, la fuente base y la hoja de estilos global."""
    try:
        app.setStyle("Fusion")
    except Exception:
        pass
    font = QFont()
    font.setPointSize(BASE_FONT_POINT_SIZE)
    app.setFont(font)
    app.setStyleSheet(_QSS)


def set_role(widget, role: str):
    """
    Marca un widget con un rol ("primary", "danger", "success", "title",
    "hint", "step_done", ...). Reaplica el estilo para que la hoja QSS lo
    reconozca de inmediato.
    """
    widget.setProperty("role", role)
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()
