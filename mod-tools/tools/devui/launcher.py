r"""launcher.py - entry point of the packaged studio.

    FFR Vision Studio.exe                      starts the studio server on a free local port and opens it in the browser
    FFR Vision Studio.exe --run <script> ...   runs one of the bundled tool scripts with the bundled Python (the server uses
                                               this where the source tree would call `python tools/<script>.py`)
    python tools/devui/launcher.py [--port N]  the same from the source tree
"""
import os, runpy, socket, sys, threading, time, webbrowser

# static imports so the bundler collects everything the server and the tool scripts need
import fastapi, uvicorn, starlette, anyio, pydantic  # noqa: F401
import numpy  # noqa: F401
import cv2  # noqa: F401 - full-card animation framing in vision_cards
import PIL.Image, PIL.ImageChops, PIL.ImageDraw, PIL.ImageOps  # noqa: F401

# the frozen interpreter inherits the console's code page (cp1252): the tools print Japanese row names, so force UTF-8 everywhere
for _stream in (sys.stdout, sys.stderr):
    try: _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
os.environ.setdefault("PYTHONIOENCODING", "utf-8"); os.environ.setdefault("PYTHONUTF8", "1")

import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
# in the PyInstaller bundle __file__ sits under _internal/; the scripts live in <exe folder>/tools like in the repository
APP = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(APP, "tools")
# where errors are written: the native app passes FFR_LOG_DIR (its logs folder); otherwise <exe folder>/logs
LOG_DIR = os.environ.get("FFR_LOG_DIR") or os.path.join(APP, "logs")

def log_crash(what):
    """the traceback goes to stderr (the app's engine log or the build console) and to logs/engine-errors.log"""
    tb = traceback.format_exc()
    try: sys.stderr.write(f"\n{what} failed:\n{tb}\n"); sys.stderr.flush()
    except Exception: pass
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, "engine-errors.log"), "a", encoding="utf-8") as f:
            f.write(f"----- {time.strftime('%Y-%m-%d %H:%M:%S')} {what} (argv: {' '.join(sys.argv[1:])[:300]})\n{tb}\n")
    except Exception: pass

def run_script():
    script = os.path.abspath(sys.argv[2]); sys.argv = [script] + sys.argv[3:]
    for p in (TOOLS, os.path.join(TOOLS, "devui"), os.path.join(TOOLS, "ffbe2ss6"), os.path.dirname(script)): sys.path.insert(0, p)
    runpy.run_path(script, run_name="__main__")

def free_port(preferred=8765):
    for p in (preferred, *range(8766, 8800)):
        with socket.socket() as s:
            try: s.bind(("127.0.0.1", p)); return p
            except OSError: continue
    return 0

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--run":
        return run_script()
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".py") and os.path.exists(sys.argv[1]):
        sys.argv.insert(1, "--run"); return run_script()      # `exe some_script.py args` is never a request to start the server
    for p in (TOOLS, os.path.join(TOOLS, "devui"), os.path.join(TOOLS, "ffbe2ss6")): sys.path.insert(0, p)
    import ffrenv  # noqa: F401  (paths for the source tree and the packaged app)
    import server                                    # tools/devui/server.py (the FastAPI app)
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else free_port()
    url = f"http://127.0.0.1:{port}"
    engine = "--engine" in sys.argv                  # supervised by the native app: no browser, machine-readable READY line
    print(f"READY {port}" if engine else f"FFR Vision Studio  -  {url}", flush=True)
    if not engine: print("Keep this window open while you use the studio; close it to stop.")
    if "--no-browser" not in sys.argv and not engine:
        threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(url)), daemon=True).start()
    uvicorn.run(server.app, host="127.0.0.1", port=port, log_level="warning")

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        log_crash("tool script" if len(sys.argv) > 1 and (sys.argv[1] == "--run" or sys.argv[1].lower().endswith(".py")) else "engine")
        sys.exit(1)   # a plain exit code: the packaged exe must never stop on a message box
