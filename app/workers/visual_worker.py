"""
Worker de análisis visual (Etapa 5).

Mide el movimiento y los cambios de escena del video en un hilo aparte.
Mismas señales que los otros workers: progress_changed, status_changed y
finished_processing(success, message, result).
"""

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.engine.visual_analysis import VisualAnalysisCancelled, measure_frames

logger = logging.getLogger(__name__)


class VisualAnalysisWorker(QThread):
    progress_changed = Signal(int)
    status_changed = Signal(str)
    finished_processing = Signal(bool, str, object)

    def __init__(self, video: dict):
        super().__init__()
        self._video = video
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        try:
            path = self._video.get("filepath")
            if not path or not Path(path).exists():
                raise RuntimeError(f"No se encuentra el video original: {path}")

            self.status_changed.emit("Analizando la imagen del video (movimiento y cambios de escena)...")
            measures = measure_frames(
                path,
                on_progress=self.progress_changed.emit,
                should_cancel=lambda: self._cancel_requested,
                total_seconds=self._video.get("duration_seconds"),
            )
            self.finished_processing.emit(True, "Análisis visual completado.", measures)
        except VisualAnalysisCancelled:
            self.finished_processing.emit(False, "Cancelado por el usuario.", None)
        except Exception as exc:
            logger.exception("Error en el análisis visual")
            self.finished_processing.emit(False, str(exc), None)
