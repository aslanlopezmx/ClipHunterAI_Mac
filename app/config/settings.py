"""
Configuración central del proyecto.
Aquí se definen las rutas que usa el resto de la aplicación,
para no repetirlas en cada archivo.

Dos modos de ejecución:
- Desarrollo (python -m app.main): todo se guarda dentro de la carpeta del proyecto.
- App empaquetada (.app de macOS / .exe): el programa vive en una carpeta de solo
  lectura, así que los datos (base de datos, logs, modelos, cachés) van a la carpeta
  de datos del usuario, y los clips exportados a su carpeta de Películas/Videos.
"""

import os
import sys
from pathlib import Path

IS_FROZEN = bool(getattr(sys, "frozen", False))

# Carpeta con los archivos del programa (código, fuentes, binarios incluidos)
if IS_FROZEN:
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
else:
    RESOURCE_DIR = Path(__file__).resolve().parent.parent.parent


def _user_data_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "ClipHunterAI"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "ClipHunterAI"
    return home / ".local" / "share" / "ClipHunterAI"


def _user_videos_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Movies" / "ClipHunter AI"
    return home / "Videos" / "ClipHunter AI"


# Carpeta raíz donde se escriben los datos (en desarrollo = carpeta del proyecto)
BASE_DIR = _user_data_dir() if IS_FROZEN else RESOURCE_DIR

# Base de datos SQLite
DB_PATH = BASE_DIR / "cliphunter.db"

# Logs
LOG_DIR = BASE_DIR / "logs"
LOG_PATH = LOG_DIR / "app.log"

# Carpeta donde se guardan referencias a los videos originales
VIDEOS_ORIGINALS_DIR = BASE_DIR / "videos" / "originals"

# Formatos de video soportados (según el documento maestro)
SUPPORTED_VIDEO_EXTENSIONS = [".mp4", ".mkv", ".mov", ".avi", ".webm"]

# Clips exportados (Etapa 6). En la app empaquetada van a una carpeta fácil de encontrar.
CLIPS_EXPORTS_DIR = (_user_videos_dir() / "Clips") if IS_FROZEN else (BASE_DIR / "clips" / "exports")

# Archivos de subtítulos (.ass) temporales de la exportación (Etapa 6B)
SUBTITLES_CACHE_DIR = BASE_DIR / "cache" / "subtitles"

# Vistas previas rápidas de clips (Etapa 6C-2): se pueden borrar cuando se quiera
PREVIEW_CACHE_DIR = BASE_DIR / "cache" / "preview_clips"
