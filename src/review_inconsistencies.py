from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import mimetypes
import sqlite3
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INCONSISTENCIES = ROOT / "reports" / "ocr" / "inconsistencias.csv"
DEFAULT_SUMMARY = ROOT / "reports" / "ocr" / "resumen.csv"
DEFAULT_FIELDS = ROOT / "reports" / "ocr" / "campos.csv"
DEFAULT_REVIEWS = ROOT / "reports" / "ocr" / "revision_inconsistencias.csv"
DEFAULT_FRAUDS = ROOT / "reports" / "ocr" / "fraude_reportado.csv"
DEFAULT_DOWNLOADS = ROOT / "downloads" / "E14" / "claveros"
DEFAULT_SOURCE_DB = ROOT / "state" / "e14.sqlite"
DEFAULT_SOURCE_DOWNLOADS = ROOT / "downloads" / "E14"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8010


HTML = r"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Revisor de inconsistencias E14</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --panel-2: #eef3f7;
      --ink: #17202a;
      --muted: #5f6b7a;
      --line: #d6dde5;
      --accent: #0b6bcb;
      --accent-ink: #ffffff;
      --danger: #b42318;
      --warning: #986400;
      --ok: #177245;
      --shadow: 0 1px 2px rgba(18, 31, 45, 0.08);
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--ink);
      letter-spacing: 0;
      overflow: hidden;
    }
    header {
      height: 58px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 0 16px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      box-shadow: var(--shadow);
    }
    h1 {
      margin: 0;
      font-size: 18px;
      line-height: 1.2;
      font-weight: 700;
      white-space: nowrap;
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }
    .nav-link {
      min-height: 34px;
      display: inline-flex;
      align-items: center;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--accent);
      font-size: 13px;
      font-weight: 700;
      text-decoration: none;
      white-space: nowrap;
    }
    .counter {
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }
    main {
      height: calc(100vh - 58px);
      display: grid;
      grid-template-columns: minmax(360px, 39vw) minmax(0, 1fr);
      min-width: 0;
    }
    aside {
      min-width: 0;
      overflow: auto;
      border-right: 1px solid var(--line);
      background: var(--panel);
    }
    .detail-scroll {
      padding: 14px;
      display: grid;
      gap: 12px;
    }
    .pdf-panel {
      min-width: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      background: #e9edf2;
    }
    .pdf-toolbar {
      min-width: 0;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    .pdf-path {
      min-width: 0;
      color: var(--muted);
      font-size: 13px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .pdf-frame {
      width: 100%;
      height: 100%;
      border: 0;
      background: #f9fafb;
    }
    .pdf-empty {
      display: grid;
      place-items: center;
      height: 100%;
      padding: 24px;
      color: var(--muted);
      text-align: center;
      font-size: 15px;
    }
    .toolbar {
      display: grid;
      gap: 10px;
      padding: 14px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfd;
    }
    .filters {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    label {
      display: block;
      margin: 0 0 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    input, select, textarea {
      width: 100%;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 6px;
      font: inherit;
      font-size: 14px;
    }
    input, select {
      height: 36px;
      padding: 0 9px;
    }
    textarea {
      min-height: 70px;
      max-height: 170px;
      resize: vertical;
      padding: 9px;
      line-height: 1.35;
    }
    button, a.button {
      height: 36px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      padding: 0 11px;
      border-radius: 6px;
      font-size: 14px;
      font-weight: 700;
      text-decoration: none;
      cursor: pointer;
      white-space: nowrap;
    }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: var(--accent-ink);
    }
    button.ok {
      background: #e8f5ef;
      border-color: #b8decf;
      color: var(--ok);
    }
    button.danger {
      color: var(--danger);
    }
    button:disabled, a.button.disabled {
      opacity: 0.45;
      cursor: not-allowed;
      pointer-events: none;
    }
    .nav {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .nav .wide { grid-column: 1 / -1; }
    .jump {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
    }
    .block {
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--panel);
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .block-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfd;
    }
    .block-title h2 {
      margin: 0;
      font-size: 15px;
      line-height: 1.25;
    }
    .block-body {
      padding: 12px;
      display: grid;
      gap: 10px;
    }
    .message {
      font-size: 18px;
      line-height: 1.25;
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .badge-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
    }
    .badge {
      min-height: 24px;
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--panel-2);
      color: var(--ink);
      padding: 3px 8px;
      font-size: 12px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .badge.error { color: var(--danger); background: #fff1f0; border-color: #f1c5c1; }
    .badge.warning { color: var(--warning); background: #fff6df; border-color: #ead7a1; }
    .badge.ok { color: var(--ok); background: #e8f5ef; border-color: #b8decf; }
    .kv {
      display: grid;
      grid-template-columns: minmax(110px, 0.38fr) minmax(0, 1fr);
      gap: 7px 10px;
      font-size: 13px;
      line-height: 1.35;
    }
    .kv dt {
      color: var(--muted);
      font-weight: 700;
    }
    .kv dd {
      margin: 0;
      min-width: 0;
      overflow-wrap: anywhere;
    }
    pre {
      margin: 0;
      padding: 10px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #f8fafc;
      font-size: 12px;
      line-height: 1.4;
      white-space: pre-wrap;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 13px;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 7px 6px;
      text-align: left;
      vertical-align: middle;
      overflow-wrap: anywhere;
    }
    th {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      background: #fbfcfd;
    }
    tr:last-child td { border-bottom: 0; }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    tr.difference-row td {
      border-top: 2px solid var(--line);
      background: #fff8e6;
      font-weight: 700;
    }
    .thumb {
      width: 78px;
      max-height: 44px;
      object-fit: contain;
      display: block;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 4px;
    }
    .field-table th:nth-child(1) { width: 34%; }
    .field-table th:nth-child(2) { width: 15%; }
    .field-table th:nth-child(3) { width: 15%; }
    .field-table th:nth-child(4) { width: 16%; }
    .field-table th:nth-child(5) { width: 20%; }
    .related-item {
      width: 100%;
      display: grid;
      gap: 4px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px;
      background: #fff;
      text-align: left;
      cursor: pointer;
    }
    .related-item.current {
      border-color: var(--accent);
      box-shadow: inset 3px 0 0 var(--accent);
    }
    .related-title {
      font-weight: 700;
      font-size: 13px;
      line-height: 1.3;
      overflow-wrap: anywhere;
    }
    .related-meta {
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .status-line {
      min-height: 18px;
      color: var(--muted);
      font-size: 13px;
    }
    .empty {
      color: var(--muted);
      font-size: 14px;
      line-height: 1.4;
    }
    @media (max-width: 980px) {
      body { overflow: auto; }
      header { position: sticky; top: 0; z-index: 2; }
      main {
        height: auto;
        grid-template-columns: 1fr;
      }
      aside {
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }
      .pdf-panel {
        height: 76vh;
      }
    }
    @media (max-width: 620px) {
      header { align-items: flex-start; height: auto; padding: 10px 12px; flex-direction: column; }
      .header-actions { width: 100%; justify-content: space-between; }
      .filters { grid-template-columns: 1fr; }
      .kv { grid-template-columns: 1fr; }
      .pdf-toolbar { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Revisor de inconsistencias E14</h1>
    <div class="header-actions">
      <a class="nav-link" href="/">Mesas</a>
      <div class="counter" id="globalCounter">Cargando</div>
      <button id="reloadBtn">Actualizar</button>
    </div>
  </header>
  <main>
    <aside>
      <div class="toolbar">
        <div class="filters">
          <div>
            <label for="statusFilter">Estado</label>
            <select id="statusFilter">
              <option value="pending">Pendientes</option>
              <option value="all">Todos</option>
              <option value="reviewed">Revisados</option>
              <option value="fraud">Fraude</option>
            </select>
          </div>
          <div>
            <label for="codeFilter">Tipo de inconsistencia</label>
            <select id="codeFilter"></select>
          </div>
          <div>
            <label for="severityFilter">Severidad</label>
            <select id="severityFilter"></select>
          </div>
          <div>
            <label for="candidateFilter">Candidatos</label>
            <select id="candidateFilter">
              <option value="all">Todos</option>
              <option value="c1_gt_c2">Candidato 1 &gt; Candidato 2</option>
              <option value="c1_lt_c2">Candidato 1 &lt; Candidato 2</option>
            </select>
          </div>
          <div>
            <label for="fullVoteFilter">100% votos</label>
            <select id="fullVoteFilter">
              <option value="all">Todos</option>
              <option value="any">Cualquier candidato con 100%</option>
              <option value="candidato_1">Candidato 1 con 100%</option>
              <option value="candidato_2">Candidato 2 con 100%</option>
            </select>
          </div>
          <div>
            <label for="sortField">Ordenar por campo</label>
            <select id="sortField"></select>
          </div>
          <div>
            <label for="sortDirection">Orden</label>
            <select id="sortDirection">
              <option value="desc">Mayor a menor</option>
              <option value="asc">Menor a mayor</option>
            </select>
          </div>
          <div>
            <label for="jumpInput">Ir a</label>
            <div class="jump">
              <input id="jumpInput" inputmode="numeric" autocomplete="off">
              <button id="jumpBtn">Ir</button>
            </div>
          </div>
        </div>
        <div>
          <label for="searchInput">Buscar</label>
          <input id="searchInput" autocomplete="off" placeholder="Mesa, puesto, mensaje, ruta">
        </div>
        <div class="nav">
          <button id="prevBtn">Anterior</button>
          <button id="nextBtn">Siguiente</button>
          <button id="randomBtn" class="wide">Aleatorio: OFF</button>
          <button id="fraudBtn" class="danger wide">Reportar fraude</button>
          <button id="reviewBtn" class="ok wide">Marcar revisada</button>
        </div>
        <div class="status-line" id="statusLine"></div>
      </div>
      <div class="detail-scroll">
        <section class="block">
          <div class="block-title">
            <h2>Inconsistencia</h2>
            <span class="badge" id="positionBadge">0 de 0</span>
          </div>
          <div class="block-body">
            <div class="badge-row" id="badges"></div>
            <div class="message" id="messageText"></div>
            <dl class="kv" id="mainMeta"></dl>
            <pre id="detailsJson"></pre>
          </div>
        </section>

        <section class="block">
          <div class="block-title">
            <h2>Campos OCR</h2>
          </div>
          <div class="block-body" id="fieldsBlock"></div>
        </section>

        <section class="block">
          <div class="block-title">
            <h2>Resumen OCR</h2>
          </div>
          <div class="block-body" id="summaryBlock"></div>
        </section>

        <section class="block">
          <div class="block-title">
            <h2>Otras inconsistencias de la mesa</h2>
          </div>
          <div class="block-body" id="relatedBlock"></div>
        </section>

        <section class="block">
          <div class="block-title">
            <h2>Nota de revision</h2>
          </div>
          <div class="block-body">
            <textarea id="noteInput"></textarea>
            <div class="nav">
              <button id="saveNoteBtn" class="primary">Guardar nota</button>
              <button id="pendingBtn" class="danger">Dejar pendiente</button>
            </div>
          </div>
        </section>
      </div>
    </aside>

    <section class="pdf-panel">
      <div class="pdf-toolbar">
        <div class="pdf-path" id="pdfPath"></div>
        <a class="button" id="openPdf" target="_blank" rel="noopener">Abrir PDF</a>
      </div>
      <div id="pdfStage"></div>
    </section>
  </main>

  <script>
    const state = {
      rows: [],
      documents: {},
      documentRequests: {},
      metrics: {},
      reviews: {},
      frauds: {},
      filtered: [],
      current: 0,
      randomNext: localStorage.getItem("randomNext") === "1",
      sortField: localStorage.getItem("sortField") || "none",
      sortDirection: localStorage.getItem("sortDirection") || "desc"
    };
    if (state.randomNext) {
      state.sortField = "none";
      localStorage.setItem("sortField", "none");
    }

    const $ = (id) => document.getElementById(id);

    const CODE_LABELS = {
      INCINERATED_NON_ZERO: "Votos incinerados mayores que cero",
      LOW_CONFIDENCE: "Baja confianza en lectura OCR",
      LOW_SIGNATURE_COUNT: "Menos de 2 firmas de jurados",
      MISSING_FIELD: "Campo obligatorio no leido",
      MISSING_PAGE: "Falta pagina requerida del PDF",
      MISSING_PDF: "PDF no encontrado",
      MISSING_SIGNATURE_PAGE: "No se pudo revisar firmas: falta pagina",
      SUM_MISMATCH: "Suma de votos no coincide con total declarado",
      URNA_GT_E11: "Total urna mayor que votantes E-11",
      URNA_TOTAL_MISMATCH: "Total urna distinto a suma total"
    };

    function codeLabel(code) {
      return CODE_LABELS[code] ? `${CODE_LABELS[code]} (${code})` : code;
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      })[ch]);
    }

    function api(path, options) {
      return fetch(path, options).then(async (response) => {
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || response.statusText);
        }
        return response.json();
      });
    }

    function reviewFor(row) {
      return state.reviews[row.review_key] || {};
    }

    function isReviewed(row) {
      return !!reviewFor(row).reviewed;
    }

    function fraudFor(row) {
      return state.frauds[row.relative_path] || state.frauds[documentKey(row)] || {};
    }

    function isFraud(row) {
      return fraudFor(row).status === "FRAUDE";
    }

    function pdfExists(row) {
      return !!row && row.pdf_exists !== false && row.pdf_missing !== true;
    }

    function documentKey(row) {
      return row ? (row.document_key || row.document_id || row.relative_path || "") : "";
    }

    function docFor(row) {
      return state.documents[documentKey(row)] || {summary: {}, fields: [], related_keys: []};
    }

    function hasDoc(row) {
      return !!(row && state.documents[documentKey(row)]);
    }

    function metricsFor(row) {
      return state.metrics[documentKey(row)] || {field_values: {}};
    }

    function detailsText(row) {
      return JSON.stringify(row.details || {}, null, 2);
    }

    function currentRow() {
      return state.filtered[state.current] || null;
    }

    function setStatus(text) {
      $("statusLine").textContent = text || "";
    }

    function populateSelects(payload) {
      const codeSelect = $("codeFilter");
      const severitySelect = $("severityFilter");
      const sortFieldSelect = $("sortField");
      const codes = Object.entries(payload.code_counts || {}).sort((a, b) => a[0].localeCompare(b[0]));
      const severities = Object.entries(payload.severity_counts || {}).sort((a, b) => a[0].localeCompare(b[0]));
      const fieldLabels = payload.field_labels || {};
      codeSelect.innerHTML = '<option value="all">Todos</option>' + codes.map(([code, count]) => {
        return `<option value="${escapeHtml(code)}">${escapeHtml(codeLabel(code))} (${count})</option>`;
      }).join("");
      severitySelect.innerHTML = '<option value="all">Todas</option>' + severities.map(([severity, count]) => {
        return `<option value="${escapeHtml(severity)}">${escapeHtml(severity)} (${count})</option>`;
      }).join("");
      const sortOptions = Object.entries(fieldLabels).sort((a, b) => a[1].localeCompare(b[1]));
      sortFieldSelect.innerHTML = '<option value="none">Sin ordenamiento</option>' + sortOptions.map(([key, label]) => {
        return `<option value="${escapeHtml(key)}">${escapeHtml(label)}</option>`;
      }).join("");
      if (!fieldLabels[state.sortField]) state.sortField = "none";
      sortFieldSelect.value = state.sortField;
      $("sortDirection").value = state.sortDirection;
    }

    function candidateValues(row) {
      const metrics = metricsFor(row);
      return {
        c1: firstNumber(metrics.candidato_1),
        c2: firstNumber(metrics.candidato_2)
      };
    }

    function tableTotal(row) {
      return firstNumber(metricsFor(row).table_total);
    }

    function fullVoteCandidate(row) {
      return metricsFor(row).full_vote_candidate || "";
    }

    function passesCandidateFilter(row, filter) {
      if (filter === "all") return true;
      const values = candidateValues(row);
      if (values.c1 === null || values.c2 === null) return false;
      if (filter === "c1_gt_c2") return values.c1 > values.c2;
      if (filter === "c1_lt_c2") return values.c1 < values.c2;
      return true;
    }

    function passesFullVoteFilter(row, filter) {
      if (filter === "all") return true;
      const candidate = fullVoteCandidate(row);
      if (filter === "any") return !!candidate;
      return candidate === filter;
    }

    function sortValue(row, fieldKey) {
      if (fieldKey === "none") return null;
      const values = metricsFor(row).field_values || {};
      return firstNumber(values[fieldKey]);
    }

    function applySorting(rows) {
      if (state.randomNext || state.sortField === "none") return rows;
      const direction = state.sortDirection === "asc" ? 1 : -1;
      return [...rows].sort((left, right) => {
        const leftValue = sortValue(left, state.sortField);
        const rightValue = sortValue(right, state.sortField);
        if (leftValue === null && rightValue === null) return left.row_number - right.row_number;
        if (leftValue === null) return 1;
        if (rightValue === null) return -1;
        if (leftValue === rightValue) return left.row_number - right.row_number;
        return leftValue > rightValue ? direction : -direction;
      });
    }

    function applyFilters(keepKey = null) {
      const status = $("statusFilter").value;
      const code = $("codeFilter").value;
      const severity = $("severityFilter").value;
      const candidateFilter = $("candidateFilter").value;
      const fullVoteFilter = $("fullVoteFilter").value;
      const search = $("searchInput").value.trim().toLowerCase();
      const filtered = state.rows.filter((row) => {
        if (status === "pending" && (isReviewed(row) || isFraud(row))) return false;
        if (status === "reviewed" && !isReviewed(row)) return false;
        if (status === "fraud" && !isFraud(row)) return false;
        if (code !== "all" && row.code !== code) return false;
        if (severity !== "all" && row.severity !== severity) return false;
        if (!passesCandidateFilter(row, candidateFilter)) return false;
        if (!passesFullVoteFilter(row, fullVoteFilter)) return false;
        if (search) {
          const fullVote = fullVoteCandidate(row);
          const metrics = metricsFor(row);
          const haystack = [
            row.message,
            row.code,
            codeLabel(row.code),
            row.severity,
            row.relative_path,
            row.department_name,
            row.municipality_name,
            row.place_name,
            row.table_number,
            fullVote ? `100% ${fullVote}` : "",
            JSON.stringify(row.details || {}),
            metrics.summary_search || ""
          ].join(" ").toLowerCase();
          if (!haystack.includes(search)) return false;
        }
        return true;
      });
      state.filtered = applySorting(filtered);
      if (keepKey) {
        const index = state.filtered.findIndex((row) => row.review_key === keepKey);
        state.current = index >= 0 ? index : Math.min(state.current, Math.max(0, state.filtered.length - 1));
      } else {
        state.current = Math.min(state.current, Math.max(0, state.filtered.length - 1));
      }
      render();
    }

    function renderCounters() {
      const total = state.rows.length;
      const reviewed = state.rows.filter(isReviewed).length;
      const fraud = Object.keys(state.frauds).length;
      const pending = state.rows.filter((row) => !isReviewed(row) && !isFraud(row)).length;
      $("globalCounter").textContent = `${state.filtered.length} visibles | ${pending} pendientes | ${reviewed}/${total} revisados | ${fraud} fraude`;
    }

    function renderRandomToggle() {
      $("randomBtn").textContent = state.randomNext ? "Aleatorio: ON" : "Aleatorio: OFF";
      $("randomBtn").classList.toggle("primary", state.randomNext);
      $("randomBtn").disabled = !state.randomNext && state.sortField !== "none";
    }

    function renderSortControls() {
      $("sortField").value = state.sortField;
      $("sortDirection").value = state.sortDirection;
      $("sortField").disabled = state.randomNext;
      $("sortDirection").disabled = state.randomNext || state.sortField === "none";
    }

    function renderBadges(row) {
      const reviewed = isReviewed(row);
      const severityClass = row.severity === "error" ? "error" : (row.severity === "warning" ? "warning" : "");
      const fullVote = fullVoteCandidate(row);
      const fullVoteText = fullVote === "candidato_1" ? "100% Candidato 1" : (fullVote === "candidato_2" ? "100% Candidato 2" : "");
      $("badges").innerHTML = [
        `<span class="badge ${severityClass}">${escapeHtml(row.severity || "sin severidad")}</span>`,
        `<span class="badge">${escapeHtml(row.code || "sin codigo")}</span>`,
        `<span class="badge ${reviewed ? "ok" : "warning"}">${reviewed ? "Revisada" : "Pendiente"}</span>`,
        fullVoteText ? `<span class="badge warning">${escapeHtml(fullVoteText)}</span>` : "",
        isFraud(row) ? '<span class="badge error">FRAUDE</span>' : "",
        pdfExists(row) ? '<span class="badge ok">PDF disponible</span>' : '<span class="badge error">PDF no encontrado</span>'
      ].filter(Boolean).join("");
    }

    function kvRows(items) {
      return items.map(([label, value]) => {
        return `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value || "")}</dd>`;
      }).join("");
    }

    function renderMainMeta(row) {
      $("mainMeta").innerHTML = kvRows([
        ["Documento", row.document_id],
        ["Departamento", row.department_name],
        ["Municipio", row.municipality_name],
        ["Zona", row.zone_code],
        ["Puesto", row.place_name],
        ["Mesa", row.table_number],
        ["Creado", row.created_at || docFor(row).created_at],
        ["Ruta", row.relative_path]
      ]);
    }

    function renderSummary(row) {
      if (!hasDoc(row)) {
        $("summaryBlock").innerHTML = '<div class="empty">Cargando detalle OCR...</div>';
        return;
      }
      const doc = docFor(row);
      const summary = doc.summary || {};
      const keys = [
        ["Estado", "status"],
        ["Candidatos", "candidate_total"],
        ["Blancos", "blank_votes"],
        ["Nulos", "null_votes"],
        ["No marcados", "unmarked_votes"],
        ["Suma total", "declared_total"],
        ["Urna", "urna_total"],
        ["E-11", "e11_total"],
        ["Incinerados", "incinerated_total"],
        ["Jurados firmantes", "signed_juror_count"],
        ["Intentos", "attempts"],
        ["Analizado", "analyzed_at"]
      ];
      const rows = keys
        .filter(([, key]) => summary[key] !== undefined && summary[key] !== "")
        .map(([label, key]) => `<tr><th>${escapeHtml(label)}</th><td>${escapeHtml(summary[key])}</td></tr>`)
        .join("");
      $("summaryBlock").innerHTML = rows
        ? `<table><tbody>${rows}</tbody></table>`
        : '<div class="empty">No hay resumen para este documento.</div>';
    }

    function confidenceText(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return value || "";
      return `${number.toFixed(1)}%`;
    }

    function numberOrNull(value) {
      if (value === undefined || value === null) return null;
      const text = String(value).trim();
      if (!text) return null;
      const number = Number(text.replace(",", "."));
      return Number.isFinite(number) ? number : null;
    }

    function formatNumber(value) {
      if (value === undefined || value === null) return "";
      const number = Number(value);
      if (!Number.isFinite(number)) return String(value);
      return Number.isInteger(number) ? String(number) : number.toFixed(2);
    }

    function firstNumber(...values) {
      for (const value of values) {
        const number = numberOrNull(value);
        if (number !== null) return number;
      }
      return null;
    }

    function fieldNumber(fields, fieldKey) {
      const field = fields.find((item) => item.field_key === fieldKey);
      return firstNumber(field && field.normalized_value);
    }

    function candidateTotalFromFields(fields) {
      const candidates = fields.filter((field) => {
        return field.field_role === "candidate_vote" || String(field.field_key || "").startsWith("candidato_");
      });
      if (!candidates.length) return null;
      const values = candidates.map((field) => numberOrNull(field.normalized_value));
      if (values.some((value) => value === null)) return null;
      return values.reduce((sum, value) => sum + value, 0);
    }

    function addValues(values) {
      if (values.some((value) => value === null || value === undefined)) return null;
      return values.reduce((sum, value) => sum + value, 0);
    }

    function differenceRow(row, fields, summary) {
      const details = row.details || {};
      const candidateTotal = firstNumber(
        candidateTotalFromFields(fields),
        summary.candidate_total,
        details.candidate_total
      );
      const blankVotes = firstNumber(fieldNumber(fields, "votos_blanco"), summary.blank_votes, details.blank_votes);
      const nullVotes = firstNumber(fieldNumber(fields, "votos_nulos"), summary.null_votes, details.null_votes);
      const unmarkedVotes = firstNumber(fieldNumber(fields, "votos_no_marcados"), summary.unmarked_votes, details.unmarked_votes);
      const declaredTotal = firstNumber(fieldNumber(fields, "suma_total"), summary.declared_total, details.declared_total);
      const urnaTotal = firstNumber(fieldNumber(fields, "total_votos_urna"), summary.urna_total, details.urna_total);
      const e11Total = firstNumber(fieldNumber(fields, "total_votantes_e11"), summary.e11_total, details.e11_total);
      const computedFromDetails = firstNumber(details.computed_total);
      const computedTotal = firstNumber(
        addValues([candidateTotal, blankVotes, nullVotes, unmarkedVotes]),
        computedFromDetails
      );

      let left = null;
      let right = null;
      let formula = "";
      if (row.code === "URNA_TOTAL_MISMATCH") {
        left = urnaTotal;
        right = declaredTotal;
        formula = `${formatNumber(left)} - ${formatNumber(right)}`;
      } else if (row.code === "URNA_GT_E11") {
        left = urnaTotal;
        right = e11Total;
        formula = `${formatNumber(left)} - ${formatNumber(right)}`;
      } else {
        left = computedTotal;
        right = declaredTotal;
        if (left !== null && right !== null) {
          formula = candidateTotal !== null && blankVotes !== null && nullVotes !== null && unmarkedVotes !== null
            ? `${formatNumber(candidateTotal)} + ${formatNumber(blankVotes)} + ${formatNumber(nullVotes)} + ${formatNumber(unmarkedVotes)} - ${formatNumber(right)}`
            : `${formatNumber(left)} - ${formatNumber(right)}`;
        }
      }

      if (left === null || right === null) return null;
      return {
        field_label: "DIFERENCIA",
        raw_text: formula,
        normalized_value: formatNumber(left - right),
        confidence: "",
        crop_path: "",
        synthetic: true
      };
    }

    function renderFields(row) {
      if (!hasDoc(row)) {
        $("fieldsBlock").innerHTML = '<div class="empty">Cargando detalle OCR...</div>';
        return;
      }
      const doc = docFor(row);
      const fields = doc.fields || [];
      const summary = doc.summary || {};
      if (!fields.length) {
        $("fieldsBlock").innerHTML = '<div class="empty">No hay campos OCR para este documento.</div>';
        return;
      }
      const calculatedDifference = differenceRow(row, fields, summary);
      const displayFields = calculatedDifference ? [...fields, calculatedDifference] : fields;
      const rows = displayFields.map((field) => {
        const thumb = field.crop_path
          ? `<img class="thumb" alt="" src="/file?path=${encodeURIComponent(field.crop_path)}">`
          : "";
        const rowClass = field.synthetic ? ' class="difference-row"' : "";
        return `<tr${rowClass}>
          <td>${escapeHtml(field.field_label || field.field_key)}</td>
          <td class="num">${escapeHtml(field.raw_text)}</td>
          <td class="num">${escapeHtml(field.normalized_value)}</td>
          <td class="num">${escapeHtml(confidenceText(field.confidence))}</td>
          <td>${thumb}</td>
        </tr>`;
      }).join("");
      $("fieldsBlock").innerHTML = `<table class="field-table">
        <thead><tr><th>Campo</th><th>Crudo</th><th>Valor</th><th>Conf.</th><th>Recorte</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    }

    function renderRelated(row) {
      if (!hasDoc(row)) {
        $("relatedBlock").innerHTML = '<div class="empty">Cargando inconsistencias relacionadas...</div>';
        return;
      }
      const doc = docFor(row);
      const relatedRows = (doc.related_keys || [])
        .map((key) => state.rows.find((item) => item.review_key === key))
        .filter(Boolean);
      if (!relatedRows.length) {
        $("relatedBlock").innerHTML = '<div class="empty">No hay otras inconsistencias en esta mesa.</div>';
        return;
      }
      $("relatedBlock").innerHTML = relatedRows.map((item) => {
        const current = item.review_key === row.review_key ? " current" : "";
        return `<button class="related-item${current}" data-key="${escapeHtml(item.review_key)}">
          <span class="related-title">${escapeHtml(item.code)} · ${escapeHtml(item.message)}</span>
          <span class="related-meta">${isReviewed(item) ? "Revisada" : "Pendiente"} · fila ${item.row_number}</span>
        </button>`;
      }).join("");
      document.querySelectorAll(".related-item").forEach((button) => {
        button.addEventListener("click", () => {
          const key = button.getAttribute("data-key");
          const index = state.filtered.findIndex((item) => item.review_key === key);
          if (index >= 0) {
            state.current = index;
          } else {
            $("statusFilter").value = "all";
            applyFilters(key);
            return;
          }
          render();
        });
      });
    }

    function renderDocumentPanels(row) {
      renderSummary(row);
      renderFields(row);
      renderRelated(row);
      ensureDocument(row);
    }

    function ensureDocument(row) {
      const key = documentKey(row);
      if (!key || state.documents[key] || state.documentRequests[key]) return;
      state.documentRequests[key] = api(`/document?key=${encodeURIComponent(key)}`)
        .then((document) => {
          state.documents[key] = document || {summary: {}, fields: [], related_keys: []};
          delete state.documentRequests[key];
          const current = currentRow();
          if (!current || documentKey(current) !== key) return;
          if (document && document.absolute_pdf_path) {
            $("pdfPath").textContent = document.absolute_pdf_path;
          }
          renderMainMeta(current);
          renderSummary(current);
          renderFields(current);
          renderRelated(current);
        })
        .catch((error) => {
          delete state.documentRequests[key];
          const current = currentRow();
          if (!current || documentKey(current) !== key) return;
          $("summaryBlock").innerHTML = '<div class="empty">No se pudo cargar el resumen OCR.</div>';
          $("fieldsBlock").innerHTML = '<div class="empty">No se pudo cargar Campos OCR.</div>';
          $("relatedBlock").innerHTML = "";
          setStatus(error.message);
        });
    }

    function renderPdf(row) {
      const pdfUrl = `/pdf?path=${encodeURIComponent(row.relative_path)}`;
      $("pdfPath").textContent = row.absolute_pdf_path || row.relative_path || "";
      $("openPdf").href = pdfUrl;
      $("openPdf").classList.toggle("disabled", !pdfExists(row));
      if (!pdfExists(row)) {
        $("pdfStage").innerHTML = '<div class="pdf-empty">No encontre el PDF en el disco para esta ruta.</div>';
        return;
      }
      $("pdfStage").innerHTML = `<iframe class="pdf-frame" id="pdfFrame" title="PDF E14" src="${pdfUrl}"></iframe>`;
    }

    function render() {
      renderCounters();
      renderRandomToggle();
      renderSortControls();
      const row = currentRow();
      if (!row) {
        $("positionBadge").textContent = "0 de 0";
        $("messageText").textContent = "Sin resultados";
        $("badges").innerHTML = "";
        $("mainMeta").innerHTML = "";
        $("detailsJson").textContent = "";
        $("summaryBlock").innerHTML = '<div class="empty">No hay elementos con los filtros actuales.</div>';
        $("fieldsBlock").innerHTML = "";
        $("relatedBlock").innerHTML = "";
        $("noteInput").value = "";
        $("pdfPath").textContent = "";
        $("openPdf").href = "#";
        $("openPdf").classList.add("disabled");
        $("pdfStage").innerHTML = '<div class="pdf-empty">Seleccione una inconsistencia.</div>';
        $("prevBtn").disabled = true;
        $("nextBtn").disabled = true;
        $("fraudBtn").disabled = true;
        $("fraudBtn").classList.remove("primary");
        $("fraudBtn").textContent = "Reportar fraude";
        $("reviewBtn").disabled = true;
        $("pendingBtn").disabled = true;
        $("saveNoteBtn").disabled = true;
        return;
      }

      const review = reviewFor(row);
      $("positionBadge").textContent = `${state.current + 1} de ${state.filtered.length}`;
      $("messageText").textContent = row.message || "";
      $("detailsJson").textContent = detailsText(row);
      $("jumpInput").value = state.current + 1;
      $("noteInput").value = review.note || "";
      $("reviewBtn").textContent = isReviewed(row) ? "Revisada" : "Marcar revisada";
      $("fraudBtn").textContent = isFraud(row) ? "Quitar FRAUDE" : "Reportar fraude";
      $("fraudBtn").classList.toggle("primary", isFraud(row));
      $("reviewBtn").disabled = false;
      $("fraudBtn").disabled = false;
      $("pendingBtn").disabled = false;
      $("saveNoteBtn").disabled = false;
      $("prevBtn").disabled = state.current <= 0;
      $("nextBtn").disabled = state.randomNext ? state.filtered.length <= 1 : state.current >= state.filtered.length - 1;

      renderBadges(row);
      renderMainMeta(row);
      renderPdf(row);
      renderDocumentPanels(row);
    }

    function randomIndex(excludeIndex = state.current) {
      if (!state.filtered.length) return 0;
      if (state.filtered.length === 1) return 0;
      const indexes = state.filtered
        .map((_, index) => index)
        .filter((index) => index !== excludeIndex);
      return indexes[Math.floor(Math.random() * indexes.length)] || 0;
    }

    function nextItem() {
      if (state.randomNext) {
        state.current = randomIndex();
        render();
        return;
      }
      if (state.current < state.filtered.length - 1) {
        state.current += 1;
        render();
      }
    }

    function prevItem() {
      if (state.current > 0) {
        state.current -= 1;
        render();
      }
    }

    async function setReviewed(reviewed, moveNext = false) {
      const row = currentRow();
      if (!row) return;
      const note = $("noteInput").value;
      const result = await api("/review", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({key: row.review_key, reviewed, note})
      });
      state.reviews = result.reviews;
      setStatus(reviewed ? "Revision guardada" : "Quedo pendiente");
      const key = row.review_key;
      applyFilters(key);
      if (moveNext && state.randomNext && state.filtered.length) {
        state.current = randomIndex(-1);
        render();
        return;
      }
      if (moveNext && state.filtered[state.current] && state.filtered[state.current].review_key === key) {
        nextItem();
      }
    }

    async function setFraud(fraud) {
      const row = currentRow();
      if (!row) return;
      const result = await api("/fraud", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          fraud,
          note: $("noteInput").value,
          document_key: documentKey(row),
          document_id: row.document_id,
          relative_path: row.relative_path,
          absolute_pdf_path: docFor(row).absolute_pdf_path || row.absolute_pdf_path || "",
          department_name: row.department_name,
          municipality_name: row.municipality_name,
          zone_code: row.zone_code,
          place_name: row.place_name,
          table_number: row.table_number,
          reported_from_code: row.code,
          reported_from_message: row.message
        })
      });
      state.frauds = result.frauds;
      setStatus(fraud ? "PDF marcado con estado FRAUDE" : "Marca de fraude removida");
      applyFilters(row.review_key);
    }

    async function loadData(keepKey = null, refresh = false) {
      setStatus("Cargando datos");
      const dataPath = refresh ? "/data?refresh=1" : "/data";
      const [payload, status] = await Promise.all([api(dataPath), api("/status")]);
      state.rows = payload.rows || [];
      state.documents = {};
      state.documentRequests = {};
      state.metrics = payload.metrics || {};
      state.reviews = status.reviews || {};
      state.frauds = status.frauds || {};
      populateSelects(payload);
      applyFilters(keepKey);
      setStatus(`CSV: ${payload.source || ""}`);
    }

    $("prevBtn").addEventListener("click", prevItem);
    $("nextBtn").addEventListener("click", nextItem);
    $("randomBtn").addEventListener("click", () => {
      if (!state.randomNext && state.sortField !== "none") return;
      state.randomNext = !state.randomNext;
      if (state.randomNext) {
        state.sortField = "none";
        localStorage.setItem("sortField", "none");
      }
      localStorage.setItem("randomNext", state.randomNext ? "1" : "0");
      applyFilters(currentRow() ? currentRow().review_key : null);
    });
    $("jumpBtn").addEventListener("click", () => {
      const target = Math.max(1, Number($("jumpInput").value || 1));
      state.current = Math.min(target - 1, Math.max(0, state.filtered.length - 1));
      render();
    });
    $("reviewBtn").addEventListener("click", () => setReviewed(true, true).catch((error) => setStatus(error.message)));
    $("fraudBtn").addEventListener("click", () => {
      const row = currentRow();
      if (!row) return;
      setFraud(!isFraud(row)).catch((error) => setStatus(error.message));
    });
    $("pendingBtn").addEventListener("click", () => setReviewed(false, false).catch((error) => setStatus(error.message)));
    $("saveNoteBtn").addEventListener("click", () => {
      const row = currentRow();
      if (!row) return;
      setReviewed(isReviewed(row), false).catch((error) => setStatus(error.message));
    });
    $("reloadBtn").addEventListener("click", () => {
      const row = currentRow();
      loadData(row ? row.review_key : null, true).catch((error) => setStatus(error.message));
    });
    $("statusFilter").addEventListener("change", () => applyFilters());
    $("codeFilter").addEventListener("change", () => applyFilters());
    $("severityFilter").addEventListener("change", () => applyFilters());
    $("candidateFilter").addEventListener("change", () => applyFilters());
    $("fullVoteFilter").addEventListener("change", () => applyFilters());
    $("sortField").addEventListener("change", (event) => {
      const row = currentRow();
      state.sortField = event.target.value;
      if (state.sortField !== "none") {
        state.randomNext = false;
        localStorage.setItem("randomNext", "0");
      }
      localStorage.setItem("sortField", state.sortField);
      applyFilters(row ? row.review_key : null);
    });
    $("sortDirection").addEventListener("change", (event) => {
      const row = currentRow();
      state.sortDirection = event.target.value;
      localStorage.setItem("sortDirection", state.sortDirection);
      applyFilters(row ? row.review_key : null);
    });
    $("searchInput").addEventListener("input", () => applyFilters());
    document.addEventListener("keydown", (event) => {
      const tag = event.target && event.target.tagName ? event.target.tagName.toLowerCase() : "";
      if (["input", "select", "textarea"].includes(tag)) return;
      if (event.key === "ArrowRight") nextItem();
      if (event.key === "ArrowLeft") prevItem();
      if (event.key.toLowerCase() === "r") setReviewed(true, true).catch((error) => setStatus(error.message));
    });

    loadData().catch((error) => {
      $("globalCounter").textContent = "Error";
      setStatus(error.message);
    });
  </script>
</body>
</html>
"""


COMPARISON_HTML = r"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Comparador de fuentes E14</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fa;
      --panel: #ffffff;
      --panel-2: #eef3f7;
      --ink: #17202a;
      --muted: #657182;
      --line: #d7dfe8;
      --accent: #075e9f;
      --accent-ink: #ffffff;
      --danger: #b42318;
      --warning: #986400;
      --ok: #177245;
      --soft-warning: #fff6df;
      --soft-danger: #fff0ee;
      --shadow: 0 1px 2px rgba(18, 31, 45, 0.08);
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--ink);
      overflow: hidden;
    }
    header {
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 0 16px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      box-shadow: var(--shadow);
    }
    h1 { margin: 0; font-size: 18px; line-height: 1.2; }
    button, select, input {
      font: inherit;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
    }
    button {
      min-height: 34px;
      padding: 0 12px;
      cursor: pointer;
      font-weight: 700;
    }
    a.nav-link, button.primary {
      min-height: 34px;
      display: inline-flex;
      align-items: center;
      padding: 0 12px;
      border-radius: 6px;
      border: 1px solid var(--accent);
      background: var(--accent);
      color: var(--accent-ink);
      font-size: 13px;
      font-weight: 700;
      text-decoration: none;
    }
    select, input { height: 34px; padding: 0 10px; min-width: 0; }
    .header-actions { display: flex; align-items: center; gap: 8px; }
    .shell {
      height: calc(100% - 56px);
      display: grid;
      grid-template-columns: 340px minmax(0, 1fr);
      min-height: 0;
    }
    aside {
      min-height: 0;
      border-right: 1px solid var(--line);
      background: var(--panel);
      display: flex;
      flex-direction: column;
    }
    .filters {
      display: grid;
      grid-template-columns: 1fr;
      gap: 8px;
      padding: 12px;
      border-bottom: 1px solid var(--line);
    }
    .filter-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .filter-row.three { grid-template-columns: 1fr 1fr 1fr; }
    .section-title {
      margin-top: 4px;
      font-size: 11px;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .metric-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .metric {
      min-height: 58px;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel-2);
    }
    .metric-value {
      display: block;
      font-size: 18px;
      line-height: 1.1;
      font-weight: 700;
    }
    .metric-label {
      display: block;
      margin-top: 4px;
      color: var(--muted);
      font-size: 11px;
    }
    .download-bar {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .download-bar button {
      width: 100%;
      min-width: 0;
      padding: 0 8px;
      font-size: 12px;
    }
    .ghost {
      background: #fff;
      color: var(--accent);
      border-color: var(--line);
    }
    .counter { font-size: 12px; color: var(--muted); }
    .list { min-height: 0; overflow: auto; padding: 8px; }
    .item {
      width: 100%;
      display: block;
      text-align: left;
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 6px;
      padding: 10px;
      margin-bottom: 8px;
      color: var(--ink);
    }
    .item.active { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(7, 94, 159, 0.12); }
    .item-title { font-weight: 700; font-size: 13px; margin-bottom: 7px; word-break: break-word; }
    .badges { display: flex; flex-wrap: wrap; gap: 5px; }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      border-radius: 999px;
      padding: 0 8px;
      font-size: 12px;
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--ink);
    }
    .badge.danger { background: var(--soft-danger); color: var(--danger); border-color: #ffd2cc; }
    .badge.warning { background: var(--soft-warning); color: var(--warning); border-color: #ffe1a3; }
    .badge.ok { background: #e8f7ef; color: var(--ok); border-color: #bfebd1; }
    main {
      min-width: 0;
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) 240px;
    }
    .detail-head {
      min-height: 58px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    .detail-title { min-width: 0; }
    .mesa { font-size: 15px; font-weight: 700; word-break: break-word; }
    .paths { margin-top: 3px; color: var(--muted); font-size: 12px; }
    .detail-actions {
      display: grid;
      justify-items: end;
      gap: 7px;
      min-width: 250px;
    }
    .nav-buttons { display: flex; align-items: center; gap: 6px; }
    .nav-buttons button { min-height: 30px; padding: 0 9px; font-size: 12px; }
    .pdf-grid {
      min-height: 0;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1px;
      background: var(--line);
    }
    .pdf-pane {
      min-width: 0;
      min-height: 0;
      background: var(--panel);
      display: grid;
      grid-template-rows: 36px minmax(0, 1fr);
    }
    .pdf-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 0 10px;
      border-bottom: 1px solid var(--line);
      font-size: 13px;
      font-weight: 700;
    }
    .pdf-title a { color: var(--accent); text-decoration: none; font-size: 12px; }
    iframe { width: 100%; height: 100%; border: 0; background: #fdfdfd; }
    .fields {
      min-height: 0;
      overflow: auto;
      border-top: 1px solid var(--line);
      background: var(--panel);
    }
    .field-toolbar {
      position: sticky;
      top: 0;
      z-index: 2;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 40px;
      padding: 0 10px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      font-size: 13px;
    }
    .field-toolbar strong { white-space: nowrap; }
    .field-note {
      color: var(--muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td {
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      white-space: nowrap;
    }
    th { position: sticky; top: 40px; background: var(--panel-2); z-index: 1; }
    td.label { white-space: normal; min-width: 180px; }
    .result-text { font-weight: 700; }
    .result-text.numeric_mismatch { color: var(--danger); }
    .result-text.ocr_uncertain { color: var(--warning); }
    .mono { font-family: Consolas, "Courier New", monospace; font-size: 12px; }
    tr.numeric_mismatch { background: var(--soft-danger); }
    tr.ocr_uncertain { background: var(--soft-warning); }
    tr.missing_field { background: #f4f1ff; }
    tr.visual_mismatch { background: #eaf4ff; }
    .empty { padding: 18px; color: var(--muted); font-size: 14px; }
    @media (max-width: 1000px) {
      body { overflow: auto; }
      .shell { height: auto; min-height: calc(100vh - 56px); grid-template-columns: 1fr; }
      aside { max-height: 380px; border-right: 0; border-bottom: 1px solid var(--line); }
      main { grid-template-rows: auto 900px 260px; }
      .pdf-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Comparador de fuentes E14</h1>
    <div class="header-actions">
      <a class="nav-link" href="/">Inconsistencias</a>
      <button class="primary" id="refreshBtn">Recargar</button>
    </div>
  </header>
  <div class="shell">
    <aside>
      <div class="filters">
        <div class="metric-grid">
          <div class="metric"><span class="metric-value" id="metricVisible">0</span><span class="metric-label">visibles</span></div>
          <div class="metric"><span class="metric-value" id="metricFirm">0</span><span class="metric-label">diferencias firmes</span></div>
          <div class="metric"><span class="metric-value" id="metricOcr">0</span><span class="metric-label">OCR dudoso</span></div>
          <div class="metric"><span class="metric-value" id="metricMissing">0</span><span class="metric-label">campos faltantes</span></div>
        </div>
        <div class="section-title">Buscar</div>
        <input id="searchInput" placeholder="Mesa, codigo o fuente">
        <div class="section-title">Filtros</div>
        <div class="filter-row">
          <select id="statusFilter">
            <option value="needs_review">Con hallazgos</option>
            <option value="all">Todas</option>
            <option value="match">Sin hallazgos</option>
          </select>
          <select id="resultFilter">
            <option value="not_match">Diferencias</option>
            <option value="numeric_mismatch">Diferencia firme</option>
            <option value="ocr_uncertain">OCR dudoso</option>
            <option value="missing_field">Campo faltante</option>
            <option value="visual_mismatch">Visual</option>
            <option value="all">Todos campos</option>
          </select>
        </div>
        <div class="filter-row">
          <select id="pairFilter">
            <option value="all">Todas las fuentes</option>
          </select>
          <select id="fieldFilter">
            <option value="all">Todos los campos</option>
          </select>
        </div>
        <div class="filter-row">
          <select id="sortFilter">
            <option value="priority">Prioridad</option>
            <option value="numeric">Mas diferencias firmes</option>
            <option value="ocr">Mas OCR dudoso</option>
            <option value="missing">Mas faltantes</option>
            <option value="mesa">Mesa</option>
            <option value="updated">Actualizadas</option>
          </select>
          <button class="ghost" id="clearBtn">Limpiar</button>
        </div>
        <div class="filter-row three">
          <input id="minNumericInput" type="number" min="0" step="1" placeholder="Firmes min">
          <input id="minOcrInput" type="number" min="0" step="1" placeholder="OCR min">
          <input id="minMissingInput" type="number" min="0" step="1" placeholder="Faltantes min">
        </div>
        <div class="section-title">Reportes</div>
        <div class="download-bar">
          <button id="reportFieldsBtn">CSV hallazgos</button>
          <button id="reportSummaryBtn">CSV resumen</button>
        </div>
        <div class="counter" id="counter">Cargando...</div>
      </div>
      <div class="list" id="list"></div>
    </aside>
    <main>
      <section class="detail-head">
        <div class="detail-title">
          <div class="mesa" id="mesaTitle">Seleccione una comparacion</div>
          <div class="paths" id="pathTitle"></div>
        </div>
        <div class="detail-actions">
          <div class="nav-buttons">
            <span class="counter" id="positionCounter"></span>
            <button id="prevBtn">Anterior</button>
            <button id="nextBtn">Siguiente</button>
          </div>
          <div class="badges" id="summaryBadges"></div>
        </div>
      </section>
      <section class="pdf-grid">
        <div class="pdf-pane">
          <div class="pdf-title"><span id="sourceATitle">Fuente A</span><a id="openA" target="_blank" rel="noopener">Abrir</a></div>
          <iframe id="pdfA"></iframe>
        </div>
        <div class="pdf-pane">
          <div class="pdf-title"><span id="sourceBTitle">Fuente B</span><a id="openB" target="_blank" rel="noopener">Abrir</a></div>
          <iframe id="pdfB"></iframe>
        </div>
      </section>
      <section class="fields" id="fields"></section>
    </main>
  </div>
  <script>
    const state = { rows: [], currentId: null, detail: null, searchTimer: null };
    const $ = (id) => document.getElementById(id);
    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[char]));
    }
    function badge(text, kind = "") {
      return `<span class="badge ${kind}">${escapeHtml(text)}</span>`;
    }
    function resultLabel(value) {
      return {
        numeric_mismatch: "diferencia firme",
        ocr_uncertain: "OCR dudoso",
        missing_field: "campo faltante",
        visual_mismatch: "visual",
        match: "igual"
      }[value] || value;
    }
    function filterParams() {
      const params = new URLSearchParams({
        status: $("statusFilter").value,
        result: $("resultFilter").value,
        pair: $("pairFilter").value,
        field: $("fieldFilter").value,
        sort: $("sortFilter").value,
        q: $("searchInput").value.trim(),
      });
      const minNumeric = $("minNumericInput").value.trim();
      const minOcr = $("minOcrInput").value.trim();
      const minMissing = $("minMissingInput").value.trim();
      if (minNumeric) params.set("min_numeric", minNumeric);
      if (minOcr) params.set("min_ocr", minOcr);
      if (minMissing) params.set("min_missing", minMissing);
      return params;
    }
    async function loadRows(keepCurrent = true) {
      const params = filterParams();
      const response = await fetch(`/comparaciones/data?${params.toString()}`);
      if (!response.ok) throw new Error("No pude cargar comparaciones");
      const payload = await response.json();
      state.rows = payload.rows || [];
      populateOptions(payload.options || {});
      updateMetrics(payload);
      renderList();
      const stillThere = keepCurrent && state.rows.some((row) => row.id === state.currentId);
      if (!stillThere) state.currentId = state.rows[0]?.id || null;
      if (state.currentId) await loadDetail(state.currentId);
      else renderEmpty();
    }
    function populateOptions(options) {
      setOptions("pairFilter", options.pairs || [], "Todas las fuentes");
      setOptions("fieldFilter", options.fields || [], "Todos los campos");
    }
    function setOptions(selectId, options, defaultLabel) {
      const select = $(selectId);
      const current = select.value || "all";
      select.innerHTML = `<option value="all">${escapeHtml(defaultLabel)}</option>` + options.map((item) => (
        `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)} (${item.count})</option>`
      )).join("");
      select.value = options.some((item) => item.value === current) ? current : "all";
    }
    function updateMetrics(payload) {
      const filtered = payload.filtered || {};
      const totals = payload.totals || {};
      $("metricVisible").textContent = filtered.comparisons ?? state.rows.length;
      $("metricFirm").textContent = filtered.numeric_mismatches ?? 0;
      $("metricOcr").textContent = filtered.ocr_uncertain ?? 0;
      $("metricMissing").textContent = filtered.missing_fields ?? 0;
      $("counter").textContent = `${state.rows.length} visibles de ${totals.comparisons || 0} comparaciones`;
    }
    function renderList() {
      $("list").innerHTML = state.rows.map((row) => {
        const active = row.id === state.currentId ? " active" : "";
        return `
          <button class="item${active}" data-id="${row.id}">
            <div class="item-title">${escapeHtml(row.mesa_key)}</div>
            <div class="badges">
              ${badge(`${row.source_a} vs ${row.source_b}`)}
              ${row.numeric_mismatches ? badge(`${row.numeric_mismatches} firmes`, "danger") : ""}
              ${row.ocr_uncertain ? badge(`${row.ocr_uncertain} OCR`, "warning") : ""}
              ${row.missing_fields ? badge(`${row.missing_fields} faltantes`, "warning") : ""}
              ${!row.numeric_mismatches && !row.ocr_uncertain && !row.missing_fields ? badge("sin hallazgos", "ok") : ""}
            </div>
            <div class="counter" style="margin-top:7px">${escapeHtml(row.updated_at || "")}</div>
          </button>
        `;
      }).join("") || `<div class="empty">No hay comparaciones para este filtro.</div>`;
      document.querySelectorAll(".item").forEach((button) => {
        button.addEventListener("click", () => {
          state.currentId = Number(button.dataset.id);
          renderList();
          loadDetail(state.currentId).catch(showError);
        });
      });
    }
    async function loadDetail(id) {
      const response = await fetch(`/comparaciones/detalle?id=${encodeURIComponent(id)}`);
      if (!response.ok) throw new Error("No pude cargar el detalle");
      state.detail = await response.json();
      renderDetail();
    }
    function renderDetail() {
      const detail = state.detail;
      if (!detail) return renderEmpty();
      const c = detail.comparison;
      const a = detail.source_a;
      const b = detail.source_b;
      $("mesaTitle").textContent = c.mesa_key;
      $("pathTitle").textContent = `${a.relative_path} | ${b.relative_path}`;
      updatePosition();
      $("summaryBadges").innerHTML = [
        badge(`${c.source_a} vs ${c.source_b}`),
        c.numeric_mismatches ? badge(`${c.numeric_mismatches} firmes`, "danger") : "",
        c.ocr_uncertain ? badge(`${c.ocr_uncertain} OCR dudoso`, "warning") : "",
        c.missing_fields ? badge(`${c.missing_fields} faltantes`, "warning") : "",
        !c.numeric_mismatches && !c.ocr_uncertain && !c.missing_fields ? badge("sin hallazgos", "ok") : "",
      ].join("");
      $("sourceATitle").textContent = c.source_a;
      $("sourceBTitle").textContent = c.source_b;
      $("pdfA").src = a.pdf_url;
      $("pdfB").src = b.pdf_url;
      $("openA").href = a.pdf_url;
      $("openB").href = b.pdf_url;
      renderFields(detail.fields || []);
    }
    function updatePosition() {
      const index = state.rows.findIndex((row) => row.id === state.currentId);
      $("positionCounter").textContent = index >= 0 ? `${index + 1} / ${state.rows.length}` : "";
      $("prevBtn").disabled = index <= 0;
      $("nextBtn").disabled = index < 0 || index >= state.rows.length - 1;
    }
    function moveSelection(delta) {
      const index = state.rows.findIndex((row) => row.id === state.currentId);
      if (index < 0) return;
      const next = state.rows[index + delta];
      if (!next) return;
      state.currentId = next.id;
      renderList();
      loadDetail(state.currentId).catch(showError);
    }
    function renderFields(fields) {
      const filter = $("resultFilter").value;
      const visible = fields.filter((row) => {
        if (filter === "all") return true;
        if (filter === "not_match") return row.result !== "match";
        return row.result === filter;
      });
      if (!visible.length) {
        $("fields").innerHTML = `<div class="empty">No hay campos para este filtro.</div>`;
        return;
      }
      $("fields").innerHTML = `
        <div class="field-toolbar">
          <strong>${visible.length} campos</strong>
          <span class="field-note">${escapeHtml(fieldSummary(visible))}</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>Campo</th><th>Resultado</th><th>Valor A</th><th>Valor B</th>
              <th>Conf A</th><th>Conf B</th><th>Visual</th><th>Motivo</th>
            </tr>
          </thead>
          <tbody>
            ${visible.map((row) => `
              <tr class="${escapeHtml(row.result)}">
                <td class="label">${escapeHtml(row.field_label || row.field_key)}</td>
                <td><span class="result-text ${escapeHtml(row.result)}">${escapeHtml(resultLabel(row.result))}</span></td>
                <td class="mono">${escapeHtml(row.value_a ?? "")}</td>
                <td class="mono">${escapeHtml(row.value_b ?? "")}</td>
                <td>${formatNumber(row.confidence_a)}</td>
                <td>${formatNumber(row.confidence_b)}</td>
                <td>${formatNumber(row.visual_score)}</td>
                <td class="label">${escapeHtml(reasonText(row))}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;
    }
    function fieldSummary(rows) {
      const counts = rows.reduce((acc, row) => {
        acc[row.result] = (acc[row.result] || 0) + 1;
        return acc;
      }, {});
      return Object.entries(counts).map(([key, value]) => `${value} ${resultLabel(key)}`).join(" | ");
    }
    function reasonText(row) {
      try {
        const details = JSON.parse(row.details_json || "{}");
        if (details.reason === "numeric_mismatch_but_visual_match") return "Valores distintos, recortes visualmente parecidos";
        if (details.reason) return details.reason;
        if (details.raw_a || details.raw_b) return `raw ${details.raw_a ?? ""} vs ${details.raw_b ?? ""}`;
      } catch (_) {
        return "";
      }
      return "";
    }
    function formatNumber(value) {
      if (value === null || value === undefined || value === "") return "";
      const number = Number(value);
      if (!Number.isFinite(number)) return escapeHtml(value);
      return number.toFixed(2);
    }
    function renderEmpty() {
      $("mesaTitle").textContent = "Seleccione una comparacion";
      $("pathTitle").textContent = "";
      $("summaryBadges").innerHTML = "";
      $("positionCounter").textContent = "";
      $("prevBtn").disabled = true;
      $("nextBtn").disabled = true;
      $("pdfA").removeAttribute("src");
      $("pdfB").removeAttribute("src");
      $("openA").removeAttribute("href");
      $("openB").removeAttribute("href");
      $("fields").innerHTML = `<div class="empty">No hay detalle cargado.</div>`;
    }
    function showError(error) { $("counter").textContent = error.message || String(error); }
    function clearFilters() {
      $("searchInput").value = "";
      $("statusFilter").value = "needs_review";
      $("resultFilter").value = "not_match";
      $("pairFilter").value = "all";
      $("fieldFilter").value = "all";
      $("sortFilter").value = "priority";
      $("minNumericInput").value = "";
      $("minOcrInput").value = "";
      $("minMissingInput").value = "";
      loadRows(false).catch(showError);
    }
    function downloadReport(kind) {
      const params = filterParams();
      params.set("kind", kind);
      window.location.href = `/comparaciones/reporte?${params.toString()}`;
    }
    $("refreshBtn").addEventListener("click", () => loadRows(true).catch(showError));
    ["statusFilter", "resultFilter", "pairFilter", "fieldFilter", "sortFilter", "minNumericInput", "minOcrInput", "minMissingInput"].forEach((id) => {
      $(id).addEventListener("change", () => loadRows(false).catch(showError));
    });
    $("clearBtn").addEventListener("click", clearFilters);
    $("reportFieldsBtn").addEventListener("click", () => downloadReport("fields"));
    $("reportSummaryBtn").addEventListener("click", () => downloadReport("summary"));
    $("prevBtn").addEventListener("click", () => moveSelection(-1));
    $("nextBtn").addEventListener("click", () => moveSelection(1));
    $("searchInput").addEventListener("input", () => {
      clearTimeout(state.searchTimer);
      state.searchTimer = setTimeout(() => loadRows(false).catch(showError), 250);
    });
    document.addEventListener("keydown", (event) => {
      const tag = event.target && event.target.tagName ? event.target.tagName.toLowerCase() : "";
      if (["input", "select", "textarea"].includes(tag)) return;
      if (event.key === "ArrowRight") moveSelection(1);
      if (event.key === "ArrowLeft") moveSelection(-1);
    });
    loadRows(false).catch(showError);
  </script>
</body>
</html>
"""


MESA_REVIEW_HTML = r"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Revisor de mesas E14</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --panel-2: #edf2f7;
      --ink: #17202a;
      --muted: #5f6b7a;
      --line: #d6dde5;
      --accent: #0b6bcb;
      --accent-ink: #ffffff;
      --danger: #b42318;
      --warning: #986400;
      --ok: #177245;
      --soft-danger: #fff0ee;
      --soft-warning: #fff6df;
      --soft-ok: #e8f7ef;
      --shadow: 0 1px 2px rgba(18, 31, 45, 0.08);
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--ink);
      overflow: hidden;
      letter-spacing: 0;
    }
    header {
      height: 58px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 0 16px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      box-shadow: var(--shadow);
    }
    h1 {
      margin: 0;
      font-size: 18px;
      line-height: 1.2;
      white-space: nowrap;
    }
    button, select, input, textarea {
      font: inherit;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
    }
    button {
      min-height: 34px;
      padding: 0 12px;
      font-weight: 700;
      cursor: pointer;
    }
    button:disabled { opacity: 0.48; cursor: default; }
    select, input { height: 34px; padding: 0 10px; min-width: 0; }
    textarea { width: 100%; min-height: 58px; padding: 8px 10px; resize: vertical; }
    .top-actions { display: flex; align-items: center; gap: 8px; min-width: 0; }
    .nav-link {
      min-height: 34px;
      display: inline-flex;
      align-items: center;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--accent);
      font-size: 13px;
      font-weight: 700;
      text-decoration: none;
      white-space: nowrap;
    }
    .primary { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
    .danger { background: var(--danger); color: #fff; border-color: var(--danger); }
    .ghost { background: #fff; color: var(--accent); border-color: var(--line); }
    .shell {
      height: calc(100vh - 58px);
      display: grid;
      grid-template-columns: 360px minmax(0, 1fr);
      min-height: 0;
    }
    aside {
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      border-right: 1px solid var(--line);
      background: var(--panel);
    }
    .filters {
      display: grid;
      gap: 8px;
      padding: 12px;
      border-bottom: 1px solid var(--line);
    }
    .filter-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .section-title {
      margin-top: 3px;
      font-size: 11px;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
    }
    .metric-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .metric {
      min-height: 58px;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel-2);
    }
    .metric-value { display: block; font-size: 19px; line-height: 1.1; font-weight: 700; }
    .metric-label { display: block; margin-top: 4px; color: var(--muted); font-size: 11px; }
    .counter { font-size: 12px; color: var(--muted); }
    .list { min-height: 0; overflow: auto; padding: 8px; }
    .item {
      width: 100%;
      display: block;
      text-align: left;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      padding: 10px;
      margin-bottom: 8px;
      color: var(--ink);
    }
    .item.active { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(11, 107, 203, 0.12); }
    .item-title { font-size: 13px; font-weight: 700; word-break: break-word; }
    .item-meta { margin-top: 7px; font-size: 12px; color: var(--muted); }
    .badges { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 7px; }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      padding: 0 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--panel-2);
      font-size: 12px;
      color: var(--ink);
    }
    .badge.danger { background: var(--soft-danger); color: var(--danger); border-color: #ffd2cc; }
    .badge.warning { background: var(--soft-warning); color: var(--warning); border-color: #ffe1a3; }
    .badge.ok { background: var(--soft-ok); color: var(--ok); border-color: #bfebd1; }
    main {
      min-width: 0;
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) 265px;
    }
    .detail-head {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 390px;
      gap: 14px;
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      min-height: 132px;
    }
    .mesa-title { font-weight: 700; font-size: 16px; word-break: break-word; }
    .mesa-subtitle { margin-top: 4px; color: var(--muted); font-size: 12px; word-break: break-word; }
    .review-box {
      display: grid;
      grid-template-rows: auto auto;
      gap: 8px;
      min-width: 0;
    }
    .review-buttons { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
    .review-buttons button { min-width: 0; padding: 0 8px; font-size: 12px; }
    .nav-buttons { display: flex; align-items: center; gap: 6px; margin-top: 8px; }
    .nav-buttons button { min-height: 30px; padding: 0 9px; font-size: 12px; }
    .pdf-grid {
      min-height: 0;
      display: grid;
      gap: 1px;
      background: var(--line);
    }
    .pdf-pane {
      min-width: 0;
      min-height: 0;
      background: var(--panel);
      display: grid;
      grid-template-rows: 38px minmax(0, 1fr);
    }
    .pdf-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 0 10px;
      border-bottom: 1px solid var(--line);
      font-size: 13px;
      font-weight: 700;
    }
    .pdf-title a { color: var(--accent); text-decoration: none; font-size: 12px; }
    iframe { width: 100%; height: 100%; border: 0; background: #fdfdfd; }
    .bottom {
      min-height: 0;
      overflow: auto;
      border-top: 1px solid var(--line);
      background: var(--panel);
    }
    .bottom-tabs {
      position: sticky;
      top: 0;
      z-index: 3;
      display: flex;
      gap: 6px;
      min-height: 42px;
      align-items: center;
      padding: 0 10px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    .bottom-tabs button { min-height: 30px; font-size: 12px; padding: 0 10px; }
    .bottom-tabs button.active { background: var(--accent); border-color: var(--accent); color: #fff; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td {
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      white-space: nowrap;
    }
    th { position: sticky; top: 42px; background: var(--panel-2); z-index: 2; }
    td.label { min-width: 180px; white-space: normal; }
    .mono { font-family: Consolas, "Courier New", monospace; font-size: 12px; }
    tr.numeric_mismatch { background: var(--soft-danger); }
    tr.ocr_uncertain { background: var(--soft-warning); }
    tr.missing_field { background: #f4f1ff; }
    .empty { padding: 18px; color: var(--muted); }
    @media (max-width: 1100px) {
      body { overflow: auto; }
      .shell { height: auto; grid-template-columns: 1fr; }
      aside { max-height: 430px; border-right: 0; border-bottom: 1px solid var(--line); }
      main { grid-template-rows: auto 900px 300px; }
      .detail-head { grid-template-columns: 1fr; }
      .pdf-grid { grid-template-columns: 1fr !important; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Revisor de mesas E14</h1>
    <div class="top-actions">
      <a class="nav-link" href="/inconsistencias">Inconsistencias OCR</a>
      <button class="primary" id="refreshBtn">Recargar</button>
    </div>
  </header>
  <div class="shell">
    <aside>
      <div class="filters">
        <div class="metric-grid">
          <div class="metric"><span class="metric-value" id="metricVisible">0</span><span class="metric-label">visibles</span></div>
          <div class="metric"><span class="metric-value" id="metricPending">0</span><span class="metric-label">pendientes</span></div>
          <div class="metric"><span class="metric-value" id="metricFirm">0</span><span class="metric-label">firmes</span></div>
          <div class="metric"><span class="metric-value" id="metricOcr">0</span><span class="metric-label">OCR dudoso</span></div>
        </div>
        <div class="section-title">Alcance</div>
        <select id="scopeFilter"></select>
        <div class="filter-row">
          <select id="reviewFilter">
            <option value="pending">Pendientes</option>
            <option value="reviewed">Revisadas</option>
            <option value="fraud">Fraude</option>
            <option value="ignored">Ignoradas</option>
            <option value="all">Todas</option>
          </select>
          <select id="findingFilter">
            <option value="all">Todos los hallazgos</option>
            <option value="numeric_mismatch">Diferencia firme</option>
            <option value="ocr_uncertain">OCR dudoso</option>
            <option value="missing_field">Campo faltante</option>
            <option value="internal_inconsistent">Inconsistencia interna</option>
          </select>
        </div>
        <div class="filter-row">
          <select id="fieldFilter"><option value="all">Todos los campos</option></select>
          <select id="sortFilter">
            <option value="priority">Prioridad</option>
            <option value="mesa">Mesa</option>
            <option value="numeric">Mas firmes</option>
            <option value="ocr">Mas OCR dudoso</option>
            <option value="updated">Actualizadas</option>
          </select>
        </div>
        <input id="searchInput" placeholder="Mesa, departamento, municipio">
        <div class="filter-row">
          <button class="ghost" id="clearBtn">Limpiar</button>
          <button id="reportBtn">CSV visible</button>
        </div>
        <div class="counter" id="counter">Cargando...</div>
      </div>
      <div class="list" id="list"></div>
    </aside>
    <main>
      <section class="detail-head">
        <div>
          <div class="mesa-title" id="mesaTitle">Seleccione una mesa</div>
          <div class="mesa-subtitle" id="mesaSubtitle"></div>
          <div class="badges" id="mesaBadges"></div>
          <div class="nav-buttons">
            <span class="counter" id="positionCounter"></span>
            <button id="prevBtn">Anterior</button>
            <button id="nextBtn">Siguiente</button>
          </div>
        </div>
        <div class="review-box">
          <textarea id="reviewNote" placeholder="Nota de revision"></textarea>
          <div class="review-buttons">
            <button class="primary" id="reviewBtn">Revisado</button>
            <button class="danger" id="fraudBtn">Fraude</button>
            <button class="ghost" id="pendingBtn">Pendiente</button>
          </div>
        </div>
      </section>
      <section class="pdf-grid" id="pdfGrid"></section>
      <section class="bottom">
        <div class="bottom-tabs">
          <button id="tabFindings" class="active">Hallazgos</button>
          <button id="tabFields">Campos</button>
          <button id="tabSources">Fuentes</button>
        </div>
        <div id="bottomContent"></div>
      </section>
    </main>
  </div>
  <script>
    const state = { rows: [], currentKey: null, detail: null, tab: "findings", searchTimer: null };
    const $ = (id) => document.getElementById(id);
    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[char]));
    }
    function badge(text, kind = "") {
      return `<span class="badge ${kind}">${escapeHtml(text)}</span>`;
    }
    function scopeLabel(scope) {
      if (!scope) return "";
      if (scope.startsWith("source:")) return `Revision ${scope.split(":")[1]}`;
      const pair = scope.replace("comparison:", "").split("|");
      return `Revision ${pair[0]} vs ${pair[1]}`;
    }
    function activeScope() { return $("scopeFilter").value || "comparison:claveros|delegados"; }
    function filterParams() {
      const params = new URLSearchParams({
        scope: activeScope(),
        review: $("reviewFilter").value,
        finding: $("findingFilter").value,
        field: $("fieldFilter").value,
        sort: $("sortFilter").value,
        q: $("searchInput").value.trim(),
      });
      return params;
    }
    async function loadRows(keepCurrent = true) {
      const response = await fetch(`/mesas/data?${filterParams().toString()}`);
      if (!response.ok) throw new Error("No pude cargar mesas");
      const payload = await response.json();
      state.rows = payload.rows || [];
      populateOptions(payload.options || {});
      updateMetrics(payload);
      renderList();
      const stillThere = keepCurrent && state.rows.some((row) => row.row_key === state.currentKey);
      if (!stillThere) state.currentKey = state.rows[0]?.row_key || null;
      if (state.currentKey) await loadDetail(state.currentKey);
      else renderEmpty();
    }
    function populateOptions(options) {
      setOptions("scopeFilter", options.scopes || [], "comparison:claveros|delegados");
      setOptions("fieldFilter", options.fields || [], "all");
    }
    function setOptions(selectId, options, fallback) {
      const select = $(selectId);
      const current = select.value || fallback;
      select.innerHTML = options.map((item) => (
        `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}${item.count !== undefined ? ` (${item.count})` : ""}</option>`
      )).join("");
      if (selectId === "fieldFilter") {
        select.innerHTML = `<option value="all">Todos los campos</option>` + select.innerHTML;
      }
      select.value = [...select.options].some((opt) => opt.value === current) ? current : fallback;
    }
    function updateMetrics(payload) {
      const f = payload.filtered || {};
      $("metricVisible").textContent = f.rows ?? state.rows.length;
      $("metricPending").textContent = f.pending ?? 0;
      $("metricFirm").textContent = f.numeric_mismatches ?? 0;
      $("metricOcr").textContent = f.ocr_uncertain ?? 0;
      $("counter").textContent = `${state.rows.length} visibles`;
    }
    function renderList() {
      $("list").innerHTML = state.rows.map((row) => {
        const active = row.row_key === state.currentKey ? " active" : "";
        return `
          <button class="item${active}" data-key="${escapeHtml(row.row_key)}">
            <div class="item-title">${escapeHtml(row.mesa_key)}</div>
            <div class="badges">
              ${badge(scopeLabel(row.scope))}
              ${badge(`${row.source_count} fuente${row.source_count === 1 ? "" : "s"}`)}
              ${row.review_status === "reviewed" ? badge("revisada", "ok") : ""}
              ${row.review_status === "fraud" ? badge("fraude", "danger") : ""}
              ${row.numeric_mismatches ? badge(`${row.numeric_mismatches} firmes`, "danger") : ""}
              ${row.ocr_uncertain ? badge(`${row.ocr_uncertain} OCR`, "warning") : ""}
              ${row.internal_inconsistent ? badge("interna", "warning") : ""}
            </div>
            <div class="item-meta">${escapeHtml(row.updated_at || "")}</div>
          </button>
        `;
      }).join("") || `<div class="empty">No hay mesas para este filtro.</div>`;
      document.querySelectorAll(".item").forEach((button) => {
        button.addEventListener("click", () => {
          state.currentKey = button.dataset.key;
          renderList();
          loadDetail(state.currentKey).catch(showError);
        });
      });
    }
    async function loadDetail(rowKey) {
      const row = state.rows.find((item) => item.row_key === rowKey);
      if (!row) return renderEmpty();
      const params = new URLSearchParams({mesa_key: row.mesa_key, scope: row.scope});
      const response = await fetch(`/mesas/detalle?${params.toString()}`);
      if (!response.ok) throw new Error("No pude cargar la mesa");
      state.detail = await response.json();
      renderDetail();
    }
    function renderDetail() {
      const detail = state.detail;
      if (!detail) return renderEmpty();
      $("mesaTitle").textContent = detail.mesa_key;
      $("mesaSubtitle").textContent = scopeLabel(detail.scope);
      $("reviewNote").value = detail.review?.note || "";
      $("mesaBadges").innerHTML = [
        badge(detail.review?.status || "pending", detail.review?.status === "reviewed" ? "ok" : detail.review?.status === "fraud" ? "danger" : ""),
        badge(`${detail.documents.length} fuente${detail.documents.length === 1 ? "" : "s"}`),
        detail.summary.numeric_mismatches ? badge(`${detail.summary.numeric_mismatches} firmes`, "danger") : "",
        detail.summary.ocr_uncertain ? badge(`${detail.summary.ocr_uncertain} OCR dudoso`, "warning") : "",
        detail.summary.internal_inconsistent ? badge("interna", "warning") : "",
      ].join("");
      renderPdfGrid(detail.documents || []);
      updatePosition();
      renderBottom();
    }
    function renderPdfGrid(documents) {
      const grid = $("pdfGrid");
      const count = Math.max(1, Math.min(3, documents.length || 1));
      grid.style.gridTemplateColumns = `repeat(${count}, minmax(0, 1fr))`;
      grid.innerHTML = documents.map((doc) => `
        <div class="pdf-pane">
          <div class="pdf-title">
            <span>${escapeHtml(doc.source_type)} ${badge(doc.status || "")}</span>
            <a href="${escapeHtml(doc.pdf_url)}" target="_blank" rel="noopener">Abrir</a>
          </div>
          <iframe src="${escapeHtml(doc.pdf_url)}"></iframe>
        </div>
      `).join("") || `<div class="empty">No hay PDF disponible para esta mesa.</div>`;
    }
    function updatePosition() {
      const index = state.rows.findIndex((row) => row.row_key === state.currentKey);
      $("positionCounter").textContent = index >= 0 ? `${index + 1} / ${state.rows.length}` : "";
      $("prevBtn").disabled = index <= 0;
      $("nextBtn").disabled = index < 0 || index >= state.rows.length - 1;
    }
    function moveSelection(delta) {
      const index = state.rows.findIndex((row) => row.row_key === state.currentKey);
      const next = state.rows[index + delta];
      if (!next) return;
      state.currentKey = next.row_key;
      renderList();
      loadDetail(state.currentKey).catch(showError);
    }
    function setTab(tab) {
      state.tab = tab;
      $("tabFindings").classList.toggle("active", tab === "findings");
      $("tabFields").classList.toggle("active", tab === "fields");
      $("tabSources").classList.toggle("active", tab === "sources");
      renderBottom();
    }
    function renderBottom() {
      const detail = state.detail;
      if (!detail) return;
      if (state.tab === "sources") return renderSources(detail);
      if (state.tab === "fields") return renderSourceFields(detail);
      return renderFindings(detail);
    }
    function renderFindings(detail) {
      const rows = detail.findings || [];
      if (!rows.length) {
        $("bottomContent").innerHTML = `<div class="empty">No hay hallazgos para este alcance.</div>`;
        return;
      }
      $("bottomContent").innerHTML = `
        <table><thead><tr><th>Campo</th><th>Resultado</th><th>A</th><th>B</th><th>Conf A</th><th>Conf B</th><th>Visual</th><th>Motivo</th></tr></thead>
        <tbody>${rows.map((row) => `
          <tr class="${escapeHtml(row.result)}">
            <td class="label">${escapeHtml(row.field_label || row.field_key)}</td>
            <td>${escapeHtml(resultLabel(row.result))}</td>
            <td class="mono">${escapeHtml(row.value_a ?? "")}</td>
            <td class="mono">${escapeHtml(row.value_b ?? "")}</td>
            <td>${formatNumber(row.confidence_a)}</td>
            <td>${formatNumber(row.confidence_b)}</td>
            <td>${formatNumber(row.visual_score)}</td>
            <td class="label">${escapeHtml(reasonText(row))}</td>
          </tr>`).join("")}</tbody></table>`;
    }
    function renderSourceFields(detail) {
      const rows = detail.source_fields || [];
      if (!rows.length) {
        $("bottomContent").innerHTML = `<div class="empty">No hay campos OCR para esta mesa.</div>`;
        return;
      }
      $("bottomContent").innerHTML = `
        <table><thead><tr><th>Fuente</th><th>Campo</th><th>Valor</th><th>Raw</th><th>Confianza</th></tr></thead>
        <tbody>${rows.map((row) => `
          <tr>
            <td>${escapeHtml(row.source_type)}</td>
            <td class="label">${escapeHtml(row.field_label || row.field_key)}</td>
            <td class="mono">${escapeHtml(row.normalized_value ?? "")}</td>
            <td class="mono">${escapeHtml(row.raw_text ?? "")}</td>
            <td>${formatNumber(row.confidence)}</td>
          </tr>`).join("")}</tbody></table>`;
    }
    function renderSources(detail) {
      $("bottomContent").innerHTML = `
        <table><thead><tr><th>Fuente</th><th>Estado OCR</th><th>Ruta</th></tr></thead>
        <tbody>${detail.documents.map((doc) => `
          <tr>
            <td>${escapeHtml(doc.source_type)}</td>
            <td>${escapeHtml(doc.status || "")}</td>
            <td class="label">${escapeHtml(doc.relative_path || "")}</td>
          </tr>`).join("")}</tbody></table>`;
    }
    function resultLabel(value) {
      return {
        numeric_mismatch: "diferencia firme",
        ocr_uncertain: "OCR dudoso",
        missing_field: "campo faltante",
        visual_mismatch: "visual",
        match: "igual",
      }[value] || value;
    }
    function reasonText(row) {
      try {
        const details = JSON.parse(row.details_json || "{}");
        if (details.reason === "numeric_mismatch_but_visual_match") return "Valores distintos, recortes similares";
        if (details.reason) return details.reason;
        if (details.raw_a || details.raw_b) return `raw ${details.raw_a ?? ""} vs ${details.raw_b ?? ""}`;
      } catch (_) {}
      return "";
    }
    function formatNumber(value) {
      if (value === null || value === undefined || value === "") return "";
      const number = Number(value);
      return Number.isFinite(number) ? number.toFixed(2) : escapeHtml(value);
    }
    function renderEmpty() {
      $("mesaTitle").textContent = "Seleccione una mesa";
      $("mesaSubtitle").textContent = "";
      $("mesaBadges").innerHTML = "";
      $("positionCounter").textContent = "";
      $("reviewNote").value = "";
      $("prevBtn").disabled = true;
      $("nextBtn").disabled = true;
      $("pdfGrid").innerHTML = `<div class="empty">No hay PDF cargado.</div>`;
      $("bottomContent").innerHTML = `<div class="empty">No hay detalle cargado.</div>`;
    }
    async function saveReview(status) {
      const detail = state.detail;
      if (!detail) return;
      const response = await fetch("/mesas/review", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          mesa_key: detail.mesa_key,
          scope: detail.scope,
          status,
          note: $("reviewNote").value,
        }),
      });
      if (!response.ok) throw new Error("No pude guardar la revision");
      await loadRows(false);
    }
    function clearFilters() {
      $("reviewFilter").value = "pending";
      $("findingFilter").value = "all";
      $("fieldFilter").value = "all";
      $("sortFilter").value = "priority";
      $("searchInput").value = "";
      loadRows(false).catch(showError);
    }
    function downloadReport() {
      window.location.href = `/mesas/reporte?${filterParams().toString()}`;
    }
    function showError(error) { $("counter").textContent = error.message || String(error); }
    $("refreshBtn").addEventListener("click", () => loadRows(true).catch(showError));
    ["scopeFilter", "reviewFilter", "findingFilter", "fieldFilter", "sortFilter"].forEach((id) => {
      $(id).addEventListener("change", () => loadRows(false).catch(showError));
    });
    $("searchInput").addEventListener("input", () => {
      clearTimeout(state.searchTimer);
      state.searchTimer = setTimeout(() => loadRows(false).catch(showError), 250);
    });
    $("clearBtn").addEventListener("click", clearFilters);
    $("reportBtn").addEventListener("click", downloadReport);
    $("prevBtn").addEventListener("click", () => moveSelection(-1));
    $("nextBtn").addEventListener("click", () => moveSelection(1));
    $("reviewBtn").addEventListener("click", () => saveReview("reviewed").catch(showError));
    $("fraudBtn").addEventListener("click", () => saveReview("fraud").catch(showError));
    $("pendingBtn").addEventListener("click", () => saveReview("pending").catch(showError));
    $("tabFindings").addEventListener("click", () => setTab("findings"));
    $("tabFields").addEventListener("click", () => setTab("fields"));
    $("tabSources").addEventListener("click", () => setTab("sources"));
    document.addEventListener("keydown", (event) => {
      const tag = event.target && event.target.tagName ? event.target.tagName.toLowerCase() : "";
      if (["input", "select", "textarea"].includes(tag)) return;
      if (event.key === "ArrowRight") moveSelection(1);
      if (event.key === "ArrowLeft") moveSelection(-1);
      if (event.key.toLowerCase() === "r") saveReview("reviewed").catch(showError);
    });
    loadRows(false).catch(showError);
  </script>
</body>
</html>
"""


@dataclass
class AppState:
    inconsistencies: Path
    summary: Path
    fields: Path
    reviews: Path
    frauds: Path
    downloads_root: Path
    source_db: Path
    lock: threading.Lock
    cache_signature: tuple[Any, ...] | None = None
    cache_payload: dict[str, Any] | None = None
    cache_documents: dict[str, dict[str, Any]] | None = None
    cache_response_signature: tuple[Any, ...] | None = None
    cache_response_json: bytes | None = None
    cache_response_gzip: bytes | None = None


def csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def connect_source_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def csv_signature(path: Path) -> tuple[str, int, int] | tuple[str, None, None]:
    if not path.exists():
        return (str(path), None, None)
    stat = path.stat()
    return (str(path), stat.st_mtime_ns, stat.st_size)


def review_key(row: dict[str, str]) -> str:
    raw = "|".join(
        [
            row.get("document_id", ""),
            row.get("relative_path", ""),
            row.get("code", ""),
            row.get("message", ""),
            row.get("details_json", ""),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()


def dedupe_review_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: dict[str, dict[str, str]] = {}
    for row in rows:
        key = review_key(row)
        if key in deduped:
            deduped.pop(key)
        deduped[key] = row
    return list(deduped.values())


def document_key(row: dict[str, str]) -> str:
    return row.get("document_id") or row.get("id") or row.get("relative_path", "")


def parse_details(raw: str) -> tuple[Any, str]:
    if not raw:
        return {}, "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}, raw
    return parsed, json.dumps(parsed, ensure_ascii=False, indent=2)


def absolute_pdf_path(downloads_root: Path, relative_path: str) -> Path:
    return downloads_root / Path(relative_path)


def load_reviews(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    reviews: dict[str, dict[str, Any]] = {}
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            key = row.get("key", "")
            if not key:
                continue
            reviews[key] = {
                "reviewed": row.get("reviewed", "").lower() in ("1", "true", "yes", "si"),
                "note": row.get("note", ""),
                "updated_at": row.get("updated_at", ""),
            }
    return reviews


def write_reviews(path: Path, reviews: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["key", "reviewed", "note", "updated_at"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for key in sorted(reviews):
            review = reviews[key]
            writer.writerow(
                {
                    "key": key,
                    "reviewed": "1" if review.get("reviewed") else "0",
                    "note": review.get("note", ""),
                    "updated_at": review.get("updated_at", ""),
                }
            )


def load_frauds(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    frauds: dict[str, dict[str, Any]] = {}
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = [row for row in csv.reader(handle) if row and any(cell.strip() for cell in row)]
    if not rows:
        return frauds

    if rows[0] and rows[0][0] == "document_key":
        headers = rows[0]
        for values in rows[1:]:
            row = dict(zip(headers, values))
            path_key = row.get("relative_path", "") or row.get("document_key", "")
            if not path_key:
                continue
            frauds[path_key] = {
                "status": "FRAUDE",
                "document_id": row.get("document_id", ""),
                "relative_path": row.get("relative_path", path_key),
                "absolute_pdf_path": row.get("absolute_pdf_path", ""),
                "department_name": row.get("department_name", ""),
                "municipality_name": row.get("municipality_name", ""),
                "zone_code": row.get("zone_code", ""),
                "place_name": row.get("place_name", ""),
                "table_number": row.get("table_number", ""),
                "reported_from_code": row.get("reported_from_code", ""),
                "reported_from_message": row.get("reported_from_message", ""),
                "note": row.get("note", ""),
                "reported_at": row.get("reported_at", ""),
                "updated_at": row.get("updated_at", ""),
            }
        return frauds

    for row in rows:
        relative_path = row[0].strip()
        if not relative_path:
            continue
        frauds[relative_path] = {
            "status": "FRAUDE",
            "relative_path": relative_path,
        }
    return frauds


def write_frauds(path: Path, frauds: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    relative_paths = sorted(
        {
            str(row.get("relative_path") or key).strip()
            for key, row in frauds.items()
            if str(row.get("relative_path") or key).strip()
        }
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for relative_path in relative_paths:
            writer.writerow([relative_path])


def load_summary(path: Path, wanted_docs: set[str], wanted_paths: set[str]) -> dict[str, dict[str, str]]:
    summaries: dict[str, dict[str, str]] = {}
    if not path.exists():
        return summaries
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            key = document_key(row)
            if key in wanted_docs or row.get("relative_path", "") in wanted_paths:
                summaries[key] = row
    return summaries


def load_fields(path: Path, wanted_docs: set[str], wanted_paths: set[str]) -> dict[str, list[dict[str, str]]]:
    fields_by_key: dict[str, dict[str, dict[str, str]]] = {}
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            key = document_key(row)
            if key in wanted_docs or row.get("relative_path", "") in wanted_paths:
                field_key = row.get("field_key", "") or str(len(fields_by_key.get(key, {})))
                fields_by_key.setdefault(key, {})[field_key] = row
    return {key: list(rows.values()) for key, rows in fields_by_key.items()}


def enrich_rows(rows: list[dict[str, str]], downloads_root: Path) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    row_fields = [
        "document_id",
        "severity",
        "code",
        "message",
        "relative_path",
        "department_name",
        "municipality_name",
        "zone_code",
        "place_name",
        "table_number",
        "created_at",
    ]
    for index, row in enumerate(rows, start=1):
        item: dict[str, Any] = {field: row.get(field, "") for field in row_fields}
        details, _ = parse_details(row.get("details_json", ""))
        pdf_path = absolute_pdf_path(downloads_root, row.get("relative_path", ""))
        key = review_key(row)
        item.update(
            {
                "row_number": index,
                "review_key": key,
                "document_key": document_key(row),
                "details": details,
                "absolute_pdf_path": str(pdf_path),
                "pdf_exists": pdf_path.exists() and pdf_path.is_file(),
            }
        )
        enriched.append(item)
    return enriched


def number_or_none(value: Any) -> int | float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        return None
    if number.is_integer():
        return int(number)
    return number


def first_number(*values: Any) -> int | float | None:
    for value in values:
        number = number_or_none(value)
        if number is not None:
            return number
    return None


def summary_search_text(summary: dict[str, str]) -> str:
    keys = [
        "status",
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
    return " ".join(str(summary.get(key, "")).strip() for key in keys if summary.get(key, "")).strip()


def build_document_metrics(summary: dict[str, str], fields: list[dict[str, str]]) -> dict[str, Any]:
    field_values: dict[str, int | float] = {}
    for field in fields:
        field_key = str(field.get("field_key", "")).strip()
        if not field_key:
            continue
        number = number_or_none(field.get("normalized_value"))
        if number is not None:
            field_values[field_key] = number

    table_total = first_number(
        field_values.get("suma_total"),
        summary.get("declared_total"),
        field_values.get("total_votos_urna"),
        summary.get("urna_total"),
    )
    candidate_1 = field_values.get("candidato_1")
    candidate_2 = field_values.get("candidato_2")
    full_vote_candidate = ""
    if table_total is not None and table_total > 0:
        if candidate_1 == table_total:
            full_vote_candidate = "candidato_1"
        elif candidate_2 == table_total:
            full_vote_candidate = "candidato_2"

    return {
        "field_values": field_values,
        "candidato_1": candidate_1,
        "candidato_2": candidate_2,
        "table_total": table_total,
        "full_vote_candidate": full_vote_candidate,
        "summary_search": summary_search_text(summary),
    }


def build_payload(app: AppState) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    rows = dedupe_review_rows(csv_rows(app.inconsistencies))
    enriched = enrich_rows(rows, app.downloads_root)
    wanted_docs = {str(row["document_key"]) for row in enriched if row.get("document_key")}
    wanted_paths = {str(row.get("relative_path", "")) for row in enriched if row.get("relative_path")}
    summaries = load_summary(app.summary, wanted_docs, wanted_paths)
    fields = load_fields(app.fields, wanted_docs, wanted_paths)

    documents: dict[str, dict[str, Any]] = {}
    metrics: dict[str, dict[str, Any]] = {}
    field_labels: dict[str, str] = {}
    for row in enriched:
        key = str(row["document_key"])
        documents.setdefault(
            key,
            {
                "summary": summaries.get(key, {}),
                "fields": fields.get(key, []),
                "related_keys": [],
                "relative_path": row.get("relative_path", ""),
                "absolute_pdf_path": row.get("absolute_pdf_path", ""),
                "created_at": row.get("created_at", ""),
            },
        )
        documents[key]["related_keys"].append(row["review_key"])

    for key, document in documents.items():
        document_fields = document.get("fields", [])
        metrics[key] = build_document_metrics(document.get("summary", {}), document_fields)
        for field in document_fields:
            field_key = str(field.get("field_key", "")).strip()
            if field_key and field_key not in field_labels:
                field_labels[field_key] = str(field.get("field_label", "") or field_key)

    code_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    for row in enriched:
        code = str(row.get("code", "") or "SIN_CODIGO")
        severity = str(row.get("severity", "") or "sin_severidad")
        code_counts[code] = code_counts.get(code, 0) + 1
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

    payload_rows: list[dict[str, Any]] = []
    for row in enriched:
        public_row = dict(row)
        pdf_exists = public_row.pop("pdf_exists", True)
        if not pdf_exists:
            public_row["pdf_missing"] = True
        public_row.pop("absolute_pdf_path", None)
        public_row.pop("document_key", None)
        public_row.pop("created_at", None)
        payload_rows.append(public_row)

    payload = {
        "rows": payload_rows,
        "metrics": metrics,
        "field_labels": field_labels,
        "code_counts": code_counts,
        "severity_counts": severity_counts,
        "source": str(app.inconsistencies),
    }
    return payload, documents


def payload_snapshot(app: AppState) -> dict[str, Any]:
    signature = (
        csv_signature(app.inconsistencies),
        csv_signature(app.summary),
        csv_signature(app.fields),
    )
    with app.lock:
        if app.cache_signature != signature or app.cache_payload is None:
            app.cache_payload, app.cache_documents = build_payload(app)
            app.cache_signature = signature
        payload = dict(app.cache_payload)
        payload["reviews"] = load_reviews(app.reviews)
        payload["frauds"] = load_frauds(app.frauds)
        return payload


def data_response_bytes(app: AppState, accepts_gzip: bool, force_refresh: bool = False) -> tuple[bytes, bool]:
    signature = (
        csv_signature(app.inconsistencies),
        csv_signature(app.summary),
        csv_signature(app.fields),
    )
    with app.lock:
        if force_refresh or app.cache_payload is None:
            app.cache_payload, app.cache_documents = build_payload(app)
            app.cache_signature = signature
            app.cache_response_signature = None
            app.cache_response_json = None
            app.cache_response_gzip = None

        response_signature = (app.cache_signature,)
        if app.cache_response_signature != response_signature or app.cache_response_json is None:
            app.cache_response_json = json.dumps(
                app.cache_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            app.cache_response_gzip = None
            app.cache_response_signature = response_signature

        if accepts_gzip:
            if app.cache_response_gzip is None:
                app.cache_response_gzip = gzip.compress(app.cache_response_json)
            return app.cache_response_gzip, True
        return app.cache_response_json, False


def status_snapshot(app: AppState) -> dict[str, Any]:
    with app.lock:
        return {
            "reviews": load_reviews(app.reviews),
            "frauds": load_frauds(app.frauds),
        }


def document_snapshot(app: AppState, key: str) -> dict[str, Any] | None:
    signature = (
        csv_signature(app.inconsistencies),
        csv_signature(app.summary),
        csv_signature(app.fields),
    )
    with app.lock:
        if app.cache_payload is None or app.cache_documents is None:
            app.cache_payload, app.cache_documents = build_payload(app)
            app.cache_signature = signature
        return app.cache_documents.get(key)


def init_review_status_schema(db_path: Path) -> None:
    if not db_path.exists():
        return
    conn = connect_source_db(db_path)
    try:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS review_status (
                    id INTEGER PRIMARY KEY,
                    mesa_key TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    source_a TEXT NOT NULL,
                    source_b TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    note TEXT,
                    reviewed_at TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(mesa_key, scope_type, source_a, source_b)
                );
                CREATE INDEX IF NOT EXISTS idx_review_status_scope
                    ON review_status(scope_type, source_a, source_b, status);
                CREATE INDEX IF NOT EXISTS idx_review_status_mesa
                    ON review_status(mesa_key);
                """
            )
    finally:
        conn.close()


def parse_review_scope(raw: str) -> tuple[str, str, str]:
    if raw.startswith("source:"):
        return "source", raw.split(":", 1)[1], ""
    if raw.startswith("comparison:"):
        pair = raw.split(":", 1)[1]
        if "|" in pair:
            source_a, source_b = pair.split("|", 1)
            return "comparison", source_a, source_b
    return "comparison", "claveros", "delegados"


def review_scope_value(scope_type: str, source_a: str, source_b: str = "") -> str:
    if scope_type == "source":
        return f"source:{source_a}"
    return f"comparison:{source_a}|{source_b}"


def review_status_row(
    conn: sqlite3.Connection,
    mesa_key: str,
    scope_type: str,
    source_a: str,
    source_b: str,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT status, note, reviewed_at, updated_at
        FROM review_status
        WHERE mesa_key = ? AND scope_type = ? AND source_a = ? AND source_b = ?
        """,
        (mesa_key, scope_type, source_a, source_b or ""),
    ).fetchone()
    if row is None:
        return {"status": "pending", "note": "", "reviewed_at": "", "updated_at": ""}
    return row_dict(row)


def upsert_review_status(
    db_path: Path,
    mesa_key: str,
    scope_type: str,
    source_a: str,
    source_b: str,
    status: str,
    note: str,
) -> dict[str, Any]:
    init_review_status_schema(db_path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reviewed_at = now if status in {"reviewed", "fraud", "ignored"} else None
    conn = connect_source_db(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO review_status (
                    mesa_key, scope_type, source_a, source_b,
                    status, note, reviewed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mesa_key, scope_type, source_a, source_b) DO UPDATE SET
                    status = excluded.status,
                    note = excluded.note,
                    reviewed_at = excluded.reviewed_at,
                    updated_at = excluded.updated_at
                """,
                (mesa_key, scope_type, source_a, source_b or "", status, note, reviewed_at, now),
            )
            return review_status_row(conn, mesa_key, scope_type, source_a, source_b)
    finally:
        conn.close()


def mesa_review_options(conn: sqlite3.Connection) -> dict[str, Any]:
    scopes: list[dict[str, Any]] = []
    comparison_rows = conn.execute(
        """
        SELECT source_a, source_b, COUNT(*) AS count
        FROM source_comparisons
        GROUP BY source_a, source_b
        ORDER BY source_a, source_b
        """
    ).fetchall()
    for row in comparison_rows:
        scopes.append(
            {
                "value": review_scope_value("comparison", row["source_a"], row["source_b"]),
                "label": f"{row['source_a']} vs {row['source_b']}",
                "count": row["count"],
            }
        )
    source_rows = conn.execute(
        """
        SELECT source_type, COUNT(*) AS count
        FROM source_documents
        WHERE EXISTS (
            SELECT 1 FROM source_document_results r
            WHERE r.source_document_id = source_documents.id
        )
        GROUP BY source_type
        ORDER BY source_type
        """
    ).fetchall()
    for row in source_rows:
        scopes.append(
            {
                "value": review_scope_value("source", row["source_type"]),
                "label": f"Solo {row['source_type']}",
                "count": row["count"],
            }
        )
    field_rows = conn.execute(
        """
        SELECT field_key, MAX(field_label) AS field_label, COUNT(*) AS count
        FROM (
          SELECT field_key, field_label FROM source_field_results
          UNION ALL
          SELECT field_key, field_label FROM source_field_comparisons
        )
        GROUP BY field_key
        ORDER BY field_key
        """
    ).fetchall()
    fields = [
        {
            "value": row["field_key"],
            "label": row["field_label"] or row["field_key"],
            "count": row["count"],
        }
        for row in field_rows
    ]
    return {"scopes": scopes, "fields": fields}


def mesa_review_rows(app: AppState, query: dict[str, list[str]], limit: int = 2000) -> dict[str, Any]:
    if not app.source_db.exists():
        return {"rows": [], "filtered": {}, "options": {"scopes": [], "fields": []}}
    init_review_status_schema(app.source_db)
    scope_type, source_a, source_b = parse_review_scope(query_value(query, "scope", "comparison:claveros|delegados"))
    review_filter = query_value(query, "review", "pending")
    finding_filter = query_value(query, "finding", "all")
    field_filter = query_value(query, "field", "all")
    search = query_value(query, "q", "").strip()
    sort = query_value(query, "sort", "priority")

    conn = connect_source_db(app.source_db)
    try:
        params: list[Any] = []
        where: list[str] = []
        if review_filter != "all":
            if review_filter == "pending":
                where.append("COALESCE(rs.status, 'pending') = 'pending'")
            else:
                where.append("COALESCE(rs.status, 'pending') = ?")
                params.append(review_filter)
        if search:
            like = f"%{search}%"
            where.append("(base.mesa_key LIKE ? OR base.relative_path LIKE ?)")
            params.extend([like, like])

        if scope_type == "source":
            base_sql = """
                SELECT sd.id AS item_id, sd.mesa_key, ? AS scope, 'source' AS scope_type,
                       sd.source_type AS source_a, '' AS source_b,
                       sd.relative_path, sd.updated_at, sd.status AS source_status,
                       0 AS numeric_mismatches, 0 AS visual_mismatches,
                       0 AS ocr_uncertain, 0 AS missing_fields,
                       CASE WHEN sd.status = 'inconsistent' THEN 1 ELSE 0 END AS internal_inconsistent,
                       (SELECT COUNT(*) FROM source_documents sx WHERE sx.mesa_key = sd.mesa_key) AS source_count
                FROM source_documents sd
                WHERE sd.source_type = ?
                  AND EXISTS (SELECT 1 FROM source_document_results r WHERE r.source_document_id = sd.id)
            """
            base_params: list[Any] = [review_scope_value(scope_type, source_a, source_b), source_a]
            if finding_filter == "internal_inconsistent":
                where.append("base.internal_inconsistent = 1")
            elif finding_filter in {"numeric_mismatch", "ocr_uncertain", "missing_field"}:
                where.append("1 = 0")
            if field_filter != "all":
                where.append(
                    "EXISTS (SELECT 1 FROM source_field_results f "
                    "WHERE f.source_document_id = base.item_id AND f.field_key = ?)"
                )
                params.append(field_filter)
        else:
            base_sql = """
                SELECT c.id AS item_id, c.mesa_key, ? AS scope, 'comparison' AS scope_type,
                       c.source_a, c.source_b, '' AS relative_path, c.updated_at,
                       c.status AS source_status, c.numeric_mismatches,
                       c.visual_mismatches, c.ocr_uncertain, c.missing_fields,
                       CASE WHEN EXISTS (
                         SELECT 1 FROM source_documents sd
                         WHERE sd.mesa_key = c.mesa_key
                           AND sd.source_type IN (c.source_a, c.source_b)
                           AND sd.status = 'inconsistent'
                       ) THEN 1 ELSE 0 END AS internal_inconsistent,
                       (SELECT COUNT(*) FROM source_documents sx WHERE sx.mesa_key = c.mesa_key) AS source_count
                FROM source_comparisons c
                WHERE c.source_a = ? AND c.source_b = ?
            """
            base_params = [review_scope_value(scope_type, source_a, source_b), source_a, source_b]
            if finding_filter == "numeric_mismatch":
                where.append("base.numeric_mismatches > 0")
            elif finding_filter == "ocr_uncertain":
                where.append("base.ocr_uncertain > 0")
            elif finding_filter == "missing_field":
                where.append("base.missing_fields > 0")
            elif finding_filter == "internal_inconsistent":
                where.append("base.internal_inconsistent = 1")
            if field_filter != "all":
                where.append(
                    "EXISTS (SELECT 1 FROM source_field_comparisons f "
                    "WHERE f.comparison_id = base.item_id AND f.field_key = ?)"
                )
                params.append(field_filter)

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        order_options = {
            "priority": "base.numeric_mismatches DESC, base.ocr_uncertain DESC, base.internal_inconsistent DESC, base.mesa_key",
            "mesa": "base.mesa_key",
            "numeric": "base.numeric_mismatches DESC, base.mesa_key",
            "ocr": "base.ocr_uncertain DESC, base.mesa_key",
            "updated": "base.updated_at DESC, base.mesa_key",
        }
        order_sql = order_options.get(sort, order_options["priority"])
        sql = f"""
            WITH base AS ({base_sql})
            SELECT base.*, COALESCE(rs.status, 'pending') AS review_status,
                   COALESCE(rs.note, '') AS review_note,
                   rs.reviewed_at, rs.updated_at AS review_updated_at
            FROM base
            LEFT JOIN review_status rs
              ON rs.mesa_key = base.mesa_key
             AND rs.scope_type = base.scope_type
             AND rs.source_a = base.source_a
             AND rs.source_b = base.source_b
            {where_sql}
            ORDER BY {order_sql}
            LIMIT ?
        """
        rows = [row_dict(row) for row in conn.execute(sql, [*base_params, *params, limit]).fetchall()]
        for row in rows:
            row["row_key"] = f"{row['scope']}|{row['mesa_key']}"
        filtered = {
            "rows": len(rows),
            "pending": sum(1 for row in rows if row.get("review_status") == "pending"),
            "numeric_mismatches": sum(int(row.get("numeric_mismatches") or 0) for row in rows),
            "ocr_uncertain": sum(int(row.get("ocr_uncertain") or 0) for row in rows),
        }
        options = mesa_review_options(conn)
    finally:
        conn.close()
    return {"rows": rows, "filtered": filtered, "options": options}


def mesa_review_detail(app: AppState, mesa_key: str, raw_scope: str) -> dict[str, Any] | None:
    if not app.source_db.exists():
        return None
    init_review_status_schema(app.source_db)
    scope_type, source_a, source_b = parse_review_scope(raw_scope)
    conn = connect_source_db(app.source_db)
    try:
        documents = [
            {
                **row_dict(row),
                "pdf_url": f"/mesas/pdf?doc_id={row['id']}",
            }
            for row in conn.execute(
                """
                SELECT id, source_type, status, relative_path, absolute_path, updated_at
                FROM source_documents
                WHERE mesa_key = ?
                  AND EXISTS (
                    SELECT 1 FROM source_document_results r
                    WHERE r.source_document_id = source_documents.id
                  )
                ORDER BY CASE source_type
                    WHEN 'claveros' THEN 0
                    WHEN 'delegados' THEN 1
                    WHEN 'transmision' THEN 2
                    ELSE 3
                  END,
                  source_type
                """,
                (mesa_key,),
            ).fetchall()
        ]
        source_fields = [
            row_dict(row)
            for row in conn.execute(
                """
                SELECT sd.source_type, f.field_key, f.field_label, f.raw_text,
                       f.normalized_value, f.confidence
                FROM source_field_results f
                JOIN source_documents sd ON sd.id = f.source_document_id
                WHERE sd.mesa_key = ?
                ORDER BY sd.source_type, f.field_key
                """,
                (mesa_key,),
            ).fetchall()
        ]
        findings: list[dict[str, Any]] = []
        summary = {
            "numeric_mismatches": 0,
            "ocr_uncertain": 0,
            "missing_fields": 0,
            "internal_inconsistent": 0,
        }
        if scope_type == "comparison":
            comparison = conn.execute(
                """
                SELECT * FROM source_comparisons
                WHERE mesa_key = ? AND source_a = ? AND source_b = ?
                """,
                (mesa_key, source_a, source_b),
            ).fetchone()
            if comparison is not None:
                comparison_dict = row_dict(comparison)
                summary.update(
                    {
                        "numeric_mismatches": comparison_dict["numeric_mismatches"],
                        "ocr_uncertain": comparison_dict["ocr_uncertain"],
                        "missing_fields": comparison_dict["missing_fields"],
                    }
                )
                findings = [
                    row_dict(row)
                    for row in conn.execute(
                        """
                        SELECT field_key, field_label, value_a, value_b,
                               confidence_a, confidence_b, visual_score, result,
                               details_json
                        FROM source_field_comparisons
                        WHERE comparison_id = ? AND result != 'match'
                        ORDER BY CASE result
                            WHEN 'numeric_mismatch' THEN 0
                            WHEN 'ocr_uncertain' THEN 1
                            WHEN 'missing_field' THEN 2
                            ELSE 3
                          END,
                          field_key
                        """,
                        (comparison_dict["id"],),
                    ).fetchall()
                ]
        internal_rows = conn.execute(
            """
            SELECT sd.source_type, r.inconsistencies_json
            FROM source_document_results r
            JOIN source_documents sd ON sd.id = r.source_document_id
            WHERE sd.mesa_key = ?
            """,
            (mesa_key,),
        ).fetchall()
        for row in internal_rows:
            try:
                issues = json.loads(row["inconsistencies_json"] or "[]")
            except json.JSONDecodeError:
                issues = []
            if issues:
                summary["internal_inconsistent"] = 1
            if scope_type == "source" and row["source_type"] == source_a:
                for issue in issues:
                    details = issue.get("details", {}) if isinstance(issue, dict) else {}
                    findings.append(
                        {
                            "field_key": details.get("field", ""),
                            "field_label": details.get("field", issue.get("code", "") if isinstance(issue, dict) else ""),
                            "value_a": "",
                            "value_b": "",
                            "confidence_a": details.get("confidence"),
                            "confidence_b": None,
                            "visual_score": None,
                            "result": "internal_inconsistent",
                            "details_json": json.dumps(issue, ensure_ascii=False),
                        }
                    )
        review = review_status_row(conn, mesa_key, scope_type, source_a, source_b)
    finally:
        conn.close()
    return {
        "mesa_key": mesa_key,
        "scope": review_scope_value(scope_type, source_a, source_b),
        "documents": documents,
        "findings": findings,
        "source_fields": source_fields,
        "summary": summary,
        "review": review,
    }


def mesa_review_report_csv(app: AppState, query: dict[str, list[str]]) -> tuple[bytes, str]:
    payload = mesa_review_rows(app, query, limit=100000)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "mesa_key",
            "scope",
            "review_status",
            "numeric_mismatches",
            "ocr_uncertain",
            "missing_fields",
            "internal_inconsistent",
            "source_count",
            "updated_at",
            "review_note",
        ]
    )
    for row in payload.get("rows", []):
        writer.writerow(
            [
                row.get("mesa_key", ""),
                row.get("scope", ""),
                row.get("review_status", ""),
                row.get("numeric_mismatches", 0),
                row.get("ocr_uncertain", 0),
                row.get("missing_fields", 0),
                row.get("internal_inconsistent", 0),
                row.get("source_count", 0),
                row.get("updated_at", ""),
                row.get("review_note", ""),
            ]
        )
    return output.getvalue().encode("utf-8-sig"), "mesas_filtradas.csv"


def query_value(query: dict[str, list[str]], key: str, default: str = "") -> str:
    return query.get(key, [default])[0]


def query_int(query: dict[str, list[str]], key: str, default: int = 0) -> int:
    try:
        return int(query_value(query, key, str(default)) or default)
    except ValueError:
        return default


def comparison_filter_sql(query: dict[str, list[str]]) -> tuple[str, list[Any]]:
    status = query_value(query, "status", "needs_review")
    result = query_value(query, "result", "not_match")
    field_key = query_value(query, "field", "all")
    source_pair = query_value(query, "pair", "all")
    search = query_value(query, "q", "").strip()
    min_numeric = query_int(query, "min_numeric", 0)
    min_ocr = query_int(query, "min_ocr", 0)
    min_missing = query_int(query, "min_missing", 0)

    where = []
    params: list[Any] = []
    if status != "all":
        where.append("c.status = ?")
        params.append(status)
    if source_pair != "all" and "|" in source_pair:
        source_a, source_b = source_pair.split("|", 1)
        where.append("c.source_a = ? AND c.source_b = ?")
        params.extend([source_a, source_b])
    if min_numeric > 0:
        where.append("c.numeric_mismatches >= ?")
        params.append(min_numeric)
    if min_ocr > 0:
        where.append("c.ocr_uncertain >= ?")
        params.append(min_ocr)
    if min_missing > 0:
        where.append("c.missing_fields >= ?")
        params.append(min_missing)
    if result == "not_match":
        where.append(
            "EXISTS (SELECT 1 FROM source_field_comparisons f "
            "WHERE f.comparison_id = c.id AND f.result != 'match')"
        )
    elif result not in ("all", ""):
        where.append(
            "EXISTS (SELECT 1 FROM source_field_comparisons f "
            "WHERE f.comparison_id = c.id AND f.result = ?)"
        )
        params.append(result)
    if field_key != "all":
        where.append(
            "EXISTS (SELECT 1 FROM source_field_comparisons f "
            "WHERE f.comparison_id = c.id AND f.field_key = ?)"
        )
        params.append(field_key)
    if search:
        like = f"%{search}%"
        where.append("(c.mesa_key LIKE ? OR c.source_a LIKE ? OR c.source_b LIKE ?)")
        params.extend([like, like, like])

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    return where_sql, params


def comparison_order_sql(query: dict[str, list[str]]) -> str:
    sort = query_value(query, "sort", "priority")
    options = {
        "priority": (
            "CASE c.status WHEN 'needs_review' THEN 0 ELSE 1 END, "
            "c.numeric_mismatches DESC, c.ocr_uncertain DESC, c.missing_fields DESC, c.mesa_key"
        ),
        "mesa": "c.mesa_key",
        "numeric": "c.numeric_mismatches DESC, c.ocr_uncertain DESC, c.mesa_key",
        "ocr": "c.ocr_uncertain DESC, c.numeric_mismatches DESC, c.mesa_key",
        "missing": "c.missing_fields DESC, c.mesa_key",
        "updated": "c.updated_at DESC, c.mesa_key",
    }
    return options.get(sort, options["priority"])


def comparison_options(conn: sqlite3.Connection) -> dict[str, Any]:
    pairs = [
        {
            "value": f"{row['source_a']}|{row['source_b']}",
            "label": f"{row['source_a']} vs {row['source_b']}",
            "count": row["count"],
        }
        for row in conn.execute(
            """
            SELECT source_a, source_b, COUNT(*) AS count
            FROM source_comparisons
            GROUP BY source_a, source_b
            ORDER BY source_a, source_b
            """
        ).fetchall()
    ]
    fields = [
        {
            "value": row["field_key"],
            "label": row["field_label"] or row["field_key"],
            "count": row["count"],
        }
        for row in conn.execute(
            """
            SELECT field_key, MAX(field_label) AS field_label, COUNT(*) AS count
            FROM source_field_comparisons
            GROUP BY field_key
            ORDER BY field_key
            """
        ).fetchall()
    ]
    return {"pairs": pairs, "fields": fields}


def comparison_data_snapshot(app: AppState, query: dict[str, list[str]]) -> dict[str, Any]:
    if not app.source_db.exists():
        return {"rows": [], "totals": {"comparisons": 0}, "filtered": {"comparisons": 0}, "options": {}}

    where_sql, params = comparison_filter_sql(query)
    limit = max(1, min(query_int(query, "limit", 1000), 5000))
    sql = f"""
        SELECT c.id, c.mesa_key, c.source_a, c.source_b, c.status,
               c.numeric_mismatches, c.visual_mismatches, c.ocr_uncertain,
               c.missing_fields, c.updated_at
        FROM source_comparisons c
        {where_sql}
        ORDER BY {comparison_order_sql(query)}
        LIMIT ?
    """
    conn = connect_source_db(app.source_db)
    try:
        rows = [row_dict(row) for row in conn.execute(sql, [*params, limit]).fetchall()]
        filtered = row_dict(
            conn.execute(
                f"""
                SELECT COUNT(*) AS comparisons,
                       COALESCE(SUM(numeric_mismatches), 0) AS numeric_mismatches,
                       COALESCE(SUM(ocr_uncertain), 0) AS ocr_uncertain,
                       COALESCE(SUM(missing_fields), 0) AS missing_fields
                FROM source_comparisons c
                {where_sql}
                """,
                params,
            ).fetchone()
        )
        totals = row_dict(
            conn.execute(
                """
                SELECT COUNT(*) AS comparisons,
                       COALESCE(SUM(numeric_mismatches), 0) AS numeric_mismatches,
                       COALESCE(SUM(ocr_uncertain), 0) AS ocr_uncertain,
                       COALESCE(SUM(missing_fields), 0) AS missing_fields
                FROM source_comparisons
                """
            ).fetchone()
        )
        options = comparison_options(conn)
    finally:
        conn.close()
    return {"rows": rows, "totals": totals, "filtered": filtered, "options": options}


def comparison_report_csv(app: AppState, query: dict[str, list[str]]) -> tuple[bytes, str]:
    where_sql, params = comparison_filter_sql(query)
    kind = query_value(query, "kind", "fields")
    result = query_value(query, "result", "not_match")
    field_key = query_value(query, "field", "all")
    output = io.StringIO()
    writer = csv.writer(output)
    conn = connect_source_db(app.source_db)
    try:
        if kind == "summary":
            rows = conn.execute(
                f"""
                SELECT c.mesa_key, c.source_a, c.source_b, c.status,
                       c.numeric_mismatches, c.visual_mismatches, c.ocr_uncertain,
                       c.missing_fields, c.summary_json, c.updated_at
                FROM source_comparisons c
                {where_sql}
                ORDER BY {comparison_order_sql(query)}
                """,
                params,
            ).fetchall()
            writer.writerow(
                [
                    "mesa_key",
                    "source_a",
                    "source_b",
                    "status",
                    "numeric_mismatches",
                    "visual_mismatches",
                    "ocr_uncertain",
                    "missing_fields",
                    "summary_json",
                    "updated_at",
                ]
            )
            for row in rows:
                writer.writerow([row[key] for key in row.keys()])
            return output.getvalue().encode("utf-8-sig"), "comparaciones_filtradas.csv"

        field_where = []
        field_params: list[Any] = []
        if result == "not_match":
            field_where.append("f.result != 'match'")
        elif result not in ("all", ""):
            field_where.append("f.result = ?")
            field_params.append(result)
        if field_key != "all":
            field_where.append("f.field_key = ?")
            field_params.append(field_key)
        if field_where and where_sql:
            field_filter_sql = f" AND {' AND '.join(field_where)}"
        elif field_where:
            field_filter_sql = f"WHERE {' AND '.join(field_where)}"
        else:
            field_filter_sql = ""
        rows = conn.execute(
            f"""
            SELECT c.mesa_key, c.source_a, c.source_b, c.status AS comparison_status,
                   f.field_key, f.field_label, f.value_a, f.value_b,
                   f.confidence_a, f.confidence_b, f.visual_score,
                   f.result, f.details_json
            FROM source_field_comparisons f
            JOIN source_comparisons c ON c.id = f.comparison_id
            {where_sql}
            {field_filter_sql}
            ORDER BY {comparison_order_sql(query)}, f.result, f.field_key
            """,
            [*params, *field_params],
        ).fetchall()
        writer.writerow(
            [
                "mesa_key",
                "source_a",
                "source_b",
                "comparison_status",
                "field_key",
                "field_label",
                "value_a",
                "value_b",
                "confidence_a",
                "confidence_b",
                "visual_score",
                "result",
                "details_json",
            ]
        )
        for row in rows:
            writer.writerow([row[key] for key in row.keys()])
    finally:
        conn.close()
    return output.getvalue().encode("utf-8-sig"), "hallazgos_filtrados.csv"


def comparison_detail_snapshot(app: AppState, comparison_id: int) -> dict[str, Any] | None:
    if not app.source_db.exists():
        return None

    conn = connect_source_db(app.source_db)
    try:
        row = conn.execute(
            """
            SELECT c.*, a.relative_path AS a_relative_path, a.absolute_path AS a_absolute_path,
                   b.relative_path AS b_relative_path, b.absolute_path AS b_absolute_path
            FROM source_comparisons c
            JOIN source_documents a ON a.id = c.source_document_a_id
            JOIN source_documents b ON b.id = c.source_document_b_id
            WHERE c.id = ?
            """,
            (comparison_id,),
        ).fetchone()
        if row is None:
            return None
        comparison = row_dict(row)
        fields = [
            row_dict(field)
            for field in conn.execute(
                """
                SELECT field_key, field_label, value_a, value_b,
                       confidence_a, confidence_b, visual_score, result,
                       details_json
                FROM source_field_comparisons
                WHERE comparison_id = ?
                ORDER BY CASE result
                    WHEN 'numeric_mismatch' THEN 0
                    WHEN 'ocr_uncertain' THEN 1
                    WHEN 'missing_field' THEN 2
                    WHEN 'visual_mismatch' THEN 3
                    ELSE 4
                  END,
                  field_key
                """,
                (comparison_id,),
            ).fetchall()
        ]
    finally:
        conn.close()

    source_a_id = int(comparison["source_document_a_id"])
    source_b_id = int(comparison["source_document_b_id"])
    return {
        "comparison": {
            "id": comparison["id"],
            "mesa_key": comparison["mesa_key"],
            "source_a": comparison["source_a"],
            "source_b": comparison["source_b"],
            "status": comparison["status"],
            "numeric_mismatches": comparison["numeric_mismatches"],
            "visual_mismatches": comparison["visual_mismatches"],
            "ocr_uncertain": comparison["ocr_uncertain"],
            "missing_fields": comparison["missing_fields"],
            "updated_at": comparison["updated_at"],
        },
        "source_a": {
            "id": source_a_id,
            "relative_path": comparison["a_relative_path"],
            "absolute_path": comparison["a_absolute_path"],
            "pdf_url": f"/comparaciones/pdf?doc_id={source_a_id}",
        },
        "source_b": {
            "id": source_b_id,
            "relative_path": comparison["b_relative_path"],
            "absolute_path": comparison["b_absolute_path"],
            "pdf_url": f"/comparaciones/pdf?doc_id={source_b_id}",
        },
        "fields": fields,
    }


def source_document_path(app: AppState, document_id: int) -> Path | None:
    if not app.source_db.exists():
        return None
    conn = connect_source_db(app.source_db)
    try:
        row = conn.execute(
            "SELECT absolute_path FROM source_documents WHERE id = ?",
            (document_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return Path(row["absolute_path"])


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


class ReviewHandler(BaseHTTPRequestHandler):
    server_version = "E14InconsistencyReview/1.0"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self.respond_html(MESA_REVIEW_HTML)
            return
        if parsed.path == "/inconsistencias":
            self.respond_html(HTML)
            return
        if parsed.path == "/comparaciones":
            self.respond_redirect("/")
            return
        if parsed.path == "/mesas/data":
            query = urllib.parse.parse_qs(parsed.query)
            self.respond_json(mesa_review_rows(self.app, query))
            return
        if parsed.path == "/mesas/detalle":
            query = urllib.parse.parse_qs(parsed.query)
            mesa_key = query.get("mesa_key", [""])[0]
            scope = query.get("scope", ["comparison:claveros|delegados"])[0]
            if not mesa_key:
                self.send_error(400, "Falta mesa_key")
                return
            detail = mesa_review_detail(self.app, mesa_key, scope)
            if detail is None:
                self.send_error(404)
                return
            self.respond_json(detail)
            return
        if parsed.path == "/mesas/reporte":
            query = urllib.parse.parse_qs(parsed.query)
            data, filename = mesa_review_report_csv(self.app, query)
            self.respond_csv(data, filename)
            return
        if parsed.path == "/mesas/pdf":
            query = urllib.parse.parse_qs(parsed.query)
            try:
                document_id = int(query.get("doc_id", ["0"])[0])
            except ValueError:
                self.send_error(400)
                return
            document_path = source_document_path(self.app, document_id)
            if document_path is None:
                self.send_error(404)
                return
            self.respond_project_file(document_path, [DEFAULT_SOURCE_DOWNLOADS])
            return
        if parsed.path == "/comparaciones/data":
            query = urllib.parse.parse_qs(parsed.query)
            self.respond_json(comparison_data_snapshot(self.app, query))
            return
        if parsed.path == "/comparaciones/reporte":
            query = urllib.parse.parse_qs(parsed.query)
            data, filename = comparison_report_csv(self.app, query)
            self.respond_csv(data, filename)
            return
        if parsed.path == "/comparaciones/detalle":
            query = urllib.parse.parse_qs(parsed.query)
            try:
                comparison_id = int(query.get("id", ["0"])[0])
            except ValueError:
                self.send_error(400)
                return
            comparison = comparison_detail_snapshot(self.app, comparison_id)
            if comparison is None:
                self.send_error(404)
                return
            self.respond_json(comparison)
            return
        if parsed.path == "/comparaciones/pdf":
            query = urllib.parse.parse_qs(parsed.query)
            try:
                document_id = int(query.get("doc_id", ["0"])[0])
            except ValueError:
                self.send_error(400)
                return
            document_path = source_document_path(self.app, document_id)
            if document_path is None:
                self.send_error(404)
                return
            self.respond_project_file(document_path, [DEFAULT_SOURCE_DOWNLOADS])
            return
        if parsed.path == "/data":
            query = urllib.parse.parse_qs(parsed.query)
            self.respond_data(force_refresh=query.get("refresh", ["0"])[0] == "1")
            return
        if parsed.path == "/status":
            self.respond_json(status_snapshot(self.app))
            return
        if parsed.path == "/document":
            query = urllib.parse.parse_qs(parsed.query)
            key = query.get("key", [""])[0]
            document = document_snapshot(self.app, key)
            if document is None:
                self.send_error(404)
                return
            self.respond_json(document)
            return
        if parsed.path == "/pdf":
            query = urllib.parse.parse_qs(parsed.query)
            relative_path = query.get("path", [""])[0]
            self.respond_project_file(absolute_pdf_path(self.app.downloads_root, relative_path), [self.app.downloads_root])
            return
        if parsed.path == "/file":
            query = urllib.parse.parse_qs(parsed.query)
            raw_path = query.get("path", [""])[0]
            self.respond_project_file(Path(raw_path), [ROOT])
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/mesas/review":
            self.handle_mesa_review()
            return
        if parsed.path == "/review":
            self.handle_review()
            return
        if parsed.path == "/fraud":
            self.handle_fraud()
            return
        self.send_error(404)

    def handle_mesa_review(self) -> None:
        payload = self.read_json()
        mesa_key = str(payload.get("mesa_key", ""))
        scope = str(payload.get("scope", "comparison:claveros|delegados"))
        status = str(payload.get("status", "pending"))
        note = str(payload.get("note", ""))
        if not mesa_key:
            self.send_error(400, "Falta mesa_key")
            return
        if status not in {"pending", "reviewed", "fraud", "ignored"}:
            self.send_error(400, "Estado invalido")
            return
        scope_type, source_a, source_b = parse_review_scope(scope)
        review = upsert_review_status(
            self.app.source_db,
            mesa_key,
            scope_type,
            source_a,
            source_b,
            status,
            note,
        )
        self.respond_json({"review": review})

    def handle_review(self) -> None:
        payload = self.read_json()
        key = str(payload.get("key", ""))
        if not key:
            self.send_error(400, "Falta key")
            return
        reviewed = bool(payload.get("reviewed"))
        note = str(payload.get("note", ""))
        now = datetime.now(timezone.utc).isoformat()
        with self.app.lock:
            reviews = load_reviews(self.app.reviews)
            reviews[key] = {"reviewed": reviewed, "note": note, "updated_at": now}
            write_reviews(self.app.reviews, reviews)
        self.respond_json({"reviews": reviews})

    def handle_fraud(self) -> None:
        payload = self.read_json()
        key = str(payload.get("relative_path", "") or payload.get("document_key", ""))
        if not key:
            self.send_error(400, "Falta relative_path")
            return
        fraud = bool(payload.get("fraud"))
        now = datetime.now(timezone.utc).isoformat()
        with self.app.lock:
            frauds = load_frauds(self.app.frauds)
            if fraud:
                previous = frauds.get(key, {})
                frauds[key] = {
                    "status": "FRAUDE",
                    "document_id": str(payload.get("document_id", "")),
                    "relative_path": str(payload.get("relative_path", "")),
                    "absolute_pdf_path": str(payload.get("absolute_pdf_path", "")),
                    "department_name": str(payload.get("department_name", "")),
                    "municipality_name": str(payload.get("municipality_name", "")),
                    "zone_code": str(payload.get("zone_code", "")),
                    "place_name": str(payload.get("place_name", "")),
                    "table_number": str(payload.get("table_number", "")),
                    "reported_from_code": str(payload.get("reported_from_code", "")),
                    "reported_from_message": str(payload.get("reported_from_message", "")),
                    "note": str(payload.get("note", "")),
                    "reported_at": previous.get("reported_at") or now,
                    "updated_at": now,
                }
            else:
                frauds.pop(key, None)
            write_frauds(self.app.frauds, frauds)
        self.respond_json({"frauds": frauds})

    @property
    def app(self) -> AppState:
        return self.server.app_state  # type: ignore[attr-defined]

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length)
        return json.loads(data.decode("utf-8"))

    def respond_html(self, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def respond_redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def respond_json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        accepts_gzip = "gzip" in self.headers.get("Accept-Encoding", "").lower()
        if accepts_gzip:
            data = gzip.compress(data)
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Vary", "Accept-Encoding")
        if accepts_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def respond_csv(self, data: bytes, filename: str) -> None:
        encoded_filename = urllib.parse.quote(filename, safe="")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f"attachment; filename=\"{filename}\"; filename*=UTF-8''{encoded_filename}")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def respond_data(self, force_refresh: bool = False) -> None:
        accepts_gzip = "gzip" in self.headers.get("Accept-Encoding", "").lower()
        data, is_gzip = data_response_bytes(self.app, accepts_gzip, force_refresh=force_refresh)
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Vary", "Accept-Encoding")
        if is_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def respond_project_file(self, path: Path, allowed_roots: list[Path]) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            self.send_error(404)
            return
        if not any(is_under(resolved, root) for root in allowed_roots):
            self.send_error(403)
            return
        if not resolved.exists() or not resolved.is_file():
            self.send_error(404)
            return
        self.respond_file(resolved)

    def respond_file(self, path: Path) -> None:
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        content_disposition = self.content_disposition_for(path)
        file_size = path.stat().st_size
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            start, end = self.parse_range(range_header, file_size)
            if start is None:
                self.send_error(416)
                return
            self.send_response(206)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", content_disposition)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            self.stream_file(path, start, end)
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", content_disposition)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(file_size))
        self.end_headers()
        self.stream_file(path, 0, file_size - 1)

    def content_disposition_for(self, path: Path) -> str:
        filename = path.name or "documento.pdf"
        ascii_filename = "".join(
            char if 32 <= ord(char) < 127 and char not in {'"', "\\", "/"} else "_"
            for char in filename
        ).strip() or "documento.pdf"
        encoded_filename = urllib.parse.quote(filename, safe="")
        return f"inline; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"

    def parse_range(self, value: str, file_size: int) -> tuple[int | None, int | None]:
        raw = value.removeprefix("bytes=").split(",", 1)[0].strip()
        if "-" not in raw:
            return None, None
        start_text, end_text = raw.split("-", 1)
        try:
            if start_text == "":
                suffix = int(end_text)
                start = max(0, file_size - suffix)
                end = file_size - 1
            else:
                start = int(start_text)
                end = int(end_text) if end_text else file_size - 1
        except ValueError:
            return None, None
        if start < 0 or start >= file_size or end < start:
            return None, None
        return start, min(end, file_size - 1)

    def stream_file(self, path: Path, start: int, end: int) -> None:
        remaining = end - start + 1
        with path.open("rb") as handle:
            handle.seek(start)
            while remaining > 0:
                chunk = handle.read(min(1024 * 512, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def log_message(self, format: str, *args: Any) -> None:
        return


class ReviewServer(ThreadingHTTPServer):
    app_state: AppState


def create_server(host: str, port: int) -> ReviewServer:
    return ReviewServer((host, port), ReviewHandler)


def serve(args: argparse.Namespace) -> None:
    init_review_status_schema(args.source_db.resolve())
    app_state = AppState(
        inconsistencies=args.inconsistencies.resolve(),
        summary=args.summary.resolve(),
        fields=args.fields.resolve(),
        reviews=args.reviews.resolve(),
        frauds=args.frauds.resolve(),
        downloads_root=args.downloads_root.resolve(),
        source_db=args.source_db.resolve(),
        lock=threading.Lock(),
    )
    try:
        server = create_server(args.host, args.port)
    except OSError:
        server = create_server(args.host, 0)
    server.app_state = app_state
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}/"
    print(f"Revisor: {url}")
    print(f"Inconsistencias: {app_state.inconsistencies}")
    print(f"Reviews: {app_state.reviews}")
    print(f"Fraude: {app_state.frauds}")
    print(f"PDFs: {app_state.downloads_root}")
    print(f"Comparaciones DB: {app_state.source_db}")
    if args.open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido.")
    finally:
        server.server_close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Visor local de inconsistencias OCR E14.")
    parser.add_argument("--inconsistencies", type=Path, default=DEFAULT_INCONSISTENCIES)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--fields", type=Path, default=DEFAULT_FIELDS)
    parser.add_argument("--reviews", type=Path, default=DEFAULT_REVIEWS)
    parser.add_argument("--frauds", type=Path, default=DEFAULT_FRAUDS)
    parser.add_argument("--downloads-root", type=Path, default=DEFAULT_DOWNLOADS)
    parser.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE_DB)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-open", dest="open_browser", action="store_false")
    parser.set_defaults(open_browser=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.inconsistencies.exists():
        print(f"No existe inconsistencias: {args.inconsistencies.resolve()}")
        return 2
    if not args.downloads_root.exists():
        print(f"No existe carpeta de PDFs: {args.downloads_root.resolve()}")
        return 2
    serve(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
