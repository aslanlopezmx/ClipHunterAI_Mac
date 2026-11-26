# Cambios para macOS (para actualizar CONTEXT.md)

Archivos nuevos: app/utils/binaries.py (busca FFmpeg/ffprobe y fuentes), run_app.py (entrada del
empaquetado), ClipHunterAI.spec (PyInstaller), requirements-mac.txt, .github/workflows/build-mac.yml,
assets/fonts/ (Liberation Sans), packaging/icon.icns, GUIA_PARA_MAC.md, GUIA_GITHUB.md.
Eliminados en esta copia: .bat, .vbs, actualizar_tema.py, desktop.ini.

Modificados:
- config/settings.py: nuevos IS_FROZEN, RESOURCE_DIR; en la app empaquetada BASE_DIR pasa a
  ~/Library/Application Support/ClipHunterAI y CLIPS_EXPORTS_DIR a ~/Movies/ClipHunter AI/Clips.
- main.py: stdout/stderr seguros sin consola, fontconfig minimo, modo --selftest.
- utils/logger.py: no usa consola si no existe.
- utils/metadata.py, workers/video_processing_worker.py, engine/{audio_analysis,visual_analysis,
  export_service}.py: usan FFMPEG/FFPROBE de binaries.py en vez de "ffmpeg" del PATH.
- engine/export_service.py: el filtro subtitles añade fontsdir fuera de Windows.
- engine/subtitles.py: FONT_NAME = Liberation Sans fuera de Windows (Arial en Windows).
- engine/transcription_service.py: CPU_THREADS = 4 en macOS.
