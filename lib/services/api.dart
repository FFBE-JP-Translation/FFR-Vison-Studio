import 'dart:convert';

import 'package:http/http.dart' as http;

/// Thin client for the engine's HTTP routes (tools/devui/server.py). Values stay as JSON maps: the catalog
/// and unit spec are large, loosely typed documents the engine owns.
class Api {
  Api(this.base);
  final String base;

  Uri _u(String path) => Uri.parse('$base$path');

  Future<dynamic> _json(http.Response r, String what) async {
    if (r.statusCode >= 400) {
      String msg = r.reasonPhrase ?? 'HTTP ${r.statusCode}';
      try {
        final b = json.decode(r.body);
        if (b is Map && b['detail'] != null) msg = b['detail'].toString();
      } catch (_) {}
      throw ApiException('$what: $msg');
    }
    return json.decode(utf8.decode(r.bodyBytes));
  }

  Future<dynamic> get(String path) async => _json(await http.get(_u(path)), path);
  Future<dynamic> post(String path, [Object? body]) async =>
      _json(await http.post(_u(path), headers: {'Content-Type': 'application/json'}, body: json.encode(body ?? {})), path);
  Future<dynamic> put(String path, Object body) async =>
      _json(await http.put(_u(path), headers: {'Content-Type': 'application/json'}, body: json.encode(body)), path);
  Future<dynamic> delete(String path) async => _json(await http.delete(_u(path)), path);

  Future<Map<String, dynamic>> status() async => (await get('/api/status')) as Map<String, dynamic>;
  Future<Map<String, dynamic>> catalog() async => (await get('/api/ffr/catalog')) as Map<String, dynamic>;
  Future<List<dynamic>> spec() async => (await get('/api/spec')) as List<dynamic>;
  Future<void> saveSpec(List<dynamic> units) => put('/api/spec', units);
  Future<Map<String, dynamic>> addUnit(String ffbeId, {String? form, String? name}) async =>
      (await post('/api/spec/add', {'ffbeId': ffbeId, 'form': form, 'name': name, 'autoport': false})) as Map<String, dynamic>;
  Future<void> deleteUnit(String key) => delete('/api/spec/$key');
  Future<List<dynamic>> ffbeUnits() async => (await get('/api/ffbe/units')) as List<dynamic>;
  Future<void> rebuildFfbeIndex() => post('/api/ffbe/units/rebuild');
  Future<Map<String, dynamic>> ffbeUnit(String id) async => (await get('/api/ffbe/unit/$id')) as Map<String, dynamic>;
  Future<void> setup(String game) => post('/api/setup', {'game': game});
  Future<Map<String, dynamic>> setupLog() async => (await get('/api/setup/log')) as Map<String, dynamic>;
  Future<void> build({required bool install}) => post('/api/build', {'install': install});
  Future<Map<String, dynamic>> buildLog() async => (await get('/api/build/log')) as Map<String, dynamic>;
  Future<Map<String, dynamic>> install() async => (await post('/api/install')) as Map<String, dynamic>;
  Future<Map<String, dynamic>> gameFiles() async => (await get('/api/game/files')) as Map<String, dynamic>;
  Future<Map<String, dynamic>> restoreGame({String? backup}) async => (await post('/api/game/restore', backup == null ? {} : {'backup': backup})) as Map<String, dynamic>;

  String iconUrl(String png) => '$base/api/ffr/icon/$png';
  String unitIcon(String key, String kind) => '$base/api/spec/$key/icon/$kind';
  String ffbeIcon(String form) => '$base/api/ffbe/icon/$form';
  String ffbePreview(String form, String anim) => '$base/api/ffbe/preview/$form/$anim';
  String animUrl(String form, String anim) => '$base/api/ffbe/anim/$form/$anim.webp';
  Future<double?> motionSeconds(String form, String anim) async => ((await get('/api/ffbe/motion/$form/$anim')) as Map)['seconds'] as double?;
  Future<Map<String, dynamic>> seq(num id) async => (await get('/api/seq/$id')) as Map<String, dynamic>;
  Future<List<String>> anims(String form) async => (((await get('/api/ffbe/anims/$form')) as Map)['anims'] as List).map((e) => e.toString()).toList();
  String advancedUrl() => '$base/';
}

class ApiException implements Exception {
  ApiException(this.message);
  final String message;
  @override
  String toString() => message;
}
