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
import 'package:provider/provider.dart';
import 'package:window_manager/window_manager.dart';

import 'design/theme.dart';
import 'design/widgets.dart';
import 'design/wordmark.dart';
import 'screens/home_screen.dart';
import 'screens/setup_screen.dart';
import 'screens/unit_screen.dart';
import 'state/app_state.dart';

const hostBase = 'https://ffbe.luminest.io/';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await windowManager.ensureInitialized();
  await windowManager.waitUntilReadyToShow(const WindowOptions(size: Size(1320, 860), minimumSize: Size(1100, 700), title: 'FFR Vision Studio', backgroundColor: Guide.desk), () async {
    await windowManager.show();
    await windowManager.focus();
  });
  final state = AppState(hostBase: Platform.environment['FFR_STUDIO_HOST'] ?? hostBase);
  runApp(ChangeNotifierProvider.value(value: state, child: const StudioApp()));
  state.boot();
}

class StudioApp extends StatefulWidget {
  const StudioApp({super.key});
  @override
  State<StudioApp> createState() => _StudioAppState();
}

class _StudioAppState extends State<StudioApp> with WindowListener {
  @override
  void initState() { super.initState(); windowManager.addListener(this); windowManager.setPreventClose(true); }
  @override
  void dispose() { windowManager.removeListener(this); super.dispose(); }
  @override
  void onWindowClose() async {
    final app = context.read<AppState>();
    await app.save();
    await app.engine?.stop();
    await windowManager.destroy();
  }
  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'FFR Vision Studio',
        debugShowCheckedModeBanner: false,
        theme: Guide.theme(),
        home: const Shell(),
      );
}

/// The desk with the spread on it. Header strip carries the title, the unit path and the save state.
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
            ConstrainedBox(constraints: const BoxConstraints(maxWidth: 420), child: Text(app.gameRoot ?? '', style: Guide.small(Guide.inkFaint), maxLines: 1, overflow: TextOverflow.ellipsis)),
          ]),
          const SizedBox(height: 12),
          Expanded(child: Paper(child: AnimatedSwitcher(duration: Guide.fast, layoutBuilder: (current, previous) => Stack(fit: StackFit.expand, children: [...previous, if (current != null) current]), child: u == null ? const HomeScreen(key: ValueKey('home')) : UnitScreen(key: ValueKey(u['key']))))),
        ]),
      ),
    );
  }
}
