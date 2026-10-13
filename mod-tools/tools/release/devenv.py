r"""devenv.py - a development environment for the native app: build a numbered pack, serve it on localhost, and start the app
against it from a scratch app-data folder. Nothing touches the live hosts or your real %LOCALAPPDATA%.

    python tools/release/devenv.py --build 6                  build pack 1.0.0 build 6 (engine + app + shards), serve it, start the app
    python tools/release/devenv.py --build 6 --no-build       serve the pack already in build/release/host and start the app
    python tools/release/devenv.py --build 6 --reset          wipe the scratch app-data first (a first-run test)
    python tools/release/devenv.py --build 6 --serve-only     just serve (for a second app started by hand)

The scratch app-data folder is build/devhome/FFR Vision Studio (LOCALAPPDATA is pointed there). The app is told the host is
http://127.0.0.1:8766/ (FFR_STUDIO_HOST). The engine zip is still fetched from the manifest's engine url; with --engine-local
the pack is built so that url points at the local server too, for a fully offline loop.
Stop with Ctrl+C: the app keeps running (close it yourself), the server stops.
"""
import http.server, os, shutil, subprocess, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOST_DIR = os.path.join(ROOT, "build", "release", "host")
DEV_HOME = os.path.join(ROOT, "build", "devhome")
APP_EXE = os.path.join(os.path.dirname(ROOT), "build", "windows", "x64", "runner", "Release", "ffr_vision_studio.exe")
SHARDS = ",".join(f"https://sprites{n}.luminest.io/" for n in (1, 2, 3, 4, 5, 6, 8))
PORT = 8766


def arg(a, name, default=None):
    return a[a.index(name) + 1] if name in a else default


def serve():
    handler = lambda *x, **k: http.server.SimpleHTTPRequestHandler(*x, directory=HOST_DIR, **k)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"serving {HOST_DIR} at http://127.0.0.1:{PORT}/")
    return srv


def main():
    a = sys.argv[1:]
    if "--help" in a or "-h" in a: sys.exit(__doc__)
    build = arg(a, "--build")
    if not build: sys.exit("--build <n> is required (the build number of 1.0.0 you are driving)")
    version = arg(a, "--version", "1.0.0")
    if "--no-build" not in a and "--serve-only" not in a:
        cmd = [sys.executable, os.path.join(ROOT, "tools", "release", "build_host_pack.py"), version, "--build", build, "--build-app", "--shard-hosts", SHARDS]
        if "--engine-local" in a: cmd += ["--engine-host", f"http://127.0.0.1:{PORT}/"]
        print("$", " ".join(cmd))
        r = subprocess.run(cmd, cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        if r.returncode != 0: sys.exit("pack build failed")
    srv = serve()
    if "--serve-only" not in a:
        if "--reset" in a and os.path.isdir(DEV_HOME): shutil.rmtree(DEV_HOME)
        os.makedirs(DEV_HOME, exist_ok=True)
        env = dict(os.environ, LOCALAPPDATA=DEV_HOME, FFR_STUDIO_HOST=f"http://127.0.0.1:{PORT}/")
        if not os.path.exists(APP_EXE): sys.exit(f"no app build at {APP_EXE}; run without --no-build or `flutter build windows --release` first")
        print(f"starting {APP_EXE}\n  app data: {DEV_HOME}\\FFR Vision Studio\n  host: http://127.0.0.1:{PORT}/ (manifest {version}.{build})")
        subprocess.Popen([APP_EXE], env=env, cwd=os.path.dirname(APP_EXE))
    print("Ctrl+C stops the server.")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
