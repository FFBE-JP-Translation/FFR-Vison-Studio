import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

/// The generation engine: a hidden local process (the packaged Python/.NET toolchain) the app starts on a free
/// port and talks to over localhost. It is stopped with POST /api/shutdown when the app closes.
class Engine {
  Engine(this.exePath);
  final String exePath;
  Process? _proc;
  int? port;
  final _log = <String>[];
  List<String> get log => List.unmodifiable(_log);

  bool get running => _proc != null && port != null;
  String get baseUrl => 'http://127.0.0.1:$port';

  Future<void> start() async {
    if (running) return;
    final proc = await Process.start(exePath, ['--engine'], workingDirectory: File(exePath).parent.path, runInShell: false);
    _proc = proc;
    final ready = Completer<int>();
    proc.stdout.transform(utf8.decoder).transform(const LineSplitter()).listen((line) {
      _log.add(line);
      if (_log.length > 400) _log.removeAt(0);
      final m = RegExp(r'^READY (\d+)').firstMatch(line);
      if (m != null && !ready.isCompleted) ready.complete(int.parse(m.group(1)!));
    });
    proc.stderr.transform(utf8.decoder).transform(const LineSplitter()).listen((line) {
      _log.add(line);
      if (_log.length > 400) _log.removeAt(0);
    });
    proc.exitCode.then((code) {
      _log.add('engine exited ($code)');
      _proc = null;
      port = null;
      if (!ready.isCompleted) ready.completeError(StateError('the engine stopped before it was ready (exit $code)'));
    });
    port = await ready.future.timeout(const Duration(seconds: 60), onTimeout: () {
      proc.kill();
      throw TimeoutException('the engine did not start within a minute');
    });
    // wait until the HTTP side answers
    for (var i = 0; i < 40; i++) {
      try {
        final r = await http.get(Uri.parse('$baseUrl/api/status')).timeout(const Duration(seconds: 3));
        if (r.statusCode == 200) return;
      } catch (_) {}
      await Future<void>.delayed(const Duration(milliseconds: 500));
    }
    throw TimeoutException('the engine started but does not answer');
  }

  Future<void> stop() async {
    final proc = _proc;
    if (proc == null) return;
    try {
      await http.post(Uri.parse('$baseUrl/api/shutdown')).timeout(const Duration(seconds: 3));
      await proc.exitCode.timeout(const Duration(seconds: 5));
    } catch (_) {
      proc.kill();
    }
    _proc = null;
    port = null;
  }
}
