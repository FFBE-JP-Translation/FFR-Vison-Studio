import 'dart:io';
import 'package:archive/archive_io.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:ffr_vision_studio/services/downloader.dart';
import 'package:ffr_vision_studio/services/unit_assets.dart';
import 'package:ffr_vision_studio/state/catalog_helpers.dart';

void main() {
  test('search combines text and categories across series and elements', () {
    final unit = {'id': '123', 'name': 'Terra', 'jpname': 'ティナ', 'categories': ['ff6', 'fire']};
    expect(matchesUnitSearch(unit, 'ter', {'ff6', 'fire'}), isTrue);
    expect(matchesUnitSearch(unit, 'ティナ', {}), isTrue);
    expect(matchesUnitSearch(unit, '', {'ff7'}), isFalse);
    expect(matchesUnitSearch(unit, 'rain', {'ff6'}), isFalse);
  });

  test('browsing cached idles makes no requests; bundles download on demand and repair missing data', () async {
    final root = Directory.systemTemp.createTempSync('ffr-unit-test-');
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final requests = <String>[];
    final sound = [4, 5, 6];
    final hash = sha256.convert(sound).toString();
    final archive = Archive();
    for (final name in ['sprites/123/unit_anime_123.png', 'sprites/123/unit_cgg_123.csv',
      'unit_records/12.json', 'lb_profiles/123.json', 'audio/lb/123.json']) {
      archive.addFile(ArchiveFile(name, 2, [123, 125]));
    }
    final bundle = ZipEncoder().encode(archive);
    final files = {'/123.ffr': bundle, '/sound.hca': sound};
    server.listen((request) async {
      requests.add(request.uri.path);
      request.response.contentLength = files[request.uri.path]!.length;
      request.response.add(files[request.uri.path]!);
      await request.response.close();
    });
    final dl = Downloader('http://127.0.0.1:${server.port}/');
    final assets = UnitAssets(downloader: dl, dataDir: p.join(root.path, 'data'), downloadDir: p.join(root.path, 'downloads'), idleDir: p.join(root.path, 'idles'));
    final info = <String, dynamic>{'url': '123.ffr', 'format': 'ffr-unit-1', 'unitId': '12', 'sha256': sha256.convert(bundle).toString(),
      'idle': {'url': '123.webp', 'sha256': sha256.convert([1, 2, 3]).toString()},
      'sounds': [{'url': 'sound.hca', 'sha256': hash}]};
    var indexed = 0;
    try {
      final cached = File(p.join(root.path, 'idles', '123.webp'));
      cached.parent.createSync(recursive: true);
      cached.writeAsBytesSync([1, 2, 3]);
      final idle = assets.idle('123');
      expect(assets.idle('124'), isNull);
      expect(idle!.readAsBytesSync(), [1, 2, 3]);
      expect(requests, isEmpty);
      final progress = <int>[];
      await Future.wait([for (var i = 0; i < 4; i++) assets.ensure('123', info, onIndexed: () async { indexed++; }, onProgress: (got, total) { progress.add(got); })]);
      expect(requests, ['/123.ffr', '/sound.hca']);
      expect(indexed, 1);
      expect(progress, contains(bundle.length));
      expect(progress, contains(sound.length));
      await assets.ensure('123', info);
      expect(requests.length, 2);
      File(p.join(root.path, 'data', 'audio', 'samples', '$hash.hca')).deleteSync();
      await assets.ensure('123', info);
      expect(requests, ['/123.ffr', '/sound.hca', '/sound.hca']);
      expect(File(p.join(root.path, 'data', 'sprites', '123', '.complete')).readAsStringSync(), info['sha256']);
    } finally {
      await server.close(force: true);
      root.deleteSync(recursive: true);
    }
  });

  test('simultaneous requests share a download and a 429 retry', () async {
    final root = Directory.systemTemp.createTempSync('ffr-retry-test-');
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    var count = 0;
    server.listen((request) async {
      count++;
      if (count == 1) {
        request.response.statusCode = 429;
        request.response.headers.set('Retry-After', '1');
      } else {
        request.response.add([1, 2]);
      }
      await request.response.close();
    });
    try {
      final dl = Downloader('http://127.0.0.1:${server.port}');
      final results = await Future.wait([for (var i = 0; i < 5; i++)
        dl.download('sound', p.join(root.path, 'sound'), sha256: sha256.convert([1, 2]).toString())]);
      expect(count, 2);
      expect(results.every((f) => f.lengthSync() == 2), isTrue);
    } finally {
      await server.close(force: true);
      root.deleteSync(recursive: true);
    }
  });
}
