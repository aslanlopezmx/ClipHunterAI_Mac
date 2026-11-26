# -*- mode: python ; coding: utf-8 -*-
# Receta de PyInstaller para generar ClipHunterAI.app (macOS).
# Uso:  pyinstaller --noconfirm ClipHunterAI.spec
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    ("app/icon.png", "app"),
    ("assets/fonts", "assets/fonts"),
]
binaries = []
hiddenimports = []

# FFmpeg + ffprobe (con sus librerías) los prepara el workflow en build/bin
import os
if os.path.isdir("build/bin"):
    datas.append(("build/bin", "bin"))

# Paquetes con archivos/librerías propios que PyInstaller no detecta solo.
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "tokenizers",
            "certifi", "huggingface_hub", "hf_xet", "httpx2", "httpcore2", "httpx", "httpcore"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # paquete no instalado: se ignora
        print(f"[spec] se omite {pkg}: {exc}")

hiddenimports += collect_submodules("app")
hiddenimports += ["scipy.ndimage", "scipy.signal", "scipy.special._cdflib"]

excludes = [
    "librosa", "numba", "llvmlite", "sklearn", "yaml", "matplotlib", "tkinter",
    "IPython", "pytest",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick3D",
]

a = Analysis(
    ["run_app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ClipHunterAI",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,        # usa la arquitectura de la máquina que compila (arm64)
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ClipHunterAI")

app = BUNDLE(
    coll,
    name="ClipHunterAI.app",
    icon="packaging/icon.icns",
    bundle_identifier="ai.cliphunter.app",
    info_plist={
        "CFBundleName": "ClipHunter AI",
        "CFBundleDisplayName": "ClipHunter AI",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "13.0",
        "NSRequiresAquaSystemAppearance": False,
    },
)
