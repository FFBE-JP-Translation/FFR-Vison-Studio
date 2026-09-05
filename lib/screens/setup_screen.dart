import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../design/theme.dart';
import '../design/widgets.dart';
import '../design/wordmark.dart';
import '../design/theme_toggle.dart';
import '../services/game_locator.dart';
import '../state/app_state.dart';

/// First run: downloads, engine start, game folder, preparation. One checklist box, like a guide's "Before you start".
class SetupScreen extends StatefulWidget {
  const SetupScreen({super.key});
  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  final _game = TextEditingController();
  bool _seeded = false;

  StepMark _state(String s) => switch (s) { 'working' => StepMark.working, 'done' => StepMark.done, 'failed' => StepMark.failed, _ => StepMark.waiting };

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    if (!_seeded && app.gameRoot != null) { _game.text = app.gameRoot!; _seeded = true; }
    final booted = app.bootSteps.every((s) => s.state == 'done');
    final gameOk = GameLocator.isGameRoot(_game.text);
    final preparing = app.setupProgress?.state == 'working';
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(32),
        child: Paper(
          width: 760,
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(28, 26, 28, 10),
              child: Row(children: [const Wordmark(size: 44), const Spacer(), const ThemeToggle()]),
            ),
            const Band('Before you start'),
            Padding(
              padding: const EdgeInsets.all(28),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Text('The first start downloads the engine and the game-side data, then reads your copy of the game once. Nothing in the game folder changes until you press "Install into the game".', style: Guide.text()),
                const SizedBox(height: 18),
                Box(
                  padding: EdgeInsets.zero,
                  child: Column(children: [
                    for (var i = 0; i < app.bootSteps.length; i++) _row(i + 1, app.bootSteps[i].label, StatusCell(_state(app.bootSteps[i].state), text: app.bootSteps[i].detail, progress: app.bootSteps[i].fraction), zebra: i.isOdd),
                    _row(5, 'Find the game', _gameCell(app, gameOk), zebra: false, tall: true),
                    _row(6, "Prepare the game's data", app.setupProgress == null
                        ? Text(booted && gameOk ? 'ready when you are' : 'waiting', style: Guide.small(Guide.inkFaint))
                        : StatusCell(_state(app.setupProgress!.state), text: app.setupProgress!.detail), zebra: true),
                  ]),
                ),
                if (app.fatal != null) ...[
                  const SizedBox(height: 14),
                  Box(fill: const Color(0xFFFBEAEA), child: Text(app.fatal!, style: Guide.text(Guide.red))),
                  const SizedBox(height: 10),
                  Row(children: [GuideButton('Try again', icon: Icons.refresh, onPressed: () { app.fatal = null; for (final s in app.bootSteps) { if (s.state == 'failed') s.state = 'waiting'; } app.boot(); })]),
                ],
                if (app.setupLog.isNotEmpty) ...[
                  const SizedBox(height: 14),
                  Container(
                    height: 150,
                    decoration: BoxDecoration(color: Guide.consoleBg),
                    padding: const EdgeInsets.all(10),
                    child: SingleChildScrollView(reverse: true, child: Text(app.setupLog.skip(app.setupLog.length > 60 ? app.setupLog.length - 60 : 0).join('\n'), style: Guide.mono(Guide.consoleFg))),
                  ),
                ],
                const SizedBox(height: 22),
                Row(children: [
                  GoButton(preparing ? 'Preparing' : 'Prepare and continue', busy: preparing, onPressed: booted && gameOk && !preparing ? () => app.runSetup(_game.text) : null),
                  const SizedBox(width: 14),
                  Expanded(child: Text(booted && !gameOk ? 'Point at the folder that contains FFRS.exe.' : 'Takes about two minutes. The game can stay closed.', style: Guide.small())),
                  GuideButton('Logs folder', small: true, icon: Icons.folder_open, onPressed: app.openLogs),
                ]),
              ]),
            ),
          ]),
        ),
      ),
    );
  }

  Widget _row(int n, String label, Widget status, {required bool zebra, bool tall = false}) => Container(
        color: zebra ? Guide.paper2 : Guide.paper,
        padding: EdgeInsets.symmetric(horizontal: 12, vertical: tall ? 10 : 8),
        child: Row(children: [
          SizedBox(width: 26, child: Text('$n', style: Guide.label(Guide.inkFaint))),
          Expanded(flex: 4, child: Text(label, style: Guide.strong())),
          Expanded(flex: 6, child: Align(alignment: Alignment.centerLeft, child: status)),
        ]),
      );

  Widget _gameCell(AppState app, bool ok) => Row(children: [
        Expanded(
          child: TextField(
            controller: _game,
            style: Guide.small(Guide.ink),
            decoration: InputDecoration(hintText: r'…\steamapps\common\FINAL FANTASY RESONANCE DEMO', suffixIcon: Icon(ok ? Icons.check : Icons.search, size: 16, color: ok ? Guide.green : Guide.inkFaint)),
            onChanged: (_) => setState(() {}),
          ),
        ),
        const SizedBox(width: 8),
        GuideButton('Browse', small: true, onPressed: () async {
          final d = await FilePicker.platform.getDirectoryPath(dialogTitle: 'Where is FINAL FANTASY RESONANCE DEMO installed?');
          if (d != null) setState(() => _game.text = d);
        }),
        const SizedBox(width: 6),
        GuideButton('Find', small: true, icon: Icons.travel_explore, onPressed: () async {
          final d = await GameLocator.detect();
          if (!mounted) return;
          if (d != null) {
            setState(() => _game.text = d);
          } else {
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Steam does not list the game and no drive has it in steamapps\common. Browse to it.', style: Guide.text(Guide.paper)), backgroundColor: Guide.ink));
          }
        }),
      ]);

  @override
  void dispose() { _game.dispose(); super.dispose(); }
}
