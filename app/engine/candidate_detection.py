"""
Detección de candidatos (Etapa 4).

Junta las señales de audio (audio_analysis.py) con las del texto
(transcripción guardada) y produce una lista de momentos candidatos:
ventana con contexto antes y después, puntuación 0-100, desglose por
categoría, motivo y transcripción.

No usa Qt ni toca la base de datos (salvo en la prueba por consola).

Cada señal se usa en UNA sola categoría para no contar dos veces lo mismo:

    audio emocional  <- qué tan fuera de lo normal está el volumen
    sorpresa         <- salto brusco de volumen seguido de reacción hablada
    conversación     <- densidad de habla, preguntas y exclamaciones
    entretenimiento  <- risas y palabras de reacción
    contexto         <- hay conversación antes Y después del momento

    acontecimiento visual <- movimiento y cambios de escena (Etapa 5)

La parte visual es opcional y suma hasta VISUAL_BONUS puntos sobre la base de
audio y texto (se busca en todo el clip). Sin análisis visual, la puntuación es
solo la de audio y texto.

Prueba por consola (desde C:\\ClipHunterAI, con el venv activado):

    python -m app.engine.candidate_detection "ruta\\audio.aac" ID_DEL_VIDEO
"""

import logging
import math
import re

import numpy as np

from app.engine.signal_utils import relative as _relative

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------
# Parámetros ajustables (se calibran con pruebas reales)
# ---------------------------------------------------------------
WEIGHTS = {            # pesos del documento maestro (audio y texto: suman 80)
    "audio": 20,
    "conversation": 25,
    "surprise": 15,
    "narrative": 10,
    "entertainment": 10,
}
# La parte visual SUMA puntos encima de esa base (en vez de repartir el peso):
# así una imagen sin acción no le quita puntos a un momento que ya era bueno.
# Es una estimación inicial (calibrada con un solo video): se ajusta con más pruebas.
VISUAL_BONUS = 25          # puntos máximos que puede sumar la acción visual
CONTEXT_BEFORE = 22        # s de contexto antes del momento
CONTEXT_AFTER = 38         # s de contexto después (antes + después = 60)
MIN_CLIP = 60              # duración mínima del clip (s): requisito de monetización en varias plataformas
MAX_CLIP = 90              # duración máxima del clip (s)
MERGE_GAP = 10             # s: candidatos más cerca que esto se fusionan
MIN_PEAK_SEPARATION = 20   # s mínimos entre dos picos
PEAK_THRESHOLD = 0.12      # fuerza mínima (0-1) para considerar un pico
MIN_SCORE = 35             # puntuación mínima para mostrar un candidato
# Cantidad de candidatos a mostrar: depende de la duración del video, en vez de
# un número fijo. Se permite un candidato más por cada MINUTES_PER_CANDIDATE
# minutos de video, con un piso y un techo para que nunca sea muy poco (video
# corto) ni demasiado para revisar (video muy largo).
MINUTES_PER_CANDIDATE = 3  # cada cuántos minutos de video se permite 1 candidato más
MIN_TARGET_COUNT = 10      # cantidad mínima, incluso en videos cortos
MAX_TARGET_COUNT = 45      # cantidad máxima, incluso en videos muy largos
CONV_WINDOW = 10           # s para medir la densidad de conversación
QUESTION_WEIGHT = 0.15     # las preguntas pesan poco (el streamer se habla solo)
MIN_EXCESS_DB = 3.0        # por debajo de +3 dB sobre lo normal no cuenta como pico
FULL_EXCESS_DB = 11.0      # +11 dB sobre lo normal = pico completo
MIN_ONSET_DB = 4.0         # salto mínimo (dB) para contar como sorpresa
FULL_ONSET_DB = 14.0       # salto de +14 dB = sorpresa completa

LAUGH_RE = re.compile(r"\b(?:ja){2,}\w*|\bje(?:je)+\w*|\bji(?:ji)+\w*|\bjaj\w*|risas?\b", re.I)
REACTION_RE = re.compile(
    r"no puede ser|no manches|no mames|qu[eé] (?:fue|pas[oó]|haces)|\bwow\b|\bdios\b|"
    r"incre[ií]ble|\bmierda\b|\bcarajo\b|\bayuda\b|\bvamos\b|lo logr[eé]|gan[eé]|perd[ií]|"
    r"me mataron|\bmuri[oó]\b|\bnooo+\b|\bsiii+\b|\bperfecto\b|\bhijo de\b|\boye\b",
    re.I,
)


# ---------------------------------------------------------------
# Señales del texto, segundo a segundo
# ---------------------------------------------------------------

def _smooth(a: np.ndarray, width: int = 3) -> np.ndarray:
    if len(a) == 0 or width <= 1:
        return a
    return np.convolve(a, np.ones(width) / width, mode="same")


def text_signals(segments: list, n_seconds: int) -> dict:
    """Convierte los segmentos de la transcripción en señales 0-1 por segundo."""
    speech = np.zeros(n_seconds)      # palabras por segundo
    excl_q = np.zeros(n_seconds)      # signos de exclamación / pregunta
    laugh = np.zeros(n_seconds)
    react = np.zeros(n_seconds)
    has_speech = np.zeros(n_seconds)

    for seg in segments:
        a = max(int(seg["start"]), 0)
        b = min(int(np.ceil(seg["end"])), n_seconds)
        if b <= a:
            continue
        text = seg["text"]
        words = len(text.split())
        span = b - a
        speech[a:b] += words / span
        excl_q[a:b] += (text.count("!") + text.count("¡") + text.count("?") + text.count("¿")) / 2 / span
        laugh[a:b] += len(LAUGH_RE.findall(text)) / span
        react[a:b] += len(REACTION_RE.findall(text)) / span
        has_speech[a:b] = 1.0

    conversation = _smooth(speech, CONV_WINDOW) + _smooth(excl_q, CONV_WINDOW) * QUESTION_WEIGHT
    entertainment = np.clip(_smooth(laugh) * 1.5 + _smooth(react) * 1.0, 0, 1)
    return {
        "conversation": conversation,
        "entertainment": entertainment,
        "has_speech": has_speech,
        "laugh": laugh,
        "react": react,
        "excl_q": excl_q,
    }


# ---------------------------------------------------------------
# Detección
# ---------------------------------------------------------------

def _category_curves(audio: dict, text: dict, n: int, visual=None) -> dict:
    """Curvas 0-1 por segundo de cada categoría de puntuación."""
    def fit(a):
        out = np.zeros(n)
        m = min(n, len(a))
        out[:m] = a[:m]
        return out

    # Se ordena con los valores reales en dB (sin recortar) y además se exige
    # una diferencia mínima real: ser "de lo más alto" no basta si apenas se nota.
    excess = fit(audio["excess_db"])
    onset_db = fit(audio["onset_db"])
    intensity = _relative(np.clip(excess, 0, None)) * np.clip(
        (excess - MIN_EXCESS_DB) / (FULL_EXCESS_DB - MIN_EXCESS_DB), 0, 1)
    onset = _relative(onset_db) * np.clip(
        (onset_db - MIN_ONSET_DB) / (FULL_ONSET_DB - MIN_ONSET_DB), 0, 1)
    conv = _relative(fit(text["conversation"]))
    ent = fit(text["entertainment"])
    speech = fit(text["has_speech"])

    # Sorpresa: salto brusco, más creíble si alguien reacciona hablando justo después.
    speech_after = np.zeros(n)
    for t in range(n):
        speech_after[t] = speech[t + 1: t + 6].mean() if t + 1 < n else 0.0
    surprise = onset * (0.5 + 0.5 * speech_after)

    visual_curve = fit(visual["activity"]) if visual is not None else np.zeros(n)

    return {"audio": intensity, "surprise": surprise, "conversation": conv,
            "entertainment": ent, "visual": visual_curve, "speech": speech}


def _narrative_score(speech: np.ndarray, peak: int) -> float:
    """Contexto narrativo: hay habla antes Y después del momento."""
    before = speech[max(0, peak - CONTEXT_BEFORE): peak]
    after = speech[peak: peak + CONTEXT_AFTER]
    if len(before) == 0 or len(after) == 0:
        return 0.0
    return float(min(1.0, min(before.mean(), after.mean()) * 1.5))


def _snap_window(start, end, segments, duration):
    """Mueve los límites para no cortar una frase por la mitad."""
    for seg in segments:
        if seg["start"] < start < seg["end"] and start - seg["start"] <= 5:
            start = seg["start"]
        if seg["start"] < end < seg["end"] and seg["end"] - end <= 5:
            end = seg["end"]
    start = max(0.0, start)
    end = min(duration, end)
    if end - start > MAX_CLIP:
        end = start + MAX_CLIP
    if end - start < MIN_CLIP:
        end = min(duration, start + MIN_CLIP)
        start = max(0.0, end - MIN_CLIP)
    # Redondeo hacia afuera: nunca deja un clip en 59.9 s por redondeo.
    return math.floor(float(start) * 10) / 10, math.ceil(float(end) * 10) / 10


def _classify(breakdown, text_info) -> str:
    audio, surprise = breakdown["audio"], breakdown["surprise"]
    conv, ent = breakdown["conversation"], breakdown["entertainment"]
    visual = breakdown.get("visual", 0.0)
    if text_info["laugh"] > 0:
        return "humor"
    if visual >= 0.5:
        return "acción"
    if surprise >= 0.5 and audio >= 0.4:
        return "sorpresa"
    if audio >= 0.5 and ent >= 0.2:
        return "reacciones"
    if text_info["questions"] >= 6 and conv >= 0.5:
        return "discusión"
    if conv >= 0.5 and audio < 0.3:
        return "historias"
    if audio >= 0.5:
        return "tensión"
    return "otros"


def _reason(breakdown, excess_db, text_info) -> str:
    parts = []
    if breakdown["audio"] >= 0.4:
        parts.append(f"volumen inusualmente alto para esa zona (+{excess_db:.0f} dB)")
    if breakdown["surprise"] >= 0.4:
        parts.append("salto brusco de volumen seguido de reacción")
    if breakdown.get("visual", 0.0) >= 0.4:
        parts.append("mucho movimiento o cambios bruscos en pantalla")
    if text_info["laugh"] > 0:
        parts.append("risas detectadas")
    elif breakdown["entertainment"] >= 0.3:
        parts.append("palabras de reacción")
    if breakdown["conversation"] >= 0.5:
        parts.append("conversación animada")
    if text_info["questions"] >= 6:
        parts.append("muchas preguntas seguidas")
    if breakdown["narrative"] >= 0.6:
        parts.append("hay contexto hablado antes y después")
    if not parts:
        return "Señales débiles combinadas"
    text = "; ".join(parts)
    return text[0].upper() + text[1:]


def target_count(duration_seconds: float) -> int:
    """Cuántos candidatos como máximo se muestran, según la duración del video."""
    minutes = duration_seconds / 60.0
    count = round(minutes / MINUTES_PER_CANDIDATE)
    return int(max(MIN_TARGET_COUNT, min(count, MAX_TARGET_COUNT)))


def _find_peaks(strength: np.ndarray) -> list:
    from scipy.signal import find_peaks
    peaks, _ = find_peaks(strength, height=PEAK_THRESHOLD, distance=MIN_PEAK_SEPARATION)
    return [int(p) for p in peaks]   # enteros normales de Python, no de numpy


def detect_candidates(audio: dict, segments: list, duration: float, visual=None) -> list:
    """
    Devuelve la lista de candidatos ordenada de mayor a menor puntuación.

    audio    : resultado de audio_analysis.analyze_audio()
    segments : lista de {"start","end","text"} (transcripción)
    duration : duración total en segundos
    visual   : resultado de visual_analysis.compute_visual_signals() (opcional)
    """
    n = int(max(audio["seconds"], int(duration)))
    if n == 0:
        return []

    text = text_signals(segments, n)
    curves = _category_curves(audio, text, n, visual)

    total_w = sum(WEIGHTS.values())
    base_keys = ("audio", "surprise", "conversation", "entertainment")
    bonus = VISUAL_BONUS if visual is not None else 0

    # Fuerza combinada por segundo (sin "contexto", que se evalúa por ventana).
    strength = _smooth(
        sum(WEIGHTS[k] * curves[k] for k in base_keys) / total_w
        + bonus / 100.0 * curves["visual"],
        3,
    )

    excess = np.zeros(n)
    excess[: len(audio["excess_db"])] = audio["excess_db"][:n]

    candidates = []
    for peak in _find_peaks(strength):
        w_start, w_end = _snap_window(peak - CONTEXT_BEFORE, peak + CONTEXT_AFTER, segments, duration)
        core_a, core_b = max(0, peak - 5), min(n, peak + 10)

        breakdown = {k: float(curves[k][core_a:core_b].max()) for k in base_keys}
        breakdown["narrative"] = _narrative_score(curves["speech"], peak)

        base_score = sum(WEIGHTS[k] * breakdown[k] for k in WEIGHTS) / total_w * 100
        if visual is not None:
            # La acción visual se busca en TODO el clip (no solo cerca del pico de
            # voz): un tiroteo puede ocurrir segundos antes o después de la reacción.
            wa, wb = max(0, int(w_start)), min(n, int(np.ceil(w_end)))
            breakdown["visual"] = float(curves["visual"][wa:wb].max()) if wb > wa else 0.0
        score = min(100.0, base_score + bonus * breakdown.get("visual", 0.0))

        a, b = int(w_start), int(np.ceil(w_end))
        in_window = [s for s in segments if s["end"] > w_start and s["start"] < w_end]
        window_text = " ".join(s["text"] for s in in_window)
        text_info = {
            "laugh": len(LAUGH_RE.findall(window_text)),
            "questions": window_text.count("?"),
        }
        candidates.append({
            "peak_time": float(peak),
            "start": w_start,
            "end": w_end,
            "duration": round(w_end - w_start, 1),
            "score": round(score, 1),
            "breakdown": {k: round(v * 100) for k, v in breakdown.items()},
            "category": _classify(breakdown, text_info),
            "reason": _reason(breakdown, float(excess[core_a:core_b].max()), text_info),
            "transcript": window_text.strip(),
        })

    candidates = _merge(candidates)
    candidates = [c for c in candidates if c["score"] >= MIN_SCORE]
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:target_count(duration)]


def _merge(candidates: list) -> list:
    """Fusiona candidatos solapados o muy cercanos (mismo acontecimiento)."""
    ordered = sorted(candidates, key=lambda c: c["start"])
    merged = []
    for cand in ordered:
        if merged and cand["start"] - merged[-1]["end"] <= MERGE_GAP:
            prev = merged[-1]
            union_len = max(prev["end"], cand["end"]) - min(prev["start"], cand["start"])
            best = cand if cand["score"] > prev["score"] else prev
            if union_len <= MAX_CLIP:
                best = dict(best)
                best["start"] = min(prev["start"], cand["start"])
                best["end"] = max(prev["end"], cand["end"])
                best["duration"] = round(best["end"] - best["start"], 1)
                best["transcript"] = (prev["transcript"] if prev["transcript"] == cand["transcript"]
                                      else (prev["transcript"] + " " + cand["transcript"]).strip())
            merged[-1] = best
        else:
            merged.append(cand)
    return merged


# ---------------------------------------------------------------
# Prueba por consola
# ---------------------------------------------------------------

def _fmt(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def print_candidates(candidates: list):
    if not candidates:
        print("No se encontraron candidatos con la puntuación mínima.")
        return
    for i, c in enumerate(candidates, 1):
        print(f"\n#{i}  {_fmt(c['start'])} - {_fmt(c['end'])}  ({c['duration']:.0f} s)  "
              f"puntuación {c['score']:.0f}/100  [{c['category']}]")
        print(f"    Motivo: {c['reason']}")
        print(f"    Desglose (0-100): " + ", ".join(f"{k}={v}" for k, v in c["breakdown"].items()))
        snippet = c["transcript"][:160] + ("..." if len(c["transcript"]) > 160 else "")
        print(f"    Texto: {snippet}")


if __name__ == "__main__":
    import sys
    from app.engine.audio_analysis import analyze_audio

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) < 3:
        print('Uso: python -m app.engine.candidate_detection "ruta\\audio.aac" ID_DEL_VIDEO')
        sys.exit(1)

    from app.database.repository import get_visual_analysis, list_transcript_segments
    from app.engine.visual_analysis import compute_visual_signals
    video_id = int(sys.argv[2])
    segs = [{"start": r["start_time"], "end": r["end_time"], "text": r["text"]}
            for r in list_transcript_segments(video_id)]
    print(f"Segmentos de transcripción: {len(segs)}")

    audio = analyze_audio(sys.argv[1], on_progress=lambda p: print(f"  audio: {p}%", end="\r"))
    print(f"\nAudio analizado: {audio['seconds']} s")

    measures = get_visual_analysis(video_id)
    visual = compute_visual_signals(measures, audio["seconds"]) if measures else None
    print("Análisis visual: " + ("incluido" if visual is not None else "no disponible (solo audio y texto)"))

    print_candidates(detect_candidates(audio, segs, float(audio["seconds"]), visual))
