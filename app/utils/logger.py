"""
Configura el sistema de registro (logs) de la aplicación.
Todo lo que pase (info, errores) queda guardado en logs/app.log
y también se muestra en la terminal, para poder diagnosticar
problemas más adelante.
"""

import logging
import sys

from app.config.settings import LOG_DIR, LOG_PATH


def setup_logger():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stderr is not None:  # en una app sin consola no hay terminal donde escribir
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )
    logging.getLogger(__name__).info("Logger inicializado correctamente.")
