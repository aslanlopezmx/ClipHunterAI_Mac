"""
Ventana para ver la vista previa de un clip (Etapa 6C-2).

Reproduce el MP4 corto y liviano que genera PreviewWorker, en formato vertical,
con botón de pausa/seguir y de repetir. Al cerrarse suelta el archivo (Windows no
deja borrar ni reemplazar un video que el reproductor tiene abierto).
"""

import logging

from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

logger = logging.getLogger(__name__)


class PreviewDialog(QDialog):
    def __init__(self, parent, video_path: str, title_note: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Vista previa del clip")
        self.resize(420, 780)

        layout = QVBoxLayout(self)
        if title_note:
            note = QLabel(title_note)
            note.setWordWrap(True)
            layout.addWidget(note)

        self.video_widget = QVideoWidget()
        layout.addWidget(self.video_widget, stretch=1)

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        self.player.errorOccurred.connect(self._on_error)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        row = QHBoxLayout()
        self.pause_btn = QPushButton("⏯ Pausa / Seguir")
        self.pause_btn.clicked.connect(self._toggle)
        row.addWidget(self.pause_btn)
        replay_btn = QPushButton("↺ Repetir")
        replay_btn.clicked.connect(self._replay)
        row.addWidget(replay_btn)
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        layout.addLayout(row)

        self.player.setSource(QUrl.fromLocalFile(video_path))
        self.player.play()

    def _toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _replay(self):
        self.player.setPosition(0)
        self.player.play()

    def _on_error(self, error, message=""):
        logger.error("Error en la vista previa: %s %s", error, message)
        self.error_label.setText(f"No se pudo reproducir la vista previa ({message or error}).")

    def done(self, result):
        # Suelta el archivo para poder reemplazarlo en la siguiente vista previa.
        self.player.stop()
        self.player.setSource(QUrl())
        super().done(result)
