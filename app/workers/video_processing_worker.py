"""
Tarea en segundo plano (QThread) que procesa un video:
1) extrae el audio, 2) genera una miniatura.

Correr esto en un QThread (en lugar del hilo principal) es lo que
permite que la ventana de la aplicación siga respondiendo mientras
FFmpeg trabaja en un video de varias horas.

FFmpeg lee y procesa el archivo por partes (streaming), así que en
ningún momento se carga el video completo en memoria RAM.
"""

import re
import subprocess
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.config.settings import BASE_DIR
from app.utils.binaries import FFMPEG

# Busca líneas como "time=00:01:23.45" en la salida de FFmpeg,
# para saber cuánto del video ya se procesó.
TIME_PATTERN = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")


class VideoProcessingWorker(QThread):
    # Señales para avisarle a la interfaz lo que va pasando
    progress_changed = Signal(int)            # 0 a 100
    status_changed = Signal(str)              # mensaje corto de estado
    finished_processing = Signal(bool, str, object)  # éxito, mensaje de error, resultado (dict o None)

    def __init__(self, video_row: dict):
        super().__init__()
        self.video = video_row
        self._cancel_requested = False
        self._process = None

    def cancel(self):
        """Se llama desde la interfaz cuando el usuario le da a 'Cancelar'."""
        self._cancel_requested = True
        if self._process and self._process.poll() is None:
            self._process.terminate()

    def run(self):
        """Este método corre en el hilo separado (no en el de la interfaz)."""
        try:
            audio_path = self._extract_audio()
            if self._cancel_requested:
                self.finished_processing.emit(False, "Cancelado por el usuario.", None)
                return

            thumbnail_path = self._generate_thumbnail()
            if self._cancel_requested:
                self.finished_processing.emit(False, "Cancelado por el usuario.", None)
                return

            self.progress_changed.emit(100)
            result = {
                "audio_path": str(audio_path),
                "thumbnail_path": str(thumbnail_path),
            }
            self.finished_processing.emit(True, "", result)

        except Exception as exc:
            self.finished_processing.emit(False, str(exc), None)

    def _extract_audio(self) -> Path:
        self.status_changed.emit("Extrayendo audio...")

        temp_dir = BASE_DIR / "videos" / "temporary"
        temp_dir.mkdir(parents=True, exist_ok=True)
        output_path = temp_dir / f"{Path(self.video['filename']).stem}_audio.aac"

        duration = float(self.video.get("duration_seconds") or 0)

        cmd = [
            FFMPEG, "-y",
            "-i", self.video["filepath"],
            "-vn", "-acodec", "aac", "-b:a", "128k",
            str(output_path),
        ]
        self._run_ffmpeg_with_progress(cmd, duration, progress_range=(0, 50))
        return output_path

    def _generate_thumbnail(self) -> Path:
        self.status_changed.emit("Generando miniatura...")

        previews_dir = BASE_DIR / "clips" / "previews"
        previews_dir.mkdir(parents=True, exist_ok=True)
        output_path = previews_dir / f"{Path(self.video['filename']).stem}_thumb.jpg"

        duration = float(self.video.get("duration_seconds") or 0)
        midpoint = max(duration / 2, 0)

        cmd = [
            FFMPEG, "-y",
            "-ss", str(midpoint),
            "-i", self.video["filepath"],
            "-frames:v", "1",
            str(output_path),
        ]
        # Para la miniatura no hace falta calcular un progreso fino,
        # solo que avance la barra al terminar.
        self._run_ffmpeg_with_progress(cmd, duration=0, progress_range=(50, 100), simple=True)
        return output_path

    def _run_ffmpeg_with_progress(self, cmd, duration, progress_range, simple=False):
        start, end = progress_range

        self._process = subprocess.Popen(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            universal_newlines=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        for line in self._process.stderr:
            if self._cancel_requested:
                self._process.terminate()
                break

            if simple or duration <= 0:
                continue

            match = TIME_PATTERN.search(line)
            if match:
                hours, minutes, seconds = match.groups()
                elapsed = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                fraction = min(elapsed / duration, 1.0)
                percent = start + int(fraction * (end - start))
                self.progress_changed.emit(percent)

        self._process.wait()

        if self._process.returncode != 0 and not self._cancel_requested:
            raise RuntimeError(f"FFmpeg terminó con error (código {self._process.returncode}).")

        if simple and not self._cancel_requested:
            self.progress_changed.emit(end)
