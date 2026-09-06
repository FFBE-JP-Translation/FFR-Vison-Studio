// FFR Vision Studio -- direction contract (impeccable seed faddaf33, assigned index 6, user-confirmed)
// THESIS: the app is a strategy-guide spread for your own vision, not a launcher dashboard; it refuses the dark card grid
//   with a blue accent that every mod tool ships.
// OWN-WORLD: glossy white page on a warm grey desk; 2 px black frames around anything that is a picture of the game;
//   saturated colour bands as section headers (FF blue, gold for Resonance, red for GO, green for done); Barlow Condensed
//   caps for headings and bands, Barlow for the page, tabular figures in stat boxes with tinted zebra rows.
// STORY: you open the guide to your unit's page, read its entry on the left, follow four numbered steps on the right, and
//   press the red GO to put it in the game.
// FIRST VIEWPORT: a two-page spread: left page "Your visions" with black-framed sprite entries; right page "Install" with
//   the game/mod status box, the red GO button and the build notes below it.
// FORM: a 90s console strategy-guide page (candidate 6 of 7 on the grounded list; seed key faddaf33).
// FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, and DESIGN.md
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path/path.dart' as p;
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:window_manager/window_manager.dart';

import 'design/theme.dart';
import 'design/theme_toggle.dart';
import 'design/widgets.dart';
import 'design/wordmark.dart';
import 'screens/about_dialog.dart';
import 'screens/copy_vision_dialog.dart';
import 'screens/home_screen.dart';
import 'screens/setup_screen.dart';
import 'screens/unit_screen.dart';
import 'services/paths.dart';
import 'state/app_state.dart';
import 'version.dart';

const hostBase = 'https://ffbe.luminest.io/';
final navKey = GlobalKey<NavigatorState>();
RandomAccessFile? _lock; // held for the app's lifetime: one studio per machine (they would share one units file)

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await windowManager.ensureInitialized();
  final alreadyRunning = !_acquireLock();
  await windowManager.waitUntilReadyToShow(
      WindowOptions(size: alreadyRunning ? const Size(520, 300) : const Size(1320, 860), minimumSize: alreadyRunning ? const Size(520, 300) : const Size(960, 600), title: 'FFR Vision Studio', backgroundColor: Guide.desk), () async {
    await windowManager.show();
    await windowManager.focus();
  });
  if (alreadyRunning) {
    runApp(const AlreadyRunningApp());
    return;
  }
  final state = AppState(hostBase: Platform.environment['FFR_STUDIO_HOST'] ?? hostBase);
  runApp(ChangeNotifierProvider.value(value: state, child: const StudioApp()));
  state.boot();
}

bool _acquireLock() {
  try {
    final root = AppPaths.resolve().root;
    final f = File(p.join(root, 'app.lock')).openSync(mode: FileMode.write);
    f.lockSync(FileLock.exclusive);
    _lock = f;
    return true;
  } on FileSystemException {
    return false;
  } catch (_) {
    return true; // if locking is not possible at all, do not refuse to start
  }
}

/// Shown instead of a second studio.
class AlreadyRunningApp extends StatelessWidget {
  const AlreadyRunningApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: Guide.theme(),
        home: Scaffold(
          body: Center(
            child: Paper(
              width: 460,
              child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                const Band('Already open'),
                Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                    Text('FFR Vision Studio is already running on this machine. Two copies would edit the same units file, so this one closes.', style: Guide.text()),
                    const SizedBox(height: 14),
                    Row(children: [const Spacer(), GuideButton('Close', onPressed: () => exit(0))]),
                  ]),
                ),
              ]),
            ),
          ),
        ),
      );
}

class StudioApp extends StatefulWidget {
  const StudioApp({super.key});
  @override
  State<StudioApp> createState() => _StudioAppState();
}

class _StudioAppState extends State<StudioApp> with WindowListener {
  bool _closing = false;
  @override
  void initState() { super.initState(); windowManager.addListener(this); windowManager.setPreventClose(true); }
  @override
  void dispose() { windowManager.removeListener(this); super.dispose(); }
  @override
  void onWindowClose() async {
    if (_closing) return;
    final app = context.read<AppState>();
    if (app.building) {
      final ctx = navKey.currentContext;
      final ok = ctx == null ? true : await showDialog<bool>(
        context: ctx,
        builder: (c) => AlertDialog(
          backgroundColor: Guide.paper, shape: Border.fromBorderSide(Guide.frame),
          title: Text('A build is running', style: Guide.h2()),
          content: Text('Closing now stops the engine in the middle of writing the mod. If it was installing, the game folder keeps the previous files (there is a backup). Close anyway?', style: Guide.text()),
          actions: [GuideButton('Keep building', onPressed: () => Navigator.pop(c, false)), GuideButton('Close anyway', danger: true, onPressed: () => Navigator.pop(c, true))],
        ),
      );
      if (ok != true) return;
    }
    _closing = true;
    await app.shutdown();
    try { _lock?.unlockSync(); _lock?.closeSync(); } catch (_) {}
    await windowManager.destroy();
  }
  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    Guide.dark = app.dark; // every Guide colour reads this; the keyed subtree redraws the whole page on a switch
    return MaterialApp(
      title: 'FFR Vision Studio',
      navigatorKey: navKey,
      debugShowCheckedModeBanner: false,
      theme: Guide.theme(),
      home: KeyedSubtree(key: ValueKey(app.dark), child: const Shell()),
    );
  }
}

/// The desk with the spread on it. Header strip carries the title, the unit path, the save state, the version and the switch.
class Shell extends StatelessWidget {
  const Shell({super.key});
  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    if (app.phase == Phase.boot || app.phase == Phase.setup || app.phase == Phase.failed) return const Scaffold(body: SetupScreen());
    final u = app.selected;
    return Scaffold(
      body: Padding(
        padding: const EdgeInsets.fromLTRB(22, 18, 22, 22),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            if (u != null) ...[
              Padding(padding: const EdgeInsets.only(bottom: 4), child: GuideButton('All visions', icon: Icons.arrow_back, small: true, onPressed: () => app.select(null))),
              const SizedBox(width: 14),
            ],
            Wordmark(size: 34, onTap: () => app.select(null)),
            if (u != null) ...[
              Padding(padding: const EdgeInsets.fromLTRB(12, 0, 12, 2), child: Text('/', style: Guide.h2(Guide.inkFaint))),
              Padding(padding: const EdgeInsets.only(bottom: 2), child: Text((u['en'] ?? '').toString().toUpperCase(), style: Guide.h2())),
            ],
            const Spacer(),
            AnimatedSwitcher(
              duration: Guide.fast,
              child: Text(app.notice ?? (app.dirty ? 'saving' : 'saved'), key: ValueKey(app.notice ?? app.dirty), style: Guide.small(app.notice != null ? Guide.red : Guide.inkSoft)),
            ),
            const SizedBox(width: 16),
            if (u == null) ...[
              if (app.updateAvailable != null) ...[
                Text('version ${app.updateAvailable} is out', style: Guide.small(Guide.blue)),
                const SizedBox(width: 8),
                GuideButton(app.updating ? (app.updateStep ?? 'updating') : 'Update now', small: true, icon: Icons.system_update_alt, onPressed: app.updating ? null : app.updateApp),
                const SizedBox(width: 16),
              ],
              InkWell(onTap: () => showAbout(context), child: Tooltip(message: 'About FFR Vision Studio', child: Text(appLabel, style: Guide.small(Guide.inkFaint)))),
              const SizedBox(width: 14),
              const ThemeToggle(),
            ] else ...[
              GuideButton('Play like a vision the game has', icon: Icons.content_copy, small: true, onPressed: () => showCopyVision(context, u, (patch) => app.update({...u, ...patch}))),
              const SizedBox(width: 8),
              GuideButton('Remove', icon: Icons.delete_outline, small: true, danger: true, onPressed: () => confirmRemove(context, app, u)),
            ],
          ]),
          if (app.engineDown) ...[
            const SizedBox(height: 10),
            Container(
              color: Guide.red,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Row(children: [
                Expanded(child: Text('The engine stopped. Nothing is saved or built until it runs again; the log is in the logs folder.', style: Guide.text(Guide.onBand))),
                GuideButton('Open logs', small: true, onPressed: app.openLogs),
                const SizedBox(width: 8),
                GuideButton('Restart the engine', small: true, icon: Icons.refresh, onPressed: app.restartEngine),
              ]),
            ),
          ] else if (app.banner != null) ...[
            const SizedBox(height: 10),
            Container(
              color: Guide.gold,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Row(children: [
                Expanded(child: Text(app.banner!, style: Guide.text(Guide.onBandFor(Guide.gold)))),
                if (app.banner!.contains('Download')) GuideButton('Download page', small: true, icon: Icons.open_in_new, onPressed: () => launchUrl(Uri.parse(app.downloadPage))),
              ]),
            ),
          ],
          const SizedBox(height: 12),
          Expanded(child: Paper(child: AnimatedSwitcher(duration: Guide.fast, layoutBuilder: (current, previous) => Stack(fit: StackFit.expand, children: [...previous, ?current]), child: u == null ? const HomeScreen(key: ValueKey('home')) : UnitScreen(key: ValueKey(u['key']))))),
        ]),
      ),
    );
  }
}
