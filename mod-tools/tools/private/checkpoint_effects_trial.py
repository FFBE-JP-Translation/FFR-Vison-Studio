"""Seal the accepted first effects trial, without changing the installed game."""
from pathlib import Path
import hashlib, json, shutil, zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'build/effects-step3'
DEST = ROOT / 'checkpoints/ffbe-effects-step3'

def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def copy(path, relative):
    out = DEST / relative
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, out)

def main():
    if DEST.exists():
        raise SystemExit('Checkpoint directory already exists; never overwrite an accepted checkpoint.')
    DEST.mkdir(parents=True)
    for folder, suffixes in [('tools', {'.py','.ps1','.lua'}), ('src', {'.cs','.csproj','.props','.targets'}), ('docs', {'.md'})]:
        for path in (ROOT/folder).rglob('*'):
            if path.is_file() and path.suffix in suffixes and not {'bin','obj','__pycache__','.venv'} & set(path.parts):
                copy(path, 'source/'+path.relative_to(ROOT).as_posix())
    for name in ['README.md','mods/EstherTsukiko/units.json','data/ffbe/presentation/attack-settings.json']:
        copy(ROOT/name, 'source/'+name)
    for path in WORK.glob('*.json'):
        copy(path, 'records/'+path.name)
    for path in (WORK/'presentation').glob('*.json'):
        copy(path, 'records/presentation/'+path.name)
    print('Accepted source and plans preserved; copying installed package set next.', flush=True)
    receipt = json.loads((WORK/'installation.json').read_text(encoding='utf-8-sig'))
    game = Path('T:/SteamLibrary/steamapps/common/FINAL FANTASY RESONANCE DEMO')
    for name, sha in receipt['packageHashes'].items():
        path = game/'FFRS/Content/Paks/~mods'/name
        assert digest(path) == sha, name
        copy(path, ('packages/' if name.startswith('zzzzzzz_FFBE_CastCamera_9_P') else 'dependencies/packages/')+name)
    restore = (ROOT/'tools/private/restore_target_camera_checkpoint.ps1').read_text(encoding='utf-8-sig')
    restore = restore.replace('accepted camera step 2', 'accepted effects step 3')
    # This seal restores exact installed packages and source; no undocumented build archive switch.
    restore = restore.replace('[switch]$RestoreBuildInputs, ', '')
    restore = restore[:restore.index('if ($RestoreBuildInputs)')] + "Write-Output 'Accepted effects restored; saves were not changed.'\n"
    (DEST/'restore.ps1').write_text(restore, encoding='utf-8')
    manifest = {'name':'Accepted FFBE effects step 3', 'createdAt':datetime.now(timezone.utc).isoformat(),
                'game':str(game), 'packageHashes':receipt['packageHashes'],
                'scope':'Exact installed ten-move effects trial and source, accepted by user before refinements.',
                'rebuildInputs':'Prepared media remain in data/ffbe/presentation/assets and build/effects-step3; exact restoration uses sealed packages.',
                'files':{p.relative_to(DEST).as_posix():digest(p) for p in sorted(DEST.rglob('*')) if p.is_file()}}
    (DEST/'checkpoint.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(f'Sealed {len(manifest["files"])} files at {DEST}', flush=True)

if __name__ == '__main__': main()
