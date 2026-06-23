from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

import analyze_e14


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "state" / "e14.sqlite"
DEFAULT_CONFIG = ROOT / "config" / "e14_rois.json"
DEFAULT_REPORT_DIR = ROOT / "reports" / "ocr" / "source_compare"
DEFAULT_SOURCE_ROOTS = {
    "claveros": ROOT / "downloads" / "E14" / "claveros",
    "delegados": ROOT / "downloads" / "E14" / "delegados",
    "transmision": ROOT / "downloads" / "E14" / "transmision",
}
SOURCE_CHOICES = tuple(DEFAULT_SOURCE_ROOTS)
COMPARABLE_FIELD_TYPES = {"number"}


def now_iso() -> str:
    return analyze_e14.now_iso()


def connect_db(db_path: Path) -> sqlite3.Connection:
    return analyze_e14.connect_db(db_path)


def mesa_key(
    corporation_code: str,
    department_code: str,
    municipality_code: str,
    zone_code: str,
    stand_code: str,
    table_number: str,
) -> str:
    return "|".join(
        [
            corporation_code,
            department_code.zfill(2),
            municipality_code.zfill(3),
            zone_code.zfill(3),
            stand_code.zfill(2),
            table_number.zfill(3),
        ]
    )


def parse_claveros_path(root: Path, pdf_path: Path) -> dict[str, str] | None:
    try:
        rel = pdf_path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    parts = list(rel.parts)
    if len(parts) < 5:
        return None

    dep_match = re.match(r"^(\d{2})_", parts[0])
    mun_match = re.match(r"^(\d{3})_", parts[1])
    zone_match = re.match(r"^ZONA_(\d+)$", parts[2], flags=re.I)
    stand_match = re.match(r"^([A-Z0-9]{2})_", parts[3], flags=re.I)
    table_match = re.search(r"MESA_(\d+)", parts[-1], flags=re.I)
    if not (dep_match and mun_match and zone_match and stand_match and table_match):
        return None

    return {
        "corporation_code": "PRE",
        "department_code": dep_match.group(1).zfill(2),
        "municipality_code": mun_match.group(1).zfill(3),
        "zone_code": zone_match.group(1).zfill(3),
        "stand_code": stand_match.group(1).upper().zfill(2),
        "table_number": table_match.group(1).zfill(3),
        "relative_path": str(rel),
    }


def parse_coded_path(root: Path, pdf_path: Path) -> dict[str, str] | None:
    try:
        rel = pdf_path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    parts = list(rel.parts)
    if len(parts) < 7:
        return None
    department, municipality, zone, stand, table, corporation = parts[:6]
    if not pdf_path.name.lower().endswith(".pdf"):
        return None
    return {
        "corporation_code": "PRE" if corporation.upper() == "PRE" else corporation.upper(),
        "department_code": department.zfill(2),
        "municipality_code": municipality.zfill(3),
        "zone_code": zone.zfill(3),
        "stand_code": stand.upper().zfill(2),
        "table_number": table.zfill(3),
        "relative_path": str(rel),
    }


def parse_source_path(source_type: str, root: Path, pdf_path: Path) -> dict[str, str] | None:
    if source_type == "claveros":
        return parse_claveros_path(root, pdf_path)
    return parse_coded_path(root, pdf_path)


def init_schema(db_path: Path) -> None:
    analyze_e14.init_db(db_path)
    conn = connect_db(db_path)
    try:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_documents (
                    id INTEGER PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    mesa_key TEXT NOT NULL,
                    corporation_code TEXT NOT NULL,
                    department_code TEXT NOT NULL,
                    municipality_code TEXT NOT NULL,
                    zone_code TEXT NOT NULL,
                    stand_code TEXT NOT NULL,
                    table_number TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    absolute_path TEXT NOT NULL,
                    file_size INTEGER,
                    file_mtime REAL,
                    file_sha1 TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    last_error TEXT,
                    discovered_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    analyzed_at TEXT,
                    UNIQUE(source_type, mesa_key)
                );

                CREATE INDEX IF NOT EXISTS idx_source_documents_mesa
                    ON source_documents(mesa_key);

                CREATE INDEX IF NOT EXISTS idx_source_documents_status
                    ON source_documents(source_type, status, updated_at);

                CREATE TABLE IF NOT EXISTS source_document_results (
                    source_document_id INTEGER PRIMARY KEY REFERENCES source_documents(id) ON DELETE CASCADE,
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

                CREATE TABLE IF NOT EXISTS source_field_results (
                    id INTEGER PRIMARY KEY,
                    source_document_id INTEGER NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
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
                    created_at TEXT NOT NULL,
                    UNIQUE(source_document_id, field_key)
                );

                CREATE INDEX IF NOT EXISTS idx_source_field_results_document
                    ON source_field_results(source_document_id);

                CREATE TABLE IF NOT EXISTS source_comparisons (
                    id INTEGER PRIMARY KEY,
                    mesa_key TEXT NOT NULL,
                    source_a TEXT NOT NULL,
                    source_b TEXT NOT NULL,
                    source_document_a_id INTEGER,
                    source_document_b_id INTEGER,
                    status TEXT NOT NULL,
                    numeric_mismatches INTEGER NOT NULL DEFAULT 0,
                    visual_mismatches INTEGER NOT NULL DEFAULT 0,
                    ocr_uncertain INTEGER NOT NULL DEFAULT 0,
                    missing_fields INTEGER NOT NULL DEFAULT 0,
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(mesa_key, source_a, source_b)
                );

                CREATE TABLE IF NOT EXISTS source_field_comparisons (
                    id INTEGER PRIMARY KEY,
                    comparison_id INTEGER NOT NULL REFERENCES source_comparisons(id) ON DELETE CASCADE,
                    field_key TEXT NOT NULL,
                    field_label TEXT,
                    value_a INTEGER,
                    value_b INTEGER,
                    confidence_a REAL,
                    confidence_b REAL,
                    visual_score REAL,
                    result TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(comparison_id, field_key)
                );
                """
            )
    finally:
        conn.close()


def discover_source(source_type: str, root: Path, db_path: Path, limit: int | None = None) -> int:
    init_schema(db_path)
    conn = connect_db(db_path)
    stamp = now_iso()
    count = 0
    skipped = 0
    try:
        with conn:
            for pdf_path in root.rglob("*.pdf"):
                if limit is not None and count >= limit:
                    break
                meta = parse_source_path(source_type, root, pdf_path)
                if not meta:
                    skipped += 1
                    continue
                stat = pdf_path.stat()
                key = mesa_key(
                    meta["corporation_code"],
                    meta["department_code"],
                    meta["municipality_code"],
                    meta["zone_code"],
                    meta["stand_code"],
                    meta["table_number"],
                )
                conn.execute(
                    """
                    INSERT INTO source_documents (
                        source_type, mesa_key, corporation_code, department_code,
                        municipality_code, zone_code, stand_code, table_number,
                        relative_path, absolute_path, file_size, file_mtime,
                        status, discovered_at, updated_at
                    ) VALUES (
                        :source_type, :mesa_key, :corporation_code, :department_code,
                        :municipality_code, :zone_code, :stand_code, :table_number,
                        :relative_path, :absolute_path, :file_size, :file_mtime,
                        'pending', :stamp, :stamp
                    )
                    ON CONFLICT(source_type, mesa_key) DO UPDATE SET
                        relative_path = excluded.relative_path,
                        absolute_path = excluded.absolute_path,
                        file_size = excluded.file_size,
                        file_mtime = excluded.file_mtime,
                        status = CASE
                            WHEN source_documents.file_size IS NOT excluded.file_size
                              OR source_documents.file_mtime IS NOT excluded.file_mtime
                            THEN 'pending'
                            ELSE source_documents.status
                        END,
                        last_error = CASE
                            WHEN source_documents.file_size IS NOT excluded.file_size
                              OR source_documents.file_mtime IS NOT excluded.file_mtime
                            THEN NULL
                            ELSE source_documents.last_error
                        END,
                        updated_at = excluded.updated_at
                    """,
                    {
                        **meta,
                        "source_type": source_type,
                        "mesa_key": key,
                        "absolute_path": str(pdf_path),
                        "file_size": stat.st_size,
                        "file_mtime": stat.st_mtime,
                        "stamp": stamp,
                    },
                )
                count += 1
    finally:
        conn.close()
    if skipped:
        print(f"Rutas omitidas por formato desconocido: {skipped}")
    return count


def source_doc_for_analysis(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "absolute_path": row["absolute_path"],
        "relative_path": f"{row['source_type']}{os.sep}{row['relative_path']}",
    }


def save_source_analysis(db_path: Path, source_document_id: int, result: dict[str, Any]) -> str:
    conn = connect_db(db_path)
    stamp = now_iso()
    inconsistencies = result.get("inconsistencies", [])
    has_errors = any(item.get("severity") == "error" for item in inconsistencies)
    status = "missing_pdf" if result.get("missing") else ("inconsistent" if has_errors else "done")
    try:
        with conn:
            conn.execute("DELETE FROM source_field_results WHERE source_document_id = ?", (source_document_id,))
            for field in result.get("fields", []):
                conn.execute(
                    """
                    INSERT INTO source_field_results (
                        source_document_id, page_index, field_key, field_label,
                        field_role, field_type, raw_text, normalized_value,
                        confidence, bbox_json, crop_path, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_document_id,
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

            summary = result.get("summary", {})
            conn.execute(
                """
                INSERT INTO source_document_results (
                    source_document_id, page_count, extracted_json, confidence_json,
                    inconsistencies_json, candidate_total, blank_votes, null_votes,
                    unmarked_votes, declared_total, urna_total, e11_total,
                    incinerated_total, signed_juror_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_document_id) DO UPDATE SET
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
                    source_document_id,
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
                UPDATE source_documents
                SET status = ?, last_error = NULL, updated_at = ?, analyzed_at = ?
                WHERE id = ?
                """,
                (status, stamp, stamp, source_document_id),
            )
    finally:
        conn.close()
    return status


def mark_source_failed(db_path: Path, source_document_id: int, error: str) -> None:
    conn = connect_db(db_path)
    try:
        with conn:
            conn.execute(
                """
                UPDATE source_documents
                SET status = 'failed', last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (error[:2000], now_iso(), source_document_id),
            )
    finally:
        conn.close()


def analyze_source(args: argparse.Namespace) -> dict[str, int]:
    init_schema(args.db)
    config = analyze_e14.load_config(args.config)
    status_filter = "'pending', 'failed', 'missing_pdf'"
    if args.force:
        status_filter = "'pending', 'failed', 'missing_pdf', 'done', 'inconsistent'"
    conn = connect_db(args.db)
    rows = conn.execute(
        f"""
        SELECT *
        FROM source_documents
        WHERE source_type = ?
          AND status IN ({status_filter})
        ORDER BY mesa_key
        LIMIT ?
        """,
        (args.source, args.limit),
    ).fetchall()
    conn.close()

    counts = {"processed": 0, "done": 0, "inconsistent": 0, "missing_pdf": 0, "failed": 0}
    for row in rows:
        try:
            result = analyze_e14.analyze_pdf(
                source_doc_for_analysis(row),
                config,
                args.out,
                args.dpi,
                args.tesseract_cmd,
                args.save_debug,
                args.engine,
                args.digit_model,
                args.model_device,
            )
            status = save_source_analysis(args.db, int(row["id"]), result)
            counts["processed"] += 1
            counts[status] = counts.get(status, 0) + 1
            print(f"{row['source_type']} {row['mesa_key']} -> {status}")
        except Exception as exc:
            mark_source_failed(args.db, int(row["id"]), str(exc))
            counts["processed"] += 1
            counts["failed"] += 1
            print(f"{row['source_type']} {row['mesa_key']} -> failed: {exc}")
    return counts


def sync_existing_claveros(db_path: Path, limit: int | None = None) -> int:
    init_schema(db_path)
    conn = connect_db(db_path)
    stamp = now_iso()
    params: list[Any] = []
    limit_sql = ""
    if limit is not None:
        limit_sql = " LIMIT ?"
        params.append(limit)
    rows = conn.execute(
        f"""
        SELECT sd.id AS source_document_id, d.id AS document_id,
               d.status, d.analyzed_at
        FROM source_documents sd
        JOIN documents d ON d.relative_path = sd.relative_path
        JOIN document_results dr ON dr.document_id = d.id
        WHERE sd.source_type = 'claveros'
          AND NOT EXISTS (
              SELECT 1 FROM source_document_results sdr
              WHERE sdr.source_document_id = sd.id
          )
        ORDER BY sd.mesa_key
        {limit_sql}
        """,
        params,
    ).fetchall()
    copied = 0
    try:
        with conn:
            for row in rows:
                source_document_id = int(row["source_document_id"])
                document_id = int(row["document_id"])
                conn.execute(
                    """
                    INSERT INTO source_document_results (
                        source_document_id, page_count, extracted_json, confidence_json,
                        inconsistencies_json, candidate_total, blank_votes, null_votes,
                        unmarked_votes, declared_total, urna_total, e11_total,
                        incinerated_total, signed_juror_count, created_at, updated_at
                    )
                    SELECT ?, page_count, extracted_json, confidence_json,
                           inconsistencies_json, candidate_total, blank_votes, null_votes,
                           unmarked_votes, declared_total, urna_total, e11_total,
                           incinerated_total, signed_juror_count, created_at, ?
                    FROM document_results
                    WHERE document_id = ?
                    ON CONFLICT(source_document_id) DO NOTHING
                    """,
                    (source_document_id, stamp, document_id),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO source_field_results (
                        source_document_id, page_index, field_key, field_label,
                        field_role, field_type, raw_text, normalized_value,
                        confidence, bbox_json, crop_path, created_at
                    )
                    SELECT ?, page_index, field_key, field_label,
                           field_role, field_type, raw_text, normalized_value,
                           confidence, bbox_json, crop_path, created_at
                    FROM field_results
                    WHERE document_id = ?
                    """,
                    (source_document_id, document_id),
                )
                conn.execute(
                    """
                    UPDATE source_documents
                    SET status = ?, analyzed_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (row["status"], row["analyzed_at"], stamp, source_document_id),
                )
                copied += 1
    finally:
        conn.close()
    return copied


def comparable_fields(config_path: Path) -> dict[str, dict[str, Any]]:
    config = analyze_e14.load_config(config_path)
    return {
        str(field["key"]): field
        for field in config.get("fields", [])
        if field.get("type") in COMPARABLE_FIELD_TYPES
    }


def load_field_map(conn: sqlite3.Connection, source_document_id: int) -> dict[str, sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT *
        FROM source_field_results
        WHERE source_document_id = ?
        """,
        (source_document_id,),
    ).fetchall()
    return {row["field_key"]: row for row in rows}


def visual_score(
    doc_a: sqlite3.Row,
    doc_b: sqlite3.Row,
    field: dict[str, Any],
    dpi: int,
) -> float | None:
    try:
        import cv2
        import numpy as np
    except Exception:
        return None

    page_index = int(field.get("page", 0))
    image_a, _ = analyze_e14.render_page(Path(doc_a["absolute_path"]), page_index, dpi)
    image_b, _ = analyze_e14.render_page(Path(doc_b["absolute_path"]), page_index, dpi)
    if image_a is None or image_b is None:
        return None
    norm_a = analyze_e14.normalize_page(image_a)
    norm_b = analyze_e14.normalize_page(image_b)
    crop_a, _ = analyze_e14.crop_relative(norm_a, field["box"])
    crop_b, _ = analyze_e14.crop_relative(norm_b, field["box"])
    gray_a = cv2.cvtColor(crop_a, cv2.COLOR_RGB2GRAY) if len(crop_a.shape) == 3 else crop_a
    gray_b = cv2.cvtColor(crop_b, cv2.COLOR_RGB2GRAY) if len(crop_b.shape) == 3 else crop_b
    gray_a = cv2.resize(gray_a, (220, 48), interpolation=cv2.INTER_AREA)
    gray_b = cv2.resize(gray_b, (220, 48), interpolation=cv2.INTER_AREA)
    _, bin_a = cv2.threshold(gray_a, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, bin_b = cv2.threshold(gray_b, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return float(np.mean(cv2.absdiff(bin_a, bin_b)) / 255.0)


def classify_field(
    field_key: str,
    field: dict[str, Any],
    row_a: sqlite3.Row | None,
    row_b: sqlite3.Row | None,
    score: float | None,
    min_confidence: float,
    visual_threshold: float,
) -> tuple[str, dict[str, Any]]:
    if row_a is None or row_b is None:
        return "missing_field", {"reason": "field_missing_in_one_source"}

    value_a = row_a["normalized_value"]
    value_b = row_b["normalized_value"]
    conf_a = row_a["confidence"]
    conf_b = row_b["confidence"]
    confident = (
        conf_a is None
        or conf_a >= min_confidence
    ) and (
        conf_b is None
        or conf_b >= min_confidence
    )

    details = {
        "raw_a": row_a["raw_text"],
        "raw_b": row_b["raw_text"],
        "field_label": field.get("label", field_key),
    }
    if value_a != value_b:
        if score is not None and score <= visual_threshold:
            return "ocr_uncertain", {
                **details,
                "reason": "numeric_mismatch_but_visual_match",
                "visual_threshold": visual_threshold,
            }
        return ("numeric_mismatch" if confident else "ocr_uncertain"), details
    return "match", details


def compare_sources(args: argparse.Namespace) -> dict[str, int]:
    init_schema(args.db)
    fields = comparable_fields(args.config)
    min_confidence = float(args.min_confidence)
    conn = connect_db(args.db)
    source_a, source_b = sorted([args.source_a, args.source_b])
    rows = conn.execute(
        """
        SELECT a.*, b.id AS b_id, b.source_type AS b_source_type,
               b.relative_path AS b_relative_path, b.absolute_path AS b_absolute_path,
               b.status AS b_status
        FROM source_documents a
        JOIN source_documents b ON b.mesa_key = a.mesa_key
        WHERE a.source_type = ?
          AND b.source_type = ?
          AND EXISTS (SELECT 1 FROM source_document_results r WHERE r.source_document_id = a.id)
          AND EXISTS (SELECT 1 FROM source_document_results r WHERE r.source_document_id = b.id)
        ORDER BY a.mesa_key
        LIMIT ?
        """,
        (source_a, source_b, args.limit),
    ).fetchall()

    counts = {"compared": 0, "needs_review": 0, "match": 0}
    try:
        with conn:
            for row in rows:
                doc_a = row
                doc_b = {
                    "id": row["b_id"],
                    "source_type": row["b_source_type"],
                    "relative_path": row["b_relative_path"],
                    "absolute_path": row["b_absolute_path"],
                    "status": row["b_status"],
                }
                fields_a = load_field_map(conn, int(doc_a["id"]))
                fields_b = load_field_map(conn, int(doc_b["id"]))
                field_results = []
                counters = {
                    "numeric_mismatches": 0,
                    "visual_mismatches": 0,
                    "ocr_uncertain": 0,
                    "missing_fields": 0,
                }
                for key, field in fields.items():
                    score = (
                        visual_score(doc_a, doc_b, field, args.dpi)
                        if args.visual
                        else None
                    )
                    result, details = classify_field(
                        key,
                        field,
                        fields_a.get(key),
                        fields_b.get(key),
                        score,
                        min_confidence,
                        args.visual_threshold,
                    )
                    if result == "numeric_mismatch":
                        counters["numeric_mismatches"] += 1
                    elif result == "visual_mismatch":
                        counters["visual_mismatches"] += 1
                    elif result == "ocr_uncertain":
                        counters["ocr_uncertain"] += 1
                    elif result == "missing_field":
                        counters["missing_fields"] += 1
                    field_results.append((key, field, fields_a.get(key), fields_b.get(key), score, result, details))

                status = "match"
                if any(counters.values()):
                    status = "needs_review"
                stamp = now_iso()
                summary = {
                    **counters,
                    "source_a_status": doc_a["status"],
                    "source_b_status": doc_b["status"],
                    "source_a_path": doc_a["relative_path"],
                    "source_b_path": doc_b["relative_path"],
                }
                conn.execute(
                    """
                    INSERT INTO source_comparisons (
                        mesa_key, source_a, source_b, source_document_a_id,
                        source_document_b_id, status, numeric_mismatches,
                        visual_mismatches, ocr_uncertain, missing_fields,
                        summary_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(mesa_key, source_a, source_b) DO UPDATE SET
                        source_document_a_id = excluded.source_document_a_id,
                        source_document_b_id = excluded.source_document_b_id,
                        status = excluded.status,
                        numeric_mismatches = excluded.numeric_mismatches,
                        visual_mismatches = excluded.visual_mismatches,
                        ocr_uncertain = excluded.ocr_uncertain,
                        missing_fields = excluded.missing_fields,
                        summary_json = excluded.summary_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        doc_a["mesa_key"],
                        source_a,
                        source_b,
                        doc_a["id"],
                        doc_b["id"],
                        status,
                        counters["numeric_mismatches"],
                        counters["visual_mismatches"],
                        counters["ocr_uncertain"],
                        counters["missing_fields"],
                        json.dumps(summary, ensure_ascii=True),
                        stamp,
                        stamp,
                    ),
                )
                comparison_id = conn.execute(
                    """
                    SELECT id FROM source_comparisons
                    WHERE mesa_key = ? AND source_a = ? AND source_b = ?
                    """,
                    (doc_a["mesa_key"], source_a, source_b),
                ).fetchone()["id"]
                conn.execute("DELETE FROM source_field_comparisons WHERE comparison_id = ?", (comparison_id,))
                for key, field, field_a, field_b, score, result, details in field_results:
                    conn.execute(
                        """
                        INSERT INTO source_field_comparisons (
                            comparison_id, field_key, field_label, value_a, value_b,
                            confidence_a, confidence_b, visual_score, result,
                            details_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            comparison_id,
                            key,
                            field.get("label", key),
                            field_a["normalized_value"] if field_a else None,
                            field_b["normalized_value"] if field_b else None,
                            field_a["confidence"] if field_a else None,
                            field_b["confidence"] if field_b else None,
                            score,
                            result,
                            json.dumps(details, ensure_ascii=True),
                            stamp,
                        ),
                    )
                counts["compared"] += 1
                counts[status] = counts.get(status, 0) + 1
                print(f"{doc_a['mesa_key']} -> {status} {counters}")
    finally:
        conn.close()
    return counts


def export_reports(db_path: Path, out_dir: Path) -> None:
    init_schema(db_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = connect_db(db_path)
    try:
        comparison_rows = conn.execute(
            """
            SELECT mesa_key, source_a, source_b, status,
                   numeric_mismatches, visual_mismatches, ocr_uncertain,
                   missing_fields, summary_json, updated_at
            FROM source_comparisons
            ORDER BY status DESC, numeric_mismatches DESC, visual_mismatches DESC, mesa_key
            """
        ).fetchall()
        write_csv(out_dir / "comparaciones.csv", comparison_rows)

        field_rows = conn.execute(
            """
            SELECT c.mesa_key, c.source_a, c.source_b, c.status AS comparison_status,
                   f.field_key, f.field_label, f.value_a, f.value_b,
                   f.confidence_a, f.confidence_b, f.visual_score,
                   f.result, f.details_json
            FROM source_field_comparisons f
            JOIN source_comparisons c ON c.id = f.comparison_id
            WHERE f.result != 'match'
            ORDER BY c.mesa_key, f.field_key
            """
        ).fetchall()
        write_csv(out_dir / "hallazgos_campos.csv", field_rows)
    finally:
        conn.close()


def write_csv(path: Path, rows: list[sqlite3.Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = rows[0].keys()
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in fieldnames})


def command_init(args: argparse.Namespace) -> int:
    init_schema(args.db)
    print(f"DB lista: {args.db}")
    return 0


def command_discover(args: argparse.Namespace) -> int:
    count = discover_source(args.source, args.root, args.db, args.limit)
    print(f"{args.source}: PDFs descubiertos {count}")
    return 0


def command_sync_existing(args: argparse.Namespace) -> int:
    if args.source != "claveros":
        print("Por ahora sync-existing solo reutiliza resultados historicos de claveros.", file=sys.stderr)
        return 2
    count = sync_existing_claveros(args.db, args.limit)
    print(f"Resultados OCR sincronizados: {count}")
    return 0


def command_analyze_source(args: argparse.Namespace) -> int:
    counts = analyze_source(args)
    print("Resumen:", ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    return 1 if counts.get("failed") else 0


def command_compare(args: argparse.Namespace) -> int:
    counts = compare_sources(args)
    print("Resumen:", ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    return 0


def command_report(args: argparse.Namespace) -> int:
    export_reports(args.db, args.out)
    print(f"Reportes: {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", type=Path, default=DEFAULT_DB)
    common.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    common.add_argument("--out", type=Path, default=DEFAULT_REPORT_DIR)
    common.add_argument("--tesseract-cmd", default="tesseract")

    parser = argparse.ArgumentParser(description="Comparador v2 de fuentes E14.", parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-db", parents=[common], help="Crea tablas v2 de comparacion.")
    init.set_defaults(func=command_init)

    discover = sub.add_parser("discover-source", parents=[common], help="Registra PDFs de una fuente.")
    discover.add_argument("--source", required=True, choices=SOURCE_CHOICES)
    discover.add_argument("--root", type=Path)
    discover.add_argument("--limit", type=int)
    discover.set_defaults(func=command_discover)

    sync = sub.add_parser("sync-existing", parents=[common], help="Reutiliza OCR historico en tablas v2.")
    sync.add_argument("--source", required=True, choices=SOURCE_CHOICES)
    sync.add_argument("--limit", type=int)
    sync.set_defaults(func=command_sync_existing)

    analyze = sub.add_parser("analyze-source", parents=[common], help="Analiza una fuente v2 pendiente.")
    analyze.add_argument("--source", required=True, choices=SOURCE_CHOICES)
    analyze.add_argument("--limit", type=int, default=20)
    analyze.add_argument("--dpi", type=int, default=300)
    analyze.add_argument("--save-debug", action="store_true")
    analyze.add_argument("--force", action="store_true", help="Reanaliza documentos ya procesados.")
    analyze.add_argument("--engine", choices=["tesseract", "digit-model"], default="digit-model")
    analyze.add_argument("--digit-model", type=Path, default=analyze_e14.DEFAULT_MODEL_PATH)
    analyze.add_argument("--model-device", choices=["auto", "cpu", "cuda"], default="cpu")
    analyze.set_defaults(func=command_analyze_source)

    compare = sub.add_parser("compare", parents=[common], help="Compara dos fuentes ya analizadas.")
    compare.add_argument("--source-a", required=True, choices=SOURCE_CHOICES)
    compare.add_argument("--source-b", required=True, choices=SOURCE_CHOICES)
    compare.add_argument("--limit", type=int, default=100)
    compare.add_argument("--dpi", type=int, default=180)
    compare.add_argument("--visual", action="store_true", help="Calcula diferencia visual por campo.")
    compare.add_argument("--visual-threshold", type=float, default=0.18)
    compare.add_argument("--min-confidence", type=float, default=55)
    compare.set_defaults(func=command_compare)

    report = sub.add_parser("report", parents=[common], help="Exporta CSVs de comparacion.")
    report.set_defaults(func=command_report)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.db = args.db.resolve()
    args.config = args.config.resolve()
    args.out = args.out.resolve()
    if hasattr(args, "root"):
        if args.root is None:
            args.root = DEFAULT_SOURCE_ROOTS[args.source]
        args.root = args.root.resolve()
    if hasattr(args, "digit_model"):
        args.digit_model = args.digit_model.resolve()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
