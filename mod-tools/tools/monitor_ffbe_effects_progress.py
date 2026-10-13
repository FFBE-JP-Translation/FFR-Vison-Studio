#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import webbrowser
from collections import Counter, deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _to_int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        if value is None:
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        return int(value)
    except Exception:
        return 0


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        # epoch seconds
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(value, str):
        try:
            if value.endswith("Z"):
                return datetime.fromisoformat(value[:-1] + "+00:00")
            return datetime.fromisoformat(value)
        except Exception:
            return None
    return None


def _tail_lines(path: Path, count: int) -> List[str]:
    if not path.exists() or count <= 0:
        return []
    dq: deque[str] = deque(maxlen=count)
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                dq.append(line.rstrip("\n"))
    except Exception:
        return []
    return list(dq)


def _error_counts(errors_obj: Optional[Any]) -> Dict[str, int]:
    if not isinstance(errors_obj, dict):
        return {}
    counts: Counter[str] = Counter()
    for key, value in errors_obj.items():
        if key == "form":
            continue
        if isinstance(value, dict):
            counts[key] = len(value)
        elif isinstance(value, list):
            counts[key] = len(value)
        elif value is None:
            counts[key] = 0
        else:
            counts[key] = 1
    return dict(counts)


def load_progress(run_dir: Path, error_lines: int = 15) -> Dict[str, Any]:
    catalog_path = run_dir / "catalog-conversion.json"
    worker_path = run_dir / "worker.json"

    catalog: Optional[Dict[str, Any]] = None
    worker: Optional[Dict[str, Any]] = None

    if catalog_path.exists():
        try:
            with catalog_path.open("r", encoding="utf-8") as f:
                catalog = json.load(f)
        except Exception:
            catalog = None

    if worker_path.exists():
        try:
            with worker_path.open("r", encoding="utf-8") as f:
                worker = json.load(f)
        except Exception:
            worker = None

    now = datetime.now(timezone.utc)
    summary = catalog.get("summary", {}) if isinstance(catalog, dict) else {}

    selected_forms = _to_int(summary.get("selectedForms"))
    processed_forms = _to_int(summary.get("processedForms"))
    bundled_forms = _to_int(summary.get("bundledForms"))
    failed_forms = _to_int(summary.get("failedForms"))
    active_moves = _to_int(summary.get("activeMoveMemberships"))
    ready_moves = _to_int(summary.get("readyMoveMemberships"))
    prepared_moves = _to_int(summary.get("preparedMoveMemberships"))
    failed_moves = _to_int(summary.get("failedMoveMemberships"))

    started_at = _parse_time(worker.get("startedUtc") if worker else None)
    updated_at = _parse_time(worker.get("processStartedUtc") if worker else None)
    elapsed_seconds = (
        max((now - started_at).total_seconds(), 0.0) if started_at else None
    )

    # Throughput is based on the overall selected run duration.
    forms_per_min = (
        (processed_forms / (elapsed_seconds / 60.0)) if elapsed_seconds and elapsed_seconds > 0 else 0.0
    )
    moves_per_min = (
        (prepared_moves / (elapsed_seconds / 60.0)) if elapsed_seconds and elapsed_seconds > 0 else 0.0
    )
    eta_seconds = (
        ((selected_forms - processed_forms) / (forms_per_min / 60.0))
        if selected_forms > 0 and forms_per_min > 0
        else None
    )

    pid = _to_int(worker.get("processId") if isinstance(worker, dict) else 0)
    process_alive = False
    if pid > 0:
        try:
            os.kill(pid, 0)
            process_alive = True
        except Exception:
            process_alive = False

    errors_obj = catalog.get("errors") if isinstance(catalog, dict) else None
    errors = _error_counts(errors_obj)

    error_messages = _tail_lines(run_dir / "conversion-errors.log", error_lines) if run_dir.exists() else []

    return {
        "run_dir": str(run_dir),
        "status": worker.get("status") if isinstance(worker, dict) else "unknown",
        "pid": pid,
        "process_alive": process_alive,
        "scope": worker.get("scope") if isinstance(worker, dict) else None,
        "startedUtc": worker.get("startedUtc") if isinstance(worker, dict) else None,
        "processStartedUtc": worker.get("processStartedUtc") if isinstance(worker, dict) else None,
        "updatedAt": now.isoformat(),
        "summary": {
            "selectedForms": selected_forms,
            "processedForms": processed_forms,
            "bundledForms": bundled_forms,
            "failedForms": failed_forms,
            "activeMoveMemberships": active_moves,
            "readyMoveMemberships": ready_moves,
            "preparedMoveMemberships": prepared_moves,
            "failedMoveMemberships": failed_moves,
        },
        "percent": {
            "forms": round((processed_forms / selected_forms * 100), 2) if selected_forms else 0.0,
            "moves": round((ready_moves / active_moves * 100), 2) if active_moves else 0.0,
        },
        "rates": {
            "formsPerMinute": round(forms_per_min, 2) if forms_per_min else 0.0,
            "movesPerMinute": round(moves_per_min, 2) if moves_per_min else 0.0,
            "etaSeconds": round(eta_seconds, 1) if eta_seconds is not None else None,
        },
        "elapsedSeconds": round(elapsed_seconds, 1) if elapsed_seconds is not None else None,
        "errors": {
            "counts": errors,
            "tail": error_messages,
        },
        "runFiles": {
            "catalogExists": catalog_path.exists(),
            "workerExists": worker_path.exists(),
            "logExists": (run_dir / "conversion-errors.log").exists(),
        },
    }


HTML_PAGE = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>FFBE Effect Converter Progress</title>
  <style>
    :root {
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      color: #0f172a;
      background: #f8fafc;
    }
    body { margin: 0; padding: 24px; background: linear-gradient(160deg, #f8fafc 0%, #ecfeff 55%, #ecfdf5 100%); }
    h1 { margin: 0 0 16px 0; font-size: 22px; }
    .card { background: #ffffffcc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; margin-bottom: 16px; box-shadow: 0 6px 20px #0f172a10; }
    .row { display: flex; gap: 12px; }
    .pill { display: inline-block; font-size: 12px; border-radius: 999px; padding: 2px 10px; margin-left: 6px; background: #e2e8f0; }
    .ok { background: #dcfce7; color: #166534; }
    .warn { background: #fee2e2; color: #991b1b; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }
    .metric { padding: 12px; border: 1px dashed #cbd5e1; border-radius: 10px; background: #f8fafc; }
    .label { color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: .02em; }
    .value { margin-top: 6px; font-size: 22px; font-weight: 700; }
    .bar-wrap { height: 10px; border-radius: 999px; background: #e2e8f0; overflow: hidden; margin: 6px 0 2px; }
    .bar { height: 100%; background: linear-gradient(90deg, #0ea5e9, #22c55e); width: 0%; transition: width .25s ease; }
    pre { margin: 0; max-height: 280px; overflow: auto; padding: 10px; background: #0f172a; color: #e2e8f0; border-radius: 8px; }
  </style>
</head>
<body>
  <h1>FFBE effects converter progress</h1>
  <div class="card">
    <div><strong>Run</strong>: <span id="runDir"></span> <span id="statusBadge" class="pill"></span></div>
    <div style="margin-top:8px;">Scope: <span id="scope">-</span> · PID: <span id="pid">-</span> · updated: <span id="updated">-</span></div>
    <div class="row" style="margin-top:10px;">
      <div class="metric">
        <div class="label">Elapsed</div>
        <div id="elapsed" class="value">-</div>
      </div>
      <div class="metric">
        <div class="label">ETA</div>
        <div id="eta" class="value">-</div>
      </div>
      <div class="metric">
        <div class="label">Forms / min</div>
        <div id="formsRate" class="value">-</div>
      </div>
      <div class="metric">
        <div class="label">Moves / min</div>
        <div id="movesRate" class="value">-</div>
      </div>
    </div>
  </div>

  <div class="card">
    <h3 style="margin-top:0;">Bundle progress</h3>
    <div class="grid">
      <div>
        <div class="label">Forms</div>
        <div class="value" id="formsText">-</div>
        <div class="bar-wrap"><div id="formsBar" class="bar"></div></div>
      </div>
      <div>
        <div class="label">Ready move memberships</div>
        <div class="value" id="movesText">-</div>
        <div class="bar-wrap"><div id="movesBar" class="bar" style="background:linear-gradient(90deg,#8b5cf6,#06b6d4);"></div></div>
      </div>
      <div>
        <div class="label">Prepared</div>
        <div id="preparedText" class="value">-</div>
      </div>
      <div>
        <div class="label">Failed</div>
        <div id="failedText" class="value">-</div>
      </div>
    </div>
  </div>

  <div class="card">
    <h3 style="margin-top:0;">Error summary</h3>
    <div id="errorCounts" class="mono">-</div>
    <h4 style="margin-bottom: 4px;">Recent conversion-errors.log</h4>
    <pre id="errorTail">-</pre>
  </div>

  <script>
    const refreshSeconds = 2000;
    async function loadStatus() {
      const response = await fetch('/status');
      const data = await response.json();
      document.getElementById('runDir').textContent = data.run_dir || '-';
      document.getElementById('scope').textContent = data.scope || '-';
      document.getElementById('pid').textContent = data.pid ? String(data.pid) : '-';
      const badge = document.getElementById('statusBadge');
      badge.textContent = `${data.status || 'unknown'}${data.process_alive ? ' · live' : ' · stopped'}`;
      badge.className = 'pill ' + (data.process_alive ? 'ok' : 'warn');
      document.getElementById('updated').textContent = data.updatedAt ? new Date(data.updatedAt).toLocaleTimeString() : '-';

      const elapsed = data.elapsedSeconds;
      if (elapsed == null) {
        document.getElementById('elapsed').textContent = '-';
      } else {
        const mins = Math.floor(elapsed / 60);
        const secs = Math.floor(elapsed % 60).toString().padStart(2, '0');
        document.getElementById('elapsed').textContent = `${mins}:${secs}`;
      }

      if (data.rates.etaSeconds == null) {
        document.getElementById('eta').textContent = 'n/a';
      } else {
        const eta = data.rates.etaSeconds;
        const minutes = Math.floor(eta / 60);
        const seconds = Math.floor(eta % 60).toString().padStart(2, '0');
        document.getElementById('eta').textContent = `${minutes}:${seconds}`;
      }

      document.getElementById('formsRate').textContent = data.rates.formsPerMinute;
      document.getElementById('movesRate').textContent = data.rates.movesPerMinute;

      const s = data.summary;
      const formsPercent = data.percent.forms || 0;
      const movesPercent = data.percent.moves || 0;
      document.getElementById('formsText').textContent = `${s.processedForms}/${s.selectedForms} (${formsPercent}%)`;
      document.getElementById('movesText').textContent = `${s.readyMoveMemberships}/${s.activeMoveMemberships} (${movesPercent}%)`;
      document.getElementById('preparedText').textContent = `${s.bundledForms} bundled, ${s.preparedMoveMemberships} prepared moves`;
      document.getElementById('failedText').textContent = `${s.failedForms} failed forms, ${s.failedMoveMemberships} failed move memberships`;
      document.getElementById('formsBar').style.width = `${Math.min(100, Math.max(0, formsPercent))}%`;
      document.getElementById('movesBar').style.width = `${Math.min(100, Math.max(0, movesPercent))}%`;

      const counts = data.errors.counts || {};
      const entries = Object.entries(counts).filter(([,v]) => v > 0).map(([k, v]) => `${k}: ${v}`);
      document.getElementById('errorCounts').textContent = entries.length ? entries.join('\\n') : 'No grouped errors yet.';
      document.getElementById('errorTail').textContent = (data.errors.tail || []).join('\\n') || 'No recent errors.';
    }

    loadStatus();
    setInterval(loadStatus, refreshSeconds);
  </script>
</body>
</html>
"""


def _status_response(run_dir: Path, error_lines: int = 15) -> str:
    status = load_progress(run_dir, error_lines=error_lines)
    return json.dumps(status, indent=2)


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/status"):
            payload = _status_response(_CURRENT_RUN_DIR, _ERROR_LINES)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
            return
        if self.path.startswith("/favicon.ico"):
            self.send_response(204)
            self.end_headers()
            return
        if self.path == "/" or self.path.startswith("/?"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
            return
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"not found")

    def log_message(self, *_args, **_kwargs):  # noqa: D401
        return


_CURRENT_RUN_DIR: Path
_ERROR_LINES = 15


def main() -> None:
    global _CURRENT_RUN_DIR, _ERROR_LINES  # noqa: PLW0603
    parser = argparse.ArgumentParser(description="Monitor FFBE converter progress via web page")
    parser.add_argument(
        "--run-dir",
        default=str(_repo_root() / "build" / "ffbe-effects-catalog-v6"),
        help="Directory containing catalog-conversion.json and worker.json",
    )
    parser.add_argument("--port", type=int, default=8765, help="Port for dashboard")
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open browser automatically",
    )
    parser.add_argument(
        "--error-lines",
        type=int,
        default=15,
        help="Number of log lines shown from conversion-errors.log",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser()
    if not run_dir.exists():
        raise FileNotFoundError(f"run dir not found: {run_dir}")
    if not run_dir.is_dir():
        raise NotADirectoryError(f"run dir is not a directory: {run_dir}")

    _CURRENT_RUN_DIR = run_dir
    _ERROR_LINES = args.error_lines
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DashboardHandler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Monitoring {run_dir}")
    print(f"Open: {url}")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
