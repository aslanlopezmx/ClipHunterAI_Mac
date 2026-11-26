"""
Servicio de transcripción (Etapa 3).

Usa Faster-Whisper para convertir el audio de un video en texto con
marcas de tiempo, en español. No depende de la interfaz (no usa Qt):
recibe funciones opcionales para reportar progreso/estado y para
saber si el usuario canceló. Así se puede usar desde un worker o
probar directamente por consola.

Prueba por consola (desde C:\\ClipHunterAI, con el venv activado):

    python -m app.engine.transcription_service "ruta\\al\\audio.aac"

Faster-Whisper lee el audio por partes, así que no se carga el audio
completo en RAM de golpe.
"""

import logging
import os
import sys
import time
from pathlib import Path

from app.config.settings import BASE_DIR

# Evita un aviso inofensivo de Hugging Face en Windows sobre "symlinks".
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------
# Parámetros ajustables (se calibran con pruebas reales en el Z1)
# ---------------------------------------------------------------
MODEL_SIZE = "small"        # opciones: tiny, base, small, medium
COMPUTE_TYPE = "int8"       # int8 = más ligero y rápido en CPU
LANGUAGE = "es"             # None = detectar idioma automáticamente
# Ryzen Z1 (Windows): 6 núcleos / 12 hilos. Chip Apple A18 Pro: 2 rápidos + 4 de eficiencia.
CPU_THREADS = 4 if sys.platform == "darwin" else 6
BEAM_SIZE = 1               # 1 = más rápido; subir a 5 = más preciso y más lento
WORD_TIMESTAMPS = True      # guarda tiempos por palabra (sirve para subtítulos en Etapa 6)
USE_VAD = True              # salta silencios y partes sin voz (acelera en gameplays)


class TranscriptionCancelled(Exception):
    """Se lanza cuando el usuario cancela la transcripción."""


def transcribe_audio(
    audio_path,
    language=LANGUAGE,
    on_progress=None,
    on_status=None,
    should_cancel=None,
) -> dict:
    """
    Transcribe un archivo de audio y devuelve un diccionario:

        {
          "language": "es",
          "language_probability": 0.98,
          "model": "small",
          "audio_duration": 600.0,        # segundos de audio
          "processing_seconds": 187.3,    # lo que tardó la transcripción
          "segments": [
              {"start": 0.0, "end": 3.2, "text": "...",
               "words": [{"start":..., "end":..., "word":..., "probability":...}]},
              ...
          ],
        }

    on_progress(int 0-100), on_status(str) y should_cancel() son opcionales.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "Falta instalar faster-whisper. Con el venv activado ejecuta: "
            "pip install faster-whisper"
        ) from exc

    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise RuntimeError(f"No se encontró el archivo de audio: {audio_path}")

    def status(msg):
        logger.info(msg)
        if on_status:
            on_status(msg)

    def cancelled():
        return bool(should_cancel and should_cancel())

    models_dir = BASE_DIR / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    status(f"Cargando modelo '{MODEL_SIZE}' (la primera vez se descarga, puede tardar)...")
    model = WhisperModel(
        MODEL_SIZE,
        device="cpu",
        compute_type=COMPUTE_TYPE,
        cpu_threads=CPU_THREADS,
        download_root=str(models_dir),
    )

    if cancelled():
        raise TranscriptionCancelled()

    status("Transcribiendo audio...")
    started = time.perf_counter()

    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=BEAM_SIZE,
        word_timestamps=WORD_TIMESTAMPS,
        vad_filter=USE_VAD,
        vad_parameters={"min_silence_duration_ms": 500},
        # Evita que un error se arrastre y se repita en audios largos.
        condition_on_previous_text=False,
    )

    total = float(info.duration or 0)
    segments = []
    last_percent = -1

    # segments_iter es un generador: el trabajo real ocurre aquí, segmento a segmento.
    for seg in segments_iter:
        if cancelled():
            raise TranscriptionCancelled()

        text = seg.text.strip()
        if text:
            words = []
            for w in (seg.words or []):
                words.append({
                    "start": round(float(w.start), 3),
                    "end": round(float(w.end), 3),
                    "word": w.word,
                    "probability": round(float(w.probability), 3),
                })
            segments.append({
                "start": round(float(seg.start), 3),
                "end": round(float(seg.end), 3),
                "text": text,
                "words": words,
            })

        if on_progress and total > 0:
            percent = min(int(seg.end / total * 100), 99)
            if percent != last_percent:
                last_percent = percent
                on_progress(percent)

    processing_seconds = time.perf_counter() - started

    if on_progress:
        on_progress(100)

    return {
        "language": info.language,
        "language_probability": round(float(info.language_probability or 0), 3),
        "model": MODEL_SIZE,
        "audio_duration": total,
        "processing_seconds": round(processing_seconds, 2),
        "segments": segments,
    }


def format_timestamp(seconds: float) -> str:
    """Convierte segundos a H:MM:SS (o M:SS si dura menos de una hora)."""
    seconds = int(max(seconds, 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


if __name__ == "__main__":
    # Prueba por consola: imprime el texto y mide la velocidad.
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if len(sys.argv) < 2:
        print('Uso: python -m app.engine.transcription_service "ruta\\al\\audio.aac"')
        sys.exit(1)

    result = transcribe_audio(
        sys.argv[1],
        on_progress=lambda p: print(f"  progreso: {p}%", end="\r"),
    )

    print("\n--- Transcripción ---")
    for s in result["segments"]:
        print(f"[{format_timestamp(s['start'])} - {format_timestamp(s['end'])}] {s['text']}")

    dur = result["audio_duration"]
    took = result["processing_seconds"]
    factor = dur / took if took > 0 else 0
    print("\n--- Resumen ---")
    print(f"Modelo: {result['model']} ({COMPUTE_TYPE}) | Idioma: {result['language']} "
          f"({result['language_probability']:.0%})")
    print(f"Audio: {dur:.1f} s | Tiempo de transcripción: {took:.1f} s | "
          f"Velocidad: {factor:.2f}x tiempo real")
    print(f"Segmentos: {len(result['segments'])}")
