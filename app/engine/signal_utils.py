"""Utilidades compartidas por los análisis de audio e imagen."""

import numpy as np

TOP_FRACTION = 0.10   # solo el 10 % más intenso DE ESTE VIDEO puntúa


def relative(a, fraction: float = TOP_FRACTION) -> np.ndarray:
    """
    Convierte una señal en 0-1 comparándola con el resto DEL MISMO VIDEO:
    1.0 = de lo más intenso de la grabación, 0 = nada destacable. Se debe
    pasar la señal SIN recortar (si muchos valores empatan en el máximo,
    el orden se pierde).
    """
    a = np.asarray(a, dtype=float)
    if len(a) == 0:
        return a
    ranks = np.searchsorted(np.sort(a), a, side="left") / len(a)
    out = np.clip((ranks - (1.0 - fraction)) / fraction, 0.0, 1.0)
    out[a <= 1e-6] = 0.0
    return out
