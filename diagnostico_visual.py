"""
Diagnóstico del análisis visual (no modifica nada).

Muestra qué midió la imagen en los momentos que tú consideras de acción y
cómo se compara con el resto del video.

Uso (desde C:\\ClipHunterAI, con el venv activado):

    python diagnostico_visual.py ID_DEL_VIDEO
    python diagnostico_visual.py ID_DEL_VIDEO 7:35-8:26 23:51-24:42 17:24-18:14
"""
import sys

import numpy as np

from app.database.repository import get_visual_analysis
from app.engine.visual_analysis import compute_visual_signals


def parse(t):
    parts = [int(x) for x in t.split(":")]
    sec = 0
    for p in parts:
        sec = sec * 60 + p
    return sec


def fmt(s):
    s = int(s)
    return f"{s // 60}:{s % 60:02d}"


def pct(sorted_arr, value):
    return 100.0 * np.searchsorted(sorted_arr, value, side="right") / len(sorted_arr)


video_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
if video_id is None:
    print(__doc__)
    sys.exit(1)

windows = sys.argv[2:] or ["7:35-8:26", "23:51-24:42", "17:24-18:14"]
m = get_visual_analysis(video_id)
if not m:
    print("Este video no tiene análisis de imagen guardado.")
    sys.exit(1)

iv = m["interval"]
motion = np.array(m["motion"])
changed = np.array(m["changed"])
flash = np.array(m["flash"])
n = len(motion)
sig = compute_visual_signals(m, int(n * iv))
activity = sig["activity"]
srt_m, srt_c, srt_f = np.sort(motion), np.sort(changed), np.sort(flash)

print(f"Fotogramas: {n} (uno cada {iv:g} s)")
print(f"Movimiento (0-1) del video entero: mediana {np.median(motion):.3f} | "
      f"p90 {np.percentile(motion, 90):.3f} | p99 {np.percentile(motion, 99):.3f} | máx {motion.max():.3f}")
print(f"Píxeles cambiados: mediana {np.median(changed):.2f} | p90 {np.percentile(changed, 90):.2f} | "
      f"máx {changed.max():.2f}")
print(f"Cambio de brillo medio (0-1): mediana {np.median(flash):.4f} | p90 {np.percentile(flash, 90):.4f} | "
      f"p99 {np.percentile(flash, 99):.4f} | máx {flash.max():.4f}")
print(f"Segundos con acción > 0.5: {int((activity > 0.5).sum())} de {len(activity)}")

print("\n--- Tus momentos (acción sostenida vs golpe, y cambios de brillo) ---")
print(f"{'tramo':14s} {'acción máx':>10s} {'seg >0.5':>9s} {'media 10':>9s} | "
      f"{'brillo máx':>10s} {'(percentil)':>11s} {'en':>6s} {'brillo p95 del tramo':>21s}")
for w in windows:
    a, b = (parse(x) for x in w.split("-"))
    seg = activity[a:b]
    i, j = int(a / iv), max(int(b / iv), int(a / iv) + 1)
    fl = flash[i:j]
    k = int(np.argmax(fl))
    print(f"{w:14s} {seg.max():10.2f} {int((seg > 0.5).sum()):9d} {np.sort(seg)[::-1][:10].mean():9.2f} | "
          f"{fl.max():10.4f} {pct(srt_f, fl.max()):10.0f}% {fmt((i + k) * iv):>6s} {np.percentile(fl, 95):21.4f}")
print("(si 'brillo máx' de tu escena de acción es claramente más alto que el de las de sigilo, el brillo sirve para separarlas)")

print("\n--- Los 8 instantes con más movimiento bruto ---")
for k in np.argsort(motion)[::-1][:8]:
    print(f"  {fmt(k * iv):>6s}  movimiento {motion[k]:.3f}  cambiados {changed[k]:.2f}")

print("\n--- Los 8 instantes con más cambio de brillo ---")
for k in np.argsort(flash)[::-1][:8]:
    print(f"  {fmt(k * iv):>6s}  brillo {flash[k]:.4f}")

print("\n--- Los 8 instantes con más 'acción' (lo que usa la puntuación) ---")
for t in np.argsort(activity)[::-1][:8]:
    print(f"  {fmt(t):>6s}  acción {activity[t]:.2f}")
