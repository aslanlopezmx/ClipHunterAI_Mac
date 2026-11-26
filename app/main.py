"""
Punto de entrada de ClipHunter AI.

Desarrollo (desde la raíz del proyecto, con el entorno virtual activo):

    python -m app.main

La app empaquetada (.app de macOS) arranca desde run_app.py, que llama a main().
Comprobación interna del paquete: ClipHunterAI --selftest
"""

import os
import sys
from pathlib import Path

# Una app sin consola (doble clic en el .app) no tiene stdout/stderr; algunas
# librerías (tqdm al descargar el modelo) fallan si escriben en None.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# Permite importar "app.xxx" al ejecutar este archivo directamente
sys.path.append(str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.config.settings import BASE_DIR, IS_FROZEN
from app.utils.logger import setup_logger
from app.database.repository import init_database
from app.interface.theme import apply_theme
from app.interface.main_window import MainWindow

ICON_PATH = Path(__file__).resolve().parent / "icon.png"


def _setup_fontconfig():
    """
    El FFmpeg incluido en la app busca fuentes con fontconfig, que en un Mac limpio
    no tiene configuración. Se genera una mínima que apunta a las fuentes del sistema.
    """
    if sys.platform != "darwin" or not IS_FROZEN:
        return
    try:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        conf = BASE_DIR / "fonts.conf"
        conf.write_text(
            '<?xml version="1.0"?>\n'
            '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
            "<fontconfig>\n"
            "  <dir>/System/Library/Fonts</dir>\n"
            "  <dir>/Library/Fonts</dir>\n"
            "  <dir>~/Library/Fonts</dir>\n"
            f"  <cachedir>{BASE_DIR / 'fontcache'}</cachedir>\n"
            "</fontconfig>\n",
            encoding="utf-8",
        )
        os.environ["FONTCONFIG_FILE"] = str(conf)
    except OSError:
        pass


def selftest() -> int:
    """Comprobación rápida de que el paquete tiene todo lo necesario (sin abrir la interfaz)."""
    import subprocess
    import tempfile

    from app.utils.binaries import FFMPEG, FFPROBE, fonts_dir

    problems = []

    def check(label, fn):
        try:
            fn()
            print(f"  ok  {label}")
        except Exception as exc:  # noqa: BLE001
            problems.append(label)
            print(f"  FALLA  {label}: {exc}")

    def imports():
        import av, ctranslate2, faster_whisper, numpy, onnxruntime  # noqa: F401
        import scipy.ndimage, scipy.signal  # noqa: F401
        from PySide6 import QtMultimedia, QtMultimediaWidgets  # noqa: F401

    def vad_asset():
        import faster_whisper
        assets = Path(faster_whisper.__file__).resolve().parent / "assets"
        if not list(assets.glob("*.onnx")):
            raise RuntimeError(f"falta el modelo de detección de voz en {assets}")

    def run(cmd):
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip()[-300:])
        return out.stdout

    def ffmpeg_features():
        run([FFPROBE, "-version"])
        filters = run([FFMPEG, "-hide_banner", "-filters"])
        encoders = run([FFMPEG, "-hide_banner", "-encoders"])
        for needed, text in (("subtitles", filters), ("boxblur", filters), ("libx264", encoders)):
            if needed not in text:
                raise RuntimeError(f"a este FFmpeg le falta: {needed}")

    def burn_subtitles():
        from app.engine.export_service import _ffmpeg_escape_path
        ass = (
            "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 240\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
            "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, "
            "Encoding\nStyle: Default,Liberation Sans,30,&H00FFFFFF,&H00FFFFFF,&H00000000,"
            "&H80000000,-1,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n\n[Events]\nFormat: Layer, Start, "
            "End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Prueba\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            ass_path = Path(tmp) / "t.ass"
            ass_path.write_text(ass, encoding="utf-8")
            fonts = fonts_dir()
            extra = f":fontsdir='{_ffmpeg_escape_path(fonts)}'" if fonts else ""
            vf = f"subtitles='{_ffmpeg_escape_path(ass_path)}'{extra}"
            run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1",
                 "-vf", vf, "-c:v", "libx264", "-f", "null", "-"])

    def window():
        setup_logger()
        init_database()
        app = QApplication.instance() or QApplication(sys.argv)
        apply_theme(app)
        win = MainWindow()
        win.close()

    print(f"FFmpeg: {FFMPEG}\nffprobe: {FFPROBE}\nFuentes: {fonts_dir()}")
    check("librerías (Qt, faster-whisper, numpy, scipy...)", imports)
    check("modelo de detección de voz incluido", vad_asset)
    check("FFmpeg con subtítulos y libx264", ffmpeg_features)
    check("quemar subtítulos en un video de prueba", burn_subtitles)
    check("crear la ventana principal", window)

    print("SELFTEST OK" if not problems else f"SELFTEST FALLÓ: {', '.join(problems)}")
    return 0 if not problems else 1


def main():
    _setup_fontconfig()
    if "--selftest" in sys.argv:
        sys.exit(selftest())

    setup_logger()
    init_database()

    # Hace que Windows muestre el icono de la app en la barra de tareas
    # (si no, muestra el de Python).
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("cliphunter.ai")
    except Exception:
        pass

    app = QApplication(sys.argv)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    apply_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
