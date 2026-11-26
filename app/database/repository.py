"""
Maneja toda la comunicación con la base de datos SQLite:
crear las tablas, guardar proyectos, videos, transcripciones y
candidatos a clip y análisis visual, y consultarlos.
"""

import json
import sqlite3
from datetime import datetime, timezone

from app.config.settings import DB_PATH


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # permite acceder a las columnas por nombre
    return conn


def init_database():
    """Crea las tablas si todavía no existen. Se llama al iniciar la app."""
    conn = _get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            filepath TEXT NOT NULL,
            filename TEXT NOT NULL,
            duration_seconds REAL,
            width INTEGER,
            height INTEGER,
            fps REAL,
            video_codec TEXT,
            audio_codec TEXT,
            size_bytes INTEGER,
            imported_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects (id)
        )
    """)

    conn.commit()
    _ensure_video_processing_columns(conn)
    _ensure_transcription_tables(conn)
    _ensure_candidate_tables(conn)
    _ensure_visual_tables(conn)
    _ensure_export_columns(conn)
    _ensure_subtitle_tables(conn)
    _ensure_template_tables(conn)
    conn.close()


def _ensure_export_columns(conn: sqlite3.Connection):
    """
    Etapa 6: región de la cámara del streamer (por video, en fracciones 0-1
    del cuadro) y ruta del clip exportado (por candidato). Se agregan solo
    si faltan, así los proyectos anteriores siguen funcionando.
    """
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(videos)")
    existing = {row["name"] for row in cur.fetchall()}
    for column in ("cam_x", "cam_y", "cam_w", "cam_h"):
        if column not in existing:
            cur.execute(f"ALTER TABLE videos ADD COLUMN {column} REAL")

    cur.execute("PRAGMA table_info(candidates)")
    existing = {row["name"] for row in cur.fetchall()}
    if "exported_path" not in existing:
        cur.execute("ALTER TABLE candidates ADD COLUMN exported_path TEXT")
    if "exported_at" not in existing:
        cur.execute("ALTER TABLE candidates ADD COLUMN exported_at TEXT")
    conn.commit()


def _ensure_subtitle_tables(conn: sqlite3.Connection):
    """
    Etapa 6B: subtítulos corregidos a mano (uno por candidato). Se guardan con
    tiempos del video original y el rango que cubrían al corregirlos.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candidate_subtitles (
            candidate_id INTEGER PRIMARY KEY,
            range_start REAL NOT NULL,
            range_end REAL NOT NULL,
            chunks_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (candidate_id) REFERENCES candidates (id)
        )
    """)
    conn.commit()


def _ensure_template_tables(conn: sqlite3.Connection):
    """
    Etapa 6C-3: plantillas de exportación. Cada una guarda una composición,
    si lleva subtítulos y con qué estilo, para aplicarlas con un clic en
    lugar de elegir las tres cosas cada vez. No son de un proyecto en
    concreto: están disponibles en todos.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS export_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            layout TEXT NOT NULL,
            subtitles_enabled INTEGER NOT NULL,
            style TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()


def _ensure_video_processing_columns(conn: sqlite3.Connection):
    """
    Agrega a la tabla videos las columnas que necesitan las Etapas 2 y 3
    (estado de procesamiento, audio extraído, miniatura, estado de
    transcripción) si todavía no existen. Así los proyectos creados en
    etapas anteriores siguen funcionando sin perder datos.
    """
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(videos)")
    existing_columns = {row["name"] for row in cur.fetchall()}

    new_columns = {
        "status": "TEXT DEFAULT 'pendiente'",
        "audio_path": "TEXT",
        "thumbnail_path": "TEXT",
        "processed_at": "TEXT",
        # Etapa 3
        "transcription_status": "TEXT DEFAULT 'pendiente'",
    }

    for column, definition in new_columns.items():
        if column not in existing_columns:
            cur.execute(f"ALTER TABLE videos ADD COLUMN {column} {definition}")

    conn.commit()


def _ensure_transcription_tables(conn: sqlite3.Connection):
    """Crea las tablas de transcripciones (Etapa 3) si no existen."""
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL UNIQUE,
            language TEXT,
            language_probability REAL,
            model TEXT,
            audio_duration REAL,
            processing_seconds REAL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (video_id) REFERENCES videos (id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transcript_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transcript_id INTEGER NOT NULL,
            seg_index INTEGER NOT NULL,
            start_time REAL NOT NULL,
            end_time REAL NOT NULL,
            text TEXT NOT NULL,
            words_json TEXT,
            FOREIGN KEY (transcript_id) REFERENCES transcripts (id)
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_segments_transcript
        ON transcript_segments (transcript_id, seg_index)
    """)

    conn.commit()


def _ensure_candidate_tables(conn: sqlite3.Connection):
    """Crea la tabla de candidatos a clip (Etapa 4) si no existe."""
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL,
            start_time REAL NOT NULL,
            end_time REAL NOT NULL,
            duration REAL NOT NULL,
            peak_time REAL,
            score REAL NOT NULL,
            category TEXT,
            reason TEXT,
            breakdown_json TEXT,
            transcript TEXT,
            review_status TEXT NOT NULL DEFAULT 'pendiente',
            created_at TEXT NOT NULL,
            FOREIGN KEY (video_id) REFERENCES videos (id)
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_candidates_video
        ON candidates (video_id, score DESC)
    """)

    conn.commit()


def _ensure_visual_tables(conn: sqlite3.Connection):
    """Crea la tabla del análisis visual (Etapa 5) si no existe."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS visual_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL UNIQUE,
            sample_interval REAL NOT NULL,
            motion_json TEXT NOT NULL,
            changed_json TEXT NOT NULL,
            flash_json TEXT NOT NULL,
            processing_seconds REAL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (video_id) REFERENCES videos (id)
        )
    """)
    conn.commit()


def create_project(name: str) -> int:
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO projects (name, created_at) VALUES (?, ?)",
        (name, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    project_id = cur.lastrowid
    conn.close()
    return project_id


def list_projects() -> list[sqlite3.Row]:
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM projects ORDER BY created_at DESC")
    rows = cur.fetchall()
    conn.close()
    return rows


def add_video(project_id: int, metadata: dict) -> int:
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO videos (
            project_id, filepath, filename, duration_seconds,
            width, height, fps, video_codec, audio_codec,
            size_bytes, imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        project_id,
        metadata["filepath"],
        metadata["filename"],
        metadata["duration_seconds"],
        metadata["width"],
        metadata["height"],
        metadata["fps"],
        metadata["video_codec"],
        metadata["audio_codec"],
        metadata["size_bytes"],
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    video_id = cur.lastrowid
    conn.close()
    return video_id


def list_videos(project_id: int) -> list[sqlite3.Row]:
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM videos WHERE project_id = ? ORDER BY imported_at DESC",
        (project_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def _delete_video_data(cur: sqlite3.Cursor, video_id: int):
    """
    Borra, para un video, todo lo que depende de él en la base de datos
    (transcripción, candidatos y sus subtítulos corregidos, análisis visual)
    y al final el propio video. No borra ningún archivo del disco: ni el
    video original, ni el audio/miniatura/clips/subtítulos ya generados.
    """
    cur.execute("SELECT id FROM transcripts WHERE video_id = ?", (video_id,))
    for row in cur.fetchall():
        cur.execute("DELETE FROM transcript_segments WHERE transcript_id = ?", (row["id"],))
    cur.execute("DELETE FROM transcripts WHERE video_id = ?", (video_id,))

    cur.execute("SELECT id FROM candidates WHERE video_id = ?", (video_id,))
    for row in cur.fetchall():
        cur.execute("DELETE FROM candidate_subtitles WHERE candidate_id = ?", (row["id"],))
    cur.execute("DELETE FROM candidates WHERE video_id = ?", (video_id,))

    cur.execute("DELETE FROM visual_analysis WHERE video_id = ?", (video_id,))
    cur.execute("DELETE FROM videos WHERE id = ?", (video_id,))


def delete_video(video_id: int):
    """
    Elimina un video del proyecto (y su transcripción, momentos detectados,
    subtítulos corregidos y análisis visual). No borra el archivo de video
    original ni los archivos ya generados (audio, miniatura, clips
    exportados, subtítulos): esos se quedan donde estaban, en el disco.
    """
    conn = _get_connection()
    try:
        _delete_video_data(conn.cursor(), video_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_project(project_id: int):
    """
    Elimina un proyecto y todos sus videos (con todo lo que depende de cada
    uno). No borra ningún archivo del disco, solo las referencias en la
    base de datos.
    """
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM videos WHERE project_id = ?", (project_id,))
        for row in cur.fetchall():
            _delete_video_data(cur, row["id"])
        cur.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_video_processing(
    video_id: int,
    status: str,
    audio_path: str | None = None,
    thumbnail_path: str | None = None,
):
    """
    Actualiza el estado de procesamiento de un video: 'pendiente',
    'procesando', 'completado' o 'error'. Si se pasan audio_path o
    thumbnail_path, se guardan también (si no, se conservan los que
    ya había).
    """
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE videos
        SET status = ?,
            audio_path = COALESCE(?, audio_path),
            thumbnail_path = COALESCE(?, thumbnail_path),
            processed_at = ?
        WHERE id = ?
    """, (
        status,
        audio_path,
        thumbnail_path,
        datetime.now(timezone.utc).isoformat(),
        video_id,
    ))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------
# Etapa 3 — Transcripciones
# ---------------------------------------------------------------

def save_transcript(video_id: int, data: dict):
    """
    Guarda la transcripción completa de un video (cabecera + segmentos)
    en una sola operación. Si el video ya tenía una transcripción, la
    reemplaza. Marca el video con transcription_status = 'completado'.

    `data` es el diccionario que devuelve transcribe_audio().
    """
    conn = _get_connection()
    try:
        cur = conn.cursor()

        # Borra una transcripción anterior del mismo video (si existe).
        cur.execute("SELECT id FROM transcripts WHERE video_id = ?", (video_id,))
        for row in cur.fetchall():
            cur.execute("DELETE FROM transcript_segments WHERE transcript_id = ?", (row["id"],))
        cur.execute("DELETE FROM transcripts WHERE video_id = ?", (video_id,))

        cur.execute("""
            INSERT INTO transcripts (
                video_id, language, language_probability, model,
                audio_duration, processing_seconds, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            video_id,
            data.get("language"),
            data.get("language_probability"),
            data.get("model"),
            data.get("audio_duration"),
            data.get("processing_seconds"),
            datetime.now(timezone.utc).isoformat(),
        ))
        transcript_id = cur.lastrowid

        cur.executemany("""
            INSERT INTO transcript_segments (
                transcript_id, seg_index, start_time, end_time, text, words_json
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, [
            (
                transcript_id,
                index,
                seg["start"],
                seg["end"],
                seg["text"],
                json.dumps(seg.get("words", []), ensure_ascii=False),
            )
            for index, seg in enumerate(data["segments"])
        ])

        cur.execute(
            "UPDATE videos SET transcription_status = 'completado' WHERE id = ?",
            (video_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_transcript(video_id: int) -> sqlite3.Row | None:
    """Devuelve la cabecera de la transcripción de un video (o None si no hay)."""
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM transcripts WHERE video_id = ?", (video_id,))
    row = cur.fetchone()
    conn.close()
    return row


def list_transcript_segments(video_id: int) -> list[sqlite3.Row]:
    """Devuelve los segmentos (con tiempos) de la transcripción de un video, en orden."""
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.seg_index, s.start_time, s.end_time, s.text, s.words_json
        FROM transcript_segments s
        JOIN transcripts t ON t.id = s.transcript_id
        WHERE t.video_id = ?
        ORDER BY s.seg_index
    """, (video_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------
# Etapa 4 — Candidatos a clip
# ---------------------------------------------------------------

def save_candidates(video_id: int, candidates: list):
    """
    Guarda los candidatos detectados para un video. Si el video ya tenía
    candidatos, los reemplaza (se pierden las aprobaciones/rechazos
    anteriores, porque corresponden a una detección distinta).

    `candidates` es la lista que devuelve detect_candidates().
    """
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM candidates WHERE video_id = ?", (video_id,))
        now = datetime.now(timezone.utc).isoformat()
        cur.executemany("""
            INSERT INTO candidates (
                video_id, start_time, end_time, duration, peak_time, score,
                category, reason, breakdown_json, transcript, review_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pendiente', ?)
        """, [
            (
                video_id,
                # float()/int() evitan que SQLite guarde números de numpy como bytes
                float(c["start"]),
                float(c["end"]),
                float(c["duration"]),
                float(c["peak_time"]) if c.get("peak_time") is not None else None,
                float(c["score"]),
                c.get("category"),
                c.get("reason"),
                json.dumps(
                    {k: int(v) for k, v in c.get("breakdown", {}).items()},
                    ensure_ascii=False,
                ),
                c.get("transcript", ""),
                now,
            )
            for c in candidates
        ])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_candidates(video_id: int) -> list[sqlite3.Row]:
    """Candidatos de un video, de mayor a menor puntuación."""
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM candidates WHERE video_id = ? ORDER BY score DESC, start_time",
        (video_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def count_candidates(video_id: int) -> int:
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n FROM candidates WHERE video_id = ?", (video_id,))
    n = cur.fetchone()["n"]
    conn.close()
    return n


def update_candidate_review(candidate_id: int, review_status: str):
    """Marca un candidato como 'pendiente', 'aprobado' o 'rechazado'."""
    if review_status not in ("pendiente", "aprobado", "rechazado"):
        raise ValueError(f"Estado de revisión no válido: {review_status}")
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE candidates SET review_status = ? WHERE id = ?",
        (review_status, candidate_id),
    )
    conn.commit()
    conn.close()


def update_candidate_times(candidate_id: int, start: float, end: float):
    """Etapa 6: guarda los tiempos ajustados a mano de un candidato."""
    if end <= start:
        raise ValueError("El final debe ser mayor que el inicio.")
    conn = _get_connection()
    conn.execute(
        "UPDATE candidates SET start_time = ?, end_time = ?, duration = ?, "
        "exported_path = NULL, exported_at = NULL WHERE id = ?",
        (float(start), float(end), round(float(end) - float(start), 1), candidate_id),
    )
    conn.commit()
    conn.close()


def set_candidate_export(candidate_id: int, path: str):
    """Etapa 6: anota dónde quedó el clip exportado."""
    conn = _get_connection()
    conn.execute(
        "UPDATE candidates SET exported_path = ?, exported_at = ? WHERE id = ?",
        (str(path), datetime.now(timezone.utc).isoformat(), candidate_id),
    )
    conn.commit()
    conn.close()


def set_video_camera(video_id: int, region):
    """
    Etapa 6: guarda la región de la cámara del streamer como fracciones
    0-1 del cuadro (x, y, ancho, alto). `None` la borra.
    """
    conn = _get_connection()
    if region is None:
        values = (None, None, None, None, video_id)
    else:
        values = (*(float(v) for v in region), video_id)
    conn.execute(
        "UPDATE videos SET cam_x = ?, cam_y = ?, cam_w = ?, cam_h = ? WHERE id = ?",
        values,
    )
    conn.commit()
    conn.close()


def get_video_camera(video_id: int):
    """Región de la cámara (x, y, ancho, alto en fracciones) o None si no está definida."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT cam_x, cam_y, cam_w, cam_h FROM videos WHERE id = ?", (video_id,)
    ).fetchone()
    conn.close()
    if not row or row["cam_x"] is None:
        return None
    return row["cam_x"], row["cam_y"], row["cam_w"], row["cam_h"]


# ---------------------------------------------------------------
# Etapa 5 — Análisis visual
# ---------------------------------------------------------------

def save_visual_analysis(video_id: int, measures: dict):
    """
    Guarda las mediciones visuales de un video (una por fotograma muestreado).
    Si el video ya tenía análisis visual, lo reemplaza.
    `measures` es el diccionario que devuelve measure_frames().
    """
    def as_floats(values):
        return json.dumps([float(v) for v in values])   # float(): nunca tipos de numpy

    conn = _get_connection()
    try:
        conn.execute("DELETE FROM visual_analysis WHERE video_id = ?", (video_id,))
        conn.execute("""
            INSERT INTO visual_analysis (
                video_id, sample_interval, motion_json, changed_json, flash_json,
                processing_seconds, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            video_id,
            float(measures["interval"]),
            as_floats(measures["motion"]),
            as_floats(measures["changed"]),
            as_floats(measures["flash"]),
            float(measures.get("processing_seconds") or 0),
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_visual_analysis(video_id: int) -> dict | None:
    """Devuelve las mediciones visuales de un video (o None si no hay)."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT * FROM visual_analysis WHERE video_id = ?", (video_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "interval": row["sample_interval"],
        "motion": json.loads(row["motion_json"]),
        "changed": json.loads(row["changed_json"]),
        "flash": json.loads(row["flash_json"]),
        "processing_seconds": row["processing_seconds"],
    }


def has_visual_analysis(video_id: int) -> bool:
    conn = _get_connection()
    row = conn.execute(
        "SELECT 1 FROM visual_analysis WHERE video_id = ?", (video_id,)
    ).fetchone()
    conn.close()
    return row is not None


# ---------------------------------------------------------------
# Etapa 6B — Subtítulos corregidos a mano
# ---------------------------------------------------------------

def save_candidate_subtitles(candidate_id: int, range_start: float, range_end: float, chunks: list):
    """Guarda los subtítulos corregidos de un candidato (reemplaza los anteriores)."""
    conn = _get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO candidate_subtitles "
        "(candidate_id, range_start, range_end, chunks_json, updated_at) VALUES (?, ?, ?, ?, ?)",
        (candidate_id, float(range_start), float(range_end),
         json.dumps(chunks, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def get_candidate_subtitles(candidate_id: int):
    """
    Subtítulos corregidos: diccionario {"range_start", "range_end", "chunks"},
    o None si el candidato no tiene correcciones guardadas.
    """
    conn = _get_connection()
    row = conn.execute(
        "SELECT * FROM candidate_subtitles WHERE candidate_id = ?", (candidate_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    try:
        chunks = json.loads(row["chunks_json"])
    except ValueError:
        return None
    return {"range_start": row["range_start"], "range_end": row["range_end"], "chunks": chunks}


def delete_candidate_subtitles(candidate_id: int):
    """Borra las correcciones: se vuelve a los subtítulos automáticos."""
    conn = _get_connection()
    conn.execute("DELETE FROM candidate_subtitles WHERE candidate_id = ?", (candidate_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------
# Etapa 6C-3 — Plantillas de exportación
# ---------------------------------------------------------------

def save_template(name: str, layout: str, subtitles_enabled: bool, style: str):
    """
    Guarda una plantilla con la composición, si lleva subtítulos y el estilo.
    Si ya existe una plantilla con ese nombre (sin importar mayúsculas), la
    reemplaza en vez de crear una segunda.
    """
    conn = _get_connection()
    conn.execute(
        "INSERT INTO export_templates (name, layout, subtitles_enabled, style, created_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET layout = excluded.layout, "
        "subtitles_enabled = excluded.subtitles_enabled, style = excluded.style, "
        "created_at = excluded.created_at",
        (name, layout, int(bool(subtitles_enabled)), style, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def list_templates() -> list[sqlite3.Row]:
    """Todas las plantillas guardadas, por nombre."""
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM export_templates ORDER BY name COLLATE NOCASE")
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_template(template_id: int):
    conn = _get_connection()
    conn.execute("DELETE FROM export_templates WHERE id = ?", (template_id,))
    conn.commit()
    conn.close()
