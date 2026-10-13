"""Run the checked-in engine or prepare its separate runtime dependencies."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import runpy
import shutil
import sys

ROOT = Path(__file__).resolve().parent


def hydrate(runtime: Path) -> None:
    """Reuse downloaded dependencies without replacing any checked-in source."""
    runtime = runtime.resolve()
    if runtime == ROOT or ROOT.is_relative_to(runtime) or runtime.is_relative_to(ROOT):
        raise ValueError('Choose a separate installed engine/dependency folder')
    if not (runtime / 'data').is_dir():
        raise FileNotFoundError('The runtime folder must contain data/ from the Studio data packs')
    groups = ('data', 'bin', 'tools/retoc', 'tools/repak', 'tools/UAssetAPI',
              'tools/UE4SS', 'tools/vgmstream', 'tools/oodle')
    count = 0
    for group in groups:
        folder = runtime / group
        if not folder.is_dir():
            continue
        for source in folder.rglob('*'):
            if not source.is_file():
                continue
            target = ROOT / group / source.relative_to(folder)
            # Authored policy and files already supplied locally take precedence.
            if target.exists():
                continue
            if source.is_symlink():
                raise ValueError(f'Symlink in dependency folder: {source}')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            count += 1
    print(f'Placed {count} runtime dependency files. Mod source was preserved.')
    print('Build the .NET projects to test source changes; bin/ffr-dt.exe takes precedence until removed.')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('engine', help='Run the engine from mod-tools/tools')
    run.add_argument('--port', type=int, default=8765)
    prepare = commands.add_parser('prepare', help='Reuse installed data packs and tool dependencies')
    prepare.add_argument('--runtime', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        hydrate(args.runtime)
        return 0
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    # Run in this process so Ctrl+C and process supervision stop the engine too.
    os.chdir(ROOT)
    sys.dont_write_bytecode = True
    sys.argv = [str(ROOT / 'tools/devui/launcher.py'), '--engine', '--port', str(args.port)]
    runpy.run_path(sys.argv[0], run_name='__main__')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
