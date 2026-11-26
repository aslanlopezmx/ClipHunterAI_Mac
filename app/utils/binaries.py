"""
Localiza FFmpeg y ffprobe, y las fuentes de los subtítulos.

Orden de búsqueda:
1) Los incluidos dentro de la app empaquetada (carpeta "bin").
2) El PATH del sistema.
3) Rutas típicas de Homebrew (una app de macOS abierta con doble clic NO hereda
   el PATH de la terminal, por eso hay que buscar ahí explícitamente).
"""

import shutil
import sys
from pathlib import Path

from app.config.settings import RESOURCE_DIR

_EXTRA_DIRS = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]


def _find(name: str) -> str:
    exe = name + (".exe" if sys.platform == "win32" else "")

    bundled = [RESOURCE_DIR / "bin" / exe]
    if getattr(sys, "frozen", False):
        # Estructura de un .app: Contents/MacOS/<exe> y Contents/Resources/bin
        bundled.append(Path(sys.executable).resolve().parent.parent / "Resources" / "bin" / exe)
        bundled.append(Path(sys.executable).resolve().parent / "bin" / exe)
    for path in bundled:
        if path.is_file():
            return str(path)

    found = shutil.which(name)
    if found:
        return found

    for folder in _EXTRA_DIRS:
        path = Path(folder) / exe
        if path.is_file():
            return str(path)

    return name  # que falle con el mensaje normal de "no se encontró"


FFMPEG = _find("ffmpeg")
FFPROBE = _find("ffprobe")


def fonts_dir():
    """
    Carpeta con las fuentes de los subtítulos, o None si no hace falta.
    En Windows se usa Arial del sistema (igual que siempre). En otros sistemas
    se usa la fuente incluida (Liberation Sans, equivalente a Arial) para que los
    subtítulos se vean igual sin depender de las fuentes instaladas.
    """
    if sys.platform == "win32":
        return None
    folder = RESOURCE_DIR / "assets" / "fonts"
    return folder if any(folder.glob("*.ttf")) else None
