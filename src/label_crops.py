from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "reports" / "ocr" / "labeling" / "manifest.csv"
DEFAULT_LABELS = ROOT / "reports" / "ocr" / "labeling" / "labels.csv"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


HTML = r"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Etiquetador E14</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #5d6773;
      --line: #d8dee6;
      --accent: #0b6bcb;
      --accent-ink: #ffffff;
      --danger: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--ink);
      letter-spacing: 0;
    }
    header {
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 18px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1 {
      font-size: 18px;
      line-height: 1.2;
      margin: 0;
      font-weight: 700;
    }
    main {
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      min-height: calc(100vh - 56px);
    }
    aside {
      padding: 16px;
      border-right: 1px solid var(--line);
      background: var(--panel);
    }
    section {
      padding: 18px;
      min-width: 0;
    }
    label {
      display: block;
      font-size: 12px;
      font-weight: 700;
      color: var(--muted);
      margin: 14px 0 6px;
    }
    select, input {
      width: 100%;
      height: 38px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      padding: 0 10px;
      border-radius: 6px;
      font-size: 15px;
    }
    .row {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    button {
      height: 38px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      padding: 0 12px;
      border-radius: 6px;
      font-size: 14px;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }
    button.primary {
      background: var(--accent);
      color: var(--accent-ink);
      border-color: var(--accent);
    }
    button.danger {
      color: var(--danger);
    }
    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .stats {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 14px;
    }
    .stat {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #fafbfc;
    }
    .stat strong {
      display: block;
      font-size: 20px;
    }
    .stat span {
      display: block;
      font-size: 12px;
      color: var(--muted);
      margin-top: 2px;
    }
    .workspace {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 340px;
      gap: 18px;
      align-items: start;
    }
    .image-stage {
      min-height: 360px;
      border: 1px solid var(--line);
      background: #fff;
      display: grid;
      place-items: center;
      overflow: auto;
      border-radius: 6px;
      padding: 18px;
    }
    .image-stage img {
      max-width: 100%;
      height: auto;
      image-rendering: auto;
      transform-origin: center;
    }
    .detail {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 6px;
      padding: 14px;
    }
    .detail h2 {
      margin: 0 0 8px;
      font-size: 17px;
      line-height: 1.25;
    }
    .meta {
      font-size: 13px;
      color: var(--muted);
      line-height: 1.45;
      overflow-wrap: anywhere;
    }
    .actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 12px;
    }
    .actions .wide { grid-column: 1 / -1; }
    .status {
      color: var(--muted);
      font-size: 13px;
      min-height: 18px;
      margin-top: 10px;
    }
    .progress {
      height: 8px;
      background: #e8edf3;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 10px;
    }
    .bar {
      height: 100%;
      background: var(--accent);
      width: 0%;
    }
    @media (max-width: 860px) {
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      .workspace { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Etiquetador E14</h1>
    <div class="meta" id="saveState">Cargando</div>
  </header>
  <main>
    <aside>
      <label for="fieldFilter">Campo</label>
      <select id="fieldFilter"></select>

      <label for="statusFilter">Estado</label>
      <select id="statusFilter">
        <option value="unlabeled">Sin etiqueta</option>
        <option value="all">Todos</option>
        <option value="labeled">Etiquetados</option>
        <option value="skipped">Saltados</option>
      </select>

      <label for="jumpInput">Ir a</label>
      <div class="row">
        <input id="jumpInput" inputmode="numeric" autocomplete="off">
        <button id="jumpBtn">Ir</button>
      </div>

      <div class="stats">
        <div class="stat"><strong id="doneCount">0</strong><span>Etiquetados</span></div>
        <div class="stat"><strong id="leftCount">0</strong><span>Pendientes</span></div>
      </div>
      <div class="progress"><div class="bar" id="progressBar"></div></div>

      <label for="zoomRange">Zoom</label>
      <input id="zoomRange" type="range" min="80" max="260" value="140">
    </aside>

    <section>
      <div class="workspace">
        <div class="image-stage">
          <img id="cropImage" alt="Recorte">
        </div>
        <div class="detail">
          <h2 id="fieldTitle">Campo</h2>
          <div class="meta" id="docMeta"></div>

          <label for="valueInput">Valor</label>
          <input id="valueInput" inputmode="numeric" autocomplete="off" autofocus>

          <div class="actions">
            <button id="prevBtn">Anterior</button>
            <button id="nextBtn">Siguiente</button>
            <button id="skipBtn">Saltar</button>
            <button id="clearBtn" class="danger">Limpiar</button>
            <button id="saveBtn" class="primary wide">Guardar</button>
          </div>
          <div class="status" id="message"></div>
        </div>
      </div>
    </section>
  </main>

  <script>
    const state = {
      rows: [],
      labels: {},
      filtered: [],
      current: 0,
      zoom: 140
    };

    const $ = (id) => document.getElementById(id);

    function labelKey(row) {
      return `${row.document_id}|${row.field_key}`;
    }

    async function api(path, options) {
      const response = await fetch(path, options);
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || response.statusText);
      }
      return response.json();
    }

    function populateFields() {
      const fields = Array.from(new Set(state.rows.map((row) => row.field_key)));
      const select = $("fieldFilter");
      select.innerHTML = '<option value="all">Todos</option>' + fields.map((field) => {
        const row = state.rows.find((item) => item.field_key === field);
        return `<option value="${field}">${row.field_label || field}</option>`;
      }).join("");
    }

    function applyFilters() {
      const field = $("fieldFilter").value;
      const status = $("statusFilter").value;
      state.filtered = state.rows.filter((row) => {
        const label = state.labels[labelKey(row)];
        if (field !== "all" && row.field_key !== field) return false;
        if (status === "unlabeled") return !label || (!label.value && !label.skipped);
        if (status === "labeled") return !!label && !!label.value && !label.skipped;
        if (status === "skipped") return !!label && !!label.skipped;
        return true;
      });
      state.current = Math.min(state.current, Math.max(0, state.filtered.length - 1));
      render();
    }

    function currentRow() {
      return state.filtered[state.current] || null;
    }

    function renderStats() {
      const total = state.rows.length;
      const labeled = state.rows.filter((row) => {
        const label = state.labels[labelKey(row)];
        return label && label.value && !label.skipped;
      }).length;
      $("doneCount").textContent = labeled;
      $("leftCount").textContent = Math.max(0, total - labeled);
      $("progressBar").style.width = total ? `${Math.round((labeled / total) * 100)}%` : "0%";
      $("saveState").textContent = `${labeled}/${total}`;
    }

    function render() {
      renderStats();
      const row = currentRow();
      if (!row) {
        $("fieldTitle").textContent = "Sin elementos";
        $("docMeta").textContent = "";
        $("cropImage").removeAttribute("src");
        $("valueInput").value = "";
        return;
      }

      const label = state.labels[labelKey(row)] || {};
      $("fieldTitle").textContent = row.field_label || row.field_key;
      $("docMeta").innerHTML = [
        `#${state.current + 1} de ${state.filtered.length}`,
        `Documento ${row.document_id}`,
        row.relative_path
      ].join("<br>");
      $("cropImage").src = `/image?path=${encodeURIComponent(row.crop_path)}`;
      $("cropImage").style.width = `${state.zoom}%`;
      $("valueInput").value = label.skipped ? "" : (label.value || "");
      $("jumpInput").value = state.current + 1;
      $("message").textContent = label.skipped ? "Saltado" : "";
      window.setTimeout(() => $("valueInput").focus(), 0);
    }

    async function saveValue(value, skipped = false) {
      const row = currentRow();
      if (!row) return;
      const clean = String(value || "").replace(/\D+/g, "");
      const payload = {
        document_id: row.document_id,
        relative_path: row.relative_path,
        field_key: row.field_key,
        field_label: row.field_label,
        field_role: row.field_role,
        crop_path: row.crop_path,
        value: skipped ? "" : clean,
        skipped
      };
      const result = await api("/label", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
      state.labels = result.labels;
      $("message").textContent = skipped ? "Saltado" : "Guardado";
      nextItem();
    }

    function nextItem() {
      if (state.current < state.filtered.length - 1) {
        state.current += 1;
      }
      render();
    }

    function prevItem() {
      if (state.current > 0) {
        state.current -= 1;
      }
      render();
    }

    async function clearCurrent() {
      const row = currentRow();
      if (!row) return;
      const result = await api("/label", {
        method: "DELETE",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({document_id: row.document_id, field_key: row.field_key})
      });
      state.labels = result.labels;
      $("message").textContent = "Limpio";
      render();
    }

    async function init() {
      const data = await api("/data");
      state.rows = data.rows;
      state.labels = data.labels;
      populateFields();
      applyFilters();
    }

    $("fieldFilter").addEventListener("change", applyFilters);
    $("statusFilter").addEventListener("change", applyFilters);
    $("zoomRange").addEventListener("input", (event) => {
      state.zoom = Number(event.target.value);
      $("cropImage").style.width = `${state.zoom}%`;
    });
    $("saveBtn").addEventListener("click", () => saveValue($("valueInput").value));
    $("skipBtn").addEventListener("click", () => saveValue("", true));
    $("clearBtn").addEventListener("click", clearCurrent);
    $("nextBtn").addEventListener("click", nextItem);
    $("prevBtn").addEventListener("click", prevItem);
    $("jumpBtn").addEventListener("click", () => {
      const target = Math.max(1, Number($("jumpInput").value || 1));
      state.current = Math.min(target - 1, Math.max(0, state.filtered.length - 1));
      render();
    });
    $("valueInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        saveValue($("valueInput").value);
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.target === $("valueInput") || event.target === $("jumpInput")) return;
      if (event.key === "ArrowRight") nextItem();
      if (event.key === "ArrowLeft") prevItem();
      if (event.key.toLowerCase() === "s") saveValue("", true);
    });

    init().catch((error) => {
      $("saveState").textContent = "Error";
      $("message").textContent = error.message;
    });
  </script>
</body>
</html>
"""


@dataclass
class AppState:
    manifest: Path
    labels: Path
    rows: list[dict[str, str]]
    lock: threading.Lock


def load_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def label_key(document_id: str, field_key: str) -> str:
    return f"{document_id}|{field_key}"


def load_labels(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    labels: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = label_key(row["document_id"], row["field_key"])
        labels[key] = {
            "value": row.get("value", ""),
            "skipped": row.get("skipped", "").lower() in ("1", "true", "yes", "si"),
        }
    return labels


def write_labels(path: Path, labels: dict[str, dict[str, Any]], rows_by_key: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "document_id",
        "relative_path",
        "field_key",
        "field_label",
        "field_role",
        "crop_path",
        "value",
        "skipped",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for key in sorted(labels.keys(), key=lambda item: (int(item.split("|", 1)[0]), item.split("|", 1)[1])):
            row = rows_by_key.get(key, {})
            label = labels[key]
            writer.writerow(
                {
                    "document_id": row.get("document_id", key.split("|", 1)[0]),
                    "relative_path": row.get("relative_path", ""),
                    "field_key": row.get("field_key", key.split("|", 1)[1]),
                    "field_label": row.get("field_label", ""),
                    "field_role": row.get("field_role", ""),
                    "crop_path": row.get("crop_path", ""),
                    "value": label.get("value", ""),
                    "skipped": "1" if label.get("skipped") else "0",
                }
            )


class LabelHandler(BaseHTTPRequestHandler):
    server_version = "E14Labeler/1.0"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self.respond_html(HTML)
            return
        if parsed.path == "/data":
            labels = load_labels(self.app.labels)
            self.respond_json({"rows": self.app.rows, "labels": labels})
            return
        if parsed.path == "/image":
            query = urllib.parse.parse_qs(parsed.query)
            raw_path = query.get("path", [""])[0]
            self.respond_file(Path(raw_path))
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if urllib.parse.urlparse(self.path).path != "/label":
            self.send_error(404)
            return
        payload = self.read_json()
        value = "".join(ch for ch in str(payload.get("value", "")) if ch.isdigit())
        skipped = bool(payload.get("skipped"))
        key = label_key(str(payload["document_id"]), str(payload["field_key"]))
        rows_by_key = {
            label_key(str(row["document_id"]), str(row["field_key"])): row
            for row in self.app.rows
        }
        with self.app.lock:
            labels = load_labels(self.app.labels)
            labels[key] = {"value": value, "skipped": skipped}
            write_labels(self.app.labels, labels, rows_by_key)
        self.respond_json({"labels": labels})

    def do_DELETE(self) -> None:
        if urllib.parse.urlparse(self.path).path != "/label":
            self.send_error(404)
            return
        payload = self.read_json()
        key = label_key(str(payload["document_id"]), str(payload["field_key"]))
        rows_by_key = {
            label_key(str(row["document_id"]), str(row["field_key"])): row
            for row in self.app.rows
        }
        with self.app.lock:
            labels = load_labels(self.app.labels)
            labels.pop(key, None)
            write_labels(self.app.labels, labels, rows_by_key)
        self.respond_json({"labels": labels})

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
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def respond_file(self, path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            self.send_error(404)
            return
        if not resolved.exists() or not resolved.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        data = resolved.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        return


class LabelServer(ThreadingHTTPServer):
    app_state: AppState


def create_server(host: str, port: int) -> LabelServer:
    if port:
        return LabelServer((host, port), LabelHandler)
    return LabelServer((host, 0), LabelHandler)


def serve(manifest: Path, labels: Path, host: str, port: int, open_browser: bool) -> None:
    rows = load_manifest(manifest)
    app_state = AppState(manifest=manifest, labels=labels, rows=rows, lock=threading.Lock())
    try:
        server = create_server(host, port)
    except PermissionError:
        server = create_server(host, 0)
    server.app_state = app_state
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}/"
    print(f"Etiquetador: {url}")
    print(f"Manifest: {manifest}")
    print(f"Labels: {labels}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido.")
    finally:
        server.server_close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Etiquetador local de recortes E14.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-open", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest = args.manifest.resolve()
    labels = args.labels.resolve()
    if not manifest.exists():
        print(f"No existe manifest: {manifest}")
        return 2
    serve(manifest, labels, args.host, args.port, not args.no_open)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
