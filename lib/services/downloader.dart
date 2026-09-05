import 'dart:convert';
import 'dart:io';

import 'package:archive/archive_io.dart';
import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:path/path.dart' as p;

/// Static files on the asset host (ffbe.luminest.io): manifest, engine, data packs, sprite packs.
class Downloader {
  Downloader(this.baseUrl);
  final String baseUrl; // e.g. https://ffbe.luminest.io/ (pack urls may be absolute, e.g. the engine on ffr.luminest.io)

  Uri _u(String rel) => rel.startsWith('http') ? Uri.parse(rel) : Uri.parse(baseUrl.endsWith('/') ? '$baseUrl$rel' : '$baseUrl/$rel');

  Future<Map<String, dynamic>> manifest() async {
    final r = await http.get(_u('manifest.json?t=${DateTime.now().millisecondsSinceEpoch}'));
    if (r.statusCode != 200) throw HttpException('manifest: HTTP ${r.statusCode}');
    return json.decode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> json_(String rel) async {
    final r = await http.get(_u(rel));
    if (r.statusCode != 200) throw HttpException('$rel: HTTP ${r.statusCode}');
    return json.decode(r.body) as Map<String, dynamic>;
  }

  /// Downloads `rel` to `dest`, reporting (received, total). Verifies sha256 when given.
  Future<File> download(String rel, String dest, {String? sha256, void Function(int, int)? onProgress}) async {
    final f = File(dest);
    if (f.existsSync() && sha256 != null && await _sha256(f) == sha256) return f;
    f.parent.createSync(recursive: true);
    final client = http.Client();
    try {
      final req = http.Request('GET', _u(rel));
      final res = await client.send(req);
      if (res.statusCode != 200) throw HttpException('$rel: HTTP ${res.statusCode}');
      final total = res.contentLength ?? 0;
      final sink = f.openWrite();
      var got = 0;
      await for (final chunk in res.stream) {
        sink.add(chunk);
        got += chunk.length;
        onProgress?.call(got, total);
      }
      await sink.close();
    } finally {
      client.close();
    }
    if (sha256 != null) {
      final h = await _sha256(f);
      if (h != sha256) {
        f.deleteSync();
        throw const FormatException('the downloaded file is damaged (checksum mismatch); try again');
      }
    }
    return f;
  }

  static Future<String> _sha256(File f) async {
    final d = await sha256.bind(f.openRead()).first;
    return d.toString();
  }

  /// Extracts a zip into `dir` (streamed from disk, so large engine archives do not sit in memory twice).
  static Future<void> unzip(File zip, String dir, {void Function(int, int)? onProgress}) async {
    Directory(dir).createSync(recursive: true);
    final input = InputFileStream(zip.path);
    try {
      final archive = ZipDecoder().decodeStream(input);
      final n = archive.length;
      var i = 0;
      for (final e in archive) {
        final out = p.join(dir, e.name);
        if (e.isFile) {
          final of = File(out);
          of.parent.createSync(recursive: true);
          final os = OutputFileStream(of.path);
          e.writeContent(os);
          await os.close();
        } else {
          Directory(out).createSync(recursive: true);
        }
        i++;
        if (i % 50 == 0) onProgress?.call(i, n);
      }
      onProgress?.call(n, n);
    } finally {
      await input.close();
    }
  }
}
