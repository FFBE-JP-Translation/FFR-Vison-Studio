import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../design/theme.dart';
import '../design/widgets.dart';
import '../state/app_state.dart';

const _stages = ['Starting', 'Preparing the game tables', 'Writing game tables and copying battle sequences', 'Applying Resonance and animation edits', 'Converting sprites and icons', 'Packing the mod', 'Verifying the game tables', 'Done'];

/// Build progress as a guide "notes" box: stage, bar, outcome, and the console on demand.
class BuildStatus extends StatefulWidget {
  const BuildStatus({super.key});
  @override
  State<BuildStatus> createState() => _BuildStatusState();
}

class _BuildStatusState extends State<BuildStatus> {
  bool open = false;
  final _scroll = ScrollController();
  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    final st = app.buildState ?? const {};
    final running = st['running'] == true;
    final ok = !running && st['result'] == 'ok';
    final failed = !running && st['result'] != null && st['result'] != 'ok';
    final stage = (st['stage'] as String?) ?? 'Starting';
    var idx = _stages.indexWhere((s) => stage.startsWith(s));
    if (idx < 0) idx = 0;
    final pct = running ? idx / (_stages.length - 1) : 1.0;
    final log = ((st['log'] as List?) ?? const []).cast<String>();
    WidgetsBinding.instance.addPostFrameCallback((_) { if (open && _scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent); });
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Band(running ? stage : ok ? 'Done' : failed ? 'Something went wrong' : 'Build', color: running ? Guide.blue : ok ? Guide.green : failed ? Guide.red : Guide.inkSoft,
          trailing: TextButton(onPressed: () => setState(() => open = !open), child: Text(open ? 'HIDE CONSOLE' : 'CONSOLE', style: Guide.band().copyWith(fontSize: 12)))),
      Box(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          if (running) ...[
            LinearProgressIndicator(value: pct, minHeight: 8, color: Guide.blue, backgroundColor: Guide.paper3),
            const SizedBox(height: 8),
            Text('A full build takes a few minutes: sprites are converted for every unit each time.', style: Guide.small()),
          ],
          if (!running && st['message'] != null) Text(st['message'] as String, style: Guide.text(ok ? Guide.green : Guide.red)),
          if (open) ...[
            const SizedBox(height: 10),
            Container(
              height: 220,
              color: Guide.ink,
              padding: const EdgeInsets.all(10),
              child: SingleChildScrollView(controller: _scroll, child: Text(log.join('\n'), style: Guide.mono(Guide.paper2))),
            ),
          ],
        ]),
      ),
    ]);
  }
}
