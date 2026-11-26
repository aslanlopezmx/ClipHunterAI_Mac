"""
Pantalla de Análisis.

Botón principal «Analizar video»: corre en secuencia, en segundo plano, los
cuatro pasos del análisis (omitiendo los que ya estén hechos):

    1) Extraer audio (y miniatura)
    2) Transcribir la voz con Faster-Whisper
    3) Analizar la imagen (movimiento y cambios de escena)
    4) Buscar momentos interesantes

Una lista de pasos muestra qué está hecho (✔), qué se está haciendo (⏳),
qué falta (○) y dónde falló (✘). Al terminar con momentos encontrados se emite
`pipeline_finished` para que la ventana principal lleve a revisarlos.

La sección «Avanzado» conserva los botones de cada paso por separado (para
repetir uno) y la transcripción.

Solo corre una tarea pesada a la vez, para no saturar la CPU/RAM.
"""

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QMessageBox, QProgressBar,
    QPushButton, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from app.database.repository import (
    count_candidates,
    delete_video,
    get_transcript,
    get_visual_analysis,
    has_visual_analysis,
    list_transcript_segments,
    list_videos,
    save_candidates,
    save_transcript,
    save_visual_analysis,
    update_video_processing,
)
from app.engine.transcription_service import format_timestamp
from app.workers.detection_worker import DetectionWorker
from app.workers.transcription_worker import TranscriptionWorker
from app.workers.video_processing_worker import VideoProcessingWorker
from app.workers.visual_worker import VisualAnalysisWorker
from app.interface.theme import set_role

logger = logging.getLogger(__name__)

# Orden del recorrido. La clave es la misma que usa _worker_kind.
PIPELINE_ORDER = ("proceso", "transcripcion", "imagen", "deteccion")
STEP_NAMES = {
    # clave: (nombre en la lista, texto mientras corre)
    "proceso": ("Extraer audio", "Extrayendo audio…"),
    "transcripcion": ("Transcribir voz", "Transcribiendo voz…"),
    "imagen": ("Analizar imagen", "Analizando imagen…"),
    "deteccion": ("Buscar momentos", "Buscando momentos…"),
}


class AnalysisView(QWidget):
    # Se emite (id del video) cuando el análisis completo terminó y hay momentos.
    pipeline_finished = Signal(int)
    # Se emite cuando cambió algo que afecta al avance del proyecto.
    analysis_changed = Signal()

    def __init__(self):
        super().__init__()
        self.current_project = None
        self._videos = []
        self._selected_video = None
        self._worker = None
        self._worker_kind = None       # "proceso", "transcripcion", "imagen" o "deteccion"
        self._active_video_id = None   # video al que pertenece la tarea en curso
        self._pipeline = None          # {"video_id": int} mientras corre «Analizar video»
        self._failed_step = None       # paso que falló o se canceló (para mostrar ✘)
        self._step_percent = 0

        layout = QVBoxLayout(self)

        self.project_label = QLabel("Ningún proyecto seleccionado. Ve a Inicio y abre un proyecto.")
        self.project_label.setWordWrap(True)
        layout.addWidget(self.project_label)

        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        set_role(self.hint_label, "hint")
        layout.addWidget(self.hint_label)

        self.video_list = QListWidget()
        self.video_list.setMaximumHeight(170)
        self.video_list.currentRowChanged.connect(self._handle_selection_changed)
        layout.addWidget(self.video_list)

        # --- Acción principal ---
        main_row = QHBoxLayout()
        self.analyze_btn = QPushButton("Analizar video")
        self.analyze_btn.setMinimumHeight(40)
        set_role(self.analyze_btn, "primary")
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.clicked.connect(self._handle_analyze)
        main_row.addWidget(self.analyze_btn)

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setMinimumHeight(40)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._handle_cancel)
        main_row.addWidget(self.cancel_btn)

        self.delete_btn = QPushButton("Eliminar video")
        set_role(self.delete_btn, "danger")
        self.delete_btn.setMinimumHeight(40)
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._handle_delete)
        main_row.addWidget(self.delete_btn)

        refresh_btn = QPushButton("Actualizar lista")
        refresh_btn.setMinimumHeight(40)
        refresh_btn.clicked.connect(self.refresh)
        main_row.addWidget(refresh_btn)
        main_row.addStretch()
        layout.addLayout(main_row)

        # --- Lista de pasos ---
        steps_frame = QFrame()
        steps_frame.setFrameShape(QFrame.Shape.StyledPanel)
        steps_layout = QVBoxLayout(steps_frame)
        steps_title = QLabel("Pasos del análisis")
        set_role(steps_title, "title")
        steps_layout.addWidget(steps_title)
        self._step_labels = {}
        for key in PIPELINE_ORDER:
            label = QLabel("")
            # (el estilo lo controla el tema)
            steps_layout.addWidget(label)
            self._step_labels[key] = label
        layout.addWidget(steps_frame)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # --- Avanzado (plegado por defecto) ---
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Avanzado")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(False)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        layout.addWidget(self.advanced_toggle)

        self.advanced_box = QWidget()
        adv_layout = QVBoxLayout(self.advanced_box)
        adv_layout.setContentsMargins(0, 0, 0, 0)

        adv_hint = QLabel("Para repetir un solo paso. Cada botón se activa cuando el paso anterior ya está hecho.")
        adv_hint.setWordWrap(True)
        set_role(adv_hint, "hint")
        adv_layout.addWidget(adv_hint)

        buttons_row = QHBoxLayout()
        self.process_btn = QPushButton("Procesar video (audio)")
        self.process_btn.clicked.connect(self._handle_process)
        buttons_row.addWidget(self.process_btn)

        self.transcribe_btn = QPushButton("Transcribir")
        self.transcribe_btn.clicked.connect(self._handle_transcribe)
        buttons_row.addWidget(self.transcribe_btn)

        self.view_transcript_btn = QPushButton("Ver transcripción")
        self.view_transcript_btn.clicked.connect(self._show_transcript)
        buttons_row.addWidget(self.view_transcript_btn)

        self.visual_btn = QPushButton("Analizar imagen")
        self.visual_btn.clicked.connect(self._handle_visual)
        buttons_row.addWidget(self.visual_btn)

        self.detect_btn = QPushButton("Detectar momentos")
        self.detect_btn.clicked.connect(self._handle_detect)
        buttons_row.addWidget(self.detect_btn)
        buttons_row.addStretch()
        adv_layout.addLayout(buttons_row)

        self.transcript_box = QTextEdit()
        self.transcript_box.setReadOnly(True)
        self.transcript_box.setMinimumHeight(180)
        self.transcript_box.setPlaceholderText(
            "Aquí aparecerá la transcripción del video seleccionado."
        )
        adv_layout.addWidget(self.transcript_box, stretch=1)

        self.advanced_box.setVisible(False)
        layout.addWidget(self.advanced_box, stretch=1)
        layout.addStretch(0)

        self._render_steps()
        self._update_buttons()

    def _toggle_advanced(self, checked: bool):
        self.advanced_box.setVisible(checked)
        self.advanced_toggle.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )

    # ---------------------------------------------------------------
    # Lista de videos
    # ---------------------------------------------------------------

    def set_current_project(self, project: dict):
        self.current_project = project
        self.project_label.setText(f"Proyecto actual: {project['name']}")
        self.transcript_box.clear()
        self._selected_video = None
        self._failed_step = None
        self.refresh()

    def select_video(self, video_id: int):
        """Refresca la lista y deja seleccionado el video indicado."""
        self._selected_video = None
        self.refresh()
        for row, video in enumerate(self._videos):
            if video["id"] == video_id:
                self.video_list.setCurrentRow(row)
                break

    def _video_by_id(self, video_id):
        return next((v for v in self._videos if v["id"] == video_id), None)

    def _step_done(self, video, key: str) -> bool:
        if key == "proceso":
            return (video["status"] or "pendiente") == "completado"
        if key == "transcripcion":
            return (video["transcription_status"] or "pendiente") == "completado"
        if key == "imagen":
            return has_visual_analysis(video["id"])
        return count_candidates(video["id"]) > 0

    def _video_summary(self, video) -> str:
        """Resumen de una línea del avance de un video, fácil de leer de un vistazo."""
        pending = [STEP_NAMES[k][0] for k in PIPELINE_ORDER if not self._step_done(video, k)]
        if not pending:
            return f"{video['filename']}   —   ✔ Listo · {count_candidates(video['id'])} momentos"
        if len(pending) == len(PIPELINE_ORDER):
            return f"{video['filename']}   —   ○ Sin analizar"
        done = len(PIPELINE_ORDER) - len(pending)
        return f"{video['filename']}   —   ◐ {done} de {len(PIPELINE_ORDER)} pasos · falta: {pending[0].lower()}"

    def refresh(self):
        previous_id = self._selected_video["id"] if self._selected_video else None

        self.video_list.blockSignals(True)
        self.video_list.clear()
        self._videos = []

        if self.current_project:
            self._videos = list_videos(self.current_project["id"])
            for video in self._videos:
                self.video_list.addItem(self._video_summary(video))

        # Conserva la selección que había (si el video sigue en la lista).
        selected_row = -1
        for row, video in enumerate(self._videos):
            if video["id"] == previous_id:
                selected_row = row
                break
        # Sin selección previa: el primer video que aún falta por analizar (o el primero).
        if selected_row < 0 and self._videos:
            selected_row = next(
                (i for i, v in enumerate(self._videos)
                 if not all(self._step_done(v, k) for k in PIPELINE_ORDER)),
                0,
            )
        if selected_row >= 0:
            self.video_list.setCurrentRow(selected_row)
        self.video_list.blockSignals(False)

        if not self.current_project:
            self.hint_label.setText("")
        elif not self._videos:
            self.hint_label.setText("Este proyecto todavía no tiene videos. Ve a «1 · Importar» para agregar uno.")
        else:
            self.hint_label.setText("Elige un video y pulsa «Analizar video»: se hacen todos los pasos solos.")

        self._handle_selection_changed(selected_row)

    def _handle_selection_changed(self, index: int):
        if 0 <= index < len(self._videos):
            new_video = self._videos[index]
            if self._selected_video is None or self._selected_video["id"] != new_video["id"]:
                self._failed_step = None
            self._selected_video = new_video
        else:
            self._selected_video = None
        self._update_buttons()
        self._render_steps()

    def _update_buttons(self):
        busy = self._worker is not None or self._pipeline is not None
        video = self._selected_video

        self.video_list.setEnabled(not busy)

        if video is None:
            for btn in (self.analyze_btn, self.process_btn, self.transcribe_btn,
                        self.view_transcript_btn, self.detect_btn, self.visual_btn,
                        self.delete_btn):
                btn.setEnabled(False)
        else:
            status = video["status"] or "pendiente"
            t_status = video["transcription_status"] or "pendiente"
            self.analyze_btn.setEnabled(not busy)
            all_done = all(self._step_done(video, k) for k in PIPELINE_ORDER)
            self.analyze_btn.setText("Volver a analizar" if all_done else "Analizar video")
            self.process_btn.setEnabled(status == "pendiente" and not busy)
            self.transcribe_btn.setEnabled(
                status == "completado" and t_status == "pendiente" and not busy
            )
            self.view_transcript_btn.setEnabled(t_status == "completado")
            self.detect_btn.setEnabled(t_status == "completado" and not busy)
            self.visual_btn.setEnabled(status == "completado" and not busy)
            self.delete_btn.setEnabled(not busy)

        self.cancel_btn.setEnabled(busy)

    def _render_steps(self):
        """Dibuja la lista de pasos del video seleccionado: ✓ hecho, … en curso, ✗ falló, ○ falta."""
        video = self._selected_video
        running = self._worker_kind if self._worker is not None else None
        for number, key in enumerate(PIPELINE_ORDER, start=1):
            name, active_text = STEP_NAMES[key]
            if running == key:
                mark, text = "…", f"{active_text} {self._step_percent}%"
                role = "step_active"
            elif self._failed_step == key:
                mark, text = "✗", f"{name} (no se completó)"
                role = "step_failed"
            elif video is not None and self._step_done(video, key):
                mark, text = "✓", name
                role = "step_done"
            else:
                mark, text = "○", name
                role = "step_pending"
            label = self._step_labels[key]
            label.setText(f"{mark}  {number}. {text}")
            set_role(label, role)

    # ---------------------------------------------------------------
    # Recorrido completo: «Analizar video»
    # ---------------------------------------------------------------

    def _handle_analyze(self):
        video = self._selected_video
        if video is None or self._worker is not None or self._pipeline is not None:
            return
        if count_candidates(video["id"]) > 0:
            answer = QMessageBox.question(
                self, "Analizar de nuevo",
                "Este video ya tiene momentos detectados. Si lo analizas de nuevo se "
                "buscan otra vez y se pierden las aprobaciones y rechazos.\n\n"
                "Los pasos ya hechos (audio, transcripción e imagen) no se repiten. ¿Continuar?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._failed_step = None
        self._pipeline = {"video_id": video["id"]}
        self._pipeline_next()

    def _pipeline_next(self):
        """Arranca el siguiente paso pendiente del recorrido."""
        pipeline = self._pipeline
        if pipeline is None:
            return
        video = self._video_by_id(pipeline["video_id"])
        if video is None:
            self._end_pipeline(False)
            return
        for key in PIPELINE_ORDER:
            # «Buscar momentos» siempre corre al final (los demás se omiten si ya están hechos).
            if key != "deteccion" and self._step_done(video, key):
                continue
            started = {
                "proceso": lambda: self._run_process(video),
                "transcripcion": lambda: self._run_transcribe(video),
                "imagen": lambda: self._run_visual(video),
                "deteccion": lambda: self._run_detect(video, confirm=False),
            }[key]()
            if started is False:           # no pudo arrancar (p. ej. no hay texto transcrito)
                self._failed_step = key
                self._end_pipeline(False)
            return

    def _after_step(self, key: str, success: bool):
        """Se llama al terminar cada paso; si va dentro del recorrido, decide qué sigue."""
        if self._pipeline is None:
            self.analysis_changed.emit()
            return
        if not success:
            self._failed_step = key
            self._end_pipeline(False)
        elif key == "deteccion":
            self._end_pipeline(True)
        else:
            self._pipeline_next()

    def _end_pipeline(self, success: bool):
        pipeline, self._pipeline = self._pipeline, None
        self._update_buttons()
        self._render_steps()
        self.analysis_changed.emit()
        if success and pipeline and count_candidates(pipeline["video_id"]) > 0:
            self.pipeline_finished.emit(pipeline["video_id"])

    # ---------------------------------------------------------------
    # Utilidades de arranque de pasos
    # ---------------------------------------------------------------

    def _begin(self, kind: str, video, status_text: str):
        self._active_video_id = video["id"]
        self._worker_kind = kind
        self._failed_step = None
        self._step_percent = 0
        self.progress_bar.setValue(0)
        self.status_label.setText(status_text)

    def _launch(self, worker, finished_slot):
        self._worker = worker
        self._connect_worker(worker, finished_slot)
        self._update_buttons()
        self._render_steps()
        worker.start()

    # ---------------------------------------------------------------
    # Paso 1: procesar video (audio + miniatura)
    # ---------------------------------------------------------------

    def _handle_process(self):
        if self._selected_video:
            self._run_process(self._selected_video)

    def _run_process(self, video):
        self._begin("proceso", video, "Iniciando procesamiento...")
        update_video_processing(video["id"], status="procesando")
        self._launch(VideoProcessingWorker(dict(video)), self._handle_process_finished)

    def _handle_process_finished(self, success: bool, message: str, result):
        video_id = self._active_video_id

        if success:
            update_video_processing(
                video_id,
                status="completado",
                audio_path=result["audio_path"],
                thumbnail_path=result["thumbnail_path"],
            )
            self.status_label.setText("Procesamiento completado.")
            logger.info("Video %s procesado correctamente.", video_id)
        else:
            update_video_processing(video_id, status="pendiente")
            if "Cancelado" in message:
                self.status_label.setText("Procesamiento cancelado.")
                logger.info("Procesamiento del video %s cancelado por el usuario.", video_id)
            else:
                self.status_label.setText(f"Error: {message}")
                logger.error("Error procesando el video %s: %s", video_id, message)
                QMessageBox.critical(self, "Error al procesar", message)

        self._release_worker()
        self.refresh()
        self._after_step("proceso", success)

    # ---------------------------------------------------------------
    # Paso 2: transcripción
    # ---------------------------------------------------------------

    def _handle_transcribe(self):
        if self._selected_video:
            self._run_transcribe(self._selected_video)

    def _run_transcribe(self, video):
        self._begin("transcripcion", video, "Iniciando transcripción...")
        self.transcript_box.clear()
        self._launch(TranscriptionWorker(dict(video)), self._handle_transcription_finished)

    def _handle_transcription_finished(self, success: bool, message: str, result):
        video_id = self._active_video_id
        saved = False

        if success:
            try:
                save_transcript(video_id, result)
            except Exception as exc:
                logger.exception("No se pudo guardar la transcripción del video %s", video_id)
                self.status_label.setText(f"Error al guardar la transcripción: {exc}")
                QMessageBox.critical(self, "Error al guardar", str(exc))
            else:
                saved = True
                duration = result["audio_duration"]
                took = result["processing_seconds"]
                speed = duration / took if took > 0 else 0
                summary = (
                    f"Transcripción completada: {format_timestamp(duration)} de audio en "
                    f"{format_timestamp(took)} ({speed:.2f}x tiempo real), "
                    f"{len(result['segments'])} segmentos, idioma: {result['language']}."
                )
                self.status_label.setText(summary)
                logger.info("Video %s transcrito. %s", video_id, summary)
        else:
            if "Cancelado" in message:
                self.status_label.setText("Transcripción cancelada.")
                logger.info("Transcripción del video %s cancelada por el usuario.", video_id)
            else:
                self.status_label.setText(f"Error: {message}")
                logger.error("Error transcribiendo el video %s: %s", video_id, message)
                QMessageBox.critical(self, "Error al transcribir", message)

        self._release_worker()
        self.refresh()

        # Solo se muestra el texto cuando se transcribe suelto (no dentro del recorrido completo).
        if saved and self._pipeline is None and self._selected_video and self._selected_video["id"] == video_id:
            self._show_transcript()

        self._after_step("transcripcion", saved)

    def _show_transcript(self):
        """Muestra en pantalla la transcripción guardada del video seleccionado."""
        if not self._selected_video:
            return

        self.advanced_toggle.setChecked(True)
        video_id = self._selected_video["id"]
        header = get_transcript(video_id)
        if header is None:
            self.transcript_box.setPlainText("Este video todavía no tiene transcripción.")
            return

        lines = [
            f"[{format_timestamp(seg['start_time'])} - {format_timestamp(seg['end_time'])}] {seg['text']}"
            for seg in list_transcript_segments(video_id)
        ]
        self.transcript_box.setPlainText("\n".join(lines) if lines else "(Sin texto detectado)")

    # ---------------------------------------------------------------
    # Paso 3: análisis visual
    # ---------------------------------------------------------------

    def _handle_visual(self):
        if self._selected_video:
            self._run_visual(self._selected_video)

    def _run_visual(self, video):
        self._begin("imagen", video, "Iniciando análisis de imagen...")
        self._launch(VisualAnalysisWorker(dict(video)), self._handle_visual_finished)

    def _handle_visual_finished(self, success: bool, message: str, result):
        video_id = self._active_video_id
        saved = False

        if success:
            try:
                save_visual_analysis(video_id, result)
            except Exception as exc:
                logger.exception("No se pudo guardar el análisis visual del video %s", video_id)
                self.status_label.setText(f"Error al guardar el análisis de imagen: {exc}")
                QMessageBox.critical(self, "Error al guardar", str(exc))
            else:
                saved = True
                frames = len(result["motion"])
                took = result["processing_seconds"]
                summary = f"Análisis de imagen completado: {frames} fotogramas en {format_timestamp(took)}."
                if self._pipeline is None:
                    summary += (" Ahora pulsa «Detectar momentos» (en Avanzado) o «Volver a analizar» "
                                "para que la imagen cuente en la puntuación.")
                self.status_label.setText(summary)
                logger.info("Video %s: %s", video_id, summary)
        else:
            if "Cancelado" in message:
                self.status_label.setText("Análisis de imagen cancelado.")
                logger.info("Análisis visual del video %s cancelado por el usuario.", video_id)
            else:
                self.status_label.setText(f"Error: {message}")
                logger.error("Error en el análisis visual del video %s: %s", video_id, message)
                QMessageBox.critical(self, "Error al analizar la imagen", message)

        self._release_worker()
        self.refresh()
        self._after_step("imagen", saved)

    # ---------------------------------------------------------------
    # Paso 4: detección de momentos
    # ---------------------------------------------------------------

    def _handle_detect(self):
        if self._selected_video:
            self._run_detect(self._selected_video, confirm=True)

    def _run_detect(self, video, confirm: bool) -> bool:
        """Arranca la detección. Devuelve False si no pudo arrancar (o el usuario dijo que no)."""
        video = dict(video)
        segments = [
            {"start": r["start_time"], "end": r["end_time"], "text": r["text"]}
            for r in list_transcript_segments(video["id"])
        ]
        if not segments:
            QMessageBox.information(
                self, "Sin transcripción",
                "Este video no tiene texto transcrito, así que no hay conversación que analizar.",
            )
            return False

        visual_measures = get_visual_analysis(video["id"])

        if confirm and count_candidates(video["id"]) > 0:
            answer = QMessageBox.question(
                self, "Detectar de nuevo",
                "Este video ya tiene momentos detectados. Si detectas de nuevo se "
                "reemplazan y se pierden las aprobaciones y rechazos. ¿Continuar?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False

        if visual_measures:
            text = "Iniciando detección (audio, texto e imagen)..."
        else:
            text = "Iniciando detección (solo audio y texto: este video no tiene análisis de imagen)..."
        self._begin("deteccion", video, text)
        self._launch(DetectionWorker(video, segments, visual_measures), self._handle_detection_finished)
        return True

    def _handle_detection_finished(self, success: bool, message: str, result):
        video_id = self._active_video_id
        saved = False

        if success:
            try:
                save_candidates(video_id, result["candidates"])
            except Exception as exc:
                logger.exception("No se pudieron guardar los candidatos del video %s", video_id)
                self.status_label.setText(f"Error al guardar los momentos: {exc}")
                QMessageBox.critical(self, "Error al guardar", str(exc))
            else:
                saved = True
                n = len(result["candidates"])
                if n:
                    summary = f"Análisis completado: {n} momentos encontrados."
                else:
                    summary = ("Análisis completado: no se encontraron momentos con "
                               "suficiente puntuación en este video.")
                self.status_label.setText(summary)
                logger.info("Video %s: %s", video_id, summary)
        else:
            if "Cancelado" in message:
                self.status_label.setText("Detección cancelada.")
                logger.info("Detección del video %s cancelada por el usuario.", video_id)
            else:
                self.status_label.setText(f"Error: {message}")
                logger.error("Error detectando momentos del video %s: %s", video_id, message)
                QMessageBox.critical(self, "Error al detectar momentos", message)

        self._release_worker()
        self.refresh()
        self._after_step("deteccion", saved)

    # ---------------------------------------------------------------
    # Utilidades compartidas
    # ---------------------------------------------------------------

    def _on_progress(self, value: int):
        self.progress_bar.setValue(value)
        self._step_percent = value
        self._render_steps()

    def _connect_worker(self, worker, finished_slot):
        worker.progress_changed.connect(self._on_progress)
        worker.status_changed.connect(self.status_label.setText)
        worker.finished_processing.connect(finished_slot)

    def _handle_delete(self):
        if not self._selected_video or self._worker is not None or self._pipeline is not None:
            return
        video = self._selected_video
        answer = QMessageBox.question(
            self, "Eliminar video",
            f"¿Eliminar «{video['filename']}» de este proyecto?\n\n"
            "Se borra su transcripción, momentos detectados, subtítulos corregidos y "
            "análisis de imagen dentro de la app.\n\n"
            "Esto NO borra el archivo de video original de tu computadora, ni el "
            "audio/miniatura/clips exportados/subtítulos que ya se hayan generado.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        delete_video(video["id"])
        logger.info("Video eliminado del proyecto: %s (id=%s)", video["filename"], video["id"])
        self._selected_video = None
        self.transcript_box.clear()
        self.refresh()
        self.analysis_changed.emit()

    def _handle_cancel(self):
        if self._worker:
            self._worker.cancel()
            self.status_label.setText("Cancelando...")

    def _release_worker(self):
        """Espera a que el hilo termine del todo antes de soltarlo."""
        if self._worker:
            self._worker.wait()
        self._worker = None
        self._worker_kind = None
        self._active_video_id = None
        self._update_buttons()
