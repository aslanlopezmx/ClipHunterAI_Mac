"""
Lee las propiedades de un archivo de video (duración, resolución,
fps, códecs, tamaño) usando ffprobe, que viene incluido con FFmpeg.
"""

import json
import subprocess
from pathlib import Path

from app.utils.binaries import FFPROBE


def get_video_metadata(filepath: str) -> dict:
    """
    Devuelve un diccionario con los datos del video.
    Lanza RuntimeError si ffprobe no puede leer el archivo
    (por ejemplo, si no es un video válido).
    """
    cmd = [
        FFPROBE,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(filepath),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    if result.returncode != 0:
        raise RuntimeError(f"ffprobe no pudo leer el archivo: {result.stderr.strip()}")

    data = json.loads(result.stdout)

    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), None
    )
    audio_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None
    )
    fmt = data.get("format", {})

    duration_seconds = float(fmt.get("duration", 0))

    fps = None
    if video_stream and video_stream.get("avg_frame_rate") not in (None, "0/0"):
        num, _, den = video_stream["avg_frame_rate"].partition("/")
        try:
            fps = round(float(num) / float(den), 2) if float(den) != 0 else None
        except (ValueError, ZeroDivisionError):
            fps = None

    return {
        "filepath": str(filepath),
        "filename": Path(filepath).name,
        "duration_seconds": round(duration_seconds, 2),
        "width": video_stream.get("width") if video_stream else None,
        "height": video_stream.get("height") if video_stream else None,
        "fps": fps,
        "video_codec": video_stream.get("codec_name") if video_stream else None,
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
        "size_bytes": int(fmt.get("size", 0)),
    }
