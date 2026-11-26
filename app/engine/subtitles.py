"""
Subtítulos (Etapa 6B; estilos múltiples en 6C-1).

Toma los tiempos por palabra que Faster-Whisper ya guardó en la base de datos
(Etapa 3) y arma un archivo .ass que FFmpeg "quema" dentro del video vertical.
No usa Qt y no vuelve a transcribir nada.

Estilos disponibles (ver STYLES más abajo):

    "highlight"  palabras resaltadas: 2-3 palabras a la vez, en MAYÚSCULAS, y la
                 palabra que se dice en ese instante cambia a amarillo
    "classic"    clásico: frases de hasta 2 líneas, blanco con contorno negro
    "minimal"    minimalista: frases pequeñas y discretas, contorno fino

Dónde se ponen (zona segura), según la composición del video:
  - "camera": en el panel del gameplay, justo encima de la cámara del streamer.
    Si el juego deja franja desenfocada debajo, el texto va ahí.
  - "full": debajo del juego, sin llegar a la zona que tapan los botones de
    TikTok/Reels.
  - "crop": el video llena todo el cuadro; el texto va en la zona segura baja.

Dato de diseño: los "chunks" (frases cortas) se guardan con tiempos del VIDEO
ORIGINAL (no del clip). Así, si el usuario ajusta el inicio/fin del clip, los
subtítulos siguen siendo válidos; solo se recortan y se desplazan al exportar.

Prueba por consola (desde C:\\ClipHunterAI, con el venv activado):

    python -m app.engine.subtitles ID_VIDEO INICIO FIN "salida.ass" [estilo] [layout]

  estilo: highlight (por defecto), classic o minimal
  layout: camera (por defecto; sin cámara marcada se usa full), full o crop
"""

import json
import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------
# Parámetros ajustables (estilo "palabras resaltadas")
# ---------------------------------------------------------------
OUT_W, OUT_H = 1080, 1920
TOP_H = 1152                  # alto del panel del gameplay cuando hay cámara
# Windows: Arial del sistema. Otros sistemas: Liberation Sans (incluida en assets/fonts,
# mismas medidas que Arial), para no depender de las fuentes instaladas.
FONT_NAME = "Arial" if sys.platform == "win32" else "Liberation Sans"
COLOR_TEXT = (255, 255, 255)        # RGB: palabras normales
COLOR_ACTIVE = (255, 221, 0)        # RGB: palabra que se dice ahora (solo "highlight")
COLOR_OUTLINE = (0, 0, 0)
SIDE_MARGIN = 70
SAFE_BOTTOM = 1540            # más abajo tapan los botones/descripción de TikTok y Reels

PAUSE_BREAK = 0.6             # s de pausa entre palabras que obliga a cambiar de pantalla
HOLD_AFTER = 0.20             # s que se queda la última palabra tras decirse
MIN_WORD_DURATION = 0.08
MAX_WORD_DURATION = 1.2       # una palabra "larga" por error del modelo no se queda congelada

# Estilos. per_word=True: una pantalla por palabra con la palabra activa resaltada.
# per_word=False: una sola pantalla por frase. soft_min = palabras mínimas para que
# una coma corte la pantalla. min_show = tiempo mínimo en pantalla de una frase.
STYLES = {
    "highlight": {
        "label": "Palabras resaltadas",
        "per_word": True, "uppercase": True,
        "font_size": 80, "bold": True, "outline": 7, "shadow": 2,
        "max_words": 3, "max_chars": 18, "soft_min": 2, "min_show": 0.0,
    },
    "classic": {
        "label": "Clásico (frases)",
        "per_word": False, "uppercase": False,
        "font_size": 64, "bold": True, "outline": 5, "shadow": 1,
        "max_words": 7, "max_chars": 38, "soft_min": 3, "min_show": 1.0,
    },
    "minimal": {
        "label": "Minimalista",
        "per_word": False, "uppercase": False,
        "font_size": 48, "bold": False, "outline": 3, "shadow": 0,
        "max_words": 6, "max_chars": 30, "soft_min": 3, "min_show": 0.9,
    },
}
DEFAULT_STYLE = "highlight"


def get_style(name) -> dict:
    """Parámetros de un estilo (si el nombre no existe, el estilo por defecto)."""
    return STYLES.get(name, STYLES[DEFAULT_STYLE])


_PUNCT_END = re.compile(r"[.!?…]$")
_PUNCT_SOFT = re.compile(r"[,;:]$")


# ---------------------------------------------------------------
# 1) Palabras -> chunks (frases cortas)
# ---------------------------------------------------------------

def words_from_segments(segments, start: float, end: float) -> list:
    """
    Palabras (con tiempos del video original) que caen dentro de [start, end].

    `segments`: filas de list_transcript_segments() o diccionarios con
    start_time / end_time / text / words_json. Si un segmento no trae tiempos
    por palabra, se reparte su texto de forma pareja en el tiempo del segmento.
    """
    out = []
    for seg in segments:
        s_start, s_end = float(seg["start_time"]), float(seg["end_time"])
        if s_end < start or s_start > end:
            continue

        raw = seg["words_json"] if "words_json" in seg.keys() else None
        try:
            words = json.loads(raw) if raw else []
        except (TypeError, ValueError):
            words = []

        if not words:
            tokens = str(seg["text"]).split()
            if not tokens:
                continue
            step = max(s_end - s_start, 0.1) / len(tokens)
            words = [{"start": s_start + i * step, "end": s_start + (i + 1) * step, "word": t}
                     for i, t in enumerate(tokens)]

        for w in words:
            text = str(w.get("word", "")).strip()
            if not text:
                continue
            w_start, w_end = float(w["start"]), float(w["end"])
            if w_end < start or w_start > end:
                continue
            out.append({"start": w_start, "end": max(w_end, w_start + MIN_WORD_DURATION),
                        "text": text})
    out.sort(key=lambda x: x["start"])
    return out


def build_chunks(words: list, style: str = DEFAULT_STYLE) -> list:
    """
    Agrupa palabras en pantallas de 1 a max_words palabras (según el estilo).
    Corta cuando: hay una pausa, termina una frase (. ! ?), se llena la
    pantalla por número de palabras o por cantidad de letras.
    Cada chunk: {"start", "end", "words": [{"start","end","text"}, ...]}.
    """
    st = get_style(style)
    max_words, max_chars, soft_min = st["max_words"], st["max_chars"], st["soft_min"]
    chunks, current = [], []

    def flush():
        if current:
            chunks.append({
                "start": current[0]["start"],
                "end": current[-1]["end"],
                "words": [dict(w) for w in current],
            })
            current.clear()

    for w in words:
        if current:
            gap = w["start"] - current[-1]["end"]
            chars = sum(len(x["text"]) + 1 for x in current) + len(w["text"])
            if gap > PAUSE_BREAK or len(current) >= max_words or chars > max_chars:
                flush()
        current.append(w)
        if _PUNCT_END.search(w["text"]) or (_PUNCT_SOFT.search(w["text"]) and len(current) >= soft_min):
            flush()
    flush()
    return chunks


def chunks_for_clip(segments, start: float, end: float, style: str = DEFAULT_STYLE) -> list:
    """Chunks automáticos de un tramo del video (tiempos del video original)."""
    return build_chunks(words_from_segments(segments, start, end), style)


def regroup_chunks(chunks: list, style: str = DEFAULT_STYLE) -> list:
    """
    Vuelve a agrupar en pantallas, según el estilo, las palabras de unos chunks
    ya existentes (por ejemplo, correcciones guardadas con otro estilo). Conserva
    el texto y los tiempos de cada palabra.
    """
    words = sorted((dict(w) for c in chunks for w in c["words"]), key=lambda w: w["start"])
    return build_chunks(words, style)


# ---------------------------------------------------------------
# 2) Corrección manual: texto editado -> palabras con tiempos
# ---------------------------------------------------------------

def chunk_text(chunk: dict) -> str:
    return " ".join(w["text"] for w in chunk["words"])


def apply_text_edit(chunk: dict, new_text: str):
    """
    Devuelve el chunk con el texto corregido, o None si el texto quedó vacío
    (la pantalla se elimina). Si el usuario solo cambió letras de palabras que
    ya existían, se conservan los tiempos de cada palabra; si cambió la
    cantidad de palabras, se reparte el tiempo del chunk según el largo.
    """
    tokens = new_text.split()
    if not tokens:
        return None
    old = chunk["words"]
    if len(tokens) == len(old):
        return {"start": chunk["start"], "end": chunk["end"],
                "words": [{"start": o["start"], "end": o["end"], "text": t}
                          for o, t in zip(old, tokens)]}

    total = (chunk["end"] - chunk["start"]) or 0.1 * len(tokens)
    weights = [len(t) + 1 for t in tokens]
    scale = total / sum(weights)
    words, t0 = [], chunk["start"]
    for token, wt in zip(tokens, weights):
        t1 = t0 + wt * scale
        words.append({"start": t0, "end": t1, "text": token})
        t0 = t1
    return {"start": chunk["start"], "end": chunk["end"], "words": words}


# ---------------------------------------------------------------
# 3) Chunks -> archivo .ass
# ---------------------------------------------------------------

def _ass_color(rgb) -> str:
    r, g, b = rgb
    return f"&H00{b:02X}{g:02X}{r:02X}&"


def _ass_time(seconds: float) -> str:
    cs = int(round(max(seconds, 0.0) * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _clean(text: str, uppercase: bool = True) -> str:
    """Quita lo que ASS interpretaría como código."""
    text = text.replace("\\", " ").replace("{", "(").replace("}", ")").replace("\n", " ")
    return text.upper() if uppercase else text


def subtitle_bottom_y(src_w: int, src_h: int, layout: str = "camera") -> int:
    """
    Coordenada Y (en el cuadro de 1080x1920) donde queda el BORDE INFERIOR del
    texto. `layout` es la composición REAL ("camera", "full" o "crop"; ver
    export_service.effective_layout). Ver la explicación de zonas en la cabecera.
    """
    if layout == "crop":
        return SAFE_BOTTOM                    # el video llena todo el cuadro
    panel_h = TOP_H if layout == "camera" else OUT_H
    fg_h = min(panel_h, OUT_W * src_h / max(src_w, 1))
    fg_bottom = (panel_h + fg_h) / 2
    gap = panel_h - fg_bottom
    if gap >= 200:
        # Hay franja desenfocada bajo el juego: el texto va al fondo del panel.
        y = fg_bottom + min(gap, 300) - 30
    else:
        y = panel_h - 40
    return int(round(min(y, SAFE_BOTTOM)))


def build_ass(chunks: list, clip_start: float, clip_end: float,
              src_w: int, src_h: int, layout: str = "camera",
              style: str = DEFAULT_STYLE) -> str:
    """
    Texto completo del archivo .ass para un clip. Los chunks vienen con tiempos
    del video original; aquí se recortan a [clip_start, clip_end] y se
    desplazan para que 0 s = inicio del clip (que es lo que ve FFmpeg).
    """
    st = get_style(style)
    bottom = subtitle_bottom_y(src_w, src_h, layout)
    margin_v = OUT_H - bottom
    bold = -1 if st["bold"] else 0
    upper = st["uppercase"]

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {OUT_W}\nPlayResY: {OUT_H}\n"
        "WrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{FONT_NAME},{st['font_size']},{_ass_color(COLOR_TEXT)},{_ass_color(COLOR_ACTIVE)},"
        f"{_ass_color(COLOR_OUTLINE)},&H80000000&,{bold},0,0,0,100,100,0,0,1,{st['outline']},"
        f"{st['shadow']},2,{SIDE_MARGIN},{SIDE_MARGIN},{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    hi = _ass_color(COLOR_ACTIVE)
    base = _ass_color(COLOR_TEXT)
    lines = []
    duration = max(clip_end - clip_start, 0.0)

    # Primero se recortan los chunks al clip y se pasan a tiempos del clip.
    trimmed = []
    for chunk in chunks:
        words = []
        for w in chunk["words"]:
            ws, we = float(w["start"]) - clip_start, float(w["end"]) - clip_start
            if we <= 0 or ws >= duration:
                continue
            words.append({"start": max(ws, 0.0), "end": min(we, duration), "text": w["text"]})
        if words:
            trimmed.append(words)
    trimmed.sort(key=lambda ws: ws[0]["start"])

    for n, words in enumerate(trimmed):
        # La pantalla nunca debe seguir visible cuando empieza la siguiente.
        limit = trimmed[n + 1][0]["start"] if n + 1 < len(trimmed) else duration

        if not st["per_word"]:
            # Una sola pantalla por frase (estilos "classic" y "minimal").
            start = words[0]["start"]
            last = words[-1]
            end = min(last["end"], last["start"] + MAX_WORD_DURATION) + HOLD_AFTER
            end = max(end, start + st["min_show"])
            end = min(end, limit, duration)
            if end - start < MIN_WORD_DURATION:
                continue
            text = " ".join(_clean(w["text"], upper) for w in words)
            lines.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}"
            )
            continue

        for i, w in enumerate(words):
            last = i + 1 == len(words)
            if not last:
                end_i = words[i + 1]["start"]
                end_i = min(end_i, w["start"] + MAX_WORD_DURATION)
            else:
                end_i = min(w["end"] + HOLD_AFTER, w["start"] + MAX_WORD_DURATION + HOLD_AFTER)
            end_i = min(end_i, limit, duration)
            if end_i - w["start"] < MIN_WORD_DURATION:
                end_i = min(w["start"] + MIN_WORD_DURATION, limit, duration)
            if end_i <= w["start"]:
                continue

            parts = []
            for j, other in enumerate(words):
                txt = _clean(other["text"], upper)
                if j == i:
                    parts.append(f"{{\\1c{hi}}}{txt}{{\\1c{base}}}")
                else:
                    parts.append(txt)
            lines.append(
                f"Dialogue: 0,{_ass_time(w['start'])},{_ass_time(end_i)},Default,,0,0,0,,"
                + " ".join(parts)
            )

    return header + "\n".join(lines) + "\n"


def write_ass(path, chunks: list, clip_start: float, clip_end: float,
              src_w: int, src_h: int, layout: str = "camera",
              style: str = DEFAULT_STYLE):
    """
    Escribe el .ass en `path` (UTF-8 con BOM, que es lo que mejor leen FFmpeg y
    Windows con tildes). Devuelve la ruta, o None si el clip no tiene texto
    (en ese caso se exporta sin subtítulos).
    """
    text = build_ass(chunks, clip_start, clip_end, src_w, src_h, layout, style)
    if "Dialogue:" not in text:
        return None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8-sig")
    return path


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)

    from app.database.repository import get_video_camera, list_transcript_segments, list_videos  # noqa
    import sqlite3
    from app.config.settings import DB_PATH

    vid, a, b, dst = int(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
    style_arg = sys.argv[5] if len(sys.argv) >= 6 else DEFAULT_STYLE
    layout_arg = sys.argv[6] if len(sys.argv) >= 7 else "camera"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    video = conn.execute("SELECT * FROM videos WHERE id = ?", (vid,)).fetchone()
    conn.close()
    if video is None:
        print("No existe ese video.")
        sys.exit(1)
    from app.engine.export_service import effective_layout
    real_layout = effective_layout(layout_arg, get_video_camera(vid))
    segs = list_transcript_segments(vid)
    chunks = chunks_for_clip(segs, a, b, style_arg)
    out = write_ass(dst, chunks, a, b, video["width"], video["height"], real_layout, style_arg)
    print(f"{len(chunks)} pantallas de texto (estilo {style_arg}, composición {real_layout}) -> {out}")
    for c in chunks[:15]:
        print(f"  {c['start'] - a:6.1f}s  {chunk_text(c)}")
