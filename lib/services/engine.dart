import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

/// The generation engine: a hidden local process (the packaged Python/.NET toolchain) the app starts on a free
/// port and talks to over localhost. It is stopped with POST /api/shutdown when the app closes. Everything it
/// prints goes to `logPath` (one file per day) so a failure can be looked at afterwards; `onExit` fires when the
/// process ends on its own (not through `stop`), so the app can offer a restart.
class Engine {
  Engine(this.exePath, {this.logPath, this.logDir, this.onExit, this.header = const []});
  final String exePath;
  final String? logPath;
  final String? logDir; // handed to the engine (FFR_LOG_DIR) so its own error and build logs land in the same folder
  final void Function(int code)? onExit;
  final List<String> header;
  Process? _proc;
  int? port;
  bool _stopping = false;
  IOSink? _sink;
  final _log = <String>[];
  List<String> get log => List.unmodifiable(_log);

  bool get running => _proc != null && port != null;
  String get baseUrl => 'http://127.0.0.1:$port';

  void _line(String line) {
    _log.add(line);
    if (_log.length > 400) _log.removeAt(0);
    try { _sink?.writeln('${DateTime.now().toIso8601String().substring(11, 19)} $line'); } catch (_) {}
  }

  Future<void> start() async {
    if (running) return;
    _stopping = false;
    if (logPath != null) {
      try {
        final f = File(logPath!);
        f.parent.createSync(recursive: true);
        _sink = f.openWrite(mode: FileMode.append);
        _sink!.writeln('----- ${DateTime.now().toIso8601String()} engine start');
        for (final h in header) {
          _sink!.writeln(h);
        }
      } catch (_) { _sink = null; }
    }
    final proc = await Process.start(exePath, ['--engine'], workingDirectory: File(exePath).parent.path, runInShell: false,
        environment: logDir == null ? null : {'FFR_LOG_DIR': logDir!});
    _proc = proc;
    final ready = Completer<int>();
    proc.stdout.transform(utf8.decoder).transform(const LineSplitter()).listen((line) {
      _line(line);
      final m = RegExp(r'^READY (\d+)').firstMatch(line);
      if (m != null && !ready.isCompleted) ready.complete(int.parse(m.group(1)!));
    });
    proc.stderr.transform(utf8.decoder).transform(const LineSplitter()).listen(_line);
    proc.exitCode.then((code) {
      _line('engine exited ($code)');
      final wasRunning = _proc == proc;
      _proc = null;
      port = null;
      if (!ready.isCompleted) ready.completeError(StateError('the engine stopped before it was ready (exit $code)'));
      if (wasRunning && !_stopping) onExit?.call(code);
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
    _stopping = true;
    if (proc == null) return;
    try {
      await http.post(Uri.parse('$baseUrl/api/shutdown')).timeout(const Duration(seconds: 3));
      await proc.exitCode.timeout(const Duration(seconds: 5));
    } catch (_) {
      proc.kill();
    }
    _proc = null;
    port = null;
    try { await _sink?.flush(); await _sink?.close(); } catch (_) {}
    _sink = null;
  }
}
