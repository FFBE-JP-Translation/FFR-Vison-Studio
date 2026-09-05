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
  AppState({required this.hostBase});
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
  String? notice; // one-line message for the footer

  JsonMap? get selected => units.cast<JsonMap?>().firstWhere((u) => u?['key'] == selectedKey, orElse: () => null);

  // ---------------------------------------------------------------- boot
  Future<void> boot() async {
    try {
      // Find the game first so the folder is already filled in while the packs download.
      if (gameRoot == null) GameLocator.detect().then((g) { if (g != null && gameRoot == null) { gameRoot = g; notifyListeners(); } });
      manifest = await dl.manifest();
      final packs = manifest!['packs'] as JsonMap;
      final installed = _readInstalled();
      Future<void> pack(int step, String name, String into) async {
        final info = packs[name] as JsonMap?;
        if (info == null) throw StateError('the host has no "$name" pack');
        final s = bootSteps[step];
        final ver = manifest!['version'];
        if (installed[name] == ver && Directory(into).existsSync()) {
          s.state = 'done'; s.detail = 'version $ver'; notifyListeners(); return;
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
        installed[name] = ver; _writeInstalled(installed);
        s.state = 'done'; s.detail = 'version $ver'; notifyListeners();
      }
      await pack(0, 'engine', paths.engineDir);
      await pack(1, 'base', paths.engineData);
      await pack(2, 'tables', p.join(paths.engineData, 'ffbe'));
      try { hostIndex = await dl.json_('ffbe/index.json'); } catch (_) {}
      final s = bootSteps[3];
      s.state = 'working'; notifyListeners();
      engine = Engine(paths.engineExe);
      await engine!.start();
      api = Api(engine!.baseUrl);
      s.state = 'done'; s.detail = 'port ${engine!.port}'; notifyListeners();
      await refreshStatus();
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
      gameRoot = (st['gameRoot'] as String?) ?? gameRoot;
      notifyListeners();
    } catch (_) {}
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

  Future<void> removeUnit(String key) async {
    await api!.deleteUnit(key);
    units = await api!.spec();
    if (selectedKey == key) selectedKey = null;
    notifyListeners();
  }

  /// Adds a Brave Exvius unit: downloads its sprite pack from the host when the engine lacks it, then asks the engine.
  Future<JsonMap> addUnit(String ffbeId, String form, String name, {void Function(String)? onStep}) async {
    final spriteDir = p.join(paths.engineSprites, form);
    if (!Directory(spriteDir).existsSync()) {
      final forms = (hostIndex?['forms'] as JsonMap?) ?? {};
      final info = forms[form] as JsonMap?;
      if (info == null) throw StateError('no sprite pack for form $form is available on the host yet');
      onStep?.call('downloading the sprites');
      final f = await dl.download(info['url'] as String, p.join(paths.downloads, '$form.zip'), sha256: info['sha256'] as String?);
      await Downloader.unzip(f, spriteDir);
      onStep?.call('indexing');
      await api!.rebuildFfbeIndex();
    }
    onStep?.call('adding to the mod');
    final u = await api!.addUnit(ffbeId, form: form, name: name);
    units = await api!.spec();
    selectedKey = u['key'] as String?;
    notifyListeners();
    return u;
  }

  // ---------------------------------------------------------------- build / install
  bool get building => buildState?['running'] == true;

  Future<void> startBuild({required bool install}) async {
    await save();
    try {
      await api!.build(install: install);
    } catch (e) {
      notice = e.toString(); notifyListeners(); return;
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

  Future<void> installLast() async {
    try {
      final r = await api!.install();
      buildState = {'running': false, 'result': 'ok', 'log': buildState?['log'] ?? <String>[], 'stage': 'Done', 'message': r['message'], 'install': true};
      await refreshStatus();
    } catch (e) { notice = e.toString(); }
    notifyListeners();
  }

  @override
  void dispose() {
    _buildTimer?.cancel(); _statusTimer?.cancel(); _saveTimer?.cancel();
    engine?.stop();
    super.dispose();
  }
}
