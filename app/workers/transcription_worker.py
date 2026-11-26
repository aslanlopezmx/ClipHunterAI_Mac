"""
Tarea en segundo plano (QThread) que transcribe el audio de un video
con Faster-Whisper, sin congelar la interfaz.

Sigue el mismo patrón que VideoProcessingWorker: emite señales de
progreso, estado y fin, y se puede cancelar.
"""

from PySide6.QtCore import QThread, Signal

from app.engine.transcription_service import (
    TranscriptionCancelled,
    transcribe_audio,
)


class TranscriptionWorker(QThread):
    progress_changed = Signal(int)                   # 0 a 100
    status_changed = Signal(str)                     # mensaje corto de estado
    finished_processing = Signal(bool, str, object)  # éxito, mensaje de error, resultado (dict o None)

    def __init__(self, video_row: dict):
        super().__init__()
        self.video = video_row
        self._cancel_requested = False

    def cancel(self):
        """Se llama desde la interfaz cuando el usuario le da a 'Cancelar'."""
        self._cancel_requested = True

    def run(self):
        """Corre en el hilo separado (no en el de la interfaz)."""
        try:
            audio_path = self.video.get("audio_path")
            if not audio_path:
                raise RuntimeError(
                    "Este video todavía no tiene audio extraído. "
                    "Primero usa 'Procesar video seleccionado'."
                )

            result = transcribe_audio(
                audio_path,
                on_progress=self.progress_changed.emit,
                on_status=self.status_changed.emit,
                should_cancel=lambda: self._cancel_requested,
            )
            self.finished_processing.emit(True, "", result)

        except TranscriptionCancelled:
            self.finished_processing.emit(False, "Cancelado por el usuario.", None)
        except Exception as exc:
            self.finished_processing.emit(False, str(exc), None)
