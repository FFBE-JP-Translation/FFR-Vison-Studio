"""Reuse unchanged native sprite/texture assets across addon rebuilds.

Only the two asset constructors are cached. Tables, maps, sequences and
installed-loadout verification always run against the current vision roster.
"""
import hashlib
import json
from pathlib import Path
import tempfile

import cooked_effect_cache as cache


def run(arguments, execute, cache_root):
    args = list(map(str, arguments))
    constructors = ('make-ss6', 'make-texture')
    command_index = next((i for i in (1, 2) if len(args) > i and args[i] in constructors), None)
    if command_index is None:
        return execute(args)
    output_index = command_index + (3 if args[command_index] == 'make-ss6' else 5)
    target = Path(args[output_index])
    compiler = Path(args[command_index - 1])
    inputs = []
    normalized = []
    for index, value in enumerate(args):
        if index == output_index:
            normalized.append({'output': target.name})
        elif index in (command_index - 1, command_index + 1, command_index + 2) or index > 0 and args[index - 1] in ('--usmap', '--schema'):
            path = Path(value)
            normalized.append({'file': path.name, 'sha256': cache.digest(path)})
            if index == command_index + 1:
                for ext in ('.uexp', '.ubulk'):
                    sibling = path.with_suffix(ext)
                    inputs.append([ext, cache.digest(sibling) if sibling.is_file() else None])
        else:
            normalized.append(value)
    for path in sorted(compiler.parent.iterdir()):
        if path.suffix == '.dll' or path.name.endswith(('.deps.json', '.runtimeconfig.json')):
            inputs.append([path.name, cache.digest(path)])
    key = hashlib.sha256(json.dumps({'version': 1, 'command': normalized,
        'dependencies': inputs}, sort_keys=True).encode()).hexdigest()
    cache_root = Path(cache_root)
    if cache.restore(cache_root, key, target.parent):
        print(f'Reused prepared asset: {target.name}', flush=True)
        return ''
    cache_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='prepare-', dir=cache_root) as temporary:
        output = Path(temporary) / target.name
        args[output_index] = str(output)
        result = execute(args)
        if not output.is_file():
            raise RuntimeError(f'Asset preparation did not produce {target.name}')
        cache.store(cache_root, key, output.parent)
        if not cache.restore(cache_root, key, target.parent):
            raise RuntimeError(f'Prepared asset verification failed: {target.name}')
        return result
