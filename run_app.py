"""Entrada para el empaquetado (PyInstaller)."""
import multiprocessing

from app.main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
