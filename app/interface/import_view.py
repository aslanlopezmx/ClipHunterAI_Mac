"""
Pantalla de Importar: permite elegir un archivo de video,
muestra sus propiedades (leídas con ffprobe) y lo guarda
en el proyecto activo.
"""

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QFormLayout,
)

from app.utils.metadata import get_video_metadata
from app.database.repository import add_video
from app.interface.theme import set_role

logger = logging.getLogger(__name__)


class ImportView(QWidget):
    # Se emite (id del video) al guardarlo: la ventana principal lleva a Análisis.
    video_saved = Signal(int)

    def __init__(self):
        super().__init__()
        self.current_project = None
        self.current_metadata = None

        layout = QVBoxLayout(self)

        self.project_label = QLabel(
            "Ningún proyecto seleccionado. Ve a Inicio y crea o elige un proyecto primero."
        )
        self.project_label.setWordWrap(True)
        layout.addWidget(self.project_label)

        select_btn = QPushButton("Seleccionar video")
        select_btn.clicked.connect(self._handle_select_file)
        layout.addWidget(select_btn)

        form_layout = QFormLayout()
        self.filename_value = QLabel("—")
        self.duration_value = QLabel("—")
        self.resolution_value = QLabel("—")
        self.fps_value = QLabel("—")
        self.codecs_value = QLabel("—")
        self.size_value = QLabel("—")

        form_layout.addRow("Archivo:", self.filename_value)
        form_layout.addRow("Duración:", self.duration_value)
        form_layout.addRow("Resolución:", self.resolution_value)
        form_layout.addRow("FPS:", self.fps_value)
        form_layout.addRow("Códecs (video / audio):", self.codecs_value)
        form_layout.addRow("Tamaño:", self.size_value)
        layout.addLayout(form_layout)

        save_row = QHBoxLayout()
        self.save_btn = QPushButton("Guardar en el proyecto")
        set_role(self.save_btn, "primary")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._handle_save)
        save_row.addWidget(self.save_btn)
        save_row.addStretch()
        layout.addLayout(save_row)

        layout.addStretch()

    def set_current_project(self, project: dict):
        self.current_project = project
        self.project_label.setText(f"Proyecto actual: {project['name']}")
        self.save_btn.setEnabled(self.current_metadata is not None)

    def _handle_select_file(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Selecciona un video", "",
            "Videos (*.mp4 *.mkv *.mov *.avi *.webm)"
        )
        if not filepath:
            return

        try:
            metadata = get_video_metadata(filepath)
        except RuntimeError as exc:
            logger.error("Error leyendo metadatos de %s: %s", filepath, exc)
            QMessageBox.critical(self, "Error al leer el video", str(exc))
            return

        self.current_metadata = metadata
        self._display_metadata(metadata)
        self.save_btn.setEnabled(self.current_project is not None)

    def _display_metadata(self, metadata: dict):
        self.filename_value.setText(metadata["filename"])

        minutes, seconds = divmod(int(metadata["duration_seconds"]), 60)
        self.duration_value.setText(f"{minutes} min {seconds} s")

        self.resolution_value.setText(f"{metadata['width']} x {metadata['height']}")
        self.fps_value.setText(str(metadata["fps"]))
        self.codecs_value.setText(f"{metadata['video_codec']} / {metadata['audio_codec']}")

        size_mb = metadata["size_bytes"] / (1024 * 1024)
        self.size_value.setText(f"{size_mb:.1f} MB")

    def _handle_save(self):
        if not self.current_project or not self.current_metadata:
            return

        video_id = add_video(self.current_project["id"], self.current_metadata)
        logger.info(
            "Video guardado en BD: id=%s, proyecto=%s",
            video_id, self.current_project["id"],
        )
        # Se limpia el formulario (evita guardar el mismo video dos veces) y se avanza solo.
        self.current_metadata = None
        self.save_btn.setEnabled(False)
        for label in (self.filename_value, self.duration_value, self.resolution_value,
                      self.fps_value, self.codecs_value, self.size_value):
            label.setText("—")
        self.video_saved.emit(video_id)
