import 'dart:convert';
import 'dart:io';

import 'package:archive/archive_io.dart';
import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:path/path.dart' as p;

/// Static files on the asset host (ffbe.luminest.io): manifest, engine, data packs, sprite packs. Pack urls may be
/// absolute (the engine on ffr.luminest.io, sprites on their shards).
class Downloader {
  Downloader(this.baseUrl);
  final String baseUrl;

  Uri _u(String rel) => rel.startsWith('http') ? Uri.parse(rel) : Uri.parse(baseUrl.endsWith('/') ? '$baseUrl$rel' : '$baseUrl/$rel');

  /// Statuses worth waiting out: the host's rate limit (429) and its hiccups (5xx). Other 4xx are final.
  static bool transient(int status) => status == 429 || status == 408 || status >= 500;

  /// How long to wait before the next try: the host's Retry-After when it says (capped), else 2, 4, 8 ... seconds.
  static Duration backoff(int attempt, Map<String, String> headers) {
    final ra = int.tryParse(headers['retry-after'] ?? '');
    if (ra != null) return Duration(seconds: ra.clamp(1, 60));
    return Duration(seconds: 2 << attempt);
  }

  Future<http.Response> _get(String rel, Duration timeout, {String label = ''}) async {
    late http.Response r;
    for (var attempt = 0; attempt < 4; attempt++) {
      r = await http.get(_u(rel)).timeout(timeout);
      if (r.statusCode == 200) return r;
      if (!transient(r.statusCode)) break;
      await Future<void>.delayed(backoff(attempt, r.headers));
    }
    throw HttpException('${label.isEmpty ? rel : label}: HTTP ${r.statusCode}${r.statusCode == 429 ? ' (the host is busy; try again in a minute)' : ''}');
  }

  Future<Map<String, dynamic>> manifest() async {
    final r = await _get('manifest.json?t=${DateTime.now().millisecondsSinceEpoch}', const Duration(seconds: 20), label: 'manifest');
    return json.decode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> json_(String rel) async {
    final r = await _get(rel, const Duration(seconds: 60));
    return json.decode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>;
  }

  /// Downloads `rel` to `dest`, reporting (received, total). Verifies sha256 when given. A broken connection, a 429 or a
  /// 5xx is retried (up to six tries, backing off) and resumes where it stopped (`.part` file + Range request).
  Future<File> download(String rel, String dest, {String? sha256, void Function(int, int)? onProgress}) async {
    final f = File(dest);
    if (f.existsSync() && sha256 != null && await _sha256(f) == sha256) return f;
    f.parent.createSync(recursive: true);
    final part = File('$dest.part');
    Object? last;
    var wait = const Duration(seconds: 1);
    for (var attempt = 0; attempt < 6; attempt++) {
      try {
        wait = Duration(seconds: 1 << attempt);
        await _fetch(rel, part, onProgress, onWait: (d) => wait = d);
        if (f.existsSync()) f.deleteSync();
        part.renameSync(f.path);
        if (sha256 != null) {
          final h = await _sha256(f);
          if (h != sha256) {
            f.deleteSync();
            throw const FormatException('the downloaded file is damaged (checksum mismatch); try again');
          }
        }
        return f;
      } on FormatException {
        rethrow;
      } on HttpException catch (e) {
        if (e.message.contains('HTTP 4') && !e.message.contains('HTTP 429') && !e.message.contains('HTTP 408')) rethrow; // a missing file will not appear by retrying
        last = e;
      } catch (e) {
        last = e;
      }
      await Future<void>.delayed(wait);
    }
    throw HttpException('$rel: the download kept failing ($last)');
  }

  Future<void> _fetch(String rel, File part, void Function(int, int)? onProgress, {void Function(Duration)? onWait}) async {
    final client = http.Client();
    try {
      var have = part.existsSync() ? part.lengthSync() : 0;
      final req = http.Request('GET', _u(rel));
      if (have > 0) req.headers['Range'] = 'bytes=$have-';
      final res = await client.send(req).timeout(const Duration(seconds: 30));
      if (res.statusCode == 200) {
        have = 0; // the host ignored the range: start over
      } else if (res.statusCode == 416) {
        return; // nothing left to fetch
      } else if (res.statusCode != 206) {
        if (transient(res.statusCode)) onWait?.call(backoff(2, res.headers));
        throw HttpException('$rel: HTTP ${res.statusCode}${res.statusCode == 429 ? ' (the host is busy)' : ''}');
      }
      final total = have + (res.contentLength ?? 0);
      final sink = part.openWrite(mode: have > 0 ? FileMode.append : FileMode.write);
      var got = have;
      try {
        await for (final chunk in res.stream.timeout(const Duration(seconds: 60))) {
          sink.add(chunk);
          got += chunk.length;
          onProgress?.call(got, total);
        }
      } finally {
        await sink.close();
      }
    } finally {
      client.close();
    }
  }

  static Future<String> _sha256(File f) async {
    final d = await sha256.bind(f.openRead()).first;
    return d.toString();
  }

  /// Extracts a zip into `dir` (streamed from disk, so large engine archives do not sit in memory twice).
  /// Entry names that would escape `dir` are skipped.
  static Future<void> unzip(File zip, String dir, {void Function(int, int)? onProgress}) async {
    Directory(dir).createSync(recursive: true);
    final root = p.normalize(p.absolute(dir));
    final input = InputFileStream(zip.path);
    try {
      final archive = ZipDecoder().decodeStream(input);
      final n = archive.length;
      var i = 0;
      for (final e in archive) {
        final name = e.name.replaceAll('\\', '/');
        if (name.isEmpty || p.isAbsolute(name) || name.contains(':') || name.split('/').contains('..')) continue;
        final out = p.normalize(p.join(root, name));
        if (!p.isWithin(root, out) && out != root) continue;
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
