"""
Pantalla "Clips detectados" (Etapa 4): lista los momentos candidatos de
un video, de mayor a menor puntuación, y permite reproducir cada uno
(con 22 s de contexto antes y 38 s después, ya incluidos en la ventana),
leer por qué fue elegido, y aprobarlo o rechazarlo.

Debajo del video hay una barra de progreso con scrubber que cubre SOLO el
momento seleccionado (desde su inicio hasta su final): se puede arrastrar o
hacer clic en cualquier punto para navegar dentro de él. Al seleccionar un
momento, el video queda en su inicio, en pausa, listo para navegar.

Etapa 6A: aquí también se pueden ajustar a mano el inicio y el final de cada
momento, marcar dónde está la cámara del streamer y exportar clips a video
vertical 9:16 (gameplay arriba, cámara abajo) a la carpeta clips\\exports.

Etapa 6B: al exportar se pueden quemar subtítulos de palabras resaltadas (casilla
«Subtítulos») hechos con los tiempos por palabra de la transcripción. El botón
«Subtítulos...» permite corregir el texto de cada clip antes de exportar.

Etapa 6C-1: se puede elegir la composición del video vertical (gameplay arriba +
cámara abajo, gameplay completo o recorte centrado) y el estilo de los subtítulos
(palabras resaltadas, clásico o minimalista). Durante la exportación, «Omitir este
clip» detiene solo el clip en curso y el lote sigue; «Cancelar todo» detiene todo.

Etapa 6C-3: las combinaciones de composición + subtítulos + estilo se pueden guardar
como «plantilla» con un nombre, para aplicarlas luego con un clic en vez de elegir
las tres cosas cada vez. Las plantillas no son de un proyecto: están disponibles en
todos. Si se cambia algo a mano, el selector vuelve a mostrar «Personalizado».

Etapa 6C-2: el botón «Vista previa» genera una muestra rápida y liviana (540 x 960, unos
12 s) con la composición, los subtítulos y el estilo elegidos, y la reproduce en una
ventana antes de exportar de verdad. Arranca desde la posición actual del reproductor si
cae dentro del clip; si no, desde su inicio. Mientras se genera se puede cancelar.

Etapa UX-2 (reorganización de la pantalla):
Solo queda siempre visible lo necesario para revisar: video, aprobar, rechazar y
siguiente. Todo lo demás (recorte, formato/subtítulos, exportar) se agrupó en
secciones plegables, cerradas por defecto, para no abrumar con ~25 controles al
mismo nivel. «Marcar cámara» se movió arriba, junto al selector de video, porque es
una configuración por video (se hace una sola vez), no una acción por clip. El botón
de exportar aprobados ahora es el principal y muestra cuántos hay. Se agregaron
atajos de teclado para revisar más rápido: espacio = pausa/seguir, A = aprobar,
R = rechazar, flechas arriba/abajo = cambiar de momento en la lista.

Etapa UX-3 (recorte más cómodo): los tiempos se muestran y se escriben en un solo formato
(1:08:14, ver app/utils/timefmt.py). Debajo del video hay una barra con dos manijas para
recortar arrastrando (ventana = clip + 30 s de margen) y, en «Recorte», botones de ±1 s y
±5 s. El recorte se guarda automáticamente en cuanto se mueve una manija o se escribe un
tiempo, así que ya no hay cambios pendientes antes de revisar, ver la vista previa o exportar.
"""

import json
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QMessageBox, QProgressBar, QPushButton, QSlider, QSplitter, QStyle, QTextEdit,
    QVBoxLayout, QWidget,
)

from app.config.settings import CLIPS_EXPORTS_DIR, PREVIEW_CACHE_DIR, SUBTITLES_CACHE_DIR
from app.database.repository import (
    count_candidates,
    delete_candidate_subtitles,
    delete_template,
    get_candidate_subtitles,
    get_video_camera,
    list_candidates,
    list_templates,
    list_transcript_segments,
    list_videos,
    save_candidate_subtitles,
    save_template,
    set_candidate_export,
    set_video_camera,
    update_candidate_review,
    update_candidate_times,
)
from app.engine.export_service import (
    DEFAULT_LAYOUT, LAYOUTS, default_output_path, effective_layout, preview_range,
)
from app.engine.subtitles import DEFAULT_STYLE, STYLES, chunks_for_clip, regroup_chunks, write_ass
from app.interface.camera_dialog import CameraDialog
from app.interface.collapsible_section import CollapsibleSection
from app.interface.preview_dialog import PreviewDialog
from app.interface.subtitle_dialog import SubtitleDialog
from app.interface.trim_widgets import RangeSlider, TimeEdit
from app.interface.theme import set_role
from app.interface.timefmt import format_time
from app.workers.export_worker import ExportWorker
from app.workers.preview_worker import PreviewWorker

logger = logging.getLogger(__name__)

BREAKDOWN_NAMES = {
    "audio": "Intensidad del audio",
    "conversation": "Interés de la conversación",
    "surprise": "Sorpresa",
    "visual": "Acontecimiento visual",
    "narrative": "Contexto narrativo",
    "entertainment": "Entretenimiento (risas/reacciones)",
}
REVIEW_MARK = {"pendiente": "·", "aprobado": "✔", "rechazado": "✘"}

# Recorte (barra de rango, campos de tiempo y botones ±)
TRIM_MARGIN_SECONDS = 30.0    # video que se ve antes y después del clip en la barra de recorte
TRIM_MIN_GAP = 1.0            # el clip debe durar al menos 1 s
TRIM_TOLERANCE = 0.06         # diferencias menores (por redondeo a décimas) no cuentan como cambio
RECOMMENDED_MIN_CLIP = 60.0   # menos que esto se marca con aviso (mínimo habitual para monetizar)


class SeekSlider(QSlider):
    """
    Barra de progreso: además de arrastrarse, salta al punto donde se hace
    clic (un QSlider normal solo avanza a pasos). Emite `seek_requested`
    (en milisegundos) cuando el usuario la mueve a mano.
    """
    seek_requested = Signal(int)

    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.sliderMoved.connect(self.seek_requested.emit)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > self.minimum():
            value = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), int(event.position().x()), self.width()
            )
            self.setValue(value)
            self.seek_requested.emit(value)
        # Se pasa el clic a Qt para que, si el usuario sigue arrastrando, mueva la barra.
        super().mousePressEvent(event)


class ClipsView(QWidget):
    def __init__(self):
        super().__init__()
        self.current_project = None
        self._videos = []            # videos del proyecto que tienen candidatos
        self._candidates = []
        self._current = None         # candidato seleccionado
        self._loaded_path = None     # video cargado en el reproductor
        self._pending_seek_ms = None
        self._play_end_ms = None     # final del momento seleccionado (ms)
        self._previewed_id = None    # momento al que ya se le posicionó el video
        self._pending_play = False   # al terminar de cargar: ¿reproducir o solo mostrar un cuadro?
        self._export_worker = None   # exportación en curso (Etapa 6A)
        self._preview_worker = None  # vista previa en curso (Etapa 6C-2)
        self._preview_note = ""       # texto que acompaña a la vista previa
        self._templates = []         # plantillas guardadas (Etapa 6C-3)
        self._applying_template = False   # evita que aplicar una plantilla la "desmarque" sola
        self._hours_mode = False         # video de 1 h o más: todos los tiempos con horas (1:08:14)
        self._trim_window = (0.0, 1.0)   # tramo del video que muestra la barra de recorte (s)
        self._trim_candidate_id = None   # momento al que pertenecen los campos de recorte

        # El widget necesita foco para que los atajos de teclado (espacio/A/R/flechas)
        # funcionen en cuanto se entra a esta pantalla.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = QVBoxLayout(self)

        self.project_label = QLabel("Ningún proyecto seleccionado. Ve a Inicio y abre un proyecto.")
        self.project_label.setWordWrap(True)
        layout.addWidget(self.project_label)

        # Video + "Marcar cámara": es configuración POR VIDEO (se hace una sola vez),
        # por eso vive aquí arriba y no mezclada con las acciones de cada clip.
        top = QHBoxLayout()
        top.addWidget(QLabel("Video:"))
        self.video_combo = QComboBox()
        self.video_combo.currentIndexChanged.connect(self._load_candidates)
        top.addWidget(self.video_combo, stretch=1)
        refresh_btn = QPushButton("Actualizar")
        refresh_btn.clicked.connect(self.refresh)
        top.addWidget(refresh_btn)
        self.camera_btn = QPushButton("🎥 Marcar cámara...")
        self.camera_btn.setToolTip("Dónde está la cámara del streamer en este video (se marca una sola vez)")
        self.camera_btn.clicked.connect(self._define_camera)
        top.addWidget(self.camera_btn)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, stretch=1)

        # Izquierda: lista de candidatos
        self.candidate_list = QListWidget()
        self.candidate_list.currentRowChanged.connect(self._handle_selection)
        splitter.addWidget(self.candidate_list)

        # Derecha: reproductor, revisión y detalle siempre visibles;
        # recorte/formato/exportar en secciones plegables debajo.
        right = QWidget()
        right_layout = QVBoxLayout(right)

        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(220)
        right_layout.addWidget(self.video_widget, stretch=2)

        # Recorte por arrastre: dos manijas (inicio y fin) sobre una ventana del video
        # (el clip más un margen). Su resumen queda alineado con el tiempo de la barra de abajo.
        trim_row = QHBoxLayout()
        self.range_slider = RangeSlider(min_gap=TRIM_MIN_GAP)
        self.range_slider.setEnabled(False)
        self.range_slider.setToolTip(
            "Arrastra las manijas para ajustar el inicio y el final del clip. "
            "Los cambios se guardan automáticamente."
        )
        self.range_slider.values_changed.connect(self._on_range_dragged)
        self.range_slider.drag_finished.connect(self._on_range_released)
        trim_row.addWidget(self.range_slider, stretch=1)
        self.trim_summary = QLabel("")
        self.trim_summary.setMinimumWidth(240)
        self.trim_summary.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        set_role(self.trim_summary, "hint")
        trim_row.addWidget(self.trim_summary)
        right_layout.addLayout(trim_row)

        # Barra de progreso / scrubber + tiempo actual y total
        seek_row = QHBoxLayout()
        self.seek_slider = SeekSlider()
        self.seek_slider.setEnabled(False)
        self.seek_slider.seek_requested.connect(self._seek_from_user)
        seek_row.addWidget(self.seek_slider, stretch=1)
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setMinimumWidth(240)
        self.time_label.setToolTip("Tiempo dentro del momento / duración del momento · posición en el video completo")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        seek_row.addWidget(self.time_label)
        right_layout.addLayout(seek_row)

        # Aviso de recorte sin guardar (con el guardado automático queda siempre oculto)
        self.trim_dirty_bar = QWidget()
        dirty_layout = QHBoxLayout(self.trim_dirty_bar)
        dirty_layout.setContentsMargins(0, 0, 0, 0)
        dirty_label = QLabel("Cambiaste el recorte a mano y todavía no está guardado.")
        set_role(dirty_label, "warning")
        dirty_layout.addWidget(dirty_label, stretch=1)
        self.quick_discard_btn = QPushButton("Descartar cambios")
        self.quick_discard_btn.clicked.connect(self._discard_trim)
        dirty_layout.addWidget(self.quick_discard_btn)
        self.quick_save_btn = QPushButton("Guardar recorte")
        set_role(self.quick_save_btn, "primary")
        self.quick_save_btn.clicked.connect(self._save_times)
        dirty_layout.addWidget(self.quick_save_btn)
        self.trim_dirty_bar.setVisible(False)
        right_layout.addWidget(self.trim_dirty_bar)

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        self.player.positionChanged.connect(self._handle_position)
        self.player.mediaStatusChanged.connect(self._handle_media_status)
        self.player.errorOccurred.connect(self._handle_player_error)

        # --- Revisar (siempre visible): reproducir, aprobar, rechazar, siguiente ---
        buttons = QHBoxLayout()
        self.play_btn = QPushButton("▶ Reproducir momento")
        self.play_btn.clicked.connect(self._play_candidate)
        buttons.addWidget(self.play_btn)
        self.pause_btn = QPushButton("⏯ Pausa / Seguir")
        self.pause_btn.setToolTip("Atajo: barra espaciadora")
        self.pause_btn.clicked.connect(self._toggle_play)
        buttons.addWidget(self.pause_btn)
        self.approve_btn = QPushButton("✔ Aprobar")
        self.approve_btn.setToolTip("Atajo: A")
        self.approve_btn.clicked.connect(lambda: self._review("aprobado"))
        buttons.addWidget(self.approve_btn)
        self.reject_btn = QPushButton("✘ Rechazar")
        self.reject_btn.setToolTip("Atajo: R")
        self.reject_btn.clicked.connect(lambda: self._review("rechazado"))
        buttons.addWidget(self.reject_btn)
        self.next_btn = QPushButton("Siguiente ▸")
        self.next_btn.setToolTip("Pasa al siguiente momento pendiente de revisión (atajo: flecha abajo)")
        self.next_btn.clicked.connect(self._go_next_pending)
        buttons.addWidget(self.next_btn)
        right_layout.addLayout(buttons)

        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        right_layout.addWidget(self.info_label)

        self.detail_box = QTextEdit()
        self.detail_box.setReadOnly(True)
        self.detail_box.setPlaceholderText("Selecciona un momento de la lista para ver el detalle.")
        self.detail_box.setMaximumHeight(160)
        right_layout.addWidget(self.detail_box)

        # --- Recorte (plegable): ajuste manual de tiempos ---
        # Una fila por extremo: [−5 s][−1 s] [campo de tiempo] [+1 s][+5 s] [usar posición actual]
        self._nudge_buttons = []

        def make_trim_row(title: str, which: str, here_text: str, here_tip: str):
            row = QHBoxLayout()
            title_label = QLabel(title)
            title_label.setMinimumWidth(48)
            row.addWidget(title_label)
            for delta in (-5, -1):
                row.addWidget(self._make_nudge_button(which, delta))
            edit = TimeEdit()
            edit.user_edited.connect(lambda _value, w=which: self._on_time_edited(w))
            row.addWidget(edit)
            for delta in (1, 5):
                row.addWidget(self._make_nudge_button(which, delta))
            here_btn = QPushButton(here_text)
            here_btn.setToolTip(here_tip)
            here_btn.clicked.connect(lambda _checked=False, w=which: self._set_from_player(w))
            row.addWidget(here_btn)
            row.addStretch(1)
            return row, edit, here_btn

        start_row, self.start_edit, self.set_start_btn = make_trim_row(
            "Inicio:", "start", "⇤ Inicio = aquí",
            "Usa la posición actual del video como inicio del clip")
        end_row, self.end_edit, self.set_end_btn = make_trim_row(
            "Fin:", "end", "Fin = aquí ⇥",
            "Usa la posición actual del video como final del clip")

        action_row = QHBoxLayout()
        self.save_times_btn = QPushButton("Guardar recorte")
        self.save_times_btn.clicked.connect(self._save_times)
        action_row.addWidget(self.save_times_btn)
        self.discard_btn = QPushButton("Descartar cambios")
        self.discard_btn.clicked.connect(self._discard_trim)
        action_row.addWidget(self.discard_btn)
        action_row.addStretch(1)

        self.recorte_section = CollapsibleSection("✂ Recorte", expanded=False)
        recorte_layout = QVBoxLayout()
        recorte_layout.addLayout(start_row)
        recorte_layout.addLayout(end_row)
        recorte_layout.addLayout(action_row)
        self.recorte_section.setContentLayout(recorte_layout)
        right_layout.addWidget(self.recorte_section)

        # --- Formato y subtítulos (plegable): plantilla primero, detalle bajo "Personalizar..." ---
        template_row = QHBoxLayout()
        template_row.addWidget(QLabel("Plantilla:"))
        self.template_combo = QComboBox()
        self.template_combo.setToolTip("Aplica una composición, subtítulos y estilo guardados antes")
        self.template_combo.currentIndexChanged.connect(self._apply_template)
        template_row.addWidget(self.template_combo, stretch=1)
        self.save_template_btn = QPushButton("💾 Guardar plantilla...")
        self.save_template_btn.setToolTip("Guarda la composición, subtítulos y estilo de ahora con un nombre")
        self.save_template_btn.clicked.connect(self._save_template)
        template_row.addWidget(self.save_template_btn)
        self.delete_template_btn = QPushButton("🗑 Eliminar plantilla")
        self.delete_template_btn.setEnabled(False)
        self.delete_template_btn.clicked.connect(self._delete_template)
        template_row.addWidget(self.delete_template_btn)

        self.customize_toggle_btn = QPushButton("Personalizar composición, subtítulos y estilo...")
        self.customize_toggle_btn.setCheckable(True)
        self.customize_toggle_btn.setToolTip(
            "La plantilla ya trae estos tres ajustes listos; ábrelo solo si quieres cambiarlos a mano."
        )

        self.customize_widget = QWidget()
        options_row = QHBoxLayout(self.customize_widget)
        options_row.setContentsMargins(0, 0, 0, 0)
        options_row.addWidget(QLabel("Composición:"))
        self.layout_combo = QComboBox()
        for key, label in LAYOUTS.items():
            self.layout_combo.addItem(label, key)
        self.layout_combo.setToolTip("Cómo se acomoda el video en la pantalla vertical 9:16")
        options_row.addWidget(self.layout_combo)
        self.subs_check = QCheckBox("Subtítulos")
        self.subs_check.setChecked(True)
        self.subs_check.setToolTip("Quema subtítulos en los clips exportados")
        options_row.addWidget(self.subs_check)
        self.style_combo = QComboBox()
        for key, st in STYLES.items():
            self.style_combo.addItem(st["label"], key)
        self.style_combo.setToolTip("Estilo de los subtítulos")
        options_row.addWidget(self.style_combo)
        self.subs_btn = QPushButton("✏ Subtítulos...")
        self.subs_btn.setToolTip("Corregir el texto de los subtítulos de este clip")
        self.subs_btn.clicked.connect(self._edit_subtitles)
        options_row.addWidget(self.subs_btn)
        self.customize_widget.setVisible(False)
        self.customize_toggle_btn.toggled.connect(self.customize_widget.setVisible)

        # Si el usuario cambia composición, subtítulos o estilo a mano, la plantilla
        # seleccionada deja de aplicar (el selector vuelve a "Personalizado").
        self.layout_combo.currentIndexChanged.connect(self._mark_custom)
        self.subs_check.toggled.connect(self._mark_custom)
        self.style_combo.currentIndexChanged.connect(self._mark_custom)

        self.format_section = CollapsibleSection("🎨 Formato y subtítulos", expanded=False)
        format_layout = QVBoxLayout()
        format_layout.addLayout(template_row)
        format_layout.addWidget(self.customize_toggle_btn)
        format_layout.addWidget(self.customize_widget)
        self.format_section.setContentLayout(format_layout)
        right_layout.addWidget(self.format_section)

        # --- Exportar (plegable): un botón principal + vista previa/clip suelto/carpeta ---
        export_row = QHBoxLayout()
        self.export_all_btn = QPushButton("Exportar aprobados")
        set_role(self.export_all_btn, "primary")
        self.export_all_btn.clicked.connect(lambda: self._export(only_current=False))
        export_row.addWidget(self.export_all_btn)
        self.preview_btn = QPushButton("👁 Vista previa")
        self.preview_btn.setToolTip(
            "Genera una muestra rápida (unos 12 s) con la composición y los subtítulos elegidos")
        self.preview_btn.clicked.connect(self._preview_clip)
        export_row.addWidget(self.preview_btn)
        self.export_one_btn = QPushButton("Exportar este clip")
        self.export_one_btn.clicked.connect(lambda: self._export(only_current=True))
        export_row.addWidget(self.export_one_btn)
        self.open_folder_btn = QPushButton("Abrir carpeta de clips")
        self.open_folder_btn.clicked.connect(self._open_exports_folder)
        export_row.addWidget(self.open_folder_btn)

        # Progreso de la exportación + omitir / cancelar (solo visible mientras se exporta)
        self.export_box = QWidget()
        box_layout = QHBoxLayout(self.export_box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        self.export_progress = QProgressBar()
        self.export_progress.setRange(0, 100)
        box_layout.addWidget(self.export_progress, stretch=1)
        self.skip_export_btn = QPushButton("⏭ Omitir este clip")
        self.skip_export_btn.setToolTip("Detiene solo el clip que se está exportando y sigue con el siguiente")
        self.skip_export_btn.clicked.connect(self._skip_export)
        box_layout.addWidget(self.skip_export_btn)
        self.cancel_export_btn = QPushButton("✘ Cancelar todo")
        self.cancel_export_btn.setToolTip("Detiene toda la exportación (lo ya exportado se conserva)")
        self.cancel_export_btn.clicked.connect(self._cancel_export)
        box_layout.addWidget(self.cancel_export_btn)
        self.export_box.setVisible(False)

        self.export_section = CollapsibleSection("📤 Exportar", expanded=False)
        export_section_layout = QVBoxLayout()
        export_section_layout.addLayout(export_row)
        export_section_layout.addWidget(self.export_box)
        self.export_section.setContentLayout(export_section_layout)
        right_layout.addWidget(self.export_section)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self._setup_shortcuts()
        self._refresh_templates()
        self._update_buttons()

    # ---------------------------------------------------------------
    # Atajos de teclado (revisar más rápido)
    # ---------------------------------------------------------------

    def _setup_shortcuts(self):
        """
        Espacio = pausa/seguir, A = aprobar, R = rechazar, flechas = cambiar de
        momento en la lista. Activos mientras el foco esté dentro de esta pantalla
        (si el foco está en un campo de texto o un spinner, ese control se queda
        con la tecla primero, como es normal en Qt).
        """
        def add(key, slot):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)
            return sc

        self._shortcuts = [
            add(Qt.Key.Key_Space, self._toggle_play),
            add("A", lambda: self._review("aprobado")),
            add("R", lambda: self._review("rechazado")),
            add(Qt.Key.Key_Down, lambda: self._select_relative(1)),
            add(Qt.Key.Key_Up, lambda: self._select_relative(-1)),
        ]

    def _select_relative(self, delta: int):
        row = self.candidate_list.currentRow()
        new_row = row + delta
        if 0 <= new_row < self.candidate_list.count():
            self.candidate_list.setCurrentRow(new_row)

    def _select_candidate_id(self, candidate_id) -> bool:
        for row, c in enumerate(self._candidates):
            if c["id"] == candidate_id:
                self.candidate_list.setCurrentRow(row)
                return True
        return False

    def _go_next_pending(self):
        """Botón «Siguiente ▸»: pasa al próximo momento aún sin revisar."""
        if not self._candidates:
            return
        start_idx = 0
        if self._current:
            idx = next((i for i, c in enumerate(self._candidates) if c["id"] == self._current["id"]), None)
            if idx is not None:
                start_idx = idx + 1
        for c in self._candidates[start_idx:]:
            if c["review_status"] == "pendiente":
                self._select_candidate_id(c["id"])
                return
        self.info_label.setText("No hay más momentos pendientes de revisar en este video.")

    # ---------------------------------------------------------------
    # Carga de datos
    # ---------------------------------------------------------------

    def set_current_project(self, project: dict):
        self.current_project = project
        self.project_label.setText(f"Proyecto actual: {project['name']}")
        self.refresh()

    def refresh(self):
        previous_id = None
        idx = self.video_combo.currentIndex()
        if 0 <= idx < len(self._videos):
            previous_id = self._videos[idx]["id"]

        self.video_combo.blockSignals(True)
        self.video_combo.clear()
        self._videos = []

        if self.current_project:
            for video in list_videos(self.current_project["id"]):
                n = count_candidates(video["id"])
                if n > 0:
                    self._videos.append(video)
                    self.video_combo.addItem(f"{video['filename']}  ({n} momentos)")

        selected = 0
        for i, video in enumerate(self._videos):
            if video["id"] == previous_id:
                selected = i
                break
        if self._videos:
            self.video_combo.setCurrentIndex(selected)
        self.video_combo.blockSignals(False)

        self._load_candidates()

    def _selected_video(self):
        idx = self.video_combo.currentIndex()
        if 0 <= idx < len(self._videos):
            return self._videos[idx]
        return None

    def _load_candidates(self, *_):
        previous_id = self._current["id"] if self._current else None
        video = self._selected_video()
        # En videos de 1 h o más todos los tiempos llevan horas, para que se vean iguales.
        self._hours_mode = bool(video and float(video["duration_seconds"] or 0) >= 3600)

        self.candidate_list.blockSignals(True)
        self.candidate_list.clear()
        self._candidates = list_candidates(video["id"]) if video else []

        selected_row = -1
        for row, c in enumerate(self._candidates):
            mark = REVIEW_MARK.get(c["review_status"], "·")
            self.candidate_list.addItem(
                f"{mark} {row + 1}. {self._fmt(c['start_time'])} - "
                f"{self._fmt(c['end_time'])} · {c['score']:.0f}/100 · {c['category']}"
                + (" · 🎬 exportado" if c["exported_path"] else "")
            )
            if c["id"] == previous_id:
                selected_row = row
        if selected_row >= 0:
            self.candidate_list.setCurrentRow(selected_row)
        self.candidate_list.blockSignals(False)

        if not self._videos:
            self.info_label.setText(
                "Todavía no hay momentos detectados. Ve a Análisis, selecciona un video "
                "transcrito y pulsa «Detectar momentos»."
            )
        self._handle_selection(selected_row)

    def _handle_selection(self, row: int):
        if 0 <= row < len(self._candidates):
            self._current = self._candidates[row]
            self._show_detail()
            self._apply_clip_range()
            # Solo se reposiciona el video si es un momento distinto (no al aprobar/rechazar).
            if self._current["id"] != self._previewed_id:
                self._previewed_id = self._current["id"]
                self._preview_candidate()
        else:
            self._current = None
            self._previewed_id = None
            self._trim_candidate_id = None
            self.player.pause()
            self.detail_box.clear()
            if self._videos:
                self.info_label.setText("")
            self._apply_clip_range()
            self._refresh_trim_ui()
        self._update_buttons()

    def _update_buttons(self):
        has = self._current is not None
        exporting = self._export_worker is not None
        previewing = self._preview_worker is not None
        busy = exporting or previewing
        for btn in (self.play_btn, self.pause_btn, self.approve_btn, self.reject_btn):
            btn.setEnabled(has)
        self.next_btn.setEnabled(bool(self._candidates))
        self.camera_btn.setEnabled(self._selected_video() is not None and not busy)
        self.subs_btn.setEnabled(has and not busy)
        self.subs_check.setEnabled(not busy)
        self.layout_combo.setEnabled(not busy)
        self.style_combo.setEnabled(not busy)
        self.preview_btn.setEnabled(has and not busy)
        self.export_one_btn.setEnabled(has and not busy)

        approved = sum(1 for c in self._candidates if c["review_status"] == "aprobado")
        self.export_all_btn.setText(f"Exportar {approved} aprobados" if approved else "Exportar aprobados")
        self.export_all_btn.setEnabled(
            self._selected_video() is not None and not busy and approved > 0
        )

        self.skip_export_btn.setVisible(not previewing)    # omitir solo aplica a exportar
        self.skip_export_btn.setEnabled(exporting)
        self.cancel_export_btn.setEnabled(busy)
        self._update_trim_state()

    def _show_detail(self):
        c = self._current
        self._load_trim_from_current()
        try:
            breakdown = json.loads(c["breakdown_json"] or "{}")
        except ValueError:
            breakdown = {}

        self.info_label.setText(
            f"Momento {self._fmt(c['start_time'])} - {self._fmt(c['end_time'])} "
            f"({c['duration']:.0f} s) · pico en {self._fmt(c['peak_time'] or 0)} · "
            f"estado: {c['review_status']}"
        )

        lines = [
            f"Puntuación: {c['score']:.0f}/100    Categoría: {c['category']}",
            "",
            f"Motivo: {c['reason']}",
            "",
            "Desglose (0-100):",
        ]
        for key, name in BREAKDOWN_NAMES.items():
            if key in breakdown:
                lines.append(f"  • {name}: {breakdown[key]}")
        lines += ["", "Lo que se dice en este tramo:", c["transcript"] or "(sin texto)"]
        self.detail_box.setPlainText("\n".join(lines))

    # ---------------------------------------------------------------
    # Revisión
    # ---------------------------------------------------------------

    def _review(self, status: str):
        if not self._current:
            return
        if not self._resolve_pending_trim():
            return
        update_candidate_review(self._current["id"], status)
        self._load_candidates()
        self._go_next_pending()

    # ---------------------------------------------------------------
    # Ajuste de tiempos (Etapa 6A)
    # ---------------------------------------------------------------

    def _fmt(self, seconds, precise: bool = False) -> str:
        """Tiempo en el formato único de la app (con horas si el video dura 1 h o más)."""
        return format_time(seconds, precise=precise, hours=self._hours_mode)

    def _total_seconds(self) -> float:
        """Duración del video seleccionado (0 si no se conoce)."""
        video = self._selected_video()
        return float(video["duration_seconds"] or 0) if video else 0.0

    def _make_nudge_button(self, which: str, delta: int) -> QPushButton:
        """Botón compacto de ±1 s / ±5 s para el inicio ("start") o el fin ("end")."""
        sign = "+" if delta > 0 else "−"
        btn = QPushButton(f"{sign}{abs(delta)} s")
        set_role(btn, "nudge")
        target = "el inicio" if which == "start" else "el final"
        btn.setToolTip(f"Mueve {target} del clip {abs(delta)} s {'después' if delta > 0 else 'antes'}")
        btn.clicked.connect(lambda _checked=False, w=which, d=delta: self._nudge(w, d))
        self._nudge_buttons.append(btn)
        return btn

    def _trim_edit(self, which: str) -> TimeEdit:
        return self.start_edit if which == "start" else self.end_edit

    def _trim_values(self):
        """(inicio, fin) que muestran ahora los campos de recorte, en segundos."""
        return self.start_edit.value(), self.end_edit.value()

    def _trim_dirty(self) -> bool:
        """¿Los campos de recorte difieren de lo guardado para el momento seleccionado?"""
        c = self._current
        if c is None:
            return False
        start, end = self._trim_values()
        return (abs(start - float(c["start_time"])) > TRIM_TOLERANCE
                or abs(end - float(c["end_time"])) > TRIM_TOLERANCE)

    def _load_trim_from_current(self, force: bool = False):
        """
        Carga en los controles de recorte los tiempos guardados del momento seleccionado.
        Si es el mismo momento de antes y tiene cambios sin guardar (por ejemplo, porque la
        lista se recargó), esos cambios se conservan, salvo que force=True.
        """
        c = self._current
        same = self._trim_candidate_id == c["id"]
        self._trim_candidate_id = c["id"]
        total = self._total_seconds()
        for edit in (self.start_edit, self.end_edit):
            edit.setMaxSeconds(total)
            edit.setHoursMode(self._hours_mode)
        if force or not (same and self._trim_dirty()):
            self.start_edit.setValue(float(c["start_time"]))
            self.end_edit.setValue(float(c["end_time"]))
        low = max(0.0, float(c["start_time"]) - TRIM_MARGIN_SECONDS)
        high = float(c["end_time"]) + TRIM_MARGIN_SECONDS
        if total:
            high = min(high, total)
        self._trim_window = (low, high)
        self._refresh_trim_ui()

    def _refresh_trim_ui(self, update_slider: bool = True):
        """Pone la barra de rango, el resumen y los botones de acuerdo con los campos de tiempo."""
        if self._current is None:
            self.range_slider.setValues(0.0, 0.0)
            self.trim_summary.setText("")
            self.trim_summary.setToolTip("")
            set_role(self.trim_summary, "hint")
            self._update_trim_state()
            return

        start, end = self._trim_values()
        if update_slider:
            low, high = self._trim_window
            low, high = min(low, start), max(high, end)       # la ventana crece si se escribe fuera de ella
            self._trim_window = (low, high)
            self.range_slider.setWindow(low, high)
            self.range_slider.setValues(start, end)

        duration = end - start
        short = duration < RECOMMENDED_MIN_CLIP
        self.trim_summary.setText(
            f"✂ {self._fmt(start)} → {self._fmt(end)} · {duration:.0f} s" + (" ⚠" if short else "")
        )
        self.trim_summary.setToolTip(
            f"Dura menos de {RECOMMENDED_MIN_CLIP:.0f} s: es el mínimo habitual para monetizar en varias plataformas."
            if short else ""
        )
        set_role(self.trim_summary, "warning" if short else "hint")
        self._update_trim_state()

    def _update_trim_state(self):
        """Activa o desactiva los controles de recorte. El aviso de cambios sin guardar queda oculto."""
        has = self._current is not None
        busy = self._export_worker is not None or self._preview_worker is not None
        for w in (self.start_edit, self.end_edit, self.range_slider,
                  self.set_start_btn, self.set_end_btn, *self._nudge_buttons):
            w.setEnabled(has)
        dirty = self._trim_dirty()
        for w in (self.save_times_btn, self.discard_btn, self.quick_save_btn, self.quick_discard_btn):
            w.setEnabled(dirty and not busy)
        # El recorte se guarda solo: el aviso naranja ya no se muestra nunca.
        self.trim_dirty_bar.setVisible(False)

    def _show_frame_at(self, seconds: float):
        """Lleva el video (en pausa) a ese instante, para ver exactamente dónde cae el corte."""
        path = self._video_path()
        if not path:
            return
        position_ms = int(max(0.0, seconds) * 1000)
        if self._loaded_path != path:
            self._go_to(path, position_ms, play=False)
        elif self._pending_seek_ms is not None:          # el video aún se está cargando
            self._pending_seek_ms = position_ms
            self._pending_play = False
        else:
            self.player.setPosition(position_ms)
            self.player.pause()

    def _persist_trim(self, start: float, end: float) -> bool:
        """
        Guardado automático del recorte del momento seleccionado: escribe en la base de
        datos, descarta subtítulos corregidos si el clip creció, actualiza el candidato en
        memoria, el texto de la lista de la izquierda y la barra de reproducción.
        """
        if self._current is None or self._export_worker is not None or self._preview_worker is not None:
            return False
        if end - start < TRIM_MIN_GAP:
            return False
        start, end = round(float(start), 1), round(float(end), 1)
        c = self._current
        if abs(start - float(c["start_time"])) < 1e-9 and abs(end - float(c["end_time"])) < 1e-9:
            return False                                  # nada cambió respecto a lo guardado

        note = ""
        try:
            update_candidate_times(c["id"], start, end)
            saved = get_candidate_subtitles(c["id"])
            if saved and not self._subs_cover(saved, start, end):
                delete_candidate_subtitles(c["id"])
                note = " Como el clip creció, se descartaron tus correcciones de subtítulos."
            # Copia editable: las filas de la base de datos pueden no permitir asignar valores.
            updated = dict(c)
            updated["start_time"] = start
            updated["end_time"] = end
            updated["duration"] = round(end - start, 1)
        except Exception as exc:
            logger.exception("No se pudo guardar el recorte del momento %s", c["id"])
            self.info_label.setText(f"No se pudo guardar el recorte: {exc}")
            return False

        # Reemplaza el candidato en memoria (el seleccionado y el de la lista interna)
        self._current = updated
        for i, cand in enumerate(self._candidates):
            if cand["id"] == updated["id"]:
                self._candidates[i] = updated
                break

        # Actualiza el texto de la lista de la izquierda (mismo formato que _load_candidates)
        row = self.candidate_list.currentRow()
        if row >= 0:
            mark = REVIEW_MARK.get(updated["review_status"], "·")
            self.candidate_list.item(row).setText(
                f"{mark} {row + 1}. {self._fmt(updated['start_time'])} - "
                f"{self._fmt(updated['end_time'])} · {updated['score']:.0f}/100 · {updated['category']}"
                + (" · 🎬 exportado" if updated["exported_path"] else "")
            )
        self._apply_clip_range()
        self.info_label.setText(
            f"Recorte guardado: {self._fmt(start)} - {self._fmt(end)} ({end - start:.0f} s)."
            + (" Si ya estaba exportado, hay que exportarlo de nuevo." if updated["exported_path"] else "")
            + note
        )
        self._update_trim_state()
        return True

    def _nudge(self, which: str, delta: int):
        """Botones ±1 s / ±5 s: mueve el inicio o el final sin cruzarlos ni salir del video."""
        if self._current is None:
            return
        start, end = self._trim_values()
        total = self._total_seconds()
        if which == "start":
            new = max(min(start + delta, end - TRIM_MIN_GAP), 0.0)
            self.start_edit.setValue(new)
        else:
            upper = total if total else float("inf")
            new = min(max(end + delta, start + TRIM_MIN_GAP), upper)
            self.end_edit.setValue(new)
        self._refresh_trim_ui()
        self._show_frame_at(new)
        # Como ya no hay botón de guardar, el ajuste con ± también se guarda al instante.
        start, end = self._trim_values()
        self._persist_trim(start, end)

    def _on_time_edited(self, which: str, seek: bool = True):
        """Se escribió un tiempo (o se usó «= aquí»): se cuida el orden, se sincroniza todo y se guarda."""
        start, end = self._trim_values()
        note = ""
        if which == "start" and start > end - TRIM_MIN_GAP:
            start = max(0.0, end - TRIM_MIN_GAP)
            self.start_edit.setValue(start)
            note = "El inicio tiene que ir antes del final: lo ajusté."
        elif which == "end" and end < start + TRIM_MIN_GAP:
            end = start + TRIM_MIN_GAP
            self.end_edit.setValue(end)
            note = "El final tiene que ir después del inicio: lo ajusté."

        # Guardado automático al terminar de escribir un tiempo
        self._persist_trim(start, end)

        self._refresh_trim_ui()
        if note:
            self.info_label.setText(note)
        if seek:
            self._show_frame_at(start if which == "start" else end)

    def _on_range_dragged(self, start: float, end: float, which: str):
        """Se arrastra una manija: los campos la siguen (el guardado ocurre al soltarla)."""
        self.start_edit.setValue(start)
        self.end_edit.setValue(end)
        self._refresh_trim_ui(update_slider=False)
        self._show_frame_at(start if which == "start" else end)

    def _on_range_released(self):
        """Se soltó una manija: se guarda el recorte automáticamente."""
        start, end = self._trim_values()
        self._persist_trim(start, end)

    def _set_from_player(self, which: str):
        """«Inicio = aquí» / «Fin = aquí»: usa la posición actual del reproductor."""
        if self._current is None or self.player.source().isEmpty():
            return
        self._trim_edit(which).setValue(round(self.player.position() / 1000.0, 1))
        self._on_time_edited(which, seek=False)         # sin mover el video: puede estar reproduciéndose

    def _discard_trim(self):
        """Vuelve a los tiempos guardados del momento seleccionado."""
        if self._current is None:
            return
        self._load_trim_from_current(force=True)
        self._preview_candidate()
        self.info_label.setText("Cambios descartados: se restauraron los tiempos guardados.")

    def _resolve_pending_trim(self) -> bool:
        """
        Con el guardado automático nunca hay cambios pendientes antes de revisar, ver la
        vista previa o exportar, así que siempre se puede continuar.
        """
        return True

    def _save_times(self) -> bool:
        """Guarda el recorte del momento seleccionado. Devuelve True si se guardó."""
        c = self._current
        if not c:
            return False
        start, end = self._trim_values()
        # Un extremo que no se tocó conserva su valor exacto (los campos redondean a 0.1 s).
        if abs(start - float(c["start_time"])) <= TRIM_TOLERANCE:
            start = float(c["start_time"])
        if abs(end - float(c["end_time"])) <= TRIM_TOLERANCE:
            end = float(c["end_time"])
        total = self._total_seconds()
        if end - start < TRIM_MIN_GAP:
            QMessageBox.warning(self, "Recorte", "El final debe ser al menos 1 segundo después del inicio.")
            return False
        if total and end > total:
            QMessageBox.warning(
                self, "Recorte",
                f"El final no puede pasar de la duración del video ({self._fmt(total)}).",
            )
            return False
        update_candidate_times(c["id"], start, end)
        note = ""
        saved = get_candidate_subtitles(c["id"])
        if saved and not self._subs_cover(saved, start, end):
            delete_candidate_subtitles(c["id"])
            note = " Como el clip creció, se descartaron tus correcciones de subtítulos."
        self._load_candidates()
        self._preview_candidate()
        self.info_label.setText(
            f"Recorte guardado: {self._fmt(start)} - {self._fmt(end)} "
            f"({end - start:.0f} s). Si ya estaba exportado, hay que exportarlo de nuevo." + note
        )
        return True

    # ---------------------------------------------------------------
    # Subtítulos (Etapa 6B)
    # ---------------------------------------------------------------

    def _current_style(self) -> str:
        return self.style_combo.currentData() or DEFAULT_STYLE

    def _current_layout(self) -> str:
        return self.layout_combo.currentData() or DEFAULT_LAYOUT

    # ---------------------------------------------------------------
    # Plantillas (Etapa 6C-3)
    # ---------------------------------------------------------------

    def _refresh_templates(self):
        """Vuelve a cargar la lista de plantillas guardadas en el selector."""
        previous_id = self.template_combo.currentData()
        self._applying_template = True
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        self.template_combo.addItem("— Personalizado —", None)
        self._templates = list_templates()
        for t in self._templates:
            self.template_combo.addItem(t["name"], t["id"])
        idx = self.template_combo.findData(previous_id)
        self.template_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.template_combo.blockSignals(False)
        self._applying_template = False
        self.delete_template_btn.setEnabled(self.template_combo.currentData() is not None)

    def _apply_template(self, *_):
        """Al elegir una plantilla: aplica su composición, subtítulos y estilo."""
        template_id = self.template_combo.currentData()
        self.delete_template_btn.setEnabled(template_id is not None)
        if template_id is None:
            return
        template = next((t for t in self._templates if t["id"] == template_id), None)
        if not template:
            return
        self._applying_template = True
        idx = self.layout_combo.findData(template["layout"])
        if idx >= 0:
            self.layout_combo.setCurrentIndex(idx)
        self.subs_check.setChecked(bool(template["subtitles_enabled"]))
        idx = self.style_combo.findData(template["style"])
        if idx >= 0:
            self.style_combo.setCurrentIndex(idx)
        self._applying_template = False
        self.info_label.setText(f"Plantilla «{template['name']}» aplicada.")

    def _mark_custom(self, *_):
        """Si el cambio lo hizo el usuario (no _apply_template), deja de haber plantilla elegida."""
        if self._applying_template:
            return
        if self.template_combo.currentData() is not None:
            self.template_combo.blockSignals(True)
            self.template_combo.setCurrentIndex(0)
            self.template_combo.blockSignals(False)
            self.delete_template_btn.setEnabled(False)

    def _save_template(self):
        name, ok = QInputDialog.getText(self, "Guardar plantilla", "Nombre de la plantilla:")
        name = name.strip()
        if not ok or not name:
            return
        existing = next((t for t in self._templates if t["name"].lower() == name.lower()), None)
        if existing:
            answer = QMessageBox.question(
                self, "Plantilla existente",
                f"Ya existe una plantilla llamada «{name}». ¿Reemplazarla?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        save_template(name, self._current_layout(), self.subs_check.isChecked(), self._current_style())
        self._refresh_templates()
        idx = self.template_combo.findText(name)
        if idx >= 0:
            self.template_combo.setCurrentIndex(idx)
        self.info_label.setText(f"Plantilla «{name}» guardada.")

    def _delete_template(self):
        template_id = self.template_combo.currentData()
        if template_id is None:
            return
        template = next((t for t in self._templates if t["id"] == template_id), None)
        name = template["name"] if template else ""
        answer = QMessageBox.question(self, "Eliminar plantilla", f"¿Eliminar la plantilla «{name}»?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        delete_template(template_id)
        self._refresh_templates()
        self.info_label.setText(f"Plantilla «{name}» eliminada.")

    @staticmethod
    def _subs_cover(saved: dict, start: float, end: float) -> bool:
        """¿Las correcciones guardadas cubren el rango actual del clip?"""
        return saved["range_start"] <= start + 0.05 and saved["range_end"] >= end - 0.05

    def _subtitle_chunks(self, candidate, segments, style):
        """
        Pantallas de subtítulos de un clip: las corregidas si valen, si no las automáticas.
        Las correcciones se guardan palabra por palabra, así que se reagrupan según el
        estilo elegido (un estilo de frases junta más palabras que el de palabras resaltadas).
        """
        saved = get_candidate_subtitles(candidate["id"])
        if saved and self._subs_cover(saved, candidate["start_time"], candidate["end_time"]):
            return regroup_chunks(saved["chunks"], style)
        return chunks_for_clip(segments, candidate["start_time"], candidate["end_time"], style)

    def _edit_subtitles(self):
        video = self._selected_video()
        c = self._current
        if not video or not c:
            return
        segments = list_transcript_segments(video["id"])
        if not segments:
            self.info_label.setText("Este video no tiene transcripción: no hay texto para subtitular.")
            return
        chunks = self._subtitle_chunks(c, segments, self._current_style())
        if not chunks:
            self.info_label.setText("En este tramo no se detectó voz: el clip saldrá sin subtítulos.")
            return
        self.player.pause()
        dialog = SubtitleDialog(self, chunks, float(c["start_time"]))
        if not dialog.exec():
            return
        if dialog.reset_requested:
            delete_candidate_subtitles(c["id"])
            self.info_label.setText("Subtítulos automáticos restaurados para este clip.")
        else:
            save_candidate_subtitles(c["id"], c["start_time"], c["end_time"], dialog.result_chunks)
            self.info_label.setText("Subtítulos corregidos guardados. Exporta el clip para verlos.")

    def _prepare_subtitles(self, chosen: list, video, layout: str, style: str):
        """
        Crea el archivo .ass de cada clip a exportar. `layout` es la composición REAL
        (ya resuelta). Devuelve {id_candidato: ruta} (solo los clips que tienen texto)
        y cuántos clips quedarán sin subtítulos.
        """
        paths, without = {}, 0
        segments = list_transcript_segments(video["id"])
        for c in chosen:
            chunks = self._subtitle_chunks(c, segments, style) if segments else []
            ass = None
            if chunks:
                try:
                    ass = write_ass(
                        SUBTITLES_CACHE_DIR / f"clip{c['id']}.ass", chunks,
                        float(c["start_time"]), float(c["end_time"]),
                        int(video["width"]), int(video["height"]), layout, style,
                    )
                except OSError:
                    logger.exception("No se pudo escribir el archivo de subtítulos del clip %s", c["id"])
            if ass:
                paths[c["id"]] = str(ass)
            else:
                without += 1
        return paths, without

    # ---------------------------------------------------------------
    # Cámara y exportación (Etapa 6A)
    # ---------------------------------------------------------------

    def _define_camera(self):
        video = self._selected_video()
        if not video:
            return
        path = video["filepath"]
        if not Path(path).exists():
            self.info_label.setText(f"No se encuentra el video original: {path}")
            return
        default_seconds = self._current["peak_time"] if self._current and self._current["peak_time"] else 5.0
        self.player.pause()
        dialog = CameraDialog(self, path, get_video_camera(video["id"]), float(default_seconds),
                              float(video["duration_seconds"] or 0))
        if dialog.exec():
            set_video_camera(video["id"], dialog.result_region)
            self.info_label.setText("Cámara guardada para este video." if dialog.result_region
                                    else "Cámara quitada: se exportará solo el gameplay.")

    def _export(self, only_current: bool):
        if self._export_worker is not None or self._preview_worker is not None:
            return
        if not self._resolve_pending_trim():
            return
        video = self._selected_video()
        if not video:
            return
        path = video["filepath"]
        if not Path(path).exists():
            self.info_label.setText(f"No se encuentra el video original: {path}")
            return

        if only_current:
            chosen = [self._current] if self._current else []
        else:
            chosen = [c for c in self._candidates if c["review_status"] == "aprobado"]
        if not chosen:
            self.info_label.setText(
                "Selecciona un momento." if only_current
                else "No hay momentos aprobados en este video. Aprueba al menos uno con «✔ Aprobar»."
            )
            return

        camera = get_video_camera(video["id"])
        chosen_layout = self._current_layout()
        if chosen_layout == "camera" and camera is None:
            answer = QMessageBox.question(
                self, "Sin cámara marcada",
                "Todavía no marcaste dónde está la cámara del streamer en este video.\n\n"
                "¿Exportar solo el gameplay a pantalla completa vertical?\n"
                "(Puedes cancelar y usar «Marcar cámara...» primero.)",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        layout = effective_layout(chosen_layout, camera)
        style = self._current_style()
        subs, without_subs = {}, 0
        if self.subs_check.isChecked():
            subs, without_subs = self._prepare_subtitles(chosen, video, layout, style)
            if without_subs:
                logger.warning("%s clip(s) sin texto: se exportan sin subtítulos", without_subs)

        jobs = []
        for c in chosen:
            number = self._candidates.index(c) + 1 if c in self._candidates else c["id"]
            jobs.append({
                "candidate_id": c["id"],
                "label": f"{number}. {self._fmt(c['start_time'])}-{self._fmt(c['end_time'])}",
                "video_path": path,
                "start": c["start_time"],
                "end": c["end_time"],
                "out_path": default_output_path(CLIPS_EXPORTS_DIR, video["filename"],
                                                c["id"], c["start_time"], c["end_time"], layout),
                "width": video["width"],
                "height": video["height"],
                "camera": camera,
                "layout": layout,
                "subtitles_path": subs.get(c["id"]),
            })

        self.player.pause()
        self.export_progress.setValue(0)
        self.export_section.set_expanded(True)
        self.export_box.setVisible(True)
        self.info_label.setText(
            "Iniciando exportación..."
            + (f" ({without_subs} clip(s) sin voz se exportan sin subtítulos)" if without_subs else "")
        )
        self._export_worker = ExportWorker(jobs)
        self._export_worker.progress_changed.connect(self.export_progress.setValue)
        self._export_worker.status_changed.connect(self.info_label.setText)
        self._export_worker.job_finished.connect(self._handle_job_finished)
        self._export_worker.job_skipped.connect(self._handle_job_skipped)
        self._export_worker.finished_processing.connect(self._handle_export_finished)
        self._export_worker.start()
        self._update_buttons()

    def _handle_job_finished(self, candidate_id: int, success: bool, message: str):
        if success:
            set_candidate_export(candidate_id, message)
        else:
            logger.error("Exportación fallida (candidato %s): %s", candidate_id, message)

    def _handle_job_skipped(self, candidate_id: int):
        logger.info("Exportación omitida por el usuario (candidato %s)", candidate_id)

    def _handle_export_finished(self, success: bool, message: str, result):
        worker, self._export_worker = self._export_worker, None
        if worker is not None:
            worker.wait()
            worker.deleteLater()
        self.export_box.setVisible(False)
        self.info_label.setText(
            f"{message} Carpeta: {CLIPS_EXPORTS_DIR}" if success else message
        )
        logger.info("Exportación terminada: %s", message)
        self._load_candidates()

    def _skip_export(self):
        """Omite solo el clip que se está exportando; el lote sigue con el siguiente."""
        if self._export_worker is not None:
            self._export_worker.skip_current()
            self.info_label.setText("Omitiendo el clip actual...")

    def _cancel_export(self):
        if self._export_worker is not None:
            self._export_worker.cancel()
            self.info_label.setText("Cancelando exportación...")
        elif self._preview_worker is not None:
            self._preview_worker.cancel()
            self.info_label.setText("Cancelando vista previa...")

    # ---------------------------------------------------------------
    # Vista previa (Etapa 6C-2)
    # ---------------------------------------------------------------

    def _prepare_preview_subtitles(self, c, video, layout: str, style: str, start: float, end: float):
        """
        .ass de la vista previa. Se arma con el tramo de la muestra (start-end), no con
        el del clip completo, para que los tiempos de los subtítulos cuadren con ella.
        Devuelve la ruta o None si ese tramo no tiene texto.
        """
        segments = list_transcript_segments(video["id"])
        chunks = self._subtitle_chunks(c, segments, style) if segments else []
        if not chunks:
            return None
        try:
            ass = write_ass(
                PREVIEW_CACHE_DIR / f"preview_clip{c['id']}.ass", chunks, start, end,
                int(video["width"]), int(video["height"]), layout, style,
            )
        except OSError:
            logger.exception("No se pudo escribir los subtítulos de la vista previa del clip %s", c["id"])
            return None
        return str(ass) if ass else None

    def _preview_clip(self):
        """Genera una muestra corta del clip seleccionado y la reproduce en una ventana."""
        if self._export_worker is not None or self._preview_worker is not None:
            return
        if not self._resolve_pending_trim():
            return
        video = self._selected_video()
        c = self._current
        if not video or not c:
            self.info_label.setText("Selecciona un momento.")
            return
        path = video["filepath"]
        if not Path(path).exists():
            self.info_label.setText(f"No se encuentra el video original: {path}")
            return

        camera = get_video_camera(video["id"])
        layout = effective_layout(self._current_layout(), camera)
        style = self._current_style()

        # Desde donde está el reproductor (si cae dentro del clip); si no, desde el inicio.
        position = None
        if self._loaded_path == path and not self.player.source().isEmpty():
            position = self.player.position() / 1000.0
        start, end = preview_range(float(c["start_time"]), float(c["end_time"]), position)

        subs_path = None
        if self.subs_check.isChecked():
            subs_path = self._prepare_preview_subtitles(c, video, layout, style, start, end)

        try:
            PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.info_label.setText(f"No se pudo crear la carpeta de vistas previas: {exc}")
            return

        job = {
            "video_path": path,
            "start": start,
            "end": end,
            "out_path": PREVIEW_CACHE_DIR / f"preview_clip{c['id']}.mp4",
            "width": video["width"],
            "height": video["height"],
            "camera": camera,
            "layout": layout,
            "subtitles_path": subs_path,
        }
        subs_note = "con subtítulos" if subs_path else "sin subtítulos"
        self._preview_note = (
            f"Vista previa de {end - start:.0f} s desde {self._fmt(start)} · "
            f"{LAYOUTS.get(layout, layout)} · {subs_note}. "
            "Es una muestra liviana: el clip exportado tendrá mejor calidad."
        )

        self.player.pause()
        self.export_progress.setValue(0)
        self.export_section.set_expanded(True)
        self.export_box.setVisible(True)
        self.info_label.setText("Generando vista previa...")
        self._preview_worker = PreviewWorker(job)
        self._preview_worker.progress_changed.connect(self.export_progress.setValue)
        self._preview_worker.status_changed.connect(self.info_label.setText)
        self._preview_worker.finished_processing.connect(self._handle_preview_finished)
        self._preview_worker.start()
        self._update_buttons()

    def _handle_preview_finished(self, success: bool, message: str, result):
        worker, self._preview_worker = self._preview_worker, None
        if worker is not None:
            worker.wait()
            worker.deleteLater()
        self.export_box.setVisible(False)
        self._update_buttons()

        if not success:
            if "Cancelado" in message:
                self.info_label.setText("Vista previa cancelada.")
            else:
                logger.error("Error generando la vista previa: %s", message)
                self.info_label.setText(f"No se pudo generar la vista previa: {message}")
            return

        self.info_label.setText(self._preview_note)
        self.player.pause()
        PreviewDialog(self, str(result), self._preview_note).exec()

    def _open_exports_folder(self):
        CLIPS_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(CLIPS_EXPORTS_DIR)))

    # ---------------------------------------------------------------
    # Reproducción
    # ---------------------------------------------------------------

    def _clip_range_ms(self):
        c = self._current
        return int(c["start_time"] * 1000), int(c["end_time"] * 1000)

    def _apply_clip_range(self):
        """La barra de progreso va del inicio al final del momento seleccionado."""
        if self._current is None:
            self.seek_slider.setRange(0, 0)
            self.seek_slider.setEnabled(False)
            self._play_end_ms = None
            self.time_label.setText("0:00 / 0:00")
            return
        start_ms, end_ms = self._clip_range_ms()
        self._play_end_ms = end_ms
        self.seek_slider.setRange(start_ms, end_ms)
        self.seek_slider.setEnabled(True)
        self._update_time_label(self.seek_slider.value())

    def _update_time_label(self, position_ms: int):
        if self._current is None:
            return
        start_ms, end_ms = self._clip_range_ms()
        inside = min(max(int(position_ms) - start_ms, 0), end_ms - start_ms)
        self.time_label.setText(
            f"{format_time(inside / 1000)} / {format_time((end_ms - start_ms) / 1000)}"
            f"  ·  video {self._fmt(int(position_ms) / 1000)}"
        )

    def _video_path(self):
        """Ruta del video original del momento seleccionado (o None, avisando si falta)."""
        video = self._selected_video()
        if not video or not self._current:
            return None
        path = video["filepath"]
        if not Path(path).exists():
            self.info_label.setText(f"No se encuentra el video original: {path}")
            return None
        return path

    def _go_to(self, path: str, position_ms: int, play: bool):
        """Lleva el reproductor a una posición del video (cargándolo si hace falta)."""
        if self._loaded_path == path:
            self.player.setPosition(position_ms)
            self.seek_slider.setValue(position_ms)
            if play:
                self.player.play()
            else:
                self.player.pause()
        else:
            self._loaded_path = path
            self._pending_seek_ms = position_ms
            self._pending_play = play
            self.player.setSource(QUrl.fromLocalFile(path))

    def _preview_candidate(self):
        """Al seleccionar un momento: video en su inicio, en pausa, listo para navegar."""
        path = self._video_path()
        if path:
            self._go_to(path, self._clip_range_ms()[0], play=False)

    def _play_candidate(self):
        """Botón «Reproducir momento»: desde el inicio del momento."""
        path = self._video_path()
        if path:
            self._go_to(path, self._clip_range_ms()[0], play=True)

    def _seek_from_user(self, position_ms: int):
        """El usuario movió la barra: navegación dentro del momento."""
        if not self._current:
            return
        start_ms, end_ms = self._clip_range_ms()
        position_ms = min(max(int(position_ms), start_ms), end_ms)
        if self._pending_seek_ms is not None:      # el video aún se está cargando
            self._pending_seek_ms = position_ms
        else:
            self.player.setPosition(position_ms)
        self._update_time_label(position_ms)

    def _toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            return
        if not self._current or self.player.source().isEmpty():
            return
        start_ms, end_ms = self._clip_range_ms()
        position = self.player.position()
        if position >= end_ms - 200 or position < start_ms - 200:
            self.player.setPosition(start_ms)      # ya terminó: vuelve a empezar el momento
        self.player.play()

    def _handle_media_status(self, status):
        loaded = (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia)
        if status in loaded and self._pending_seek_ms is not None:
            position = self._pending_seek_ms
            self._pending_seek_ms = None
            self.player.setPosition(position)
            self.seek_slider.setValue(position)
            if self._pending_play:
                self.player.play()
            else:
                self.player.pause()      # deja un cuadro visible en el inicio del momento

    def _handle_position(self, position_ms: int):
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(position_ms)
        self._update_time_label(position_ms)
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if playing and self._play_end_ms is not None and position_ms >= self._play_end_ms:
            self.player.pause()          # llegó al final del momento

    def _handle_player_error(self, error, message=""):
        logger.error("Error del reproductor: %s %s", error, message)
        self._loaded_path = None
        self._pending_seek_ms = None
        self.seek_slider.setEnabled(False)
        self.info_label.setText(
            f"No se pudo reproducir el video aquí ({message or error}). "
            "Puedes abrirlo en tu reproductor y buscar el minuto indicado."
        )

    def pause(self):
        self.player.pause()
