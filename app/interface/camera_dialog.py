"""
Diálogo para marcar dónde está la cámara del streamer (Etapa 6A).

Muestra un fotograma del video; el usuario arrastra el mouse para dibujar un
rectángulo sobre la cámara. El rectángulo mantiene la proporción del panel
inferior del video vertical (1080 x 768), así la cámara sale sin deformarse.
Se puede elegir otro segundo del video si la cámara no se ve en el primero.

El resultado son fracciones 0-1 del cuadro (x, y, ancho, alto), o None si el
usuario quita la cámara.
"""

import logging

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from app.engine.export_service import extract_frame_png
from app.utils.geometry import constrained_rect, to_fractions
from app.interface.theme import set_role

logger = logging.getLogger(__name__)


class FrameCanvas(QWidget):
    """Dibuja el fotograma y el rectángulo de la cámara."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(480, 270)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._image = None
        self._rect = None        # (x, y, w, h) en fracciones 0-1
        self._anchor = None      # punto inicial del arrastre (en píxeles del widget)

    def set_image(self, image: QImage):
        self._image = image
        self.update()

    def set_region(self, fractions):
        self._rect = fractions
        self.update()

    def region(self):
        return self._rect

    def _image_area(self) -> QRectF:
        """Zona del widget donde se dibuja la imagen (centrada, sin deformar)."""
        if self._image is None or self._image.isNull():
            return QRectF()
        iw, ih = self._image.width(), self._image.height()
        scale = min(self.width() / iw, self.height() / ih)
        w, h = iw * scale, ih * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(20, 20, 20))
        area = self._image_area()
        if area.isEmpty():
            p.setPen(QColor(200, 200, 200))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Cargando fotograma...")
            return
        p.drawImage(area, self._image)
        if self._rect:
            fx, fy, fw, fh = self._rect
            r = QRectF(area.x() + fx * area.width(), area.y() + fy * area.height(),
                       fw * area.width(), fh * area.height())
            p.fillRect(r, QColor(0, 200, 255, 50))
            p.setPen(QPen(QColor(0, 200, 255), 3))
            p.drawRect(r)

    def mousePressEvent(self, event):
        area = self._image_area()
        if event.button() == Qt.MouseButton.LeftButton and not area.isEmpty():
            self._anchor = event.position()

    def mouseMoveEvent(self, event):
        area = self._image_area()
        if self._anchor is None or area.isEmpty():
            return
        a, pos = self._anchor, event.position()
        anchor = (a.x() - area.x(), a.y() - area.y())
        point = (pos.x() - area.x(), pos.y() - area.y())
        rect = constrained_rect(anchor, point, (area.width(), area.height()))
        if rect[2] >= 4:
            self._rect = to_fractions(rect, (area.width(), area.height()))
            self.update()

    def mouseReleaseEvent(self, event):
        self._anchor = None


class CameraDialog(QDialog):
    def __init__(self, parent, video_path: str, current_region, default_seconds: float,
                 duration: float):
        super().__init__(parent)
        self.setWindowTitle("Marcar la cámara del streamer")
        self.resize(900, 620)
        self._video_path = video_path
        self.result_region = current_region
        self.removed = False

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Arrastra con el mouse para dibujar un rectángulo sobre la cámara del streamer. "
            "Si la cámara no se ve en este instante, elige otro segundo del video y pulsa «Cargar»."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.canvas = FrameCanvas()
        layout.addWidget(self.canvas, stretch=1)
        self.canvas.set_region(current_region)

        row = QHBoxLayout()
        row.addWidget(QLabel("Segundo del video:"))
        self.seconds_spin = QDoubleSpinBox()
        self.seconds_spin.setDecimals(1)
        self.seconds_spin.setRange(0, max(duration - 1, 0))
        self.seconds_spin.setValue(min(max(default_seconds, 0), max(duration - 1, 0)))
        row.addWidget(self.seconds_spin)
        load_btn = QPushButton("Cargar")
        load_btn.clicked.connect(self._load_frame)
        row.addWidget(load_btn)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QHBoxLayout()
        save_btn = QPushButton("Guardar cámara")
        set_role(save_btn, "primary")
        save_btn.clicked.connect(self._save)
        remove_btn = QPushButton("Quitar cámara")
        set_role(remove_btn, "danger")
        remove_btn.clicked.connect(self._remove)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        for b in (save_btn, remove_btn, cancel_btn):
            buttons.addWidget(b)
        layout.addLayout(buttons)

        self._load_frame()

    def _load_frame(self):
        try:
            png = extract_frame_png(self._video_path, self.seconds_spin.value())
        except Exception as exc:
            logger.exception("No se pudo cargar el fotograma")
            QMessageBox.warning(self, "Cámara", str(exc))
            return
        image = QImage.fromData(png)
        if image.isNull():
            QMessageBox.warning(self, "Cámara", "No se pudo mostrar el fotograma.")
            return
        self.canvas.set_image(image)

    def _save(self):
        region = self.canvas.region()
        if not region:
            QMessageBox.information(self, "Cámara", "Dibuja primero un rectángulo sobre la cámara.")
            return
        self.result_region = region
        self.removed = False
        self.accept()

    def _remove(self):
        self.result_region = None
        self.removed = True
        self.accept()
