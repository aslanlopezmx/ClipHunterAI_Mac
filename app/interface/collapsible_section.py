"""
Sección plegable reutilizable: un botón de título con una flecha que, al
pulsarse, muestra u oculta el contenido de abajo. Sirve para agrupar
controles que no hacen falta todo el tiempo (recorte, formato, exportar)
sin que ocupen espacio en pantalla cuando no se usan.

Uso:

    section = CollapsibleSection("✂ Recorte")
    content_layout = QVBoxLayout()
    content_layout.addWidget(...)
    section.setContentLayout(content_layout)
    layout.addWidget(section)
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    def __init__(self, title: str, expanded: bool = False):
        super().__init__()

        self._toggle_btn = QToolButton()
        self._toggle_btn.setText(title)
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(expanded)
        self._toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle_btn.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self._toggle_btn.setStyleSheet(
            "QToolButton { border: none; font-weight: bold; padding: 4px 0; }"
        )
        self._toggle_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # toggled (no clicked): así también se abre/cierra cuando se llama a set_expanded() desde código.
        self._toggle_btn.toggled.connect(self._on_toggled)

        self.content = QWidget()
        self.content.setVisible(expanded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._toggle_btn)
        layout.addWidget(self.content)

    def _on_toggled(self, checked: bool):
        self.content.setVisible(checked)
        self._toggle_btn.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    def setContentLayout(self, layout):
        """Asigna el layout con los controles de esta sección (llamar una sola vez)."""
        self.content.setLayout(layout)

    def set_expanded(self, expanded: bool):
        """Abre o cierra la sección desde código (por ejemplo, al iniciar una exportación)."""
        self._toggle_btn.setChecked(expanded)

    def is_expanded(self) -> bool:
        return self._toggle_btn.isChecked()
