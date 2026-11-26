"""
Worker de vista previa (Etapa 6C-2).

Genera en un hilo aparte una muestra corta y liviana del clip (misma composición
y subtítulos que tendría al exportarlo) para verla antes de la exportación final.
No toca la base de datos: el resultado es solo un archivo temporal.

Señales (como los otros workers):
    progress_changed(int), status_changed(str),
    finished_processing(bool, str, object)   object = ruta del MP4 (str) o None
"""

import logging

from PySide6.QtCore import QThread, Signal

from app.engine.export_service import ExportCancelled, export_clip

logger = logging.getLogger(__name__)


class PreviewWorker(QThread):
    progress_changed = Signal(int)
    status_changed = Signal(str)
    finished_processing = Signal(bool, str, object)

    def __init__(self, job: dict):
        """
        job: video_path, start, end, out_path, width, height,
             camera (tuple o None), layout, subtitles_path (opcional)
        """
        super().__init__()
        self._job = job
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        job = self._job
        try:
            self.status_changed.emit("Generando vista previa...")
            path = export_clip(
                job["video_path"], job["start"], job["end"], job["out_path"],
                job["width"], job["height"], job.get("camera"),
                subtitles_path=job.get("subtitles_path"),
                on_progress=self.progress_changed.emit,
                should_cancel=lambda: self._cancel_requested,
                layout=job.get("layout", "camera"),
                preview=True,
            )
            self.finished_processing.emit(True, "Vista previa lista.", str(path))
        except ExportCancelled:
            self.finished_processing.emit(False, "Cancelado por el usuario.", None)
        except Exception as exc:
            logger.exception("Error generando la vista previa")
            self.finished_processing.emit(False, str(exc), None)
