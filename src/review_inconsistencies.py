from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import mimetypes
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
DEFAULT_DOWNLOADS = ROOT / "downloads" / "E14"
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


@dataclass
class AppState:
    inconsistencies: Path
    summary: Path
    fields: Path
    reviews: Path
    frauds: Path
    downloads_root: Path
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
            self.respond_html(HTML)
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
        if parsed.path == "/review":
            self.handle_review()
            return
        if parsed.path == "/fraud":
            self.handle_fraud()
            return
        self.send_error(404)

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
    app_state = AppState(
        inconsistencies=args.inconsistencies.resolve(),
        summary=args.summary.resolve(),
        fields=args.fields.resolve(),
        reviews=args.reviews.resolve(),
        frauds=args.frauds.resolve(),
        downloads_root=args.downloads_root.resolve(),
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
