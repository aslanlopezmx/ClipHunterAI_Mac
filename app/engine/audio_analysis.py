"""
Análisis de audio (Etapa 4).

Mide qué tan fuerte suena el audio segundo a segundo y detecta los
momentos en que el sonido se sale de lo normal para ESA parte del video
(no solo "volumen alto": un streamer que grita todo el rato no genera
picos, uno que de pronto estalla sí).

No usa Qt. FFmpeg decodifica el audio y lo entrega en trozos de 60 s,
así que nunca se carga el audio completo en memoria (3 horas = ~10 800
números, nada más).

Prueba por consola (desde C:\\ClipHunterAI, con el venv activado):

    python -m app.engine.audio_analysis "ruta\\al\\audio.aac"
"""

import logging
import subprocess

import numpy as np

from app.utils.binaries import FFMPEG

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000          # Hz; suficiente para voz y reacciones
CHUNK_SECONDS = 60           # cuánto audio se procesa por vez
BASELINE_WINDOW = 61         # s: "lo normal" = mediana de este entorno
MIN_SPREAD_DB = 2.0          # evita que el ruido de fondo parezca un pico
SILENCE_DB = -60.0           # por debajo de esto se considera silencio
ONSET_LOOKBACK = 5           # s previos con los que se compara el salto
IGNORE_START = 6             # s iniciales sin referencia previa: se ignoran


class AudioAnalysisCancelled(Exception):
    """Se lanza cuando el usuario cancela el análisis."""


def measure_loudness(audio_path, on_progress=None, should_cancel=None,
                     total_seconds=None) -> np.ndarray:
    """
    Devuelve un arreglo con el nivel de volumen (en dB) de cada segundo
    del audio. 0 dB sería el máximo posible; lo normal es -50 a -10.
    """
    cmd = [
        FFMPEG, "-v", "error", "-i", str(audio_path),
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-",
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # sin ventana negra en Windows
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=flags)

    bytes_per_chunk = SAMPLE_RATE * 2 * CHUNK_SECONDS
    levels = []
    leftover = np.zeros(0, dtype=np.int16)
    last_percent = -1

    try:
        while True:
            if should_cancel and should_cancel():
                raise AudioAnalysisCancelled()

            data = b""
            while len(data) < bytes_per_chunk:
                piece = proc.stdout.read(bytes_per_chunk - len(data))
                if not piece:
                    break
                data += piece
            if not data:
                break

            samples = np.frombuffer(data[: len(data) // 2 * 2], dtype=np.int16)
            samples = np.concatenate([leftover, samples])
            whole = len(samples) // SAMPLE_RATE
            leftover = samples[whole * SAMPLE_RATE:]
            if whole:
                block = samples[: whole * SAMPLE_RATE].reshape(whole, SAMPLE_RATE)
                block = block.astype(np.float32) / 32768.0
                rms = np.sqrt(np.mean(block ** 2, axis=1))
                levels.extend(20 * np.log10(rms + 1e-9))

            if on_progress and total_seconds:
                percent = min(int(len(levels) / total_seconds * 100), 99)
                if percent != last_percent:
                    last_percent = percent
                    on_progress(percent)

        # Último segundo incompleto (si es de al menos medio segundo).
        if len(leftover) >= SAMPLE_RATE // 2:
            rms = np.sqrt(np.mean((leftover.astype(np.float32) / 32768.0) ** 2))
            levels.append(20 * np.log10(rms + 1e-9))

        proc.wait()
        if proc.returncode not in (0, None) and not levels:
            err = proc.stderr.read().decode("utf-8", "ignore")[-500:]
            raise RuntimeError(f"FFmpeg no pudo leer el audio: {err}")
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdout.close()
        proc.stderr.close()

    if on_progress:
        on_progress(100)
    return np.array(levels, dtype=np.float32)


def compute_signals(levels_db: np.ndarray) -> dict:
    """
    A partir del volumen por segundo calcula dos señales (ambas 0 a 1):

    - "intensity": cuánto se aleja el volumen de lo normal en esa zona
      (mediana móvil de ~1 min). El volumen alto SOSTENIDO sube la mediana
      y por eso no cuenta como pico.
    - "onset": qué tan brusco fue el salto respecto a los 5 s anteriores
      (sirve para detectar sustos, gritos repentinos, explosiones).
    """
    from scipy.ndimage import median_filter

    n = len(levels_db)
    if n == 0:
        return {"intensity": np.zeros(0), "onset": np.zeros(0), "onset_db": np.zeros(0), "excess_db": np.zeros(0)}

    size = min(BASELINE_WINDOW, n if n % 2 else n - 1) or 1
    baseline = median_filter(levels_db, size=size, mode="nearest")
    spread = median_filter(np.abs(levels_db - baseline), size=size, mode="nearest") * 1.4826
    spread = np.maximum(spread, MIN_SPREAD_DB)

    z = (levels_db - baseline) / spread
    z[levels_db < SILENCE_DB] = 0.0
    intensity = np.clip(z / 6.0, 0.0, 1.0)

    # Salto frente al promedio de los segundos anteriores.
    onset = np.zeros(n, dtype=np.float32)
    csum = np.concatenate([[0.0], np.cumsum(levels_db, dtype=np.float64)])
    for t in range(1, n):
        a = max(0, t - ONSET_LOOKBACK)
        prev_mean = (csum[t] - csum[a]) / (t - a)
        onset[t] = levels_db[t] - prev_mean
    onset[levels_db < SILENCE_DB] = 0.0
    onset_db = np.clip(onset, 0.0, None)     # salto real en dB (sin recortar)
    onset = np.clip(onset / 12.0, 0.0, 1.0)

    # Al inicio del archivo no hay nada con qué comparar: falsa alarma segura.
    intensity[:IGNORE_START] = 0.0
    onset[:IGNORE_START] = 0.0
    onset_db[:IGNORE_START] = 0.0

    return {
        "intensity": intensity.astype(np.float32),
        "onset": onset,
        "onset_db": onset_db.astype(np.float32),
        "excess_db": (levels_db - baseline).astype(np.float32),
    }


def analyze_audio(audio_path, on_progress=None, should_cancel=None,
                  total_seconds=None) -> dict:
    """Mide el volumen y calcula las señales. Devuelve todo en un diccionario."""
    levels = measure_loudness(audio_path, on_progress, should_cancel, total_seconds)
    signals = compute_signals(levels)
    signals["levels_db"] = levels
    signals["seconds"] = len(levels)
    return signals


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) < 2:
        print('Uso: python -m app.engine.audio_analysis "ruta\\al\\audio.aac"')
        sys.exit(1)

    res = analyze_audio(sys.argv[1], on_progress=lambda p: print(f"  progreso: {p}%", end="\r"))
    print(f"\nSegundos analizados: {res['seconds']}")
    top = np.argsort(res["intensity"])[::-1][:10]
    print("Los 10 segundos con volumen más fuera de lo normal:")
    for t in sorted(top):
        print(f"  {int(t)//60}:{int(t)%60:02d}  intensidad={res['intensity'][t]:.2f}  "
              f"salto={res['onset'][t]:.2f}  (+{res['excess_db'][t]:.1f} dB sobre lo normal)")
