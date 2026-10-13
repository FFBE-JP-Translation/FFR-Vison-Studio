"""Freeze the user-accepted step-two build without changing the installed game."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'build/target-camera-step2-retry'
DEST = ROOT / 'checkpoints/ffbe-camera-step2'
GAME = Path('T:/SteamLibrary/steamapps/common/FINAL FANTASY RESONANCE DEMO')
STEM = 'zzzzzzz_FFBE_CastCamera_9_P'


def read(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))


def digest(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def copy(src, relative):
    dst = DEST / relative
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def archive(name, files):
    dst = DEST / 'archives' / name
    dst.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED, compresslevel=3) as z:
        for p in sorted(set(files)):
            z.write(p, p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(dst) as z:
        assert z.testzip() is None, name


def main():
    if (DEST / 'checkpoint.json').exists():
        raise SystemExit('Checkpoint already sealed; choose a new name rather than replacing it.')
    installed = read(WORK / 'installation.json')
    mods = GAME / 'FFRS/Content/Paks/~mods'
    assert digest(ROOT / 'mods/EstherTsukiko/units.json') == digest(WORK / 'units.json')
    for name, expected in installed['packageHashes'].items():
        assert digest(mods / name) == expected, 'Installed package differs: ' + name
        copy(mods / name, ('packages/' if name.startswith(STEM) else 'dependencies/packages/') + name)
    print('Copied and verified all 24 installed mod files.', flush=True)

    sources = []
    for folder, suffixes in [('tools', {'.py', '.ps1', '.lua'}),
                             ('src', {'.cs', '.csproj', '.props', '.targets'}),
                             ('docs', {'.md'})]:
        sources += [p for p in (ROOT / folder).rglob('*') if p.is_file()
                    and p.suffix in suffixes and not {'bin', 'obj', '__pycache__', '.venv'} & set(p.parts)]
    sources += [ROOT / 'mods/EstherTsukiko/units.json',
                ROOT / 'data/ffbe/presentation/attack-settings.json', ROOT / 'README.md']
    for p in sources:
        copy(p, 'source/' + p.relative_to(ROOT).as_posix())
    for p in WORK.glob('*'):
        if p.is_file() and not p.name.startswith('SEQ_'):
            copy(p, 'records/' + p.name)
    for name in ('main.lua', 'stage.lua', 'run.ps1'):
        copy(WORK / 'runtime' / name, 'records/runtime/' + name)
    runs = {r['run'] for r in read(WORK / 'runtime-verification.json')}
    for run in runs:
        folder = WORK / 'runtime/runs' / run
        for p in folder.rglob('*'):
            if p.is_file():
                copy(p, 'records/runtime/runs/' + run + '/' + p.relative_to(folder).as_posix())
    # A runnable reconstruction does not depend on mutable build/ data or FFBE re-rendering.
    inputs = [p for folder in ('build/visions_mod/assets', 'build/cast-camera-step1/installed-legacy')
              for p in (ROOT / folder).rglob('*') if p.is_file()]
    inputs += [p for p in WORK.glob('*') if p.is_file()]
    inputs += [p for p in (ROOT / 'checkpoints/ffbe-camera-step1').rglob('*') if p.is_file()]
    shell = ROOT / 'extracted/legacy/FFRS/Content/Sequencer/Battle/Skill/440110/440111/Track'
    inputs += list(shell.glob('SEQ_Battle_440111_Cut_000.*'))
    assert len(list(shell.glob('SEQ_Battle_440111_Cut_000.*'))) >= 2
    archive('workspace-inputs.zip', inputs)
    tool_files = [p for p in (ROOT / 'src/ffr-dt/bin/Release/net8.0').rglob('*') if p.is_file()]
    tool_files += [p for p in (ROOT / 'src/ffr-export/bin/Release/net10.0').rglob('*') if p.is_file()]
    tool_files += [ROOT / 'tools/retoc/retoc.exe', ROOT / 'tools/repak/repak.exe', ROOT / 'extracted/Mappings.usmap']
    archive('native-tools.zip', tool_files)
    print('Saved source, cooked assets, baseline tables, build plans, tools, and native evidence.', flush=True)
    copy(ROOT / 'tools/private/restore_target_camera_checkpoint.ps1', 'restore.ps1')
    copy(ROOT / 'docs/51-camera-checkpoint-recovery.md', 'README.md')
    manifest = {
        'name': 'Accepted FFBE camera step 2', 'createdAt': datetime.now(timezone.utc).isoformat(),
        'game': str(GAME), 'work': str(WORK), 'userAssessment': '90% success',
        'knownIssues': ['Small delay after target zoom before effects', 'Pan/zoom handoff feels staggered'],
        'roster': ['2B -Neo Vision-', 'A.I. Katy', 'Sora (KHIII)', 'Rain & Fina'],
        'scope': 'Exact accepted camera build before Esther replacement and effect implementation',
        'packageHashes': installed['packageHashes'],
        'baseGameDependency': 'Installed FFR demo; base game and player saves are not copied',
        'files': {p.relative_to(DEST).as_posix(): digest(p) for p in sorted(DEST.rglob('*')) if p.is_file()}
    }
    (DEST / 'checkpoint.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'checkpoint': str(DEST), 'files': len(manifest['files']),
                      'bytes': sum(p.stat().st_size for p in DEST.rglob('*') if p.is_file())}), flush=True)


if __name__ == '__main__':
    main()
