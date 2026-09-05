import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../design/theme.dart';
import '../design/widgets.dart';
import '../state/app_state.dart';
import '../state/catalog_helpers.dart';

/// "Play like an existing vision": copies one of the game's visions onto the unit. Abilities, passives and stat boosts by
/// awakening tier, stats, attack type, roles, and the Resonance's numbers. The unit keeps its own look and name.
Future<void> showCopyVision(BuildContext context, Map<String, dynamic> unit, void Function(Map<String, dynamic> patch) set) async {
  final app = context.read<AppState>();
  final cat = app.catalog!;
  final visions = (cat['visions'] as List).cast<Map<String, dynamic>>().where((v) => (v['stats'] as Map?)?['MaxHitPoint'] != null).toList()
    ..sort((a, b) => (a['name'] as String).compareTo(b['name'] as String));
  final skillsById = {for (final s in (cat['skills'] as List).cast<Map<String, dynamic>>()) s['id'] as num: s};
  final passivesById = {for (final s in (cat['passives'] as List).cast<Map<String, dynamic>>()) s['id'] as num: s};
  final templates = (cat['lbTemplates'] as List).cast<Map<String, dynamic>>();
  String? picked;
  await showDialog<void>(
    context: context,
    builder: (c) => StatefulBuilder(builder: (c, setState) {
      final v = picked == null ? null : visions.firstWhere((x) => '${x['id']}' == picked);
      final aw = ((v?['awakening'] as List?) ?? []).map((t) => (t as List).cast<List>()).toList();
      String grantName(List g) => g[0] == 'ActiveSkill'
          ? (skillsById[g[1] as num]?['name']?.toString() ?? 'skill ${g[1]}')
          : g[0] == 'PassiveSkill'
              ? (passivesById[g[1] as num]?['name']?.toString() ?? 'passive ${g[1]}')
              : '${statParams.where((p) => p.$1 == (g[1] as num).toInt()).map((p) => p.$2).firstOrNull ?? 'stat'} +${g.length > 2 ? g[2] : ''}';
      return Dialog(
        backgroundColor: Colors.transparent,
        insetPadding: const EdgeInsets.all(32),
        child: Paper(
          width: 820,
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Band('Play like a vision the game already has'),
            Padding(
              padding: const EdgeInsets.all(16),
              child: SizedBox(
                height: 460,
                child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  SizedBox(
                    width: 280,
                    child: Box(
                      padding: EdgeInsets.zero,
                      child: ListView.builder(
                        itemCount: visions.length,
                        itemBuilder: (_, i) {
                          final x = visions[i]; final active = '${x['id']}' == picked;
                          return Material(
                            color: active ? Guide.paper3 : (i.isOdd ? Guide.paper2 : Guide.paper),
                            child: InkWell(
                              onTap: () => setState(() => picked = '${x['id']}'),
                              child: Padding(
                                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
                                child: Row(children: [
                                  Expanded(child: Text(x['name'] as String, style: Guide.strong())),
                                  Text('${x['attackType'] == 'Magic' ? 'Magic' : 'Physical'} · ${((x['roles'] as List?) ?? []).map((r) => r.toString().replaceAll('eUnitRole::', '')).join(', ')}', style: Guide.small(), overflow: TextOverflow.ellipsis),
                                ]),
                              ),
                            ),
                          );
                        },
                      ),
                    ),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: v == null
                        ? Center(child: Text('Pick a vision on the left. Everything it knows is copied onto ${unit['en']}.', style: Guide.small()))
                        : SingleChildScrollView(
                            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                              Text((v['name'] as String).toUpperCase(), style: Guide.h2()),
                              const SizedBox(height: 8),
                              Box(
                                padding: EdgeInsets.zero,
                                child: Column(children: [
                                  for (var i = 0; i < statFields.length; i++) StatRow(statFields[i].$2, '${(v['stats'] as Map)[statFields[i].$1] ?? '-'}', zebra: i.isOdd),
                                ]),
                              ),
                              const SizedBox(height: 10),
                              for (var t = 0; t < aw.length; t++) ...[
                                Text('TIER ${t + 1}', style: Guide.label()),
                                const SizedBox(height: 2),
                                Text(aw[t].isEmpty ? 'nothing' : aw[t].map(grantName).join(' · '), style: Guide.small(Guide.ink)),
                                const SizedBox(height: 6),
                              ],
                              Text('RESONANCE', style: Guide.label()),
                              const SizedBox(height: 2),
                              Text(skillsById[v['finishBlow'] as num]?['name']?.toString() ?? '-', style: Guide.small(Guide.ink)),
                            ]),
                          ),
                  ),
                ]),
              ),
            ),
            Container(
              decoration: BoxDecoration(border: Border(top: BorderSide(color: Guide.hairline))),
              padding: const EdgeInsets.all(12),
              child: Row(children: [
                Expanded(child: Text('Replaces the unit\'s abilities, bonuses, stats, type, roles and Resonance numbers. Its look, name and Resonance animation stay.', style: Guide.small())),
                GuideButton('Cancel', onPressed: () => Navigator.pop(c)),
                const SizedBox(width: 8),
                GoButton('Copy this vision', color: Guide.blue, onPressed: v == null ? null : () {
                  final lb = Map<String, dynamic>.from((unit['lb_custom'] as Map?) ?? {});
                  final fb = v['finishBlow'] as num;
                  final mech = skillsById[fb];
                  if (mech != null) {
                    lb['from'] = fb;
                    if (templates.any((t) => t['id'] == fb)) lb['visuals'] = fb;
                    if (fb >= 440000 && fb < 441000) lb['caption_from'] = fb;
                    final s = Map<String, dynamic>.from((lb['set'] as Map?) ?? {});
                    s['element'] = mech['element'] ?? 'None';
                    if (mech['dmgType'] == 'Physic' || mech['dmgType'] == 'Magic') { s['DamageType'] = mech['dmgType']; s['damageCalcType'] = mech['dmgType']; s['SkillIcon.TagName'] = iconTagFor(cat, (s['element'] ?? 'None').toString(), mech['dmgType'] == 'Physic', false); }
                    lb['set'] = s;
                    lb['descAuto'] = true;
                    lb['desc'] = describe(mech, s);
                  }
                  set({
                    'stats': {...((unit['stats'] as Map?) ?? {}), ...(v['stats'] as Map)},
                    'attackType': v['attackType'] == 'Magic' ? 'Magic' : 'Physic',
                    'roles': List<String>.from(((v['roles'] as List?) ?? ['eUnitRole::Attacker']).map((e) => e.toString())),
                    'awakening': aw.map((t) => t.map((g) => List<dynamic>.from(g)).toList()).toList(),
                    'lb_custom': lb,
                  });
                  Navigator.pop(c);
                }),
              ]),
            ),
          ]),
        ),
      );
    }),
  );
}
