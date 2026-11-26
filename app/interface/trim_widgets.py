"""
Widgets para ajustar el recorte de un clip (usados en la pantalla Clips detectados).

- TimeEdit: campo de texto para un tiempo. Muestra y entiende el formato único de la
  app (1:08:14, 1:08:14.5 o segundos sueltos como 4094.8).
- RangeSlider: barra con dos manijas (inicio y final) para recortar arrastrando.
  Muestra solo una "ventana" del video (el clip más un margen), no el video entero,
  para que las manijas se puedan mover con precisión en videos largos.
"""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLineEdit, QToolTip, QWidget

from app.interface.theme import ACCENT, BORDER, FG, set_role
from app.interface.timefmt import format_time, parse_time


def time_to_x(t: float, win_min: float, win_max: float, left: float, right: float) -> float:
    """Posición horizontal (px) de un tiempo dentro de la ventana mostrada."""
    span = win_max - win_min
    if span <= 0:
        return left
    return left + (t - win_min) / span * (right - left)


def x_to_time(x: float, win_min: float, win_max: float, left: float, right: float) -> float:
    """Tiempo que corresponde a una posición horizontal (px), limitado a la ventana."""
    width = right - left
    if width <= 0:
        return win_min
    ratio = min(max((x - left) / width, 0.0), 1.0)
    return win_min + ratio * (win_max - win_min)


class TimeEdit(QLineEdit):
    """
    Campo de tiempo. `value()` devuelve segundos; `setValue()` cambia el valor sin emitir
    señal. `user_edited(float)` se emite solo cuando el usuario escribe un valor nuevo y
    válido (si escribe algo que no se entiende, el campo vuelve al valor anterior).
    """
    user_edited = Signal(float)

    def __init__(self):
        super().__init__()
        self._value = 0.0
        self._max = 0.0          # 0 = sin límite superior conocido
        self._hours = False      # mostrar siempre horas (videos de 1 h o más)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(110)
        self.setMaximumWidth(130)
        self.setToolTip("Formato 1:08:14 (también acepta segundos, como 4094.8). Enter para aplicar.")
        set_role(self, "time")
        self.editingFinished.connect(self._commit)
        self._render()

    def value(self) -> float:
        return self._value

    def setValue(self, seconds: float):
        self._value = self._clamp(seconds)
        self._render()

    def setMaxSeconds(self, seconds: float):
        self._max = max(0.0, float(seconds or 0.0))

    def setHoursMode(self, on: bool):
        self._hours = bool(on)
        self._render()

    def _clamp(self, seconds: float) -> float:
        value = max(0.0, float(seconds))
        if self._max:
            value = min(value, self._max)
        return round(value, 1)

    def _render(self):
        self.setText(format_time(self._value, precise=True, hours=self._hours))

    def _commit(self):
        parsed = parse_time(self.text())
        if parsed is None:
            self._render()
            QToolTip.showText(
                self.mapToGlobal(self.rect().bottomLeft()),
                "No entendí ese tiempo. Escríbelo como 1:08:14 o en segundos (4094.8).",
                self,
            )
            return
        new_value = self._clamp(parsed)
        changed = abs(new_value - self._value) > 1e-9
        self._value = new_value
        self._render()
        if changed:
            self.user_edited.emit(new_value)


class RangeSlider(QWidget):
    """
    Barra con dos manijas. Trabaja en segundos dentro de una ventana (`setWindow`).
    `values_changed(inicio, final, manija)` se emite SOLO cuando el usuario arrastra
    ("start" o "end"); `setValues` es silencioso. Las manijas nunca se acercan más de
    `min_gap` segundos entre sí.
    """
    values_changed = Signal(float, float, str)
    drag_finished = Signal()

    HANDLE_W = 12
    GROOVE_H = 6

    def __init__(self, min_gap: float = 1.0):
        super().__init__()
        self._win_min = 0.0
        self._win_max = 1.0
        self._start = 0.0
        self._end = 1.0
        self._gap = float(min_gap)
        self._dragging = None        # "start" | "end" | None
        self._grab_offset = 0.0      # distancia entre el clic y el centro de la manija
        self.setFixedHeight(30)
        self.setMinimumWidth(120)
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    # --- API pública ---------------------------------------------------

    def setWindow(self, win_min: float, win_max: float):
        win_min, win_max = float(win_min), float(win_max)
        if win_max - win_min < self._gap:
            win_max = win_min + self._gap
        self._win_min, self._win_max = win_min, win_max
        self.update()

    def setValues(self, start: float, end: float):
        self._start = min(max(float(start), self._win_min), self._win_max)
        self._end = min(max(float(end), self._win_min), self._win_max)
        self.update()

    def values(self):
        return self._start, self._end

    # --- Geometría -----------------------------------------------------

    def _track(self):
        half = self.HANDLE_W / 2
        return half, self.width() - half

    def _x(self, t: float) -> float:
        left, right = self._track()
        return time_to_x(t, self._win_min, self._win_max, left, right)

    def _t(self, x: float) -> float:
        left, right = self._track()
        return x_to_time(x, self._win_min, self._win_max, left, right)

    # --- Dibujo --------------------------------------------------------

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        height = self.height()
        left, right = self._track()

        groove = QRectF(left, (height - self.GROOVE_H) / 2, right - left, self.GROOVE_H)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(BORDER))
        painter.drawRoundedRect(groove, 3, 3)

        x_start, x_end = self._x(self._start), self._x(self._end)
        accent = QColor(ACCENT) if enabled else QColor("#555555")
        selected = QRectF(x_start, groove.top(), max(x_end - x_start, 0.0), self.GROOVE_H)
        painter.setBrush(accent)
        painter.drawRoundedRect(selected, 3, 3)

        painter.setBrush(QColor(FG) if enabled else QColor("#777777"))
        painter.setPen(QPen(accent, 1.5))
        for x in (x_start, x_end):
            handle = QRectF(x - self.HANDLE_W / 2, 3, self.HANDLE_W, height - 6)
            painter.drawRoundedRect(handle, 3, 3)
        painter.end()

    # --- Ratón ---------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.isEnabled():
            return
        x = event.position().x()
        x_start, x_end = self._x(self._start), self._x(self._end)
        d_start, d_end = abs(x - x_start), abs(x - x_end)
        if d_start != d_end:
            which = "start" if d_start < d_end else "end"
        else:                                    # manijas encimadas: decide el lado del clic
            which = "start" if x < x_start else "end"
        handle_x = x_start if which == "start" else x_end
        self._dragging = which
        if abs(x - handle_x) <= self.HANDLE_W:
            self._grab_offset = x - handle_x     # se agarró la manija: no salta
        else:
            self._grab_offset = 0.0              # clic en la barra: la manija salta ahí
            self._move_to(x)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._move_to(event.position().x())

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = None
            self.drag_finished.emit()

    def _move_to(self, x: float):
        t = round(self._t(x - self._grab_offset), 1)
        if self._dragging == "start":
            t = max(min(max(t, self._win_min), self._end - self._gap), self._win_min)
            if abs(t - self._start) < 1e-9:
                return
            self._start = t
        else:
            t = min(max(min(t, self._win_max), self._start + self._gap), self._win_max)
            if abs(t - self._end) < 1e-9:
                return
            self._end = t
        self.update()
        self.values_changed.emit(self._start, self._end, self._dragging)
