import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;

import '../services/api.dart';
import '../services/downloader.dart';
import '../services/engine.dart';
import '../services/game_locator.dart';
import '../services/paths.dart';
import '../version.dart';

/// Where the app is in its life: bootstrapping (downloads + engine), first-run setup, or ready.
enum Phase { boot, setup, ready, failed }

class Progress {
  Progress(this.label, {this.state = 'waiting', this.fraction, this.detail});
  final String label;
  String state; // waiting | working | done | failed
  double? fraction;
  String? detail;
}

/// Loose-typed views over the engine's JSON documents.
typedef JsonMap = Map<String, dynamic>;

class AppState extends ChangeNotifier {
  AppState({required this.hostBase}) { _loadSettings(); _afterUpdate(); }
  final String hostBase;
  final paths = AppPaths.resolve();
  late final Downloader dl = Downloader(hostBase);
  Engine? engine;
  Api? api;

  Phase phase = Phase.boot;
  String? fatal;
  final bootSteps = <Progress>[
    Progress('Download the engine'),
    Progress('Download the game-side data'),
    Progress('Download the Brave Exvius tables'),
    Progress('Start the engine'),
  ];
  String? gameRoot;
  bool gameRunning = false;
  bool modInstalled = false;
  bool dark = false; // the night edition of the guide
  final Map<String, List<String>> _anims = {};
  int backups = 0;
  int placed = 0;
  Progress? setupProgress;
  final setupLog = <String>[];

  JsonMap? manifest;
  JsonMap? hostIndex; // ffbe/index.json: units + forms with packs
  JsonMap? catalog;
  List<dynamic> units = [];
  String? selectedKey;
  bool dirty = false;
  JsonMap? buildState; // /api/build/log
  Timer? _buildTimer;
  Timer? _statusTimer;
  String? notice; // one-line message in the header for a few seconds
  String? banner; // a standing message (offline, old app); shown until the situation changes
  String? updateAvailable; // "1.0.0 build 5" when the host has a newer app
  bool engineDown = false; // the engine process ended on its own
  bool updating = false;
  String? updateStep;
  String? engineVersion;
  bool _stopping = false;

  JsonMap? get selected => units.cast<JsonMap?>().firstWhere((u) => u?['key'] == selectedKey, orElse: () => null);
  String get logsDir => p.join(paths.root, 'logs');
  String get downloadPage => hostBase.endsWith('/') ? hostBase : '$hostBase/';

  // ---------------------------------------------------------------- boot
  Future<void> boot() async {
    try {
      // Find the game first so the folder is already filled in while the packs download.
      if (gameRoot == null) GameLocator.detect().then((g) { if (g != null && gameRoot == null) { gameRoot = g; notifyListeners(); } });
      final installed = _readInstalled();
      final haveEngine = installed['engine'] != null && File(paths.engineExe).existsSync();
      JsonMap? man;
      String? why;
      try { man = await dl.manifest(); } catch (e) { why = e.toString(); }

      if (man == null) {
        // Offline (or the host is down): run what is installed.
        if (!haveEngine) throw StateError('Could not reach the download host ($why) and nothing is installed yet. Check the connection and try again.');
        _markInstalled(installed);
        banner = 'Could not reach the download host. Running the installed version; updates are checked next start.';
      } else {
        manifest = man;
        final tag = man['version'].toString();
        final minApp = (man['minApp'] ?? '').toString();
        if (compareTags(tag, appTag) > 0 && (man['packs'] as JsonMap?)?['app'] != null) {
          updateAvailable = man['displayVersion'] != null ? '${man['displayVersion']} build ${man['build']}' : tag;
        }
        final tooNew = minApp.isNotEmpty && compareTags(minApp, appTag) > 0;
        if (tooNew) {
          // The host's engine needs a newer app than this one. Keep what is installed rather than mixing versions.
          if (!haveEngine) throw StateError('This copy of the app ($appLabel) is older than the packs on the host. Download the new app from $downloadPage.');
          _markInstalled(installed);
          banner = 'A newer version is on the host and needs the new app. Download it from the page; this copy keeps working as it is.';
        } else {
          final packs = man['packs'] as JsonMap;
          Future<void> pack(int step, String name, String into) async {
            final info = packs[name] as JsonMap?;
            if (info == null) throw StateError('the host has no "$name" pack');
            final s = bootSteps[step];
            if (installed[name] == tag && Directory(into).existsSync()) {
              s.state = 'done'; s.detail = 'version ${_pretty(tag)}'; notifyListeners(); return;
            }
            s.state = 'working'; notifyListeners();
            final dest = p.join(paths.downloads, p.basename(info['url'] as String));
            final f = await dl.download(info['url'] as String, dest, sha256: info['sha256'] as String?, onProgress: (got, total) {
              s.fraction = total > 0 ? got / total : null;
              s.detail = '${(got / 1048576).toStringAsFixed(0)} MB';
              notifyListeners();
            });
            s.detail = 'unpacking'; s.fraction = null; notifyListeners();
            await Downloader.unzip(f, into);
            installed[name] = tag; _writeInstalled(installed);
            s.state = 'done'; s.detail = 'version ${_pretty(tag)}'; notifyListeners();
          }
          await pack(0, 'engine', paths.engineDir);
          await pack(1, 'base', paths.engineData);
          await pack(2, 'tables', p.join(paths.engineData, 'ffbe'));
        }
        try {
          hostIndex = await dl.json_('ffbe/index.json');
          File(p.join(paths.root, 'ffbe_index_cache.json')).writeAsStringSync(json.encode(hostIndex));
        } catch (_) {}
      }
      if (hostIndex == null) {
        try { hostIndex = json.decode(File(p.join(paths.root, 'ffbe_index_cache.json')).readAsStringSync()) as JsonMap; } catch (_) {}
      }
      await _startEngine(bootSteps[3]);
      gameRoot ??= await GameLocator.detect();
      final st = await api!.status();
      phase = (st['setupNeeded'] == true) ? Phase.setup : Phase.ready;
      if (phase == Phase.ready) await loadAll();
      _statusTimer = Timer.periodic(const Duration(seconds: 8), (_) => refreshStatus());
    } catch (e) {
      final working = bootSteps.where((s) => s.state == 'working');
      for (final s in working) { s.state = 'failed'; s.detail = e.toString(); }
      fatal = e.toString();
      phase = Phase.failed;
    }
    notifyListeners();
  }

  String _pretty(String tag) {
    final parts = tag.split('.');
    return parts.length == 4 ? '${parts.take(3).join('.')} build ${parts[3]}' : tag;
  }

  void _markInstalled(Map<String, dynamic> installed) {
    for (final (i, name) in ['engine', 'base', 'tables'].indexed) {
      bootSteps[i].state = 'done';
      bootSteps[i].detail = 'installed ${_pretty(installed[name]?.toString() ?? '?')}';
    }
    notifyListeners();
  }

  Future<void> _startEngine(Progress s) async {
    s.state = 'working'; s.detail = null; notifyListeners();
    final day = DateTime.now().toIso8601String().substring(0, 10);
    engine = Engine(
      paths.engineExe,
      logPath: p.join(logsDir, 'engine-$day.log'),
      logDir: logsDir,
      header: ['app $appLabel', 'host $hostBase', 'engine ${File(paths.engineExe).path}'],
      onExit: (code) {
        engineDown = true;
        api = null;
        notifyListeners();
      },
    );
    await engine!.start();
    api = Api(engine!.baseUrl);
    engineDown = false;
    s.state = 'done'; s.detail = 'port ${engine!.port}'; notifyListeners();
    await refreshStatus();
  }

  /// After the engine stopped on its own: start it again and reload everything.
  Future<void> restartEngine() async {
    try {
      await _startEngine(bootSteps[3]);
      if (phase == Phase.ready) await loadAll();
      showNotice('The engine is back.');
    } catch (e) {
      showNotice('The engine could not be restarted: $e');
    }
  }

  Map<String, dynamic> _readInstalled() {
    try { return json.decode(File(paths.installedManifest).readAsStringSync()) as Map<String, dynamic>; } catch (_) { return {}; }
  }
  void _writeInstalled(Map<String, dynamic> m) => File(paths.installedManifest).writeAsStringSync(json.encode(m));

  Future<void> refreshStatus() async {
    if (api == null) return;
    try {
      final st = await api!.status();
      gameRunning = st['gameRunning'] == true;
      modInstalled = st['modInstalled'] == true;
      backups = (st['backups'] as num?)?.toInt() ?? 0;
      placed = (st['placed'] as num?)?.toInt() ?? 0;
      gameRoot = (st['gameRoot'] as String?) ?? gameRoot;
      engineVersion = st['engineVersion']?.toString();
      notifyListeners();
    } catch (_) {
      if (engine != null && !engine!.running && !_stopping) { engineDown = true; notifyListeners(); }
    }
  }

  /// Opens the folder with the engine logs in Explorer.
  Future<void> openLogs() async {
    Directory(logsDir).createSync(recursive: true);
    try { await Process.start('explorer.exe', [logsDir]); } catch (_) {}
  }

  // ---------------------------------------------------------------- first-run setup
  Future<void> runSetup(String game) async {
    setupProgress = Progress('Preparing the game\'s data', state: 'working');
    setupLog.clear();
    notifyListeners();
    try {
      await api!.setup(game);
      while (true) {
        await Future<void>.delayed(const Duration(seconds: 1));
        final l = await api!.setupLog();
        final lines = (l['log'] as List).cast<String>();
        setupLog..clear()..addAll(lines);
        setupProgress!.detail = lines.isEmpty ? null : lines.last;
        notifyListeners();
        if (l['running'] != true) {
          if (l['result'] == 'ok') {
            setupProgress!.state = 'done';
            phase = Phase.ready;
            await loadAll();
          } else {
            setupProgress!.state = 'failed';
            setupProgress!.detail = lines.isEmpty ? 'the preparation did not finish' : lines.last;
          }
          break;
        }
      }
    } catch (e) {
      setupProgress!.state = 'failed';
      setupProgress!.detail = e.toString();
    }
    notifyListeners();
  }

  // ---------------------------------------------------------------- data
  Future<void> loadAll() async {
    catalog = await api!.catalog();
    units = await api!.spec();
    await refreshStatus();
    notifyListeners();
  }

  void select(String? key) { selectedKey = key; notifyListeners(); }

  void update(JsonMap unit) {
    units = units.map((u) => (u as JsonMap)['key'] == unit['key'] ? unit : u).toList();
    dirty = true;
    notifyListeners();
    _saveSoon();
  }

  Timer? _saveTimer;
  void _saveSoon() {
    _saveTimer?.cancel();
    _saveTimer = Timer(const Duration(milliseconds: 700), save);
  }

  Future<void> save() async {
    if (!dirty || api == null) return;
    try { await api!.saveSpec(units); dirty = false; notice = null; } catch (e) { notice = 'Could not save: $e'; }
    notifyListeners();
  }

  Future<bool> removeUnit(String key) async {
    try {
      await api!.deleteUnit(key);
      units = await api!.spec();
      if (selectedKey == key) selectedKey = null;
      notifyListeners();
      return true;
    } catch (e) {
      showNotice('Could not remove the unit: $e');
      return false;
    }
  }

  /// The face icon of a unit form on the host (every unit has one there, before any sprite download).
  String hostIconUrl(String form) => '${downloadPage}ffbe/icons/$form.png';

  /// Makes sure a form's sprite pack is on this machine: downloads it from its shard and lets the engine index it.
  /// A pack counts as present only when its sheet, its parts file and the completion marker are all there.
  Future<void> ensureSprites(String form, {void Function(String)? onStep}) async {
    final spriteDir = p.join(paths.engineSprites, form);
    final complete = File(p.join(spriteDir, '.complete')).existsSync() ||
        (File(p.join(spriteDir, 'unit_anime_$form.png')).existsSync() && File(p.join(spriteDir, 'unit_cgg_$form.csv')).existsSync());
    if (complete) return;
    final forms = (hostIndex?['forms'] as JsonMap?) ?? {};
    final info = forms[form] as JsonMap?;
    if (info == null) throw StateError(banner != null && banner!.startsWith('Could not reach') ? 'the sprites for this look are not on this machine and the download host is unreachable' : 'no sprite pack for form $form is available on the host yet');
    onStep?.call('downloading the sprites');
    final f = await dl.download(info['url'] as String, p.join(paths.downloads, '$form.zip'), sha256: info['sha256'] as String?);
    await Downloader.unzip(f, spriteDir);
    if (!File(p.join(spriteDir, 'unit_anime_$form.png')).existsSync()) throw StateError('the sprite pack for $form is incomplete');
    File(p.join(spriteDir, '.complete')).writeAsStringSync(DateTime.now().toIso8601String());
    onStep?.call('indexing');
    await api!.rebuildFfbeIndex();
    _anims.remove(form);
  }

  /// Animation names for a form, from the engine, cached.
  Future<List<String>> animsFor(String form) async {
    final c = _anims[form];
    if (c != null) return c;
    final a = await api!.anims(form);
    _anims[form] = a;
    return a;
  }

  Future<JsonMap> addUnit(String ffbeId, String form, String name, {void Function(String)? onStep}) async {
    await ensureSprites(form, onStep: onStep);
    onStep?.call('adding to the mod');
    final u = await api!.addUnit(ffbeId, form: form, name: name);
    units = await api!.spec();
    selectedKey = u['key'] as String?;
    notifyListeners();
    return u;
  }

  // ---------------------------------------------------------------- self-update
  /// A running exe cannot replace itself, so: stage the new app next to the app data, write a small batch file that waits for
  /// this process to end, copies the staged folder over the one the exe lives in and starts the new exe, then leave.
  Future<void> updateApp() async {
    final info = (manifest?['packs'] as JsonMap?)?['app'] as JsonMap?;
    if (info == null || updating) return;
    final exePath = Platform.resolvedExecutable;
    final exeDir = File(exePath).parent.path;
    try { final t = File(p.join(exeDir, '.write_test')); t.writeAsStringSync('x'); t.deleteSync(); }
    catch (_) { showNotice('The app folder is read-only, so it cannot update itself. Download the new version from the page.'); return; }
    updating = true; updateStep = 'downloading'; notifyListeners();
    try {
      final ver = manifest!['version'].toString();
      final f = await dl.download(info['url'] as String, p.join(paths.downloads, 'app-$ver.zip'), sha256: info['sha256'] as String?, onProgress: (got, total) {
        updateStep = 'downloading ${(got / 1048576).toStringAsFixed(0)} MB'; notifyListeners();
      });
      final staging = p.join(paths.root, 'app-staging', ver);
      if (Directory(staging).existsSync()) Directory(staging).deleteSync(recursive: true);
      updateStep = 'unpacking'; notifyListeners();
      await Downloader.unzip(f, staging);
      final inner = Directory(staging).listSync().whereType<Directory>().toList();
      final src = inner.length == 1 ? inner.first.path : staging;
      if (!File(p.join(src, p.basename(exePath))).existsSync() && !File(p.join(src, 'FFR Vision Studio.exe')).existsSync()) throw StateError('the downloaded app has no executable');
      final newExe = File(p.join(src, p.basename(exePath))).existsSync() ? p.basename(exePath) : 'FFR Vision Studio.exe';
      final cmd = File(p.join(paths.root, 'update.cmd'));
      cmd.writeAsStringSync('@echo off\r\n'
          ':wait\r\n'
          'tasklist /FI "PID eq $pid" 2>NUL | find "$pid" >NUL && (timeout /t 1 /nobreak >NUL & goto wait)\r\n'
          'robocopy "$src" "$exeDir" /E /IS /IT /NFL /NDL /NJH /NJS >NUL\r\n'
          'rmdir /S /Q "$staging"\r\n'
          'start "" "${p.join(exeDir, newExe)}"\r\n'
          'del "%~f0"\r\n');
      updateStep = 'restarting'; notifyListeners();
      await Process.start('cmd.exe', ['/c', cmd.path], mode: ProcessStartMode.detached);
      await shutdown();
      exit(0);
    } catch (e) {
      updating = false; updateStep = null;
      showNotice('The update did not go through: $e. The download page has the new version.');
    }
  }

  /// After a self-update: drop the helper and say what happened, once.
  void _afterUpdate() {
    try {
      final cmd = File(p.join(paths.root, 'update.cmd'));
      if (cmd.existsSync()) cmd.deleteSync();
      final st = Directory(p.join(paths.root, 'app-staging'));
      if (st.existsSync()) st.deleteSync(recursive: true);
      final f = File(paths.settingsFile);
      final j = f.existsSync() ? json.decode(f.readAsStringSync()) as Map : <String, dynamic>{};
      final last = j['lastRun']?.toString();
      if (last != null && last != appTag) banner = 'Updated to $appLabel.';
      j['lastRun'] = appTag;
      f.writeAsStringSync(json.encode(j));
    } catch (_) {}
  }

  // ---------------------------------------------------------------- settings
  void _loadSettings() {
    try {
      final f = File(paths.settingsFile);
      if (f.existsSync()) { final j = json.decode(f.readAsStringSync()) as Map; dark = j['dark'] == true; }
    } catch (_) {}
  }

  /// One-line message in the header for a few seconds.
  void showNotice(String s) {
    notice = s; notifyListeners();
    Future.delayed(const Duration(seconds: 6), () { if (notice == s) { notice = null; notifyListeners(); } });
  }

  void setDark(bool v) {
    dark = v; notifyListeners();
    try {
      final f = File(paths.settingsFile);
      final j = f.existsSync() ? json.decode(f.readAsStringSync()) as Map : <String, dynamic>{};
      j['dark'] = dark;
      f.writeAsStringSync(json.encode(j));
    } catch (_) {}
  }

  // ---------------------------------------------------------------- build / install
  bool get building => buildState?['running'] == true;

  Future<void> startBuild({required bool install}) async {
    await save();
    try {
      await api!.build(install: install);
    } catch (e) {
      showNotice(e.toString()); return;
    }
    buildState = {'running': true, 'log': <String>[], 'stage': 'Starting'};
    notifyListeners();
    _buildTimer?.cancel();
    _buildTimer = Timer.periodic(const Duration(milliseconds: 1200), (t) async {
      try {
        buildState = await api!.buildLog();
        if (buildState?['running'] != true) { t.cancel(); await refreshStatus(); }
      } catch (_) {}
      notifyListeners();
    });
  }

  /// Removes what the studio placed in the game folder and puts back what was there before; or puts one backup back.
  Future<Map<String, dynamic>> restoreGame({String? backup}) async {
    final r = await api!.restoreGame(backup: backup);
    showNotice(r['message']?.toString() ?? 'Done.');
    await refreshStatus();
    return r;
  }

  Future<void> installLast() async {
    try {
      final r = await api!.install();
      buildState = {'running': false, 'result': 'ok', 'log': buildState?['log'] ?? <String>[], 'stage': 'Done', 'message': r['message'], 'install': true};
      await refreshStatus();
    } catch (e) { showNotice(e.toString()); }
    notifyListeners();
  }

  Future<void> shutdown() async {
    _stopping = true;
    _buildTimer?.cancel(); _statusTimer?.cancel(); _saveTimer?.cancel();
    await save();
    await engine?.stop();
  }

  @override
  void dispose() {
    _stopping = true;
    _buildTimer?.cancel(); _statusTimer?.cancel(); _saveTimer?.cancel();
    engine?.stop();
    super.dispose();
  }
}
