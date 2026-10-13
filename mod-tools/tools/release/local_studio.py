"""Run a staged Studio build with a local asset host and isolated app data.

python -B tools/release/local_studio.py --build 15
No game files or normal Studio settings are changed by this launcher.
"""
import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import zipfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=int, default=15)
    args = parser.parse_args()
    build = ROOT / 'build' / f'build{args.build}'
    host = build / 'host'
    local = build / 'local-home'
    app_root = local / 'FFR Vision Studio'
    engine = app_root / 'engine'
    manifest = json.loads((host / 'manifest.json').read_text())
    # Use the app packaged with this build. Another Studio may still be running
    # from Flutter's shared Release folder, which must not be overwritten.
    app_info = manifest['packs']['app']
    app_zip = host / urlsplit(app_info['url']).path.lstrip('/')
    if hashlib.sha256(app_zip.read_bytes()).hexdigest() != app_info['sha256']:
        raise ValueError('Local Studio app archive checksum mismatch')
    app_dir = build / 'studio' / app_info['sha256'][:16]
    marker = app_dir / '.complete'
    if not marker.exists():
        with zipfile.ZipFile(app_zip) as z:
            for name in z.namelist():
                if not (app_dir / name).resolve().is_relative_to(app_dir.resolve()):
                    raise ValueError('Invalid path in local Studio archive')
            z.extractall(app_dir)
        marker.write_text(app_info['sha256'])
    app = next(app_dir.rglob('FFR Vision Studio.exe'))
    index = json.loads((host / 'ffbe/index.json').read_text(encoding='utf-8'))
    # Seed only reusable preparation, leaving an empty test mod and keeping
    # the real Studio's authored units and settings in their original folder.
    original = Path(os.environ.get('LOCALAPPDATA', '')) / 'FFR Vision Studio/engine'
    if not (app_root / '.seeded').exists():
        for rel in ('extracted', 'build/devui', 'build/icons'):
            if (original / rel).is_dir():
                shutil.copytree(original / rel, engine / rel, dirs_exist_ok=True)
        if (original / 'config.json').exists():
            engine.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original / 'config.json', engine / 'config.json')
        layout = original / 'data/DA_UIUnitSsLayout.json'
        if layout.exists():
            layout_target = engine / 'build/visions_mod/check/da/DA_UIUnitSsLayout.json'
            layout_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(layout, layout_target)
        app_root.mkdir(parents=True, exist_ok=True)
        (app_root / '.seeded').write_text('Cached game preparation copied; test mod is separate.\n')

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(host), **kw)

        def log_message(self, *args):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/manifest.json':
                doc = json.loads(json.dumps(manifest))
                for info in doc['packs'].values():
                    if info.get('url'):
                        info['url'] = base + urlsplit(info['url']).path.lstrip('/')
            elif path == '/ffbe/index.json':
                doc = json.loads(json.dumps(index))
                for form, info in doc.get('forms', {}).items():
                    info['url'] = base + f'ffbe/sprites/{form}.zip'
                for form, info in doc.get('unitBundles', {}).items():
                    info['url'] = base + f'ffbe/units/{form}.ffr'
                    if info.get('idle'):
                        info['idle']['url'] = base + f'ffbe/idle/{form}.webp'
            else:
                return super().do_GET()
            data = json.dumps(doc, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    base = f'http://127.0.0.1:{server.server_port}/'
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = dict(os.environ, LOCALAPPDATA=str(local), FFR_STUDIO_HOST=base, FFR_LOCAL_RESONANCE_TEST='1')
    try:
        subprocess.run([str(app)], cwd=app.parent, env=env, check=True)
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
