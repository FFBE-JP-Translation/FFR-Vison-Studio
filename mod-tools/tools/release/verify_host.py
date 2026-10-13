"""Verify public release objects against the staged catalog, with bounded traffic.

python -B tools/release/verify_host.py --host-tree build/build14/host \
    --out build/build14/production/public-assets.json --domains units2.luminest.io
The saved report supports resuming verification without downloading matches again.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import threading
import time
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-tree', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--base', default='https://ffbe.luminest.io/')
    parser.add_argument('--domains', nargs='*')
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    manifest = json.loads((args.host_tree / 'manifest.json').read_text())
    index = json.loads((args.host_tree / 'ffbe/index.json').read_text(encoding='utf-8'))
    objects = {}
    for info in [*manifest['packs'].values(), *index['unitBundles'].values()]:
        if info.get('url') and info.get('sha256'):
            objects[urljoin(args.base, info['url'])] = info
        for sound in info.get('sounds', []):
            objects[urljoin(args.base, sound['url'])] = sound
    if args.domains:
        objects = {u: v for u, v in objects.items() if urlsplit(u).hostname in args.domains}
    results = json.loads(args.out.read_text()) if args.out.exists() else {}
    pending = {u: v for u, v in objects.items() if not (results.get(u, {}).get('ok') and results[u].get('sha256') == v['sha256'])}
    print(f'Checking {len(pending)} public objects ({len(objects)-len(pending)} already verified)', flush=True)
    # A single host receives at most three requests per second from this checker.
    lock = threading.Lock()
    next_request = {}
    def verify(url, info):
        for attempt in range(6):
            domain = urlsplit(url).hostname
            with lock:
                now = time.monotonic()
                start = max(now, next_request.get(domain, now))
                next_request[domain] = start + .35
            time.sleep(max(0, start-time.monotonic()))
            try:
                request = Request(url + ('&' if '?' in url else '?') + 'v=' + info['sha256'], headers={'Accept-Encoding': 'identity'})
                with urlopen(request, timeout=45) as response:
                    h = hashlib.sha256(); count = 0
                    while chunk := response.read(1048576):
                        h.update(chunk); count += len(chunk)
                if h.hexdigest() != info['sha256'] or count != info['size']:
                    raise ValueError(f'Content mismatch: {count} bytes, {h.hexdigest()}')
                return {'ok': True, 'size': count, 'sha256': h.hexdigest()}
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as ex:
                error = f'{type(ex).__name__}: {ex}'
                if attempt == 5:
                    return {'ok': False, 'error': error}
                delay = min(30, 2 ** (attempt+1))
                if isinstance(ex, HTTPError) and ex.headers.get('Retry-After', '').isdigit():
                    delay = min(60, int(ex.headers['Retry-After']))
                time.sleep(delay)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(verify, u, v): u for u, v in pending.items()}
        for n, future in enumerate(as_completed(futures), 1):
            url = futures[future]; result = future.result(); results[url] = result
            if not result['ok']:
                print('FAILED', url, result['error'], flush=True)
            if n % 50 == 0 or n == len(futures):
                args.out.write_text(json.dumps(results, indent=2))
                print(f'Verified {n}/{len(pending)} objects; failures {sum(not r["ok"] for r in results.values())}', flush=True)
    failed = [u for u in objects if not results.get(u, {}).get('ok')]
    print(f'Public verification: {len(objects)-len(failed)}/{len(objects)} matched', flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
