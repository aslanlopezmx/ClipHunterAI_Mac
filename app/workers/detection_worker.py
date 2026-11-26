"""
Worker de detección de momentos (Etapa 4).

Corre el análisis de audio y la detección de candidatos en un hilo
aparte para que la ventana no se congele. Usa las mismas señales que
los otros workers: progress_changed, status_changed y
finished_processing(success, message, result).
"""

import logging

from PySide6.QtCore import QThread, Signal

from app.engine.audio_analysis import AudioAnalysisCancelled, analyze_audio
from app.engine.candidate_detection import detect_candidates
from app.engine.visual_analysis import compute_visual_signals

logger = logging.getLogger(__name__)


class DetectionWorker(QThread):
    progress_changed = Signal(int)
    status_changed = Signal(str)
    finished_processing = Signal(bool, str, object)

    def __init__(self, video: dict, segments: list, visual_measures: dict | None = None):
        super().__init__()
        self._video = video
        self._segments = segments
        self._visual_measures = visual_measures   # None = solo audio y texto
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        try:
            audio_path = self._video.get("audio_path")
            if not audio_path:
                raise RuntimeError("Este video todavía no tiene audio extraído.")

            self.status_changed.emit("Analizando el audio...")
            audio = analyze_audio(
                audio_path,
                on_progress=self.progress_changed.emit,
                should_cancel=lambda: self._cancel_requested,
                total_seconds=self._video.get("duration_seconds"),
            )

            self.status_changed.emit("Buscando momentos interesantes...")
            visual = None
            if self._visual_measures:
                visual = compute_visual_signals(self._visual_measures, audio["seconds"])
            candidates = detect_candidates(audio, self._segments, float(audio["seconds"]), visual)

            self.progress_changed.emit(100)
            self.finished_processing.emit(True, "Detección completada.", {"candidates": candidates})
        except AudioAnalysisCancelled:
            self.finished_processing.emit(False, "Cancelado por el usuario.", None)
        except Exception as exc:
            logger.exception("Error en la detección de momentos")
            self.finished_processing.emit(False, str(exc), None)
