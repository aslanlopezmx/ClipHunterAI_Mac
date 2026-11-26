"""
Pantalla de Inicio: muestra la lista de proyectos y permite
crear uno nuevo o abrir uno existente (doble clic).
"""

import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QPushButton, QInputDialog, QMessageBox,
)

from app.database.repository import create_project, delete_project, list_projects
from app.interface.theme import set_role

logger = logging.getLogger(__name__)


class DashboardView(QWidget):
    def __init__(self, on_project_selected=None):
        super().__init__()
        self.on_project_selected = on_project_selected
        self._projects = []

        layout = QVBoxLayout(self)

        title = QLabel("Proyectos")
        set_role(title, "title")
        layout.addWidget(title)

        hint = QLabel("Doble clic en un proyecto para abrirlo e importar videos.")
        set_role(hint, "hint")
        layout.addWidget(hint)

        self.project_list = QListWidget()
        self.project_list.itemDoubleClicked.connect(self._handle_project_double_click)
        layout.addWidget(self.project_list)

        buttons_row = QHBoxLayout()
        new_project_btn = QPushButton("Nuevo proyecto")
        set_role(new_project_btn, "primary")
        new_project_btn.clicked.connect(self._handle_new_project)
        buttons_row.addWidget(new_project_btn)
        delete_project_btn = QPushButton("Eliminar proyecto")
        set_role(delete_project_btn, "danger")
        delete_project_btn.clicked.connect(self._handle_delete_project)
        buttons_row.addWidget(delete_project_btn)
        buttons_row.addStretch()
        layout.addLayout(buttons_row)

        self.refresh()

    def refresh(self):
        self.project_list.clear()
        self._projects = list_projects()
        for project in self._projects:
            fecha = project["created_at"][:10]
            self.project_list.addItem(f"{project['name']}   (creado: {fecha})")

    def _handle_new_project(self):
        name, ok = QInputDialog.getText(self, "Nuevo proyecto", "Nombre del proyecto:")
        if ok and name.strip():
            project_id = create_project(name.strip())
            logger.info("Proyecto creado: %s (id=%s)", name, project_id)
            self.refresh()
        elif ok:
            QMessageBox.warning(self, "Nombre inválido", "El nombre del proyecto no puede estar vacío.")

    def _handle_delete_project(self):
        row = self.project_list.currentRow()
        if not (0 <= row < len(self._projects)):
            QMessageBox.information(self, "Eliminar proyecto", "Selecciona primero un proyecto de la lista.")
            return
        project = self._projects[row]
        answer = QMessageBox.question(
            self, "Eliminar proyecto",
            f"¿Eliminar el proyecto «{project['name']}»?\n\n"
            "Se borra todo lo guardado de este proyecto dentro de la app (videos "
            "importados, transcripciones, momentos detectados y subtítulos corregidos).\n\n"
            "Esto NO borra archivos de tu computadora: ni los videos originales, ni el "
            "audio/miniaturas/clips exportados/subtítulos que ya se hayan generado.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        delete_project(project["id"])
        logger.info("Proyecto eliminado: %s (id=%s)", project["name"], project["id"])
        self.refresh()

    def _handle_project_double_click(self, item):
        index = self.project_list.row(item)
        project = self._projects[index]
        if self.on_project_selected:
            self.on_project_selected(dict(project))
