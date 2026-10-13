"""Local review page and revision-checked, atomic decision storage.

python -B -m tools.effect_review.serve --port 8767
Only the review directory is served. This server cannot convert or install.
"""
import argparse
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT/'docs/effect-review'
LOCK = threading.Lock()


class ReviewError(ValueError):
    pass


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def validate_review(value, catalog):
    if not isinstance(value, dict) or value.get('schemaVersion') != 1 or value.get('catalogId') != catalog['catalogId']:
        raise ReviewError('The decisions belong to a different catalog snapshot.')
    keys, options = {e['key'] for e in catalog['effects']}, {o['id'] for o in catalog['options']}
    decisions = value.get('decisions')
    if not isinstance(decisions, dict) or set(decisions) != keys:
        raise ReviewError('Decisions must include every effect key exactly once.')
    if type(value.get('revision')) is not int or value['revision'] < 0:
        raise ReviewError('Invalid revision.')
    if value.get('stage') not in ('mapping', 'ready'):
        raise ReviewError('Invalid review stage.')
    for key, choice in decisions.items():
        if not isinstance(choice, dict):
            raise ReviewError(f'Invalid choice for {key}.')
        targets = choice.get('targets')
        if not isinstance(targets, list) or not 1 <= len(targets) <= 12 or any(not isinstance(t, str) or t not in options for t in targets):
            raise ReviewError(f'Unknown or empty FFR mapping for {key}.')
        if len(set(targets)) != len(targets):
            raise ReviewError(f'Duplicate destination in {key}.')
        if not isinstance(choice.get('notes'), str) or len(choice['notes']) > 10000 or type(choice.get('reviewed')) is not bool:
            raise ReviewError(f'Invalid notes or review state for {key}.')
        if value['stage'] == 'ready' and not choice['reviewed']:
            raise ReviewError('Finish reviewing all effects before marking the review finished.')
    if value['stage'] == 'ready':
        for effect in catalog['effects']:
            choice = decisions[effect['key']]
            if effect['observed'] and 'other' in choice['targets'] and not choice['notes'].strip():
                raise ReviewError(f"Observed Other choice {effect['key']} needs notes.")
    # Only review fields are accepted. Source metadata/policy cannot be replaced
    # by an imported document, and notes are never interpreted as executable code.
    return {'schemaVersion': 1, 'catalogId': catalog['catalogId'], 'revision': value['revision'],
            'stage': value['stage'], 'decisions': {k: {f: v[f] for f in ('targets','notes','reviewed')}
                                                   for k, v in decisions.items()},
            'policies': catalog['policies']}


class ReviewStore:
    def __init__(self, directory=DIRECTORY):
        self.directory = directory
        self.catalog = read(directory/'catalog.json')
        self.path = directory/'review-decisions.json'
        self.defaults = read(directory/'mapping-defaults.json')

    def current(self):
        value = read(self.path) if self.path.exists() else self.defaults
        return validate_review(value, self.catalog)

    def save(self, value):
        clean = validate_review(value, self.catalog)
        with LOCK:
            current = self.current()
            if clean['revision'] != current['revision']:
                raise ReviewError('Save conflict: another page has saved newer decisions. Export this draft before reloading.')
            clean['revision'] += 1
            clean['updatedAt'] = datetime.now(timezone.utc).isoformat()
            backups = self.directory/'decision-backups'
            backups.mkdir(exist_ok=True)
            if self.path.exists():
                backup = backups/f"review-{current['revision']:06d}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.json"
                backup.write_bytes(self.path.read_bytes())
            temporary = self.path.with_suffix('.json.tmp')
            with temporary.open('w', encoding='utf-8') as stream:
                json.dump(clean, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            return clean


def handler_factory(store):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(store.directory), **kwargs)

        def send_json(self, status, value):
            data = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

        def local_request(self, write=False):
            expected = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') not in (expected, f'localhost:{self.server.server_port}'):
                self.send_json(403, {'error': 'This review is available only on localhost.'})
                return False
            origin = self.headers.get('Origin')
            if origin and origin not in (f'http://{expected}', f'http://localhost:{self.server.server_port}'):
                self.send_json(403, {'error': 'Cross-origin review writes are not allowed.'})
                return False
            if write and self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                self.send_json(415, {'error': 'Use a JSON decisions document.'})
                return False
            return True

        def do_GET(self):
            if not self.local_request():
                return
            route = urlsplit(self.path).path
            if route == '/api/review':
                try:
                    self.send_json(200, store.current())
                except (ReviewError, ValueError) as error:
                    self.send_json(409, {'error': str(error)})
            elif route == '/api/health':
                self.send_json(200, {'service': 'ffr-effect-review', 'catalogId': store.catalog['catalogId']})
            elif route.startswith('/api/'):
                self.send_json(404, {'error': 'Unknown review endpoint.'})
            else:
                path = Path(self.translate_path(self.path)).resolve()
                if not path.is_relative_to(store.directory.resolve()) or path.is_dir() and route != '/':
                    self.send_json(403, {'error': 'Only review files can be opened.'})
                    return
                super().do_GET()

        def do_POST(self):
            if not self.local_request(write=True):
                return
            if urlsplit(self.path).path != '/api/review':
                self.send_json(404, {'error': 'Unknown review endpoint.'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 5_000_000:
                    raise ReviewError('Decision document is empty or too large.')
                result = store.save(json.loads(self.rfile.read(length)))
                self.send_json(200, {'revision': result['revision'], 'updatedAt': result['updatedAt']})
            except (ValueError, TypeError, KeyError) as error:
                self.send_json(409 if 'conflict' in str(error).lower() else 400, {'error': str(error)})
            except OSError as error:
                self.send_json(500, {'error': f'Could not save decisions: {error}'})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_factory(ReviewStore()))
    print(f'Effect review: http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
