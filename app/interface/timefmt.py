"""
Formato único de tiempos para toda la app.

Se muestra como H:MM:SS (1:08:14) o como M:SS (8:14) cuando todo dura menos de
una hora. En los campos de edición se añade una décima solo si hace falta
(1:08:14.5). También se pueden escribir segundos sueltos (4094.8).
"""

import math
import re

_DIGITS = re.compile(r"[0-9]+")
_SECONDS = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def format_time(seconds, precise: bool = False, hours=None) -> str:
    """
    Convierte segundos a texto.

    precise=False redondea a segundos enteros (listas y etiquetas).
    precise=True agrega una décima solo si el tiempo no es entero (campos de edición).
    hours=None muestra horas solo si el tiempo llega a 1 h; hours=True las muestra
    siempre (útil para que todos los tiempos de un video de varias horas se vean igual).
    """
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        value = 0.0
    if not math.isfinite(value) or value < 0:
        value = 0.0

    tenths_total = int(round(value * 10))
    if precise:
        whole, tenth = divmod(tenths_total, 10)
    else:
        whole, tenth = int(round(value)), 0

    hrs, rest = divmod(whole, 3600)
    mins, secs = divmod(rest, 60)
    if hrs > 0 or hours:
        text = f"{hrs}:{mins:02d}:{secs:02d}"
    else:
        text = f"{mins}:{secs:02d}"
    if precise and tenth:
        text += f".{tenth}"
    return text


def parse_time(text):
    """
    Convierte lo que escribió el usuario a segundos, o devuelve None si no se entiende.

    Acepta: "4094.8", "68:14", "1:08:14", "1:08:14.5" (también coma decimal: "14,5").
    """
    cleaned = (text or "").strip().replace(",", ".")
    if not cleaned:
        return None
    parts = cleaned.split(":")
    if len(parts) > 3:
        return None
    if not all(_DIGITS.fullmatch(p) for p in parts[:-1]):
        return None
    if not _SECONDS.fullmatch(parts[-1]):
        return None

    last = float(parts[-1])
    if len(parts) >= 2 and last >= 60:        # "1:75" no es un tiempo válido
        return None
    if len(parts) == 3 and int(parts[1]) >= 60:   # "1:75:00" tampoco
        return None

    total, factor = last, 60
    for part in reversed(parts[:-1]):
        total += int(part) * factor
        factor *= 60
    return total
