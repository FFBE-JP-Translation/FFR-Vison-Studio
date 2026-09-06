import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../design/theme.dart';
import '../design/widgets.dart';
import '../state/app_state.dart';
import '../state/catalog_helpers.dart';
import 'steps/abilities_step.dart';
import 'steps/bonuses_step.dart';
import 'steps/resonance_step.dart';
import 'steps/stats_step.dart';
import 'unit_anim_pane.dart';

/// A unit's page: left, the character entry (sprite, stats); right, the walkthrough in four numbered steps.
class UnitScreen extends StatefulWidget {
  const UnitScreen({super.key});
  @override
  State<UnitScreen> createState() => _UnitScreenState();
}

class _UnitScreenState extends State<UnitScreen> {
  int step = 0;
  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    final u = app.selected;
    if (u == null) return const SizedBox.shrink();
    final api = app.api!;
    final stats = (u['stats'] as Map?) ?? {};
    final form = (u['ffbe'] as Map?)?['id']?.toString();
    void set(Map<String, dynamic> patch) => app.update({...u, ...patch});
    return Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      SizedBox(
        width: 300,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Band((u['en'] ?? '').toString(), color: Guide.ink),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(14),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                if (form != null) UnitAnimPane(unit: u, height: 210) else Frame(padding: 8, child: PixelImage(api.unitIcon(u['key'] as String, 'face'), width: 128, height: 128)),
                const SizedBox(height: 6),
                Text('${u['attackType'] == 'Magic' ? 'Magic' : 'Physical'} · ${((u['roles'] as List?) ?? []).map((r) => r.toString().replaceAll('eUnitRole::', '')).join(', ')}', style: Guide.small()),
                const SizedBox(height: 14),
                Band('Stats at level 1', color: Guide.blue),
                Box(
                  padding: EdgeInsets.zero,
                  child: Column(children: [
                    for (var i = 0; i < statFields.length; i++) StatRow(statFields[i].$2, '${stats[statFields[i].$1] ?? '-'}', zebra: i.isOdd),
                  ]),
                ),
                const SizedBox(height: 14),
                Band('Resonance', color: Guide.gold),
                Box(child: Builder(builder: (_) {
                  final lb = u['lb_custom'] as Map?;
                  final tpl = (app.catalog?['lbTemplates'] as List?)?.cast<Map>().where((t) => t['id'] == (lb?['visuals'] ?? lb?['from'])).firstOrNull;
                  final el = (lb?['set'] as Map?)?['element']?.toString();
                  return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(lb?['desc']?.toString().isNotEmpty == true ? lb!['desc'].toString() : 'Set in step 4.', style: Guide.small(Guide.ink)),
                    if (tpl != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text('${tpl['name']}${el != null && el != 'None' ? ' · $el' : ''}${tpl['good'] == true ? '' : ' · no limit-burst motion'}', style: Guide.small(tpl['good'] == true ? Guide.inkSoft : Guide.red))),
                  ]);
                })),
              ]),
            ),
          ),
        ]),
      ),
      Container(width: 2, color: Guide.ink),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Container(
            color: Guide.paper2,
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 0),
            child: PageTabs(tabs: const ['Abilities', 'Bonuses', 'Stats', 'Resonance'], index: step, onSelect: (i) => setState(() => step = i)),
          ),
          Container(height: 2, color: Guide.ink),
          Expanded(
            child: AnimatedSwitcher(
              duration: Guide.fast,
              layoutBuilder: (current, previous) => Stack(fit: StackFit.expand, children: [...previous, ?current]),
              child: switch (step) {
                0 => AbilitiesStep(key: const ValueKey('a'), unit: u, set: set),
                1 => BonusesStep(key: const ValueKey('b'), unit: u, set: set),
                2 => StatsStep(key: const ValueKey('s'), unit: u, set: set),
                _ => ResonanceStep(key: const ValueKey('r'), unit: u, set: set),
              },
            ),
          ),
        ]),
      ),
    ]);
  }
}

/// Asks, then removes the unit from the mod (the next install removes it from the game).
Future<void> confirmRemove(BuildContext context, AppState app, Map<String, dynamic> u) async {
  final ok = await showDialog<bool>(context: context, builder: (c) => AlertDialog(
    backgroundColor: Guide.paper, shape: Border.fromBorderSide(Guide.frame),
    title: Text('Remove ${u['en']} from the mod?', style: Guide.h2()),
    content: Text('The unit and its choices are deleted from the mod. The next install removes it from the game.', style: Guide.text()),
    actions: [GuideButton('Keep', onPressed: () => Navigator.pop(c, false)), GuideButton('Remove', danger: true, onPressed: () => Navigator.pop(c, true))],
  ));
  if (ok == true) await app.removeUnit(u['key'] as String);
}
