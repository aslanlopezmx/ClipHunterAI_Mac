"""
Diálogo para corregir los subtítulos de un clip antes de exportarlo (Etapa 6B).

Muestra el texto en pantallas cortas (lo que se verá de 2 a 3 palabras a la
vez). El usuario corrige las palabras que Whisper entendió mal en la columna
«Texto»; si deja una línea vacía, esa pantalla desaparece. La columna «Tiempo»
no se edita: es el segundo (dentro del clip) donde aparece esa pantalla.

Resultado:
  - result_chunks : lista de pantallas corregidas (tiempos del video original)
  - reset_requested : True si el usuario pidió volver a los subtítulos automáticos
"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from app.engine.subtitles import apply_text_edit, chunk_text
from app.interface.theme import set_role

logger = logging.getLogger(__name__)


class SubtitleDialog(QDialog):
    def __init__(self, parent, chunks: list, clip_start: float):
        super().__init__(parent)
        self.setWindowTitle("Corregir subtítulos")
        self.resize(640, 560)
        self._chunks = chunks
        self._clip_start = clip_start
        self.result_chunks = None
        self.reset_requested = False

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Corrige el texto que se entendió mal. Cada línea es lo que aparece en pantalla "
            "a la vez. Una línea vacía se elimina. En el video final se verá en MAYÚSCULAS "
            "con la palabra que se dice resaltada."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(len(chunks), 2)
        self.table.setHorizontalHeaderLabels(["Tiempo", "Texto"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        for row, chunk in enumerate(chunks):
            rel = max(chunk["start"] - clip_start, 0.0)
            time_item = QTableWidgetItem(f"{int(rel) // 60}:{rel % 60:04.1f}")
            time_item.setFlags(Qt.ItemFlag.ItemIsEnabled)          # no editable
            self.table.setItem(row, 0, time_item)
            self.table.setItem(row, 1, QTableWidgetItem(chunk_text(chunk)))
        layout.addWidget(self.table, stretch=1)

        buttons = QHBoxLayout()
        save_btn = QPushButton("Guardar subtítulos")
        set_role(save_btn, "primary")
        save_btn.clicked.connect(self._save)
        reset_btn = QPushButton("Volver a los automáticos")
        reset_btn.setToolTip("Descarta tus correcciones y usa el texto original de la transcripción")
        reset_btn.clicked.connect(self._reset)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        for b in (save_btn, reset_btn, cancel_btn):
            buttons.addWidget(b)
        layout.addLayout(buttons)

    def _save(self):
        edited = []
        for row, chunk in enumerate(self._chunks):
            item = self.table.item(row, 1)
            new_chunk = apply_text_edit(chunk, item.text() if item else chunk_text(chunk))
            if new_chunk is not None:
                edited.append(new_chunk)
        self.result_chunks = edited
        self.reset_requested = False
        self.accept()

    def _reset(self):
        self.result_chunks = None
        self.reset_requested = True
        self.accept()
