"""
Análisis visual (Etapa 5).

Mide qué tanto cambia la imagen a lo largo del video, para detectar
acción que el audio no revela (tiroteos, persecuciones, explosiones,
cortes de escena). No depende de ningún juego: solo compara fotogramas.

Cómo funciona:
- FFmpeg lee el video, toma 1 fotograma cada SAMPLE_INTERVAL segundos, lo
  reduce a 160x90 en blanco y negro y lo entrega por una tubería. Nunca se
  carga el video completo en memoria (cada fotograma pesa 14 KB).
- Por cada fotograma se mide cuánto cambió respecto al anterior.

Limitación conocida: si el video trae la cámara del streamer incrustada,
sus movimientos también cuentan como cambio en pantalla. Definir la región
de la cámara llegará más adelante.

Prueba por consola (desde C:\\ClipHunterAI, con el venv activado):

    python -m app.engine.visual_analysis "ruta\\al\\video.mp4"
"""

import logging
import subprocess
import time

import numpy as np

from app.engine.signal_utils import relative
from app.utils.binaries import FFMPEG

logger = logging.getLogger(__name__)

SAMPLE_INTERVAL = 2.0        # s entre fotogramas analizados
FRAME_W, FRAME_H = 160, 90   # tamaño al que se reduce cada fotograma
PIXEL_CHANGE = 25            # cambio (0-255) para considerar que un píxel cambió
BASELINE_SECONDS = 300       # "lo normal" = mediana de unos 5 min alrededor
SMOOTH_SAMPLES = 3           # suavizado del movimiento
MIN_MOTION_EXCESS = 0.01     # movimiento sobre lo normal para empezar a contar
FULL_MOTION_EXCESS = 0.08    # movimiento sobre lo normal = acción completa
CUT_MIN = 0.45               # fracción de pantalla cambiada para contar como corte
CUT_FULL = 0.80
CUT_WEIGHT = 0.6             # un corte de escena pesa menos que acción sostenida


class VisualAnalysisCancelled(Exception):
    """Se lanza cuando el usuario cancela el análisis visual."""


def measure_frames(video_path, interval=SAMPLE_INTERVAL, on_progress=None,
                   should_cancel=None, total_seconds=None) -> dict:
    """
    Recorre el video y devuelve, por cada fotograma muestreado:
      motion  : cambio medio de brillo respecto al anterior (0-1)
      changed : fracción de píxeles que cambiaron mucho (0-1)
      flash   : cambio del brillo medio de toda la imagen (0-1)
    """
    cmd = [
        FFMPEG, "-v", "error", "-i", str(video_path), "-an", "-sn",
        "-vf", f"fps=1/{interval},scale={FRAME_W}:{FRAME_H}:flags=area,format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    started = time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=flags)

    frame_bytes = FRAME_W * FRAME_H
    motion, changed, flash = [], [], []
    prev = None
    last_percent = -1

    try:
        while True:
            if should_cancel and should_cancel():
                raise VisualAnalysisCancelled()

            data = b""
            while len(data) < frame_bytes:
                piece = proc.stdout.read(frame_bytes - len(data))
                if not piece:
                    break
                data += piece
            if len(data) < frame_bytes:
                break

            frame = np.frombuffer(data, dtype=np.uint8).astype(np.int16)
            if prev is None:
                motion.append(0.0)
                changed.append(0.0)
                flash.append(0.0)
            else:
                diff = np.abs(frame - prev)
                motion.append(float(diff.mean() / 255.0))
                changed.append(float((diff > PIXEL_CHANGE).mean()))
                flash.append(float(abs(frame.mean() - prev.mean()) / 255.0))
            prev = frame

            if on_progress and total_seconds:
                percent = min(int(len(motion) * interval / total_seconds * 100), 99)
                if percent != last_percent:
                    last_percent = percent
                    on_progress(percent)

        proc.wait()
        if proc.returncode not in (0, None) and not motion:
            err = proc.stderr.read().decode("utf-8", "ignore")[-500:]
            raise RuntimeError(f"FFmpeg no pudo leer el video: {err}")
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdout.close()
        proc.stderr.close()

    if on_progress:
        on_progress(100)

    return {
        "interval": float(interval),
        "motion": motion,
        "changed": changed,
        "flash": flash,
        "processing_seconds": round(time.perf_counter() - started, 2),
    }


def compute_visual_signals(measures: dict, seconds: int) -> dict:
    """
    Convierte las mediciones en una señal 0-1 por segundo ("activity"):
    qué tanta acción visual hay, comparada con lo normal de ESE video.
    Un video siempre en movimiento no genera acción; un tiroteo en medio
    de una exploración tranquila sí.
    """
    from scipy.ndimage import median_filter

    interval = float(measures["interval"])
    motion = np.asarray(measures["motion"], dtype=float)
    changed = np.asarray(measures["changed"], dtype=float)
    n = len(motion)
    if n == 0 or seconds <= 0:
        return {"activity": np.zeros(max(seconds, 0), dtype=np.float32), "excess_motion": 0.0}

    smooth = np.convolve(motion, np.ones(SMOOTH_SAMPLES) / SMOOTH_SAMPLES, mode="same")
    size = max(3, int(BASELINE_SECONDS / interval))
    size = min(size, n if n % 2 else n - 1) or 1
    baseline = median_filter(smooth, size=size, mode="nearest")
    excess = np.clip(smooth - baseline, 0.0, None)

    motion_term = relative(excess) * np.clip(
        (excess - MIN_MOTION_EXCESS) / (FULL_MOTION_EXCESS - MIN_MOTION_EXCESS), 0, 1)
    cut_term = relative(changed) * np.clip((changed - CUT_MIN) / (CUT_FULL - CUT_MIN), 0, 1)
    per_sample = np.maximum(motion_term, CUT_WEIGHT * cut_term)

    times = np.arange(n) * interval
    activity = np.interp(np.arange(seconds), times, per_sample, right=0.0)
    return {
        "activity": activity.astype(np.float32),
        "excess_motion": float(excess.max()) if n else 0.0,
    }


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) < 2:
        print('Uso: python -m app.engine.visual_analysis "ruta\\al\\video.mp4"')
        sys.exit(1)

    m = measure_frames(sys.argv[1], on_progress=lambda p: print(f"  progreso: {p}%", end="\r"))
    seconds = int(len(m["motion"]) * m["interval"])
    sig = compute_visual_signals(m, seconds)
    print(f"\nFotogramas analizados: {len(m['motion'])} en {m['processing_seconds']} s "
          f"(video de ~{seconds} s -> {seconds / max(m['processing_seconds'], 0.01):.1f}x tiempo real)")
    top = np.argsort(sig["activity"])[::-1][:10]
    print("Los 10 segundos con más acción visual:")
    for t in sorted(top):
        print(f"  {int(t)//60}:{int(t)%60:02d}  acción={sig['activity'][t]:.2f}")
