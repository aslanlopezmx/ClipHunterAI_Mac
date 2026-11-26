"""
Ventana principal de ClipHunter AI.

Barra de navegación a la izquierda con el recorrido en pasos numerados
(1 · Importar → 2 · Analizar → 3 · Revisar y exportar), cada uno con una marca
de avance (✔ hecho, ○ pendiente), y un área de contenido a la derecha que
cambia según la opción seleccionada.

Flujo automático:
  - Al abrir un proyecto: va a Analizar si ya tiene videos, y a Importar si no.
  - Al guardar un video: va a Analizar con ese video seleccionado.
  - Al terminar «Analizar video» con momentos encontrados: va a revisarlos.
"""

import logging

from PySide6.QtWidgets import QMainWindow, QListWidget, QStackedWidget, QWidget, QHBoxLayout

from app.database.repository import count_candidates, list_candidates, list_videos
from app.interface.dashboard import DashboardView
from app.interface.import_view import ImportView
from app.interface.analysis_view import AnalysisView
from app.interface.clips_view import ClipsView

logger = logging.getLogger(__name__)

# Índices de las pantallas (coinciden con las filas de la barra lateral).
PAGE_HOME, PAGE_IMPORT, PAGE_ANALYSIS, PAGE_CLIPS = range(4)
NAV_LABELS = ["Inicio", "1 · Importar", "2 · Analizar", "3 · Revisar y exportar"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ClipHunter AI")
        self.resize(1000, 650)
        self._project = None

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QHBoxLayout(central_widget)

        # Barra de navegación lateral
        self.nav_list = QListWidget()
        self.nav_list.addItems(NAV_LABELS)
        self.nav_list.setFixedWidth(200)
        self.nav_list.currentRowChanged.connect(self._handle_navigation)
        layout.addWidget(self.nav_list)

        # Área de contenido (una pantalla a la vez)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages)

        self.dashboard_view = DashboardView(on_project_selected=self._handle_project_selected)
        self.import_view = ImportView()
        self.analysis_view = AnalysisView()
        self.clips_view = ClipsView()

        self.pages.addWidget(self.dashboard_view)  # índice 0 -> Inicio
        self.pages.addWidget(self.import_view)     # índice 1 -> Importar
        self.pages.addWidget(self.analysis_view)   # índice 2 -> Analizar
        self.pages.addWidget(self.clips_view)      # índice 3 -> Revisar y exportar

        self.import_view.video_saved.connect(self._handle_video_saved)
        self.analysis_view.pipeline_finished.connect(self._handle_analysis_finished)
        self.analysis_view.analysis_changed.connect(self._update_nav_marks)

        self._update_nav_marks()
        self.nav_list.setCurrentRow(PAGE_HOME)

    def _handle_navigation(self, index: int):
        if index < 0:
            return
        self.pages.setCurrentIndex(index)
        if index != PAGE_CLIPS:  # al salir de la revisión se pausa el video
            self.clips_view.pause()
        if index == PAGE_ANALYSIS:  # refrescar la lista al entrar
            self.analysis_view.refresh()
        elif index == PAGE_CLIPS:  # mostrar los momentos más recientes
            self.clips_view.refresh()
            self.clips_view.setFocus()  # para que funcionen los atajos (espacio/A/R/flechas)
        self._update_nav_marks()

    def _update_nav_marks(self):
        """Pone ✔ / ○ en cada paso de la barra lateral según el avance del proyecto."""
        done = [False, False, False, False]
        if self._project:
            videos = list_videos(self._project["id"])
            done[PAGE_IMPORT] = bool(videos)
            done[PAGE_ANALYSIS] = any(count_candidates(v["id"]) > 0 for v in videos)
            done[PAGE_CLIPS] = any(
                c["exported_path"] for v in videos for c in list_candidates(v["id"])
            )
        for row, label in enumerate(NAV_LABELS):
            item = self.nav_list.item(row)
            if row == PAGE_HOME:
                item.setText(label)
            else:
                item.setText(f"{'✓' if done[row] else '○'}  {label}")

    def _handle_project_selected(self, project: dict):
        self._project = project
        self.import_view.set_current_project(project)
        self.analysis_view.set_current_project(project)
        self.clips_view.set_current_project(project)
        has_videos = bool(list_videos(project["id"]))
        self._update_nav_marks()
        # Con videos ya importados se abre en Analizar; si no, en Importar.
        self.nav_list.setCurrentRow(PAGE_ANALYSIS if has_videos else PAGE_IMPORT)
        logger.info("Proyecto activo cambiado a: %s", project["name"])

    def _handle_video_saved(self, video_id: int):
        self._update_nav_marks()
        self.nav_list.setCurrentRow(PAGE_ANALYSIS)
        self.analysis_view.select_video(video_id)
        logger.info("Video %s guardado: se pasa a Analizar.", video_id)

    def _handle_analysis_finished(self, video_id: int):
        """Terminó el análisis completo: lleva directo a revisar los momentos."""
        self._update_nav_marks()
        self.nav_list.setCurrentRow(PAGE_CLIPS)
        logger.info("Análisis del video %s terminado: se pasa a revisar momentos.", video_id)
