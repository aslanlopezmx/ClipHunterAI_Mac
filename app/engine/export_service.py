"""
Exportación de clips a video vertical 9:16 (Etapa 6A).

Toma un tramo del video original (inicio-fin en segundos) y genera un MP4
de 1080 x 1920 con FFmpeg, sin tocar el original. No usa Qt.

Composición (la elegida para esta etapa: "gameplay arriba, cámara abajo"):

    +---------------------+
    |      GAMEPLAY       |   1080 x 1152   juego completo, centrado, con el
    |  (fondo desenfocado)|                 mismo video desenfocado de fondo
    +---------------------+
    |       CÁMARA        |   1080 x 768    recorte de la región de la cámara
    +---------------------+

Si el video no tiene región de cámara definida, el gameplay ocupa todo el
cuadro vertical (con fondo desenfocado).

Etapa 6C-1: hay tres composiciones (parámetro `layout`):

    "camera"  gameplay arriba + cámara abajo (la de arriba; sin cámara marcada
              se comporta como "full")
    "full"    gameplay completo: el video entero centrado, con fondo desenfocado
    "crop"    recorte centrado: el video llena todo el cuadro vertical (se pierden
              los lados, pero el centro se ve grande)

Etapa 6C-2: con `preview=True` se genera una muestra rápida y liviana (540 x 960,
calidad baja) para ver cómo quedará el clip antes de exportarlo de verdad.

Los subtítulos (Etapa 6B) se queman con el parámetro `subtitles_path` (archivo .ass).

Prueba por consola (desde C:\\ClipHunterAI, con el venv activado):

    python -m app.engine.export_service "video.mp4" INICIO FIN "salida.mp4" [x y w h]

  INICIO y FIN en segundos; x y w h (opcionales) = región de la cámara en
  fracciones 0-1 del cuadro, por ejemplo: 0.70 0.65 0.28 0.31
  Opcional al final: layout=full  o  layout=crop  (por defecto: camera)
"""

import logging
import re
import subprocess
import time
from pathlib import Path

from app.utils.binaries import FFMPEG, fonts_dir
from app.utils.geometry import CAM_PANEL_H, CAM_PANEL_W, to_pixels

logger = logging.getLogger(__name__)

OUT_W, OUT_H = 1080, 1920
TOP_H = OUT_H - CAM_PANEL_H            # 1152
CRF = 20                               # calidad (menor = mejor y más pesado)
PRESET = "veryfast"                    # velocidad de codificación en CPU
AUDIO_BITRATE = "160k"
BLUR_SCALE = 4                         # el fondo se desenfoca en baja resolución (mucho más rápido)

# Vista previa (6C-2): misma composición, pero pequeña y rápida de generar
PREVIEW_W, PREVIEW_H = 540, 960
PREVIEW_PRESET = "ultrafast"
PREVIEW_CRF = 30
PREVIEW_SECONDS = 12                   # duración de la muestra

# Composiciones disponibles (Etapa 6C-1): clave -> texto que ve el usuario
LAYOUTS = {
    "camera": "Gameplay arriba + cámara abajo",
    "full": "Gameplay completo (fondo desenfocado)",
    "crop": "Recorte centrado (pantalla llena)",
}
DEFAULT_LAYOUT = "camera"
# Sufijo del nombre de archivo para no pisar el clip hecho con otra composición
LAYOUT_FILE_TAG = {"camera": "", "full": "completo", "crop": "centrado"}


def effective_layout(layout, camera) -> str:
    """Composición que realmente se usa: "camera" sin cámara marcada equivale a "full"."""
    if layout not in LAYOUTS:
        layout = DEFAULT_LAYOUT
    if layout == "camera" and not camera:
        return "full"
    return layout


class ExportCancelled(Exception):
    """Se lanza cuando el usuario cancela la exportación."""


def _ffmpeg_escape_path(path) -> str:
    """Ruta segura para usar dentro de un filtro de FFmpeg (subtítulos)."""
    p = str(path).replace("\\", "/")
    return p.replace(":", "\\:").replace("'", r"\'")


def build_filter(src_w: int, src_h: int, camera=None, subtitles_path=None,
                 layout: str = DEFAULT_LAYOUT) -> str:
    """
    Cadena de filtros de FFmpeg para la composición vertical.

    camera : (fx, fy, fw, fh) en fracciones 0-1 del cuadro, o None.
    layout : "camera", "full" o "crop" (ver la cabecera del archivo).
    """
    def blur_bg(w, h):
        sw, sh = w // BLUR_SCALE, h // BLUR_SCALE
        return (f"scale={sw}:{sh}:force_original_aspect_ratio=increase,"
                f"crop={sw}:{sh},boxblur=6:2,scale={w}:{h}")

    mode = effective_layout(layout, camera)
    if mode == "camera":
        cx, cy, cw, ch = to_pixels(camera, src_w, src_h)
        graph = (
            "[0:v]split=3[a][b][c];"
            f"[a]{blur_bg(OUT_W, TOP_H)}[bg];"
            f"[b]scale={OUT_W}:{TOP_H}:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[top];"
            f"[c]crop={cw}:{ch}:{cx}:{cy},scale={CAM_PANEL_W}:{CAM_PANEL_H}[cam];"
            "[top][cam]vstack=inputs=2[v0]"
        )
    elif mode == "crop":
        graph = (
            f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{OUT_H}[v0]"
        )
    else:  # "full"
        graph = (
            "[0:v]split=2[a][b];"
            f"[a]{blur_bg(OUT_W, OUT_H)}[bg];"
            f"[b]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[v0]"
        )

    if subtitles_path:                       # Etapa 6B
        fonts = fonts_dir()
        extra = f":fontsdir='{_ffmpeg_escape_path(fonts)}'" if fonts else ""
        graph += f";[v0]subtitles='{_ffmpeg_escape_path(subtitles_path)}'{extra}[v]"
    else:
        graph += ";[v0]null[v]"
    return graph


def build_command(video_path, start, end, out_path, src_w, src_h,
                  camera=None, subtitles_path=None, layout=DEFAULT_LAYOUT,
                  preview=False) -> list:
    duration = max(float(end) - float(start), 0.1)
    graph = build_filter(src_w, src_h, camera, subtitles_path, layout)
    if preview:
        # Los subtítulos se dibujan a 1080x1920 (como en el clip final) y luego se reduce.
        graph += f";[v]scale={PREVIEW_W}:{PREVIEW_H}[vp]"
    return [
        FFMPEG, "-y", "-v", "error", "-nostdin",
        "-ss", f"{float(start):.3f}", "-t", f"{duration:.3f}",
        "-i", str(video_path),
        "-filter_complex", graph,
        "-map", "[vp]" if preview else "[v]", "-map", "0:a:0?",
        "-c:v", "libx264",
        "-preset", PREVIEW_PRESET if preview else PRESET,
        "-crf", str(PREVIEW_CRF if preview else CRF),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k" if preview else AUDIO_BITRATE,
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        str(out_path),
    ]


def export_clip(video_path, start, end, out_path, src_w, src_h, camera=None,
                subtitles_path=None, on_progress=None, should_cancel=None,
                layout=DEFAULT_LAYOUT, preview=False) -> Path:
    """
    Exporta un clip. Devuelve la ruta del MP4 creado.

    on_progress(percent 0-100) y should_cancel() son opcionales.
    Si falla o se cancela, no deja un archivo a medias.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    duration = max(float(end) - float(start), 0.1)

    cmd = build_command(video_path, start, end, out_path, src_w, src_h,
                        camera, subtitles_path, layout, preview)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, creationflags=flags)
    last = -1
    ok = False
    try:
        for line in proc.stdout:
            if should_cancel and should_cancel():
                raise ExportCancelled()
            m = re.match(r"out_time_us=(\d+)", line)
            if m and on_progress:
                pct = min(int(int(m.group(1)) / 1e6 / duration * 100), 99)
                if pct != last:
                    last = pct
                    on_progress(pct)
        proc.wait()
        if proc.returncode != 0:
            err = proc.stderr.read()[-600:]
            raise RuntimeError(f"FFmpeg no pudo exportar el clip: {err}")
        ok = True
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
        proc.stderr.close()
        if not ok and out_path.exists():
            try:
                out_path.unlink()
            except OSError:
                logger.warning("No se pudo borrar el archivo incompleto: %s", out_path)

    if on_progress:
        on_progress(100)
    return out_path


def preview_range(clip_start: float, clip_end: float, position=None):
    """
    Tramo de la vista previa: PREVIEW_SECONDS desde `position` (segundos del video
    original) si cae dentro del clip; si no, desde el inicio del clip.
    """
    start = float(clip_start)
    if position is not None and clip_start <= position < clip_end - 1.0:
        start = float(position)
    return start, min(float(clip_end), start + PREVIEW_SECONDS)


def extract_frame_png(video_path, seconds: float) -> bytes:
    """Un fotograma del video (PNG en memoria), para definir la región de la cámara."""
    cmd = [
        FFMPEG, "-v", "error", "-nostdin", "-ss", f"{max(float(seconds), 0):.3f}",
        "-i", str(video_path), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-",
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(cmd, capture_output=True, creationflags=flags, timeout=60)
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError("No se pudo leer un fotograma del video: "
                           + result.stderr.decode("utf-8", "ignore")[-300:])
    return result.stdout


def safe_name(text: str) -> str:
    """Nombre de archivo sin caracteres que Windows no acepta."""
    return re.sub(r'[<>:"/\\|?*\s]+', "_", text).strip("._") or "clip"


def default_output_path(exports_dir, video_filename, candidate_id, start, end,
                        layout=DEFAULT_LAYOUT) -> Path:
    """Ruta de salida. La composición por defecto no lleva sufijo (nombres de siempre)."""
    stem = safe_name(Path(video_filename).stem)
    tag = LAYOUT_FILE_TAG.get(layout, "")
    suffix = f"_{tag}" if tag else ""
    return Path(exports_dir) / f"{stem}_clip{candidate_id}_{int(start)}-{int(end)}{suffix}.mp4"


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)
    args = [x for x in sys.argv[1:] if not x.startswith("layout=")]
    layout_arg = next((x.split("=", 1)[1] for x in sys.argv[1:] if x.startswith("layout=")), DEFAULT_LAYOUT)
    if len(args) < 4:
        print(__doc__)
        sys.exit(1)
    src, a, b, dst = args[0], float(args[1]), float(args[2]), args[3]
    cam = tuple(float(v) for v in args[4:8]) if len(args) >= 8 else None

    from app.utils.metadata import get_video_metadata
    meta = get_video_metadata(src)
    t0 = time.perf_counter()
    out = export_clip(src, a, b, dst, meta["width"], meta["height"], cam,
                      on_progress=lambda p: print(f"  exportando: {p}%", end="\r"),
                      layout=layout_arg)
    took = time.perf_counter() - t0
    print(f"\nListo: {out}  ({took:.1f} s para {b - a:.0f} s de video, {(b - a) / max(took, 0.01):.1f}x)")
