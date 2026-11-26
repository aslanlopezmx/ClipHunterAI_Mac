"""
Geometría de la región de la cámara del streamer (Etapa 6A).

Sin Qt, para poder probarse por separado. La región se guarda como
fracciones del cuadro (0 a 1), así sirve aunque el video cambie de
resolución.
"""

# Proporción fija de la región de la cámara = proporción del panel inferior
# del video vertical (1080 x 768). Así la cámara se ve completa, sin deformarse.
CAM_PANEL_W = 1080
CAM_PANEL_H = 768
CAM_ASPECT = CAM_PANEL_W / CAM_PANEL_H     # 1.40625


def constrained_rect(anchor, pos, bounds, aspect=CAM_ASPECT):
    """
    Rectángulo con proporción fija, que nace en `anchor` y crece hacia `pos`.

    anchor, pos : (x, y) en píxeles de la imagen mostrada
    bounds      : (ancho, alto) de la imagen mostrada
    Devuelve (x, y, w, h) siempre dentro de la imagen.
    """
    ax, ay = anchor
    px, py = pos
    bw, bh = bounds
    ax = min(max(ax, 0), bw)
    ay = min(max(ay, 0), bh)

    sign_x = 1 if px >= ax else -1
    sign_y = 1 if py >= ay else -1

    room_w = (bw - ax) if sign_x > 0 else ax
    room_h = (bh - ay) if sign_y > 0 else ay

    w = abs(px - ax)
    w = min(w, room_w, room_h * aspect)       # no se sale por ningún lado
    h = w / aspect

    x = ax if sign_x > 0 else ax - w
    y = ay if sign_y > 0 else ay - h
    return x, y, w, h


def to_fractions(rect, bounds):
    """(x, y, w, h) en píxeles de la imagen mostrada -> fracciones 0-1."""
    x, y, w, h = rect
    bw, bh = bounds
    return x / bw, y / bh, w / bw, h / bh


def to_pixels(fractions, width, height):
    """
    Fracciones -> píxeles del video original, con valores pares y dentro
    del cuadro (lo que exige H.264). La proporción 1080:768 se conserva.
    """
    fx, fy, fw, fh = fractions
    w = int(round(fw * width / 2)) * 2
    w = max(16, min(w, width // 2 * 2))
    h = int(round(w / CAM_ASPECT / 2)) * 2
    if h > height // 2 * 2:                    # por si el video es muy bajo
        h = height // 2 * 2
        w = int(round(h * CAM_ASPECT / 2)) * 2
    x = int(round(fx * width / 2)) * 2
    y = int(round(fy * height / 2)) * 2
    x = max(0, min(x, width - w))
    y = max(0, min(y, height - h))
    return x, y, w, h
