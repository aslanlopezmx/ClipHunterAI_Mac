"""
Worker de exportación (Etapa 6A).

Exporta uno o varios clips, uno tras otro (una cola sencilla), en un hilo
aparte para que la ventana no se congele. Se puede cancelar de dos maneras:

  - cancel():       detiene TODO el lote (no se borra lo ya exportado)
  - skip_current(): detiene solo el clip en curso y sigue con el siguiente
                    (Etapa 6C-1)

Señales:
    progress_changed(int)            0-100 del lote completo
    status_changed(str)              mensaje corto
    job_finished(int, bool, str)     id del candidato, éxito, ruta o error
    job_skipped(int)                 id del candidato omitido por el usuario
    finished_processing(bool, str, object)   resumen final (igual que los otros workers)
"""

import logging

from PySide6.QtCore import QThread, Signal

from app.engine.export_service import ExportCancelled, export_clip

logger = logging.getLogger(__name__)


class ExportWorker(QThread):
    progress_changed = Signal(int)
    status_changed = Signal(str)
    job_finished = Signal(int, bool, str)
    job_skipped = Signal(int)
    finished_processing = Signal(bool, str, object)

    def __init__(self, jobs: list):
        """
        jobs: lista de diccionarios con
              candidate_id, label, video_path, start, end, out_path,
              width, height, camera (tuple o None),
              subtitles_path (opcional), layout (opcional: camera / full / crop)
        """
        super().__init__()
        self._jobs = jobs
        self._cancel_requested = False
        self._current_index = -1      # clip que se está exportando ahora
        self._skip_index = -1         # clip que el usuario pidió omitir

    def cancel(self):
        """Detiene todo el lote."""
        self._cancel_requested = True

    def skip_current(self):
        """Detiene solo el clip que se está exportando; el lote sigue con el siguiente."""
        self._skip_index = self._current_index

    def run(self):
        total = len(self._jobs)
        done, failed, skipped = [], [], []
        try:
            for i, job in enumerate(self._jobs):
                if self._cancel_requested:
                    break
                self._current_index = i
                self.status_changed.emit(f"Exportando clip {i + 1} de {total}: {job['label']}")

                def on_progress(p, i=i):
                    self.progress_changed.emit(int((i + p / 100) / total * 100))

                try:
                    path = export_clip(
                        job["video_path"], job["start"], job["end"], job["out_path"],
                        job["width"], job["height"], job.get("camera"),
                        subtitles_path=job.get("subtitles_path"),
                        on_progress=on_progress,
                        should_cancel=lambda i=i: self._cancel_requested or self._skip_index == i,
                        layout=job.get("layout", "camera"),
                    )
                    done.append(str(path))
                    self.job_finished.emit(job["candidate_id"], True, str(path))
                except ExportCancelled:
                    if self._cancel_requested:
                        break
                    # Solo se omitió este clip: se anota y el lote continúa.
                    skipped.append(job["label"])
                    self.job_skipped.emit(job["candidate_id"])
                except Exception as exc:
                    logger.exception("Error exportando el candidato %s", job["candidate_id"])
                    failed.append(job["label"])
                    self.job_finished.emit(job["candidate_id"], False, str(exc))

            self.progress_changed.emit(100)
            if self._cancel_requested:
                self.finished_processing.emit(False, "Cancelado por el usuario.", {"done": done})
            elif failed and not done:
                self.finished_processing.emit(False, f"No se pudo exportar: {', '.join(failed)}.", {"done": done})
            else:
                msg = f"{len(done)} clip(s) exportado(s)."
                if skipped:
                    msg += f" Omitidos: {', '.join(skipped)}."
                if failed:
                    msg += f" Fallaron: {', '.join(failed)}."
                self.finished_processing.emit(True, msg, {"done": done})
        except Exception as exc:
            logger.exception("Error en la exportación")
            self.finished_processing.emit(False, str(exc), None)
