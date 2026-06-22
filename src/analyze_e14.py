from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "state" / "e14.sqlite"
DEFAULT_CONFIG = ROOT / "config" / "e14_rois.json"
DEFAULT_DOWNLOAD_ROOT = ROOT / "downloads" / "E14"
DEFAULT_REPORT_DIR = ROOT / "reports" / "ocr"
DEFAULT_MODEL_PATH = DEFAULT_REPORT_DIR / "model" / "digit_cnn.pt"

_DIGIT_MODEL_CACHE: dict[tuple[str, str], Any] = {}


class DependencyError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_int(value: str | None) -> int | None:
    if value is None:
        return None
    # En formularios manuscritos es comun ver rellenos tipo **5 o X05.
    # Para calculos se conservan solo digitos, dejando el texto crudo aparte.
    digits = re.sub(r"\D+", "", value)
    if not digits:
        return None
    return int(digits)


def norm_name(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace("_", " ").strip().upper()


def norm_department_code(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D+", "", str(value))
    if not digits:
        return str(value).strip().zfill(2)
    return str(int(digits)).zfill(2)


def connect_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path) -> None:
    conn = connect_db(db_path)
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                source_download_id INTEGER UNIQUE,
                relative_path TEXT NOT NULL UNIQUE,
                absolute_path TEXT NOT NULL,
                file_size INTEGER,
                file_mtime REAL,
                file_sha1 TEXT,
                department_code TEXT,
                department_name TEXT,
                municipality_code TEXT,
                municipality_name TEXT,
                zone_code TEXT,
                place_code TEXT,
                place_name TEXT,
                table_number TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                last_worker TEXT,
                lock_started_at TEXT,
                discovered_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                analyzed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_documents_status
                ON documents(status, updated_at);

            CREATE TABLE IF NOT EXISTS field_results (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                page_index INTEGER NOT NULL,
                field_key TEXT NOT NULL,
                field_label TEXT,
                field_role TEXT,
                field_type TEXT,
                raw_text TEXT,
                normalized_value INTEGER,
                confidence REAL,
                bbox_json TEXT,
                crop_path TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_field_results_document
                ON field_results(document_id);

            CREATE TABLE IF NOT EXISTS document_results (
                document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
                page_count INTEGER,
                extracted_json TEXT NOT NULL,
                confidence_json TEXT NOT NULL,
                inconsistencies_json TEXT NOT NULL,
                candidate_total INTEGER,
                blank_votes INTEGER,
                null_votes INTEGER,
                unmarked_votes INTEGER,
                declared_total INTEGER,
                urna_total INTEGER,
                e11_total INTEGER,
                incinerated_total INTEGER,
                signed_juror_count INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS inconsistencies (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                severity TEXT NOT NULL,
                code TEXT NOT NULL,
                message TEXT NOT NULL,
                details_json TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_inconsistencies_document
                ON inconsistencies(document_id);
            """
        )
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(documents)").fetchall()
        }
        if "source_download_id" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN source_download_id INTEGER")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_source_download_id "
                "ON documents(source_download_id)"
            )
        result_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(document_results)").fetchall()
        }
        if "signed_juror_count" not in result_columns:
            conn.execute("ALTER TABLE document_results ADD COLUMN signed_juror_count INTEGER")
    conn.close()


def path_metadata(root: Path, pdf_path: Path) -> dict[str, Any]:
    try:
        rel = pdf_path.resolve().relative_to(root.resolve())
    except ValueError:
        rel = pdf_path

    parts = list(rel.parts)
    if parts and parts[0].upper() == "E14":
        parts = parts[1:]

    data: dict[str, Any] = {
        "relative_path": str(rel).replace("/", os.sep),
        "department_code": None,
        "department_name": None,
        "municipality_code": None,
        "municipality_name": None,
        "zone_code": None,
        "place_code": None,
        "place_name": None,
        "table_number": None,
    }

    if len(parts) >= 1:
        match = re.match(r"^(\d{2})_(.+)$", parts[0])
        if match:
            data["department_code"] = match.group(1)
            data["department_name"] = norm_name(match.group(2))
    if len(parts) >= 2:
        match = re.match(r"^(\d{3})_(.+)$", parts[1])
        if match:
            data["municipality_code"] = match.group(1)
            data["municipality_name"] = norm_name(match.group(2))
    if len(parts) >= 3:
        match = re.match(r"^ZONA_(\d+)$", parts[2], flags=re.I)
        if match:
            data["zone_code"] = match.group(1).zfill(2)
    if len(parts) >= 4:
        match = re.match(r"^(\d{2})_(.+)$", parts[3])
        if match:
            data["place_code"] = match.group(1)
            data["place_name"] = norm_name(match.group(2))
    if parts:
        match = re.search(r"MESA_(\d+)", parts[-1], flags=re.I)
        if match:
            data["table_number"] = match.group(1).zfill(3)

    return data


def file_sha1(path: Path, block_size: int = 1024 * 1024) -> str:
    import hashlib

    digest = hashlib.sha1()
    with path.open("rb") as fh:
        while True:
            block = fh.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


def relative_to_root(root: Path, pdf_path: Path) -> str:
    try:
        return str(pdf_path.relative_to(root))
    except ValueError:
        return str(pdf_path)


def discover_pdfs(root: Path, db_path: Path, hash_files: bool = False) -> int:
    init_db(db_path)
    conn = connect_db(db_path)
    count = 0
    stamp = now_iso()
    root = root.resolve()

    if table_exists(conn, "downloads"):
        rows = conn.execute(
            """
            SELECT id, local_path, department_id, department_name,
                   municipality_id, municipality_name, zone_id,
                   polling_place_id, polling_place_name, table_number,
                   status AS download_status
            FROM downloads
            ORDER BY id
            """
        ).fetchall()
        existing_rows = conn.execute(
            """
            SELECT id, source_download_id, relative_path, status,
                   file_size, file_mtime, file_sha1
            FROM documents
            """
        ).fetchall()
        existing_by_source = {
            row["source_download_id"]: row
            for row in existing_rows
            if row["source_download_id"] is not None
        }
        existing_by_relative = {row["relative_path"]: row for row in existing_rows}

        conn.execute("BEGIN")
        try:
            for download in rows:
                pdf_path = Path(download["local_path"])
                downloaded_status = download["download_status"] == "downloaded"
                exists = pdf_path.exists() if downloaded_status else False
                is_downloaded = downloaded_status and exists
                stat = pdf_path.stat() if exists else None
                sha1 = file_sha1(pdf_path) if hash_files and exists else None
                rel_path = relative_to_root(root, pdf_path)
                row = existing_by_source.get(download["id"]) or existing_by_relative.get(rel_path)

                if row:
                    file_changed = (
                        stat is not None
                        and (
                            row["file_size"] != stat.st_size
                            or row["file_mtime"] != stat.st_mtime
                            or (hash_files and row["file_sha1"] != sha1)
                        )
                    )
                    should_queue = is_downloaded and (
                        row["status"] in ("missing_pdf", "failed") or file_changed
                    )
                    should_mark_missing = (
                        not is_downloaded
                        and row["status"] not in ("processing", "done", "inconsistent", "missing_pdf")
                    )
                    if should_queue or should_mark_missing:
                        conn.execute(
                            """
                            UPDATE documents
                            SET source_download_id = :source_download_id,
                                relative_path = :relative_path,
                                absolute_path = :absolute_path,
                                file_size = :file_size,
                                file_mtime = :file_mtime,
                                file_sha1 = COALESCE(:file_sha1, file_sha1),
                                department_code = :department_code,
                                department_name = :department_name,
                                municipality_code = :municipality_code,
                                municipality_name = :municipality_name,
                                zone_code = :zone_code,
                                place_code = :place_code,
                                place_name = :place_name,
                                table_number = :table_number,
                                status = CASE
                                    WHEN :should_queue THEN 'pending'
                                    WHEN :should_mark_missing THEN 'missing_pdf'
                                    ELSE status
                                END,
                                last_error = CASE WHEN :should_queue THEN NULL ELSE last_error END,
                                updated_at = :updated_at
                            WHERE id = :id
                            """,
                            {
                                "id": row["id"],
                                "source_download_id": download["id"],
                                "relative_path": rel_path,
                                "absolute_path": str(pdf_path),
                                "file_size": stat.st_size if stat else None,
                                "file_mtime": stat.st_mtime if stat else None,
                                "file_sha1": sha1,
                                "department_code": str(download["department_id"]).zfill(2),
                                "department_name": download["department_name"],
                                "municipality_code": str(download["municipality_id"]).zfill(3),
                                "municipality_name": download["municipality_name"],
                                "zone_code": str(download["zone_id"]).zfill(2),
                                "place_code": str(download["polling_place_id"]).zfill(2),
                                "place_name": download["polling_place_name"],
                                "table_number": str(download["table_number"]).zfill(3),
                                "should_queue": 1 if should_queue else 0,
                                "should_mark_missing": 1 if should_mark_missing else 0,
                                "updated_at": stamp,
                            },
                        )
                else:
                    conn.execute(
                        """
                        INSERT INTO documents (
                            source_download_id, relative_path, absolute_path,
                            file_size, file_mtime, file_sha1,
                            department_code, department_name,
                            municipality_code, municipality_name,
                            zone_code, place_code, place_name, table_number,
                            status, discovered_at, updated_at
                        ) VALUES (
                            :source_download_id, :relative_path, :absolute_path,
                            :file_size, :file_mtime, :file_sha1,
                            :department_code, :department_name,
                            :municipality_code, :municipality_name,
                            :zone_code, :place_code, :place_name, :table_number,
                            :status, :updated_at, :updated_at
                        )
                        """,
                        {
                            "source_download_id": download["id"],
                            "relative_path": rel_path,
                            "absolute_path": str(pdf_path),
                            "file_size": stat.st_size if stat else None,
                            "file_mtime": stat.st_mtime if stat else None,
                            "file_sha1": sha1,
                            "department_code": str(download["department_id"]).zfill(2),
                            "department_name": download["department_name"],
                            "municipality_code": str(download["municipality_id"]).zfill(3),
                            "municipality_name": download["municipality_name"],
                            "zone_code": str(download["zone_id"]).zfill(2),
                            "place_code": str(download["polling_place_id"]).zfill(2),
                            "place_name": download["polling_place_name"],
                            "table_number": str(download["table_number"]).zfill(3),
                            "status": "pending" if is_downloaded else "missing_pdf",
                            "updated_at": stamp,
                        },
                    )
                count += 1
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            conn.close()
            raise

        conn.close()
        return count

    for pdf_path in root.rglob("*.pdf"):
        if not pdf_path.is_file():
            continue
        stat = pdf_path.stat()
        meta = path_metadata(root, pdf_path)
        sha1 = file_sha1(pdf_path) if hash_files else None
        row = conn.execute(
            "SELECT id, status, file_size, file_mtime, file_sha1 FROM documents WHERE relative_path = ?",
            (meta["relative_path"],),
        ).fetchone()

        should_reprocess = False
        if row:
            should_reprocess = (
                row["status"] == "missing_pdf"
                or row["file_size"] != stat.st_size
                or row["file_mtime"] != stat.st_mtime
                or (hash_files and row["file_sha1"] != sha1)
            )

        params = {
            **meta,
            "absolute_path": str(pdf_path),
            "file_size": stat.st_size,
            "file_mtime": stat.st_mtime,
            "file_sha1": sha1,
            "updated_at": stamp,
        }

        if row:
            conn.execute(
                """
                UPDATE documents
                SET absolute_path = :absolute_path,
                    file_size = :file_size,
                    file_mtime = :file_mtime,
                    file_sha1 = COALESCE(:file_sha1, file_sha1),
                    department_code = :department_code,
                    department_name = :department_name,
                    municipality_code = :municipality_code,
                    municipality_name = :municipality_name,
                    zone_code = :zone_code,
                    place_code = :place_code,
                    place_name = :place_name,
                    table_number = :table_number,
                    status = CASE WHEN :should_reprocess THEN 'pending' ELSE status END,
                    last_error = CASE WHEN :should_reprocess THEN NULL ELSE last_error END,
                    updated_at = :updated_at
                WHERE relative_path = :relative_path
                """,
                {**params, "should_reprocess": 1 if should_reprocess else 0},
            )
        else:
            conn.execute(
                """
                INSERT INTO documents (
                    relative_path, absolute_path, file_size, file_mtime, file_sha1,
                    department_code, department_name, municipality_code, municipality_name,
                    zone_code, place_code, place_name, table_number,
                    status, discovered_at, updated_at
                ) VALUES (
                    :relative_path, :absolute_path, :file_size, :file_mtime, :file_sha1,
                    :department_code, :department_name, :municipality_code, :municipality_name,
                    :zone_code, :place_code, :place_name, :table_number,
                    'pending', :updated_at, :updated_at
                )
                """,
                params,
            )
        count += 1

    conn.close()
    return count


def import_expected(manifest: Path, root: Path, db_path: Path) -> int:
    init_db(db_path)
    conn = connect_db(db_path)
    stamp = now_iso()
    count = 0

    with manifest.open("r", newline="", encoding="utf-8-sig") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        has_header = "relative_path" in sample.lower() or "path" in sample.lower()
        reader: Any
        if has_header:
            reader = csv.DictReader(fh)
            paths = [row.get("relative_path") or row.get("path") or row.get("file") for row in reader]
        else:
            reader = csv.reader(fh)
            paths = [row[0] for row in reader if row]

    for raw_path in paths:
        if not raw_path:
            continue
        rel_path = Path(str(raw_path).strip().strip('"'))
        abs_path = rel_path if rel_path.is_absolute() else root / rel_path
        exists = abs_path.exists()
        meta = path_metadata(root, abs_path)
        stat = abs_path.stat() if exists else None
        conn.execute(
            """
            INSERT INTO documents (
                relative_path, absolute_path, file_size, file_mtime,
                department_code, department_name, municipality_code, municipality_name,
                zone_code, place_code, place_name, table_number,
                status, discovered_at, updated_at
            ) VALUES (
                :relative_path, :absolute_path, :file_size, :file_mtime,
                :department_code, :department_name, :municipality_code, :municipality_name,
                :zone_code, :place_code, :place_name, :table_number,
                :status, :stamp, :stamp
            )
            ON CONFLICT(relative_path) DO UPDATE SET
                absolute_path = excluded.absolute_path,
                file_size = excluded.file_size,
                file_mtime = excluded.file_mtime,
                status = CASE
                    WHEN excluded.status = 'pending' AND documents.status = 'missing_pdf' THEN 'pending'
                    ELSE documents.status
                END,
                updated_at = excluded.updated_at
            """,
            {
                **meta,
                "absolute_path": str(abs_path),
                "file_size": stat.st_size if stat else None,
                "file_mtime": stat.st_mtime if stat else None,
                "status": "pending" if exists else "missing_pdf",
                "stamp": stamp,
            },
        )
        count += 1

    conn.close()
    return count


def reset_stale_jobs(db_path: Path, stale_minutes: int) -> int:
    init_db(db_path)
    conn = connect_db(db_path)
    cutoff = time.time() - stale_minutes * 60
    rows = conn.execute(
        "SELECT id, lock_started_at FROM documents WHERE status = 'processing'"
    ).fetchall()
    reset_ids: list[int] = []
    for row in rows:
        try:
            locked_at = datetime.fromisoformat(row["lock_started_at"]).timestamp()
        except Exception:
            locked_at = 0
        if locked_at < cutoff:
            reset_ids.append(row["id"])
    if reset_ids:
        conn.executemany(
            """
            UPDATE documents
            SET status = 'pending', last_error = 'Reset stale processing job', updated_at = ?
            WHERE id = ?
            """,
            [(now_iso(), row_id) for row_id in reset_ids],
        )
    conn.close()
    return len(reset_ids)


def department_filter_sql(
    department_code: str | None = None,
    department_name: str | None = None,
) -> tuple[str, list[str]]:
    clauses: list[str] = []
    params: list[str] = []
    normalized_code = norm_department_code(department_code)
    if normalized_code:
        clauses.append("department_code = ?")
        params.append(normalized_code)
    if department_name:
        normalized_name = norm_name(department_name)
        if normalized_name:
            clauses.append("UPPER(REPLACE(department_name, '_', ' ')) = ?")
            params.append(normalized_name)
    if not clauses:
        return "", []
    return " AND " + " AND ".join(clauses), params


def claim_next_job(
    db_path: Path,
    worker_id: str,
    department_code: str | None = None,
    department_name: str | None = None,
) -> sqlite3.Row | None:
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        department_where, department_params = department_filter_sql(department_code, department_name)
        row = conn.execute(
            f"""
            SELECT *
            FROM documents
            WHERE status = 'pending'
            {department_where}
            ORDER BY id
            LIMIT 1
            """,
            department_params,
        ).fetchone()
        if not row:
            conn.execute("COMMIT")
            return None
        stamp = now_iso()
        conn.execute(
            """
            UPDATE documents
            SET status = 'processing',
                attempts = attempts + 1,
                last_worker = ?,
                lock_started_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (worker_id, stamp, stamp, row["id"]),
        )
        conn.execute("COMMIT")
        return row
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def require_runtime(tesseract_cmd: str, engine: str = "tesseract", digit_model_path: Path | None = None) -> None:
    missing: list[str] = []
    for module in ("fitz", "cv2", "PIL", "numpy"):
        try:
            __import__(module)
        except Exception:
            missing.append(module)
    if missing:
        raise DependencyError("Faltan modulos Python: " + ", ".join(missing))

    if engine == "digit-model":
        try:
            __import__("torch")
        except Exception as exc:
            raise DependencyError("Falta PyTorch para usar --engine digit-model.") from exc
        if digit_model_path is None or not digit_model_path.exists():
            raise DependencyError(f"No encuentro el modelo de digitos: {digit_model_path}")
        return

    if not shutil.which(tesseract_cmd):
        raise DependencyError(
            f"No encuentro Tesseract OCR en PATH usando '{tesseract_cmd}'."
        )


def render_page(pdf_path: Path, page_index: int, dpi: int):
    try:
        import fitz
        import numpy as np
    except Exception as exc:
        raise DependencyError("PyMuPDF/numpy no estan disponibles.") from exc

    doc = fitz.open(str(pdf_path))
    if page_index >= doc.page_count:
        doc.close()
        return None, 0
    page = doc.load_page(page_index)
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    page_count = doc.page_count
    doc.close()
    return image, page_count


def rotate_image(image, angle: float):
    import cv2

    height, width = image.shape[:2]
    center = (width // 2, height // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    new_width = int((height * sin) + (width * cos))
    new_height = int((height * cos) + (width * sin))
    matrix[0, 2] += (new_width / 2) - center[0]
    matrix[1, 2] += (new_height / 2) - center[1]
    return cv2.warpAffine(image, matrix, (new_width, new_height), borderValue=(255, 255, 255))


def normalize_page(image):
    import cv2
    import numpy as np

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if len(image.shape) == 3 else image
    mask = gray < 248
    coords = np.argwhere(mask)
    if coords.size:
        y0, x0 = coords.min(axis=0)
        y1, x1 = coords.max(axis=0) + 1
        pad = max(8, int(min(image.shape[:2]) * 0.01))
        y0 = max(0, y0 - pad)
        x0 = max(0, x0 - pad)
        y1 = min(image.shape[0], y1 + pad)
        x1 = min(image.shape[1], x1 + pad)
        image = image[y0:y1, x0:x1]
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if len(image.shape) == 3 else image

    edges = cv2.Canny(gray, 60, 180)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=150,
        minLineLength=max(80, int(image.shape[1] * 0.35)),
        maxLineGap=20,
    )
    angles: list[float] = []
    if lines is not None:
        for line in lines[:200]:
            x1, y1, x2, y2 = line[0]
            angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
            if -5 <= angle <= 5:
                angles.append(angle)
    if angles:
        median_angle = sorted(angles)[len(angles) // 2]
        if abs(median_angle) > 0.15:
            image = rotate_image(image, median_angle)

    return image


def crop_relative(image, box: list[float], pad: int = 2):
    height, width = image.shape[:2]
    x0 = max(0, int(width * box[0]) - pad)
    y0 = max(0, int(height * box[1]) - pad)
    x1 = min(width, int(width * box[2]) + pad)
    y1 = min(height, int(height * box[3]) + pad)
    return image[y0:y1, x0:x1], [x0, y0, x1, y1]


def prepare_for_ocr(image, field_type: str):
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if len(image.shape) == 3 else image
    scale = 3 if field_type == "number" else 2
    gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh


def parse_tesseract_tsv(tsv: str) -> tuple[str, float | None]:
    lines = [line for line in tsv.splitlines() if line.strip()]
    if len(lines) <= 1:
        return "", None
    header = lines[0].split("\t")
    try:
        text_idx = header.index("text")
        conf_idx = header.index("conf")
    except ValueError:
        return "", None
    texts: list[str] = []
    confs: list[float] = []
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) <= max(text_idx, conf_idx):
            continue
        text = cols[text_idx].strip()
        if text:
            texts.append(text)
        try:
            conf = float(cols[conf_idx])
        except ValueError:
            continue
        if conf >= 0 and text:
            confs.append(conf)
    avg_conf = sum(confs) / len(confs) if confs else None
    return " ".join(texts).strip(), avg_conf


def crop_has_dark_ink(image, cell_count: int = 3, threshold: int = 180, min_pixels: int = 20) -> bool:
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if len(image.shape) == 3 else image
    height, width = gray.shape[:2]
    dark_pixels = 0
    for index in range(cell_count):
        x0 = round(width * index / cell_count)
        x1 = round(width * (index + 1) / cell_count)
        cell = gray[:, x0:x1]
        cell_height, cell_width = cell.shape[:2]
        y0 = int(cell_height * 0.14)
        y1 = max(y0 + 1, int(cell_height * 0.86))
        cx0 = int(cell_width * 0.14)
        cx1 = max(cx0 + 1, int(cell_width * 0.86))
        inner = cell[y0:y1, cx0:cx1]
        dark_pixels += int((inner < threshold).sum())
        if dark_pixels >= min_pixels:
            return True
    return False


def cell_dark_pixel_count(image, cell_index: int, cell_count: int = 3, threshold: int = 180) -> int:
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if len(image.shape) == 3 else image
    height, width = gray.shape[:2]
    x0 = round(width * cell_index / cell_count)
    x1 = round(width * (cell_index + 1) / cell_count)
    cell = gray[:, x0:x1]
    cell_height, cell_width = cell.shape[:2]
    y0 = int(cell_height * 0.14)
    y1 = max(y0 + 1, int(cell_height * 0.86))
    cx0 = int(cell_width * 0.14)
    cx1 = max(cx0 + 1, int(cell_width * 0.86))
    inner = cell[y0:y1, cx0:cx1]
    return int((inner < threshold).sum())


def get_digit_model(model_path: Path, device: str):
    if device == "auto":
        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"

    key = (str(model_path.resolve()), device)
    cached = _DIGIT_MODEL_CACHE.get(key)
    if cached is not None:
        return cached

    import train_e14_digit_model as digit_model

    deps = digit_model.load_dependencies()
    _, _, torch, *_rest, ModelClass = deps
    checkpoint = torch.load(str(model_path), map_location=device, weights_only=False)
    model = ModelClass().to(device)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    cached = (digit_model, deps, model, device)
    _DIGIT_MODEL_CACHE[key] = cached
    return cached


def ocr_digit_model_image(image, model_path: Path, device: str) -> tuple[str, float | None]:
    digits, confidence, _ = ocr_digit_model_candidates_image(image, model_path, device)
    return digits, confidence


def ocr_digit_model_candidates_image(
    image,
    model_path: Path,
    device: str,
) -> tuple[str, float | None, list[dict[str, Any]]]:
    import cv2

    if not crop_has_dark_ink(image):
        return "", 0.0, []

    digit_model, deps, model, resolved_device = get_digit_model(model_path, device)
    _, np, torch, *_ = deps
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if len(image.shape) == 3 else image
    if hasattr(digit_model, "predict_field_candidates"):
        candidates = digit_model.predict_field_candidates(gray, model, cv2, np, torch, resolved_device)
        if candidates:
            best = candidates[0]
            return str(best["digits"]), float(best["confidence"]), candidates
    digits, confidence = digit_model.predict_field(gray, model, cv2, np, torch, resolved_device)
    return digits, confidence, [{"digits": digits, "value": to_int(digits), "confidence": confidence}]


def ocr_image(
    image,
    field: dict[str, Any],
    defaults: dict[str, Any],
    tesseract_cmd: str,
    engine: str = "tesseract",
    digit_model_path: Path | None = None,
    model_device: str = "cpu",
) -> tuple[str, float | None]:
    if engine == "digit-model" and field.get("type") == "number":
        if digit_model_path is None:
            raise DependencyError("Falta --digit-model para usar --engine digit-model.")
        return ocr_digit_model_image(image, digit_model_path, model_device)

    if field.get("type") == "number" and field.get("digit_cells", defaults.get("digit_cells", 3)):
        return ocr_number_image(image, field, defaults, tesseract_cmd)

    return ocr_tesseract_image(image, field, defaults, tesseract_cmd)


def field_row_for_key(field_rows: list[dict[str, Any]], field_key: str) -> dict[str, Any] | None:
    for row in field_rows:
        if row.get("field_key") == field_key:
            return row
    return None


def apply_consistency_corrections(
    fields: list[dict[str, Any]],
    values: dict[str, int | None],
    confidences: dict[str, float | None],
    field_rows: list[dict[str, Any]],
    field_features: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    role_by_key = {field.get("key"): field.get("role") for field in fields}
    candidate_keys = [key for key, role in role_by_key.items() if role == "candidate_vote"]
    additive_keys = candidate_keys + ["votos_blanco", "votos_nulos", "votos_no_marcados"]
    declared_total = values.get("suma_total")

    if declared_total is None or any(values.get(key) is None for key in additive_keys):
        return []

    computed_total = sum(int(values[key] or 0) for key in additive_keys)
    diff = declared_total - computed_total
    if diff <= 0 or diff % 100 != 0 or diff > 500:
        return []

    candidate_alternatives: list[dict[str, Any]] = []
    for key in candidate_keys:
        current_value = values.get(key)
        if current_value is None:
            continue
        for candidate in field_features.get(key, {}).get("candidates", [])[:20]:
            candidate_value = candidate.get("value")
            if candidate_value is None or int(candidate_value) == int(current_value):
                continue
            corrected_total = computed_total - int(current_value) + int(candidate_value)
            if corrected_total == declared_total:
                candidate_alternatives.append(
                    {
                        "field": key,
                        "old_value": int(current_value),
                        "new_value": int(candidate_value),
                        "raw_text": field_row_for_key(field_rows, key).get("raw_text")
                        if field_row_for_key(field_rows, key)
                        else None,
                        "candidate_digits": candidate.get("digits"),
                        "candidate_confidence": candidate.get("confidence"),
                        "computed_before": computed_total,
                        "computed_after": corrected_total,
                    }
                )

    if len(candidate_alternatives) == 1:
        alternative = candidate_alternatives[0]
        key = alternative["field"]
        new_value = int(alternative["new_value"])
        values[key] = new_value
        row = field_row_for_key(field_rows, key)
        if row is not None:
            row["normalized_value"] = new_value
        return [
            {
                "severity": "warning",
                "code": "CONSISTENCY_SELECTED_MODEL_ALTERNATIVE",
                "message": "Se escogio una lectura alternativa del modelo porque cuadra exactamente con la suma total del acta.",
                "details": {
                    "field": key,
                    "old_value": alternative["old_value"],
                    "new_value": new_value,
                    "raw_text": alternative["raw_text"],
                    "candidate_digits": alternative["candidate_digits"],
                    "declared_total": declared_total,
                    "computed_before": alternative["computed_before"],
                    "computed_after": alternative["computed_after"],
                    "candidate_confidence": alternative["candidate_confidence"],
                },
            }
        ]

    leading_digit = diff // 100
    suspects: list[dict[str, Any]] = []
    for key in candidate_keys:
        value = values.get(key)
        row = field_row_for_key(field_rows, key)
        if value is None or row is None or value >= 100:
            continue
        raw_digits = re.sub(r"\D+", "", str(row.get("raw_text") or "")).zfill(3)
        if len(raw_digits) != 3 or raw_digits[0] != "0":
            continue
        leading_dark_pixels = int(field_features.get(key, {}).get("leading_dark_pixels") or 0)
        if leading_dark_pixels < 900:
            continue
        suspects.append(
            {
                "field": key,
                "old_value": value,
                "new_value": value + diff,
                "raw_text": row.get("raw_text"),
                "confidence": confidences.get(key),
                "leading_dark_pixels": leading_dark_pixels,
            }
        )

    if len(suspects) != 1:
        return []

    suspect = suspects[0]
    key = suspect["field"]
    new_value = int(suspect["new_value"])
    if new_value >= 1000 or new_value // 100 != leading_digit:
        return []

    values[key] = new_value
    row = field_row_for_key(field_rows, key)
    if row is not None:
        row["normalized_value"] = new_value

    return [
        {
            "severity": "warning",
            "code": "CONSISTENCY_CORRECTED_LEADING_DIGIT",
            "message": "Se corrigio un posible digito inicial omitido usando la suma total del acta.",
            "details": {
                "field": key,
                "old_value": suspect["old_value"],
                "new_value": new_value,
                "raw_text": suspect["raw_text"],
                "declared_total": declared_total,
                "computed_before": computed_total,
                "computed_after": computed_total + diff,
                "leading_dark_pixels": suspect["leading_dark_pixels"],
                "confidence": suspect["confidence"],
            },
        }
    ]


def detect_signature_crop(crop, min_dark_density: float, min_components: int) -> dict[str, Any]:
    import cv2

    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY) if len(crop.shape) == 3 else crop
    dark = (gray < 185).astype("uint8")
    dark_pixels = int(dark.sum())
    area = int(gray.shape[0] * gray.shape[1])
    density = dark_pixels / max(1, area)

    component_count = 0
    if dark_pixels:
        labels_count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(dark, 8)
        component_count = sum(
            1
            for index in range(1, labels_count)
            if int(stats[index, cv2.CC_STAT_AREA]) >= 8
        )

    signed = density >= min_dark_density and component_count >= min_components
    confidence = min(100.0, density / max(min_dark_density, 0.0001) * 70.0)
    if signed:
        confidence = max(confidence, min(100.0, component_count / max(min_components, 1) * 50.0))

    return {
        "signed": signed,
        "dark_pixels": dark_pixels,
        "dark_density": density,
        "component_count": component_count,
        "confidence": confidence,
    }


def analyze_signatures(
    normalized_cache: dict[int, Any],
    signature_config: dict[str, Any],
    doc: sqlite3.Row,
    report_dir: Path,
    save_debug: bool,
) -> tuple[list[dict[str, Any]], int | None, list[dict[str, Any]], dict[str, Any]]:
    if not signature_config:
        return [], None, [], {}

    page_index = int(signature_config.get("page", 1))
    image = normalized_cache.get(page_index)
    min_signed = int(signature_config.get("min_signed", 2))
    min_dark_density = float(signature_config.get("min_dark_density", 0.018))
    min_components = int(signature_config.get("min_components", 2))

    if image is None:
        return (
            [],
            0,
            [
                {
                    "severity": "error",
                    "code": "MISSING_SIGNATURE_PAGE",
                    "message": "No existe la pagina requerida para validar firmas de jurados.",
                    "details": {"page": page_index + 1, "min_signed": min_signed},
                },
                {
                    "severity": "error",
                    "code": "LOW_SIGNATURE_COUNT",
                    "message": "Menos de 2 jurados firmaron el formulario.",
                    "details": {"signed_juror_count": 0, "min_signed": min_signed, "signed_jurors": []},
                },
            ],
            {"signed_jurors": [], "signature_scores": {}},
        )

    rows: list[dict[str, Any]] = []
    signed_jurors: list[str] = []
    scores: dict[str, Any] = {}

    for index, box_config in enumerate(signature_config.get("boxes", []), start=1):
        key = box_config.get("key") or f"firma_jurado_{index}"
        label = box_config.get("label") or f"Firma jurado {index}"
        crop, bbox = crop_relative(image, box_config["box"], pad=0)
        score = detect_signature_crop(crop, min_dark_density, min_components)
        scores[key] = score
        if score["signed"]:
            signed_jurors.append(key)

        crop_path: str | None = None
        if save_debug:
            debug_crop_path = report_dir / "debug" / "signatures" / safe_debug_name(
                doc["relative_path"], page_index, key
            )
            save_debug_image(crop, debug_crop_path)
            crop_path = str(debug_crop_path)

        rows.append(
            {
                "page_index": page_index,
                "field_key": key,
                "field_label": label,
                "field_role": "juror_signature",
                "field_type": "signature",
                "raw_text": "signed" if score["signed"] else "blank",
                "normalized_value": 1 if score["signed"] else 0,
                "confidence": score["confidence"],
                "bbox_json": json.dumps(bbox),
                "crop_path": crop_path,
            }
        )

    signed_count = len(signed_jurors)
    inconsistencies: list[dict[str, Any]] = []
    if signed_count < min_signed:
        inconsistencies.append(
            {
                "severity": "error",
                "code": "LOW_SIGNATURE_COUNT",
                "message": "Menos de 2 jurados firmaron el formulario.",
                "details": {
                    "signed_juror_count": signed_count,
                    "min_signed": min_signed,
                    "signed_jurors": signed_jurors,
                    "signature_scores": scores,
                },
            }
        )

    return rows, signed_count, inconsistencies, {"signed_jurors": signed_jurors, "signature_scores": scores}


def ocr_tesseract_image(image, field: dict[str, Any], defaults: dict[str, Any], tesseract_cmd: str) -> tuple[str, float | None]:
    from PIL import Image

    field_type = field.get("type", "text")
    psm = str(field.get("psm", defaults.get("psm", 7)))
    lang = field.get("lang", defaults.get("lang", "eng"))
    processed = prepare_for_ocr(image, field_type)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        Image.fromarray(processed).save(tmp_path)
        cmd = [
            tesseract_cmd,
            str(tmp_path),
            "stdout",
            "--psm",
            psm,
            "-l",
            lang,
        ]
        if field_type == "number":
            whitelist = field.get("number_whitelist", defaults.get("number_whitelist", "0123456789*Xx"))
            cmd.extend(["-c", f"tessedit_char_whitelist={whitelist}"])
        cmd.append("tsv")
        run = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if run.returncode != 0:
            raise DependencyError(run.stderr.strip() or "Tesseract fallo sin mensaje.")
        return parse_tesseract_tsv(run.stdout)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def digit_shape_guess(cell_image) -> str | None:
    import cv2
    import numpy as np

    gray = cv2.cvtColor(cell_image, cv2.COLOR_RGB2GRAY) if len(cell_image.shape) == 3 else cell_image
    height, width = gray.shape[:2]
    if height < 8 or width < 8:
        return None

    y0 = int(height * 0.13)
    y1 = int(height * 0.87)
    x0 = int(width * 0.10)
    x1 = int(width * 0.90)
    gray = gray[y0:y1, x0:x1]
    dark = (gray < 160).astype("uint8")
    if int(dark.sum()) < 20:
        return None

    ys, xs = np.where(dark)
    left, right = int(xs.min()), int(xs.max()) + 1
    top, bottom = int(ys.min()), int(ys.max()) + 1
    roi = dark[top:bottom, left:right]
    box_width = right - left
    box_height = bottom - top
    if box_width <= 0 or box_height <= 0:
        return None

    fill = float(roi.sum()) / float(box_width * box_height)
    aspect = float(box_width) / float(box_height)
    contours, _ = cv2.findContours((roi * 255).astype("uint8"), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area = sum(cv2.contourArea(contour) for contour in contours)
    perimeter = sum(cv2.arcLength(contour, True) for contour in contours)
    circularity = (4.0 * math.pi * area / (perimeter * perimeter)) if perimeter else 0.0

    if fill > 0.55 and circularity > 0.55 and 0.70 < aspect < 1.35:
        return "0"
    if aspect < 0.65 and fill < 0.50 and box_height > box_width * 1.35:
        return "1"
    if 0.85 <= aspect <= 1.25 and 0.18 <= fill <= 0.30 and circularity < 0.18:
        return "7"
    if 0.62 <= aspect <= 0.88 and 0.22 <= fill <= 0.38 and 0.20 <= circularity <= 0.45:
        return "9"

    return None


def ocr_digit_cell(cell_image, field: dict[str, Any], defaults: dict[str, Any], tesseract_cmd: str) -> str | None:
    shape_digit = digit_shape_guess(cell_image)
    if shape_digit is not None:
        return shape_digit

    cell_field = dict(field)
    cell_field["type"] = "number"
    cell_field["psm"] = 10
    raw_text, _ = ocr_tesseract_image(cell_image, cell_field, defaults, tesseract_cmd)
    digits = re.sub(r"\D+", "", raw_text or "")
    if digits:
        return digits[-1]
    return None


def ocr_number_image(image, field: dict[str, Any], defaults: dict[str, Any], tesseract_cmd: str) -> tuple[str, float | None]:
    whole_text, whole_confidence = ocr_tesseract_image(image, field, defaults, tesseract_cmd)
    cell_count = int(field.get("digit_cells", defaults.get("digit_cells", 3)))
    if cell_count <= 1:
        return whole_text, whole_confidence

    height, width = image.shape[:2]
    cell_digits: list[str | None] = []
    for index in range(cell_count):
        x0 = round(width * index / cell_count)
        x1 = round(width * (index + 1) / cell_count)
        cell = image[:, x0:x1]
        cell_digits.append(ocr_digit_cell(cell, field, defaults, tesseract_cmd))

    if all(digit is not None for digit in cell_digits):
        return "".join(digit or "" for digit in cell_digits), whole_confidence

    known_digits = [digit for digit in cell_digits if digit is not None]
    whole_digits = re.sub(r"\D+", "", whole_text or "")
    if len(known_digits) >= 2:
        return "".join(digit if digit is not None else "" for digit in cell_digits), whole_confidence
    if whole_digits:
        if len(whole_digits) <= cell_count:
            return whole_digits, whole_confidence
        if cell_digits and cell_digits[0] == "0" and cell_count == 3:
            return "0" + whole_digits[-2:], whole_confidence
        return whole_digits[-cell_count:], whole_confidence

    return "".join(digit if digit is not None else "" for digit in cell_digits), whole_confidence


def safe_debug_name(relative_path: str, page_index: int, field_key: str | None = None) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", relative_path)
    if field_key:
        return f"{base}__p{page_index + 1}__{field_key}.png"
    return f"{base}__p{page_index + 1}__page.png"


def save_debug_image(image, path: Path) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(path)


def analyze_pdf(
    doc: sqlite3.Row,
    config: dict[str, Any],
    report_dir: Path,
    dpi: int,
    tesseract_cmd: str,
    save_debug: bool,
    engine: str = "tesseract",
    digit_model_path: Path | None = None,
    model_device: str = "cpu",
) -> dict[str, Any]:
    pdf_path = Path(doc["absolute_path"])
    if not pdf_path.exists():
        return {
            "missing": True,
            "fields": [],
            "inconsistencies": [
                {
                    "severity": "warning",
                    "code": "MISSING_PDF",
                    "message": "El PDF no existe todavia; queda para una corrida futura.",
                    "details": {"path": str(pdf_path)},
                }
            ],
        }

    defaults = config.get("defaults", {})
    fields = config.get("fields", [])
    signature_config = config.get("signature_detection", {})
    page_indexes_set = {int(field.get("page", 0)) for field in fields}
    if signature_config:
        page_indexes_set.add(int(signature_config.get("page", 1)))
    page_indexes = sorted(page_indexes_set)
    page_cache: dict[int, Any] = {}
    normalized_cache: dict[int, Any] = {}
    page_count = 0

    for page_index in page_indexes:
        image, count = render_page(pdf_path, page_index, dpi)
        page_count = max(page_count, count)
        if image is None:
            continue
        normalized = normalize_page(image)
        page_cache[page_index] = image
        normalized_cache[page_index] = normalized
        if save_debug:
            debug_path = report_dir / "debug" / "pages" / safe_debug_name(doc["relative_path"], page_index)
            save_debug_image(normalized, debug_path)

    field_rows: list[dict[str, Any]] = []
    values: dict[str, int | None] = {}
    confidences: dict[str, float | None] = {}
    field_features: dict[str, dict[str, Any]] = {}
    inconsistencies: list[dict[str, Any]] = []

    for field in fields:
        page_index = int(field.get("page", 0))
        image = normalized_cache.get(page_index)
        if image is None:
            if field.get("required", False):
                inconsistencies.append(
                    {
                        "severity": "error",
                        "code": "MISSING_PAGE",
                        "message": f"No existe la pagina requerida para {field['key']}.",
                        "details": {"page": page_index + 1, "field": field["key"]},
                    }
                )
            continue

        crop, bbox = crop_relative(image, field["box"])
        if field.get("type") == "number":
            field_features[field["key"]] = {
                "leading_dark_pixels": cell_dark_pixel_count(crop, 0),
            }
        if engine == "digit-model" and field.get("type") == "number":
            if digit_model_path is None:
                raise DependencyError("Falta --digit-model para usar --engine digit-model.")
            raw_text, confidence, candidates = ocr_digit_model_candidates_image(
                crop,
                digit_model_path,
                model_device,
            )
            field_features.setdefault(field["key"], {})["candidates"] = candidates
        else:
            raw_text, confidence = ocr_image(
                crop,
                field,
                defaults,
                tesseract_cmd,
                engine,
                digit_model_path,
                model_device,
            )
        normalized_value = to_int(raw_text) if field.get("type") == "number" else None
        values[field["key"]] = normalized_value
        confidences[field["key"]] = confidence

        crop_path: str | None = None
        if save_debug:
            debug_crop_path = report_dir / "debug" / "crops" / safe_debug_name(
                doc["relative_path"], page_index, field["key"]
            )
            save_debug_image(crop, debug_crop_path)
            crop_path = str(debug_crop_path)

        field_rows.append(
            {
                "page_index": page_index,
                "field_key": field["key"],
                "field_label": field.get("label"),
                "field_role": field.get("role"),
                "field_type": field.get("type"),
                "raw_text": raw_text,
                "normalized_value": normalized_value,
                "confidence": confidence,
                "bbox_json": json.dumps(bbox),
                "crop_path": crop_path,
            }
        )

        min_conf = float(field.get("min_confidence", defaults.get("min_confidence", 55)))
        if field.get("required", False) and normalized_value is None:
            inconsistencies.append(
                {
                    "severity": "error",
                    "code": "MISSING_FIELD",
                    "message": f"No se pudo leer el campo {field.get('label', field['key'])}.",
                    "details": {"field": field["key"], "raw_text": raw_text},
                }
            )
        if confidence is not None and confidence < min_conf:
            inconsistencies.append(
                {
                    "severity": "warning",
                    "code": "LOW_CONFIDENCE",
                    "message": f"Baja confianza OCR en {field.get('label', field['key'])}: {confidence:.1f}.",
                    "details": {"field": field["key"], "confidence": confidence, "raw_text": raw_text},
                }
            )

    inconsistencies.extend(
        apply_consistency_corrections(fields, values, confidences, field_rows, field_features)
    )

    max_reasonable_votes = defaults.get("max_reasonable_votes")
    if max_reasonable_votes is not None:
        max_reasonable_votes = int(max_reasonable_votes)
        for field in fields:
            if field.get("type") != "number":
                continue
            key = field.get("key")
            value = values.get(key)
            if value is not None and int(value) > max_reasonable_votes:
                inconsistencies.append(
                    {
                        "severity": "warning",
                        "code": "HIGH_VOTE_VALUE",
                        "message": f"Valor numerico inusualmente alto en {field.get('label', key)}: {value}.",
                        "details": {
                            "field": key,
                            "field_label": field.get("label"),
                            "value": int(value),
                            "threshold": max_reasonable_votes,
                            "raw_text": field_row_for_key(field_rows, str(key)).get("raw_text")
                            if field_row_for_key(field_rows, str(key))
                            else None,
                            "confidence": confidences.get(key),
                        },
                    }
                )

    signature_rows, signed_juror_count, signature_inconsistencies, signature_details = analyze_signatures(
        normalized_cache,
        signature_config,
        doc,
        report_dir,
        save_debug,
    )
    field_rows.extend(signature_rows)
    if signed_juror_count is not None:
        values["jurados_firmantes"] = signed_juror_count
        confidences["jurados_firmantes"] = None
    inconsistencies.extend(signature_inconsistencies)

    role_values: dict[str, list[int]] = {}
    for field in fields:
        role = field.get("role")
        key = field.get("key")
        value = values.get(key)
        if role and value is not None:
            role_values.setdefault(role, []).append(value)

    candidate_total = sum(role_values.get("candidate_vote", []))
    blank_votes = values.get("votos_blanco")
    null_votes = values.get("votos_nulos")
    unmarked_votes = values.get("votos_no_marcados")
    declared_total = values.get("suma_total")
    urna_total = values.get("total_votos_urna")
    e11_total = values.get("total_votantes_e11")
    incinerated_total = values.get("total_votos_incinerados")

    additive_parts = [candidate_total, blank_votes, null_votes, unmarked_votes]
    if all(value is not None for value in additive_parts) and declared_total is not None:
        computed_total = sum(int(value) for value in additive_parts if value is not None)
        if computed_total != declared_total:
            inconsistencies.append(
                {
                    "severity": "error",
                    "code": "SUM_MISMATCH",
                    "message": "La suma de candidatos + blancos + nulos + no marcados no coincide con la suma total.",
                    "details": {"computed_total": computed_total, "declared_total": declared_total},
                }
            )

    if urna_total is not None and declared_total is not None and urna_total != declared_total:
        inconsistencies.append(
            {
                "severity": "error",
                "code": "URNA_TOTAL_MISMATCH",
                "message": "Total votos en la urna no coincide con la suma total.",
                "details": {"urna_total": urna_total, "declared_total": declared_total},
            }
        )

    if e11_total is not None and urna_total is not None and urna_total > e11_total:
        inconsistencies.append(
            {
                "severity": "error",
                "code": "URNA_GT_E11",
                "message": "Total votos en urna supera total votantes E-11.",
                "details": {"urna_total": urna_total, "e11_total": e11_total},
            }
        )

    if incinerated_total not in (None, 0):
        inconsistencies.append(
            {
                "severity": "warning",
                "code": "INCINERATED_NON_ZERO",
                "message": "Hay votos incinerados diferentes de cero.",
                "details": {"incinerated_total": incinerated_total},
            }
        )

    return {
        "missing": False,
        "page_count": page_count,
        "fields": field_rows,
        "values": values,
        "confidences": confidences,
        "inconsistencies": inconsistencies,
        "summary": {
            "candidate_total": candidate_total,
            "blank_votes": blank_votes,
            "null_votes": null_votes,
            "unmarked_votes": unmarked_votes,
            "declared_total": declared_total,
            "urna_total": urna_total,
            "e11_total": e11_total,
            "incinerated_total": incinerated_total,
            "signed_juror_count": signed_juror_count,
            "signature_details": signature_details,
        },
    }


def save_analysis(
    db_path: Path,
    document_id: int,
    result: dict[str, Any],
    max_attempts: int,
) -> str:
    conn = connect_db(db_path)
    stamp = now_iso()
    status = "missing_pdf" if result.get("missing") else "done"
    inconsistencies = result.get("inconsistencies", [])
    has_errors = any(item.get("severity") == "error" for item in inconsistencies)
    if not result.get("missing") and has_errors:
        status = "inconsistent"

    try:
        with conn:
            conn.execute("DELETE FROM field_results WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM inconsistencies WHERE document_id = ?", (document_id,))

            for field in result.get("fields", []):
                conn.execute(
                    """
                    INSERT INTO field_results (
                        document_id, page_index, field_key, field_label, field_role,
                        field_type, raw_text, normalized_value, confidence, bbox_json,
                        crop_path, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        field["page_index"],
                        field["field_key"],
                        field.get("field_label"),
                        field.get("field_role"),
                        field.get("field_type"),
                        field.get("raw_text"),
                        field.get("normalized_value"),
                        field.get("confidence"),
                        field.get("bbox_json"),
                        field.get("crop_path"),
                        stamp,
                    ),
                )

            for item in inconsistencies:
                conn.execute(
                    """
                    INSERT INTO inconsistencies (
                        document_id, severity, code, message, details_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        item["severity"],
                        item["code"],
                        item["message"],
                        json.dumps(item.get("details", {}), ensure_ascii=True),
                        stamp,
                    ),
                )

            summary = result.get("summary", {})
            conn.execute(
                """
                INSERT INTO document_results (
                    document_id, page_count, extracted_json, confidence_json,
                    inconsistencies_json, candidate_total, blank_votes, null_votes,
                    unmarked_votes, declared_total, urna_total, e11_total,
                    incinerated_total, signed_juror_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    page_count = excluded.page_count,
                    extracted_json = excluded.extracted_json,
                    confidence_json = excluded.confidence_json,
                    inconsistencies_json = excluded.inconsistencies_json,
                    candidate_total = excluded.candidate_total,
                    blank_votes = excluded.blank_votes,
                    null_votes = excluded.null_votes,
                    unmarked_votes = excluded.unmarked_votes,
                    declared_total = excluded.declared_total,
                    urna_total = excluded.urna_total,
                    e11_total = excluded.e11_total,
                    incinerated_total = excluded.incinerated_total,
                    signed_juror_count = excluded.signed_juror_count,
                    updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    result.get("page_count"),
                    json.dumps(result.get("values", {}), ensure_ascii=True),
                    json.dumps(result.get("confidences", {}), ensure_ascii=True),
                    json.dumps(inconsistencies, ensure_ascii=True),
                    summary.get("candidate_total"),
                    summary.get("blank_votes"),
                    summary.get("null_votes"),
                    summary.get("unmarked_votes"),
                    summary.get("declared_total"),
                    summary.get("urna_total"),
                    summary.get("e11_total"),
                    summary.get("incinerated_total"),
                    summary.get("signed_juror_count"),
                    stamp,
                    stamp,
                ),
            )

            conn.execute(
                """
                UPDATE documents
                SET status = ?, last_error = NULL, lock_started_at = NULL,
                    updated_at = ?, analyzed_at = ?
                WHERE id = ?
                """,
                (status, stamp, stamp, document_id),
            )
    finally:
        conn.close()
    return status


def mark_failed(db_path: Path, document_id: int, error: str, max_attempts: int) -> str:
    conn = connect_db(db_path)
    row = conn.execute("SELECT attempts FROM documents WHERE id = ?", (document_id,)).fetchone()
    attempts = int(row["attempts"]) if row else max_attempts
    status = "failed" if attempts >= max_attempts else "pending"
    conn.execute(
        """
        UPDATE documents
        SET status = ?, last_error = ?, lock_started_at = NULL, updated_at = ?
        WHERE id = ?
        """,
        (status, error[:2000], now_iso(), document_id),
    )
    conn.close()
    return status


@dataclass
class WorkerOptions:
    db_path: str
    config_path: str
    report_dir: str
    dpi: int
    tesseract_cmd: str
    save_debug: bool
    max_attempts: int
    worker_limit: int | None
    engine: str
    digit_model_path: str | None
    model_device: str
    live_report: bool
    department_code: str | None
    department_name: str | None


def worker_main(worker_number: int, options: WorkerOptions) -> dict[str, int]:
    worker_id = f"pid-{os.getpid()}-{worker_number}"
    db_path = Path(options.db_path)
    config = load_config(Path(options.config_path))
    report_dir = Path(options.report_dir)
    counts = {"processed": 0, "done": 0, "inconsistent": 0, "missing_pdf": 0, "failed": 0}

    try:
        require_runtime(
            options.tesseract_cmd,
            options.engine,
            Path(options.digit_model_path) if options.digit_model_path else None,
        )
    except Exception as exc:
        return {"processed": 0, "done": 0, "inconsistent": 0, "missing_pdf": 0, "failed": 1, "fatal": 1}

    while True:
        if options.worker_limit is not None and counts["processed"] >= options.worker_limit:
            break
        job = claim_next_job(
            db_path,
            worker_id,
            options.department_code,
            options.department_name,
        )
        if job is None:
            break
        try:
            result = analyze_pdf(
                job,
                config,
                report_dir,
                options.dpi,
                options.tesseract_cmd,
                options.save_debug,
                options.engine,
                Path(options.digit_model_path) if options.digit_model_path else None,
                options.model_device,
            )
            status = save_analysis(db_path, job["id"], result, options.max_attempts)
            if options.live_report:
                append_live_analysis(report_dir, job, result, status)
            counts["processed"] += 1
            counts[status] = counts.get(status, 0) + 1
        except Exception as exc:
            error = repr(exc)
            status = mark_failed(db_path, job["id"], error, options.max_attempts)
            if options.live_report:
                append_live_failure(report_dir, job, error, status)
            counts["processed"] += 1
            counts[status] = counts.get(status, 0) + 1

    return counts


def pending_count(
    db_path: Path,
    department_code: str | None = None,
    department_name: str | None = None,
) -> int:
    conn = connect_db(db_path)
    department_where, department_params = department_filter_sql(department_code, department_name)
    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM documents WHERE status = 'pending' {department_where}",
        department_params,
    ).fetchone()
    conn.close()
    return int(row["n"])


def status_counts(
    db_path: Path,
    department_code: str | None = None,
    department_name: str | None = None,
) -> dict[str, int]:
    conn = connect_db(db_path)
    department_where, department_params = department_filter_sql(department_code, department_name)
    rows = conn.execute(
        f"""
        SELECT status, COUNT(*) AS n
        FROM documents
        WHERE 1 = 1 {department_where}
        GROUP BY status
        """,
        department_params,
    ).fetchall()
    conn.close()
    return {row["status"]: int(row["n"]) for row in rows}


def requeue_documents(db_path: Path, statuses: list[str], limit: int | None, reset_attempts: bool) -> int:
    init_db(db_path)
    conn = connect_db(db_path)
    placeholders = ",".join("?" for _ in statuses)
    limit_clause = "" if limit is None else f"LIMIT {int(limit)}"
    rows = conn.execute(
        f"""
        SELECT id
        FROM documents
        WHERE status IN ({placeholders})
        ORDER BY id
        {limit_clause}
        """,
        tuple(statuses),
    ).fetchall()
    ids = [int(row["id"]) for row in rows]
    if not ids:
        conn.close()
        return 0

    stamp = now_iso()
    with conn:
        conn.executemany(
            """
            UPDATE documents
            SET status = 'pending',
                attempts = CASE WHEN ? THEN 0 ELSE attempts END,
                last_error = NULL,
                lock_started_at = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            [(1 if reset_attempts else 0, stamp, document_id) for document_id in ids],
        )
    conn.close()
    return len(ids)


def reset_analysis_state(db_path: Path, report_dir: Path, delete_report_csvs: bool) -> dict[str, int]:
    init_db(db_path)
    conn = connect_db(db_path)
    docs = conn.execute("SELECT id, absolute_path FROM documents").fetchall()

    pending_ids: list[int] = []
    missing_ids: list[int] = []
    for row in docs:
        path = Path(row["absolute_path"]) if row["absolute_path"] else None
        if path and path.exists():
            pending_ids.append(int(row["id"]))
        else:
            missing_ids.append(int(row["id"]))

    stamp = now_iso()
    with conn:
        conn.execute("DELETE FROM field_results")
        conn.execute("DELETE FROM document_results")
        conn.execute("DELETE FROM inconsistencies")
        if pending_ids:
            conn.executemany(
                """
                UPDATE documents
                SET status = 'pending', attempts = 0, last_error = NULL,
                    last_worker = NULL, lock_started_at = NULL,
                    updated_at = ?, analyzed_at = NULL
                WHERE id = ?
                """,
                [(stamp, document_id) for document_id in pending_ids],
            )
        if missing_ids:
            conn.executemany(
                """
                UPDATE documents
                SET status = 'missing_pdf', attempts = 0, last_error = NULL,
                    last_worker = NULL, lock_started_at = NULL,
                    updated_at = ?, analyzed_at = NULL
                WHERE id = ?
                """,
                [(stamp, document_id) for document_id in missing_ids],
            )
    conn.close()

    deleted_csvs = 0
    if delete_report_csvs:
        for folder in (report_dir, report_dir / "live"):
            if not folder.exists():
                continue
            for path in folder.glob("*.csv"):
                path.unlink()
                deleted_csvs += 1

    return {
        "pending": len(pending_ids),
        "missing_pdf": len(missing_ids),
        "deleted_csvs": deleted_csvs,
    }


def analyze_pending(
    db_path: Path,
    config_path: Path,
    report_dir: Path,
    workers: int,
    dpi: int,
    tesseract_cmd: str,
    save_debug: bool,
    max_attempts: int,
    limit: int | None,
    engine: str = "tesseract",
    digit_model_path: Path | None = None,
    model_device: str = "cpu",
    live_report: bool = True,
    department_code: str | None = None,
    department_name: str | None = None,
) -> dict[str, int]:
    init_db(db_path)
    total_pending = pending_count(db_path, department_code, department_name)
    if total_pending == 0:
        return {"processed": 0, "done": 0, "inconsistent": 0, "missing_pdf": 0, "failed": 0}

    if limit is not None:
        total_pending = min(total_pending, limit)
    workers = max(1, min(workers, total_pending))
    if limit is not None:
        base_limit, remainder = divmod(total_pending, workers)
        worker_limits = [
            base_limit + (1 if index < remainder else 0)
            for index in range(workers)
        ]
    else:
        worker_limits = [None for _ in range(workers)]

    aggregate = {"processed": 0, "done": 0, "inconsistent": 0, "missing_pdf": 0, "failed": 0}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = []
        for index, worker_limit in enumerate(worker_limits):
            options = WorkerOptions(
                db_path=str(db_path),
                config_path=str(config_path),
                report_dir=str(report_dir),
                dpi=dpi,
                tesseract_cmd=tesseract_cmd,
                save_debug=save_debug,
                max_attempts=max_attempts,
                worker_limit=worker_limit,
                engine=engine,
                digit_model_path=str(digit_model_path) if digit_model_path else None,
                model_device=model_device,
                live_report=live_report,
                department_code=department_code,
                department_name=department_name,
            )
            futures.append(pool.submit(worker_main, index + 1, options))
        for future in as_completed(futures):
            result = future.result()
            if result.get("fatal"):
                raise DependencyError(
                    "Un worker no pudo iniciar. Ejecuta 'python scripts/analyze_e14.py doctor'."
                )
            for key, value in result.items():
                if key == "fatal":
                    continue
                aggregate[key] = aggregate.get(key, 0) + int(value)
    return aggregate


def write_csv(path: Path, rows: list[sqlite3.Row], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row[name] if name in row.keys() else "" for name in fieldnames})


class CsvAppendLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        if os.name == "nt":
            import msvcrt

            self.handle.seek(0)
            while True:
                try:
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.handle is None:
            return
        if os.name == "nt":
            import msvcrt

            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def append_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    lock_path = path.with_name(path.name + ".lock")
    with CsvAppendLock(lock_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        needs_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            if needs_header:
                writer.writeheader()
            writer.writerows(rows)
            fh.flush()
            os.fsync(fh.fileno())


LIVE_SUMMARY_FIELDS = [
    "analyzed_at",
    "document_id",
    "status",
    "relative_path",
    "department_name",
    "municipality_name",
    "zone_code",
    "place_name",
    "table_number",
    "candidate_total",
    "blank_votes",
    "null_votes",
    "unmarked_votes",
    "declared_total",
    "urna_total",
    "e11_total",
    "incinerated_total",
    "signed_juror_count",
    "page_count",
]

REPORT_SUMMARY_FIELDS = [
    "id",
    "status",
    "department_code",
    "department_name",
    "municipality_code",
    "municipality_name",
    "zone_code",
    "place_code",
    "place_name",
    "table_number",
    "relative_path",
    "candidate_total",
    "blank_votes",
    "null_votes",
    "unmarked_votes",
    "declared_total",
    "urna_total",
    "e11_total",
    "incinerated_total",
    "signed_juror_count",
    "attempts",
    "last_error",
    "analyzed_at",
]

REPORT_FIELD_FIELDS = [
    "document_id",
    "relative_path",
    "field_key",
    "field_label",
    "field_role",
    "raw_text",
    "normalized_value",
    "confidence",
    "crop_path",
]

LIVE_INCONSISTENCY_FIELDS = [
    "document_id",
    "severity",
    "code",
    "message",
    "details_json",
    "relative_path",
    "department_name",
    "municipality_name",
    "zone_code",
    "place_name",
    "table_number",
    "created_at",
]

LIVE_FAILED_FIELDS = [
    "analyzed_at",
    "document_id",
    "status",
    "error",
    "relative_path",
    "absolute_path",
    "department_name",
    "municipality_name",
    "zone_code",
    "place_name",
    "table_number",
]


def append_live_analysis(report_dir: Path, doc: sqlite3.Row, result: dict[str, Any], status: str) -> None:
    live_dir = report_dir / "live"
    stamp = now_iso()
    summary = result.get("summary", {})
    append_csv(
        live_dir / "resumen_live.csv",
        LIVE_SUMMARY_FIELDS,
        [
            {
                "analyzed_at": stamp,
                "document_id": doc["id"],
                "status": status,
                "relative_path": doc["relative_path"],
                "department_name": doc["department_name"],
                "municipality_name": doc["municipality_name"],
                "zone_code": doc["zone_code"],
                "place_name": doc["place_name"],
                "table_number": doc["table_number"],
                "candidate_total": summary.get("candidate_total"),
                "blank_votes": summary.get("blank_votes"),
                "null_votes": summary.get("null_votes"),
                "unmarked_votes": summary.get("unmarked_votes"),
                "declared_total": summary.get("declared_total"),
                "urna_total": summary.get("urna_total"),
                "e11_total": summary.get("e11_total"),
                "incinerated_total": summary.get("incinerated_total"),
                "signed_juror_count": summary.get("signed_juror_count"),
                "page_count": result.get("page_count"),
            }
        ],
    )
    append_csv(
        report_dir / "resumen.csv",
        REPORT_SUMMARY_FIELDS,
        [
            {
                "id": doc["id"],
                "status": status,
                "department_code": doc["department_code"],
                "department_name": doc["department_name"],
                "municipality_code": doc["municipality_code"],
                "municipality_name": doc["municipality_name"],
                "zone_code": doc["zone_code"],
                "place_code": doc["place_code"],
                "place_name": doc["place_name"],
                "table_number": doc["table_number"],
                "relative_path": doc["relative_path"],
                "candidate_total": summary.get("candidate_total"),
                "blank_votes": summary.get("blank_votes"),
                "null_votes": summary.get("null_votes"),
                "unmarked_votes": summary.get("unmarked_votes"),
                "declared_total": summary.get("declared_total"),
                "urna_total": summary.get("urna_total"),
                "e11_total": summary.get("e11_total"),
                "incinerated_total": summary.get("incinerated_total"),
                "signed_juror_count": summary.get("signed_juror_count"),
                "attempts": doc["attempts"],
                "last_error": "",
                "analyzed_at": stamp,
            }
        ],
    )

    field_rows = []
    for field in result.get("fields", []):
        field_rows.append(
            {
                "document_id": doc["id"],
                "relative_path": doc["relative_path"],
                "field_key": field.get("field_key"),
                "field_label": field.get("field_label"),
                "field_role": field.get("field_role"),
                "raw_text": field.get("raw_text"),
                "normalized_value": field.get("normalized_value"),
                "confidence": field.get("confidence"),
                "crop_path": field.get("crop_path"),
            }
        )
    append_csv(report_dir / "campos.csv", REPORT_FIELD_FIELDS, field_rows)

    inconsistency_rows = []
    for item in result.get("inconsistencies", []):
        inconsistency_rows.append(
            {
                "document_id": doc["id"],
                "severity": item.get("severity"),
                "code": item.get("code"),
                "message": item.get("message"),
                "details_json": json.dumps(item.get("details", {}), ensure_ascii=True),
                "relative_path": doc["relative_path"],
                "department_name": doc["department_name"],
                "municipality_name": doc["municipality_name"],
                "zone_code": doc["zone_code"],
                "place_name": doc["place_name"],
                "table_number": doc["table_number"],
                "created_at": stamp,
            }
        )
    append_csv(report_dir / "inconsistencias.csv", LIVE_INCONSISTENCY_FIELDS, inconsistency_rows)


def append_live_failure(report_dir: Path, doc: sqlite3.Row, error: str, status: str) -> None:
    append_csv(
        report_dir / "live" / "fallidos_live.csv",
        LIVE_FAILED_FIELDS,
        [
            {
                "analyzed_at": now_iso(),
                "document_id": doc["id"],
                "status": status,
                "error": error[:2000],
                "relative_path": doc["relative_path"],
                "absolute_path": doc["absolute_path"],
                "department_name": doc["department_name"],
                "municipality_name": doc["municipality_name"],
                "zone_code": doc["zone_code"],
                "place_name": doc["place_name"],
                "table_number": doc["table_number"],
            }
        ],
    )


def export_reports(db_path: Path, out_dir: Path) -> None:
    init_db(db_path)
    conn = connect_db(db_path)

    summary_fields = [
        "id",
        "status",
        "department_code",
        "department_name",
        "municipality_code",
        "municipality_name",
        "zone_code",
        "place_code",
        "place_name",
        "table_number",
        "relative_path",
        "candidate_total",
        "blank_votes",
        "null_votes",
        "unmarked_votes",
        "declared_total",
        "urna_total",
        "e11_total",
        "incinerated_total",
        "signed_juror_count",
        "attempts",
        "last_error",
        "analyzed_at",
    ]
    rows = conn.execute(
        """
        SELECT d.id, d.status, d.department_code, d.department_name,
               d.municipality_code, d.municipality_name, d.zone_code,
               d.place_code, d.place_name, d.table_number, d.relative_path,
               r.candidate_total, r.blank_votes, r.null_votes, r.unmarked_votes,
               r.declared_total, r.urna_total, r.e11_total, r.incinerated_total,
               r.signed_juror_count, d.attempts, d.last_error, d.analyzed_at
        FROM documents d
        LEFT JOIN document_results r ON r.document_id = d.id
        ORDER BY d.relative_path
        """
    ).fetchall()
    write_csv(out_dir / "resumen.csv", rows, summary_fields)

    inconsistency_fields = [
        "document_id",
        "severity",
        "code",
        "message",
        "details_json",
        "relative_path",
        "department_name",
        "municipality_name",
        "zone_code",
        "place_name",
        "table_number",
        "created_at",
    ]
    rows = conn.execute(
        """
        SELECT i.document_id, i.severity, i.code, i.message, i.details_json,
               d.relative_path, d.department_name, d.municipality_name,
               d.zone_code, d.place_name, d.table_number, i.created_at
        FROM inconsistencies i
        JOIN documents d ON d.id = i.document_id
        ORDER BY
            CASE i.severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
            d.relative_path
        """
    ).fetchall()
    write_csv(out_dir / "inconsistencias.csv", rows, inconsistency_fields)

    pending_fields = [
        "id",
        "status",
        "relative_path",
        "absolute_path",
        "department_name",
        "municipality_name",
        "zone_code",
        "place_name",
        "table_number",
        "attempts",
        "last_error",
        "updated_at",
    ]
    rows = conn.execute(
        """
        SELECT id, status, relative_path, absolute_path, department_name,
               municipality_name, zone_code, place_name, table_number,
               attempts, last_error, updated_at
        FROM documents
        WHERE status IN ('pending', 'missing_pdf', 'processing')
        ORDER BY status, relative_path
        """
    ).fetchall()
    write_csv(out_dir / "pendientes.csv", rows, pending_fields)

    rows = conn.execute(
        """
        SELECT id, status, relative_path, absolute_path, department_name,
               municipality_name, zone_code, place_name, table_number,
               attempts, last_error, updated_at
        FROM documents
        WHERE status = 'failed'
        ORDER BY relative_path
        """
    ).fetchall()
    write_csv(out_dir / "fallidos.csv", rows, pending_fields)

    field_fields = [
        "document_id",
        "relative_path",
        "field_key",
        "field_label",
        "field_role",
        "raw_text",
        "normalized_value",
        "confidence",
        "crop_path",
    ]
    rows = conn.execute(
        """
        SELECT f.document_id, d.relative_path, f.field_key, f.field_label,
               f.field_role, f.raw_text, f.normalized_value, f.confidence,
               f.crop_path
        FROM field_results f
        JOIN documents d ON d.id = f.document_id
        ORDER BY d.relative_path, f.id
        """
    ).fetchall()
    write_csv(out_dir / "campos.csv", rows, field_fields)

    conn.close()


def export_labeling_crops(
    db_path: Path,
    config_path: Path,
    root: Path,
    out_dir: Path,
    limit: int,
    dpi: int,
    include_pages: bool,
    statuses: list[str],
    random_sample: bool,
) -> int:
    init_db(db_path)
    discover_pdfs(root, db_path, hash_files=False)
    config = load_config(config_path)
    fields = config.get("fields", [])
    page_indexes = sorted({int(field.get("page", 0)) for field in fields})

    conn = connect_db(db_path)
    placeholders = ",".join("?" for _ in statuses)
    order_by = "RANDOM()" if random_sample else "id"
    rows = conn.execute(
        f"""
        SELECT *
        FROM documents
        WHERE status IN ({placeholders})
          AND absolute_path IS NOT NULL
        ORDER BY {order_by}
        LIMIT ?
        """,
        (*statuses, limit),
    ).fetchall()
    conn.close()

    crops_dir = out_dir / "labeling" / "crops"
    pages_dir = out_dir / "labeling" / "pages"
    manifest_path = out_dir / "labeling" / "manifest.csv"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    rows_written = 0
    with manifest_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "document_id",
                "relative_path",
                "field_key",
                "field_label",
                "field_role",
                "page_index",
                "crop_path",
            ],
        )
        writer.writeheader()

        for doc in rows:
            pdf_path = Path(doc["absolute_path"])
            if not pdf_path.exists():
                continue

            normalized_cache: dict[int, Any] = {}
            for page_index in page_indexes:
                image, _ = render_page(pdf_path, page_index, dpi)
                if image is None:
                    continue
                normalized = normalize_page(image)
                normalized_cache[page_index] = normalized
                if include_pages:
                    page_path = pages_dir / safe_debug_name(doc["relative_path"], page_index)
                    save_debug_image(normalized, page_path)

            for field in fields:
                page_index = int(field.get("page", 0))
                image = normalized_cache.get(page_index)
                if image is None:
                    continue
                crop, _ = crop_relative(image, field["box"])
                crop_path = crops_dir / safe_debug_name(doc["relative_path"], page_index, field["key"])
                save_debug_image(crop, crop_path)
                writer.writerow(
                    {
                        "document_id": doc["id"],
                        "relative_path": doc["relative_path"],
                        "field_key": field["key"],
                        "field_label": field.get("label"),
                        "field_role": field.get("role"),
                        "page_index": page_index,
                        "crop_path": str(crop_path),
                    }
                )
                rows_written += 1

    return rows_written


def guard_tesseract_results(args: argparse.Namespace) -> bool:
    if getattr(args, "engine", "tesseract") == "digit-model":
        model_path = getattr(args, "digit_model", DEFAULT_MODEL_PATH)
        if not model_path.exists():
            print(f"No encuentro el modelo de digitos: {model_path}")
            print("Entrenalo primero con:")
            print("  python src/train_e14_digit_model.py")
            return False
        return True
    if getattr(args, "allow_ocr_results", False):
        return True
    print(
        "El guardado de resultados OCR con Tesseract esta bloqueado por seguridad: "
        "la muestra manuscrita no fue confiable. Usa el subcomando 'crops' para generar "
        "recortes de entrenamiento, o agrega --allow-ocr-results si de verdad quieres "
        "guardar resultados experimentales."
    )
    return False


def command_doctor(args: argparse.Namespace) -> int:
    print(f"Python: {sys.version.split()[0]}")
    checks = [
        ("fitz", "PyMuPDF"),
        ("cv2", "opencv-python"),
        ("PIL", "Pillow"),
        ("numpy", "numpy"),
    ]
    ok = True
    for module, package in checks:
        try:
            __import__(module)
            print(f"OK {package}")
        except Exception:
            print(f"MISSING {package}")
            ok = False

    if getattr(args, "engine", "tesseract") == "digit-model":
        try:
            import torch

            print(f"OK PyTorch: {torch.__version__}")
        except Exception:
            print("MISSING PyTorch")
            ok = False
        if args.digit_model.exists():
            print(f"OK Modelo digitos: {args.digit_model}")
        else:
            print(f"MISSING Modelo digitos: {args.digit_model}")
            ok = False
    else:
        tesseract = shutil.which(args.tesseract_cmd)
        if tesseract:
            print(f"OK Tesseract: {tesseract}")
        else:
            print(f"MISSING Tesseract command: {args.tesseract_cmd}")
            ok = False

    if not ok:
        print("")
        if getattr(args, "engine", "tesseract") == "digit-model":
            print("Para el modo modelo instala PyTorch y entrena primero:")
            print("  python -m pip install torch")
            print("  python src/train_e14_digit_model.py")
        else:
            print("Instala dependencias Python con:")
            print("  python -m pip install -r requirements.txt")
            print("Y asegura que tesseract.exe este en PATH.")
        return 1
    return 0


def command_init_db(args: argparse.Namespace) -> int:
    init_db(args.db)
    print(f"DB lista: {args.db}")
    return 0


def command_discover(args: argparse.Namespace) -> int:
    count = discover_pdfs(args.root, args.db, args.hash_files)
    print(f"PDFs vistos: {count}")
    print("Estados:", status_counts(args.db))
    return 0


def command_import_expected(args: argparse.Namespace) -> int:
    count = import_expected(args.manifest, args.root, args.db)
    print(f"Rutas esperadas importadas: {count}")
    print("Estados:", status_counts(args.db))
    return 0


def command_requeue(args: argparse.Namespace) -> int:
    count = requeue_documents(args.db, args.status, args.limit, args.reset_attempts)
    print(f"Documentos reencolados: {count}")
    print("Estados:", status_counts(args.db))
    return 0


def command_reset_analysis(args: argparse.Namespace) -> int:
    if not args.yes:
        print("Este comando borra resultados OCR/modelo y reportes CSV, pero no borra PDFs.")
        print("Vuelve a ejecutarlo con --yes para confirmar.")
        return 2
    result = reset_analysis_state(args.db, args.out, not args.keep_report_csvs)
    print("Analisis reiniciado:", result)
    print("Estados:", status_counts(args.db))
    return 0


def command_analyze(args: argparse.Namespace) -> int:
    if not guard_tesseract_results(args):
        return 2
    reset = reset_stale_jobs(args.db, args.stale_minutes)
    if reset:
        print(f"Trabajos stale reiniciados: {reset}")
    result = analyze_pending(
        args.db,
        args.config,
        args.out,
        args.workers,
        args.dpi,
        args.tesseract_cmd,
        args.save_debug,
        args.max_attempts,
        args.limit,
        args.engine,
        args.digit_model,
        args.model_device,
        not args.no_live_report,
        args.department_code,
        args.department_name,
    )
    print("Analisis:", result)
    print("Estados:", status_counts(args.db, args.department_code, args.department_name))
    return 0


def command_run(args: argparse.Namespace) -> int:
    if not guard_tesseract_results(args):
        return 2
    idle_started: float | None = None
    while True:
        reset = reset_stale_jobs(args.db, args.stale_minutes)
        found = discover_pdfs(args.root, args.db, args.hash_files)
        if reset:
            print(f"Trabajos stale reiniciados: {reset}")
        print(f"Discovery: {found} PDFs vistos")

        result = analyze_pending(
            args.db,
            args.config,
            args.out,
            args.workers,
            args.dpi,
            args.tesseract_cmd,
            args.save_debug,
            args.max_attempts,
            args.limit,
            args.engine,
            args.digit_model,
            args.model_device,
            not args.no_live_report,
            args.department_code,
            args.department_name,
        )
        print("Analisis:", result)
        print("Estados:", status_counts(args.db, args.department_code, args.department_name))
        export_reports(args.db, args.out)

        if not args.watch:
            break
        if result.get("processed", 0) == 0:
            if idle_started is None:
                idle_started = time.time()
            elif time.time() - idle_started >= args.idle_seconds:
                print(f"Sin nuevos trabajos durante {args.idle_seconds}s; saliendo.")
                break
        else:
            idle_started = None
        time.sleep(args.discover_every)
    return 0


def command_report(args: argparse.Namespace) -> int:
    export_reports(args.db, args.out)
    print(f"Reportes escritos en: {args.out}")
    print("Estados:", status_counts(args.db))
    return 0


def command_crops(args: argparse.Namespace) -> int:
    count = export_labeling_crops(
        args.db,
        args.config,
        args.root,
        args.out,
        args.limit,
        args.dpi,
        args.include_pages,
        args.status or ["pending"],
        args.random,
    )
    print(f"Recortes generados: {count}")
    print(f"Manifest: {args.out / 'labeling' / 'manifest.csv'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", type=Path, default=DEFAULT_DB, help="Ruta SQLite.")
    common.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Config de ROIs.")
    common.add_argument("--out", type=Path, default=DEFAULT_REPORT_DIR, help="Carpeta de reportes.")
    common.add_argument("--tesseract-cmd", default="tesseract", help="Comando o ruta de Tesseract.")

    parser = argparse.ArgumentParser(description="OCR masivo para PDFs E14.", parents=[common])

    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Verifica dependencias.", parents=[common])
    doctor.add_argument("--engine", choices=["tesseract", "digit-model"], default="tesseract")
    doctor.add_argument("--digit-model", type=Path, default=DEFAULT_MODEL_PATH)
    doctor.set_defaults(func=command_doctor)

    init = sub.add_parser("init-db", help="Crea/actualiza esquema SQLite.", parents=[common])
    init.set_defaults(func=command_init_db)

    discover = sub.add_parser("discover", help="Escanea PDFs existentes y los pone en cola.", parents=[common])
    discover.add_argument("--root", type=Path, default=DEFAULT_DOWNLOAD_ROOT)
    discover.add_argument("--hash-files", action="store_true", help="Calcula SHA1; mas lento pero detecta cambios exactos.")
    discover.set_defaults(func=command_discover)

    expected = sub.add_parser("import-expected", help="Importa rutas esperadas desde CSV.", parents=[common])
    expected.add_argument("--manifest", type=Path, required=True)
    expected.add_argument("--root", type=Path, default=DEFAULT_DOWNLOAD_ROOT)
    expected.set_defaults(func=command_import_expected)

    requeue = sub.add_parser("requeue", help="Devuelve documentos a pending para reprocesarlos.", parents=[common])
    requeue.add_argument(
        "--status",
        action="append",
        choices=["inconsistent", "done", "failed", "missing_pdf", "processing"],
        required=True,
        help="Estado a reencolar. Puede repetirse.",
    )
    requeue.add_argument("--limit", type=int)
    requeue.add_argument("--reset-attempts", action="store_true")
    requeue.set_defaults(func=command_requeue)

    reset_analysis = sub.add_parser(
        "reset-analysis",
        help="Borra resultados OCR/modelo y vuelve a empezar sin tocar PDFs.",
        parents=[common],
    )
    reset_analysis.add_argument("--yes", action="store_true", help="Confirma el borrado de resultados OCR.")
    reset_analysis.add_argument("--keep-report-csvs", action="store_true", help="No borra CSVs de reports/ocr.")
    reset_analysis.set_defaults(func=command_reset_analysis)

    analyze = sub.add_parser("analyze", help="Analiza documentos pending.", parents=[common])
    analyze.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    analyze.add_argument("--dpi", type=int, default=300)
    analyze.add_argument("--save-debug", action="store_true")
    analyze.add_argument("--max-attempts", type=int, default=3)
    analyze.add_argument("--stale-minutes", type=int, default=120)
    analyze.add_argument("--limit", type=int)
    analyze.add_argument("--engine", choices=["tesseract", "digit-model"], default="tesseract")
    analyze.add_argument("--digit-model", type=Path, default=DEFAULT_MODEL_PATH)
    analyze.add_argument("--model-device", choices=["auto", "cpu", "cuda"], default="cpu")
    analyze.add_argument("--department-code", help="Filtra pending por codigo de departamento, por ejemplo 68.")
    analyze.add_argument("--department", "--department-name", dest="department_name", help="Filtra pending por nombre exacto normalizado.")
    analyze.add_argument("--no-live-report", action="store_true")
    analyze.add_argument("--allow-ocr-results", action="store_true")
    analyze.set_defaults(func=command_analyze)

    run = sub.add_parser("run", help="Discover + analyze + report.", parents=[common])
    run.add_argument("--root", type=Path, default=DEFAULT_DOWNLOAD_ROOT)
    run.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    run.add_argument("--dpi", type=int, default=300)
    run.add_argument("--save-debug", action="store_true")
    run.add_argument("--max-attempts", type=int, default=3)
    run.add_argument("--stale-minutes", type=int, default=120)
    run.add_argument("--limit", type=int)
    run.add_argument("--hash-files", action="store_true")
    run.add_argument("--watch", action="store_true")
    run.add_argument("--idle-seconds", type=int, default=300)
    run.add_argument("--discover-every", type=int, default=30)
    run.add_argument("--engine", choices=["tesseract", "digit-model"], default="tesseract")
    run.add_argument("--digit-model", type=Path, default=DEFAULT_MODEL_PATH)
    run.add_argument("--model-device", choices=["auto", "cpu", "cuda"], default="cpu")
    run.add_argument("--department-code", help="Filtra pending por codigo de departamento, por ejemplo 68.")
    run.add_argument("--department", "--department-name", dest="department_name", help="Filtra pending por nombre exacto normalizado.")
    run.add_argument("--no-live-report", action="store_true")
    run.add_argument("--allow-ocr-results", action="store_true")
    run.set_defaults(func=command_run)

    report = sub.add_parser("report", help="Exporta CSVs desde la DB.", parents=[common])
    report.set_defaults(func=command_report)

    crops = sub.add_parser("crops", help="Genera recortes de muestra sin guardar resultados OCR.", parents=[common])
    crops.add_argument("--root", type=Path, default=DEFAULT_DOWNLOAD_ROOT)
    crops.add_argument("--limit", type=int, default=20)
    crops.add_argument("--dpi", type=int, default=300)
    crops.add_argument("--include-pages", action="store_true")
    crops.add_argument("--random", action="store_true", help="Muestrea documentos al azar en vez de tomar los primeros IDs.")
    crops.add_argument(
        "--status",
        action="append",
        choices=["pending", "inconsistent", "done", "failed", "missing_pdf"],
        default=None,
        help="Estado de documentos para muestrear. Puede repetirse.",
    )
    crops.set_defaults(func=command_crops)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.db = args.db.resolve()
    args.config = args.config.resolve()
    args.out = args.out.resolve()
    if hasattr(args, "root"):
        args.root = args.root.resolve()
    if hasattr(args, "manifest"):
        args.manifest = args.manifest.resolve()
    if hasattr(args, "digit_model"):
        args.digit_model = args.digit_model.resolve()
    try:
        return int(args.func(args))
    except DependencyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrumpido por usuario.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
