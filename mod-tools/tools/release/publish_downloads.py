"""Stage the Memorial downloads addition while retaining every build-15 asset."""
from pathlib import Path
import hashlib
import json
import re
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/memorial-downloads'
SITE = ROOT / 'tools/release/site'
APK = Path('C:/Users/Raegen/AppData/Local/Temp/FFBE-Memorial-EN.apk')
PREVIOUS = ROOT / 'deployment/ffbe-site-1.0.0.15.zip'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    apk = APK.read_bytes()
    assert len(apk) == 137720149
    with zipfile.ZipFile(APK) as android:
        assert 'AndroidManifest.xml' in android.namelist()
        assert android.testzip() is None
    with zipfile.ZipFile(PREVIOUS) as old:
        manifest = json.loads(old.read('root/manifest.json'))
        app = manifest['packs']['app']
        app_bytes = old.read('root/' + app['url'])
        assert len(app_bytes) == app['size'] and sha(app_bytes) == app['sha256']
        home = old.read('root/index.html').decode().replace('\r\n', '\n').replace('\r', '')
        live = urllib.request.urlopen('https://ffbe.luminest.io/?downloads-preflight=20260916', timeout=45).read().decode()
        normalize = lambda s: re.sub(r'\s+', ' ', s).strip()
        assert normalize(live) == normalize(home), 'Live homepage differs from retained release; reconcile first.'
        source = (SITE / 'index.html').read_text(encoding='utf-8')
        notice = re.search(r'  <section aria-labelledby="memorial-heading".*?</section>', source, re.S).group()
        assert 'memorial-heading' not in home
        home = home.replace('  <div class="cross">', notice + '\n  <div class="cross">', 1)
        downloads = (SITE / 'downloads/index.html').read_text(encoding='utf-8').replace('{{APK_SHA256}}', sha(apk))
        (SITE / 'downloads/index.html').write_text(downloads, encoding='utf-8')
        checksums = sha(apk) + '  FFBE-Memorial-EN.apk\n' + app['sha256'] + '  FFR-Vision-Studio-1.0.0.15.zip\n'
        (SITE / 'downloads/checksums.txt').write_text(checksums, encoding='utf-8')
        additions = {'root/index.html': home.encode(), 'root/downloads/index.html': downloads.encode(),
                     'root/downloads/checksums.txt': checksums.encode(), 'root/downloads/FFBE-Memorial-EN.apk': apk}
        archive = OUT / 'ffbe-memorial-downloads_20260916.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_STORED) as new:
            for info in old.infolist():
                if info.filename not in additions:
                    new.writestr(info, old.read(info))
            for name, data in additions.items():
                new.writestr(name, data)
        with zipfile.ZipFile(archive) as new:
            assert new.testzip() is None
            retained = 0
            for info in old.infolist():
                if info.filename != 'root/index.html':
                    assert sha(new.read(info.filename)) == sha(old.read(info)), info.filename
                    retained += 1
            new.extractall(OUT / 'preview')
        report = {'archive': str(archive), 'apkSha256': sha(apk), 'apkSize': len(apk),
                  'windows': app, 'retainedFiles': retained, 'archiveSize': archive.stat().st_size}
        (OUT / 'verification.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
