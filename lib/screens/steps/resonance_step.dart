import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../design/theme.dart';
import '../../design/widgets.dart';
import '../../state/app_state.dart';
import '../../state/catalog_helpers.dart';
import '../unit_anim_pane.dart';

/// Step 4: one of the demo's Resonance animations plus one existing Resonance's mechanics.
class ResonanceStep extends StatefulWidget {
  const ResonanceStep({super.key, required this.unit, required this.set});
  final Map<String, dynamic> unit;
  final void Function(Map<String, dynamic> patch) set;
  @override
  State<ResonanceStep> createState() => _ResonanceStepState();
}

class _ResonanceStepState extends State<ResonanceStep> {
  bool _described = false;

  @override
  void initState() {
    super.initState();
    if (widget.unit['lb_custom'] == null) WidgetsBinding.instance.addPostFrameCallback((_) => _enable());
  }

  void _enable() {
    final u = widget.unit;
    widget.set({'lb_custom': {
      'from': 414090, 'visuals': 414090, 'clone_sequence': true, 'mute': ['VO_'], 'caption_from': 440260, 'jp': '${u['jp']}_LB', 'en': "${u['en']}'s Resonance",
      'desc': '', 'descAuto': true, 'set': {'element': 'None'},
      'sequence_edits': {'master': [{'match': {'EventType': 'OtherChangeSubSpaceColor'}, 'set': {'Other_ChangeSubSpaceColor_Color': {'R': 0.25, 'G': 0.25, 'B': 0.35, 'A': 1.0}}}]}, 'effect_swaps': [],
    }});
  }

  @override
  Widget build(BuildContext context) {
    final app = context.read<AppState>();
    final cat = app.catalog!;
    final lb = widget.unit['lb_custom'] as Map?;
    if (lb == null) return Center(child: Text('preparing', style: Guide.small()));
    final finish = (cat['skills'] as List).cast<Map<String, dynamic>>().where((s) => s['attr'] == 'FinishBlow').toList();
    final effById = {for (final e in (cat['effects'] as List).cast<Map<String, dynamic>>()) e['id'] as num: e};
    final templates = (cat['lbTemplates'] as List).cast<Map<String, dynamic>>();
    String label(Map<String, dynamic> s) { final o = ownerOf(cat, s['id'] as num); return "${o != null ? "$o's " : ''}${s['name']}"; }
    bool isDamage(Map<String, dynamic> s) => (s['dmgType'] == 'Physic' || s['dmgType'] == 'Magic') && (s['mag'] as num) > 0;
    final damaging = finish.where(isDamage).toList();
    final healing = finish.where((s) => s['dmgType'] == 'None' && s['relation'] == 'Friendlies' && s['effectType'] == 'DamageAndRecovery' && (s['mag'] as num) > 0).toList();
    final buffing = finish.where((s) => s['dmgType'] == 'None' && s['relation'] == 'Friendlies' && !healing.contains(s)).toList();
    final debuffing = finish.where((s) => s['relation'] == 'Enemies' && (s['effects'] as List).any((id) { final e = effById[id as num]; return e != null && ['ParameterVariation', 'AccuracyVariation'].contains(e['type']) && e['status'] != null && e['status'] != 'None'; })).toList();
    final mech = finish.where((s) => s['id'] == lb['from']).firstOrNull ?? finish.first;
    final kind = isDamage(mech) ? 'damage' : healing.contains(mech) ? 'heal' : buffing.contains(mech) ? 'buff' : 'debuff';
    final st = Map<String, dynamic>.from((lb['set'] as Map?) ?? {});
    final element = (st['element'] ?? mech['element'] ?? 'None').toString();
    final physical = (st['DamageType'] ?? mech['dmgType']) == 'Physic';
    final vis = (lb['visuals'] ?? lb['from']) as num;

    String autoDesc(Map<String, dynamic>? from, Map<String, dynamic> s) {
      final base = describe(from, s);
      final fx = ((from?['effects'] as List?) ?? []).map((id) => effectLabel(effById[id as num])).whereType<String>();
      return [base, ...fx].join(' ');
    }
    void upd(Map<String, dynamic> patch) {
      final n = {...lb, ...patch};
      if (n['descAuto'] != false) n['desc'] = autoDesc(finish.where((s) => s['id'] == n['from']).firstOrNull, Map<String, dynamic>.from((n['set'] as Map?) ?? {}));
      widget.set({'lb_custom': n});
    }
    // Units arrive from the engine with a bare default; write the description once so the entry reads like the others.
    if (!_described && lb['descAuto'] == null) {
      _described = true;
      WidgetsBinding.instance.addPostFrameCallback((_) { if (mounted) upd({'descAuto': true}); });
    }
    void setMech(num id) {
      final m = finish.firstWhere((s) => s['id'] == id);
      final s = Map<String, dynamic>.from(st);
      if (isDamage(m)) {
        s['element'] = st['element'] ?? m['element']; s['DamageType'] = m['dmgType']; s['damageCalcType'] = m['dmgType'];
        s['SkillIcon.TagName'] = iconTagFor(cat, (s['element'] ?? 'None').toString(), m['dmgType'] == 'Physic', false);
      } else {
        s.remove('DamageType'); s.remove('damageCalcType'); s['element'] = 'None';
        s['SkillIcon.TagName'] = healing.contains(m) ? 'UI.Skill.Action.Icon.Heal' : m['relation'] == 'Enemies' ? 'UI.Skill.Action.Icon.BadStatus' : 'UI.Skill.Action.Icon.Support';
      }
      upd({'from': id, 'caption_from': (id >= 440000 && id < 441000) ? id : (lb['caption_from'] ?? 440260), 'set': s});
    }
    void setKind(String k) {
      final pool = k == 'damage' ? damaging : k == 'heal' ? healing : k == 'buff' ? buffing : debuffing;
      if (pool.isEmpty) return;
      setMech((pool.where((s) => s['target'] == 'Group').firstOrNull ?? pool.first)['id'] as num);
    }
    void setDamageType(bool phys) {
      final pool = damaging.where((s) => (s['dmgType'] == 'Physic') == phys).toList();
      final same = pool.where((s) => s['target'] == mech['target']).firstOrNull ?? pool.firstOrNull;
      if (same != null) setMech(same['id'] as num);
    }
    final pool = kind == 'damage' ? damaging.where((s) => (s['dmgType'] == 'Physic') == physical).toList() : kind == 'heal' ? healing : kind == 'buff' ? buffing : debuffing;

    Widget row(String label, Widget child) => Padding(padding: const EdgeInsets.symmetric(vertical: 5), child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [SizedBox(width: 110, child: Padding(padding: const EdgeInsets.only(top: 8), child: Text(label.toUpperCase(), style: Guide.label()))), Expanded(child: child)]));
    Widget radio<T>(T v, T g, String l, ValueChanged<T?> on) => Row(mainAxisSize: MainAxisSize.min, children: [Radio<T>(value: v, groupValue: g, onChanged: on), Text(l, style: Guide.text()), const SizedBox(width: 10)]);

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Band('Resonance', color: Guide.gold),
            Box(
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                row('Name', TextFormField(key: ValueKey('lbname-${widget.unit['key']}'), initialValue: (lb['en'] ?? '').toString(), onChanged: (v) => upd({'en': v}))),
                row('Animation', Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  DropdownButtonFormField<num>(
                    key: ValueKey('vis$vis'), initialValue: templates.any((t) => t['id'] == vis) ? vis : null,
                    items: [for (final t in templates) DropdownMenuItem(value: t['id'] as num, child: Text(label(t), style: Guide.text()))],
                    onChanged: (v) { if (v != null) upd({'visuals': v, 'effect_swaps': []}); },
                  ),
                  const SizedBox(height: 4),
                  Text("The Resonance animations the demo ships with a full battle sequence. The unit's own limit-burst motion and Tronn's domain are kept.", style: Guide.small()),
                ])),
                row('It is', Wrap(children: [
                  for (final (k, l) in [('damage', 'a damaging ability'), ('heal', 'a healing ability'), ('buff', 'a buffing ability'), ('debuff', 'a debuffing ability')]) radio<String>(k, kind, l, (_) => setKind(k)),
                ])),
                if (kind == 'damage') ...[
                  row('Damage', Row(children: [radio<bool>(true, physical, 'Physical', (_) => setDamageType(true)), radio<bool>(false, physical, 'Magical', (_) => setDamageType(false))])),
                  row('Element', Wrap(spacing: 6, runSpacing: 6, children: [
                    for (final e in elements)
                      ChoiceChip(
                        label: Row(mainAxisSize: MainAxisSize.min, children: [ElementSwatch(e, size: 9), const SizedBox(width: 6), Text(e == 'None' ? 'Non-elemental' : e, style: Guide.small(Guide.ink))]),
                        selected: element == e, showCheckmark: false, selectedColor: Guide.paper3, backgroundColor: Guide.paper, shape: RoundedRectangleBorder(borderRadius: BorderRadius.zero, side: BorderSide(color: element == e ? Guide.ink : Guide.hairline, width: element == e ? 2 : 1)),
                        onSelected: (_) => upd({'set': {...st, 'element': e, 'SkillIcon.TagName': iconTagFor(cat, e, physical, false)}}),
                      ),
                  ])),
                  row('Targets', DropdownButtonFormField<String>(
                    key: ValueKey('tt${st['TargetType'] ?? mech['target']}'), initialValue: (st['TargetType'] ?? mech['target'] ?? 'Group').toString(),
                    items: const [DropdownMenuItem(value: 'Single', child: Text('One enemy')), DropdownMenuItem(value: 'Group', child: Text('All enemies')), DropdownMenuItem(value: 'Random', child: Text('Random enemies'))],
                    onChanged: (v) => upd({'set': {...st, 'TargetType': v}}),
                  )),
                ],
                row('Numbers like', Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  DropdownButtonFormField<num>(
                    isExpanded: true,
                    key: ValueKey('from${lb['from']}-$kind-$physical'), initialValue: pool.any((s) => s['id'] == lb['from']) ? lb['from'] as num : null,
                    items: [for (final s in pool) DropdownMenuItem(value: s['id'] as num, child: Text('${label(s)}: ${describe(s)}', style: Guide.text(), overflow: TextOverflow.ellipsis))],
                    onChanged: (v) { if (v != null) setMech(v); },
                  ),
                  const SizedBox(height: 4),
                  Text("The power, hit count and extra effects of that vision's Resonance, with your element and damage type applied.", style: Guide.small()),
                  const SizedBox(height: 6),
                  Wrap(spacing: 6, runSpacing: 6, children: [
                    for (final t in (mech['effects'] as List).map((id) => effectLabel(effById[id as num])).whereType<String>())
                      Container(decoration: BoxDecoration(border: Border.all(color: Guide.gold, width: 1.5)), padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2), child: Text(t, style: Guide.small(Guide.ink))),
                  ]),
                ])),
                row('Description', Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  TextFormField(key: ValueKey('lbdesc-${lb['desc']}-${lb['descAuto']}'), initialValue: (lb['desc'] ?? '').toString(), maxLines: 3, readOnly: lb['descAuto'] != false, onChanged: (v) => upd({'desc': v, 'descAuto': false})),
                  Row(mainAxisSize: MainAxisSize.min, children: [Checkbox(value: lb['descAuto'] != false, onChanged: (v) => upd({'descAuto': v == true})), Text('write it for me', style: Guide.small())]),
                ])),
              ]),
            ),
          ]),
        ),
        const SizedBox(width: 16),
        SizedBox(
          width: 360,
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Band('Limit burst', color: Guide.gold, trailing: Text('BRAVE EXVIUS MOTION', style: Guide.band(Guide.onBandFor(Guide.gold)).copyWith(fontSize: 11, letterSpacing: 0.6))),
            const SizedBox(height: 8),
            UnitAnimPane(unit: widget.unit, initial: 'limitatk', height: 280),
            const SizedBox(height: 8),
            Text("The unit's own limit-burst motion plays in the game inside the chosen Resonance sequence. The arrows show its other motions.", style: Guide.small()),
          ]),
        ),
      ]),
    );
  }
}
