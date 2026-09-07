import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../design/choice.dart';
import '../../design/resonance_field_color.dart';
import '../../design/theme.dart';
import '../../design/widgets.dart';
import '../../state/app_state.dart';
import '../../state/catalog_helpers.dart';
import '../unit_anim_pane.dart';

/// Step 4: the vision's own LB presentation plus the selected skill mechanics.
class ResonanceStep extends StatefulWidget {
  const ResonanceStep({super.key, required this.unit, required this.set});
  final Map<String, dynamic> unit;
  final void Function(Map<String, dynamic> patch) set;
  @override
  State<ResonanceStep> createState() => _ResonanceStepState();
}

class _ResonanceStepState extends State<ResonanceStep> {
  bool _described = false;
  double? lbSeconds; // the unit's own limit-burst motion length
  Map<String, dynamic>? beLb; // Brave Exvius limit burst: name, effects
  Map<String, dynamic>? lbProfile;
  String? profileError;
  int profileRequest = 0;
  bool showTimeline = false;
  Map<String, dynamic>? seq;
  num? seqFor;

  @override
  void initState() {
    super.initState();
    if (widget.unit['lb_custom'] == null) WidgetsBinding.instance.addPostFrameCallback((_) => _enable());
    _loadUnitFacts();
    _loadProfile();
  }

  @override
  void didUpdateWidget(covariant ResonanceStep oldWidget) {
    super.didUpdateWidget(oldWidget);
    if ((oldWidget.unit['ffbe'] as Map?)?['id'] != (widget.unit['ffbe'] as Map?)?['id']) {
      lbSeconds = null; beLb = null; _described = false;
      _loadUnitFacts();
    }
    if (oldWidget.unit['key'] != widget.unit['key'] ||
        (oldWidget.unit['ffbe'] as Map?)?['id'] != (widget.unit['ffbe'] as Map?)?['id'] ||
        (oldWidget.unit['lb_custom'] as Map?)?['ffbe_lb_id'] != (widget.unit['lb_custom'] as Map?)?['ffbe_lb_id']) {
      _loadProfile();
    }
  }

  Future<void> _loadProfile() async {
    final request = ++profileRequest;
    lbProfile = null; profileError = null;
    final app = context.read<AppState>();
    final ff = widget.unit['ffbe'] as Map?;
    final form = ff?['id']?.toString();
    if (form == null || (app.catalog?['ffbeResonance'] as Map?)?['lbProfiles'] != true) return;
    try {
      final profile = await app.api!.ffbeLb(form,
          lbId: (widget.unit['lb_custom'] as Map?)?['ffbe_lb_id']?.toString(), source: (ff?['source'] ?? 'JP').toString());
      if (!mounted || request != profileRequest) return;
      setState(() => lbProfile = profile);
      final lb = widget.unit['lb_custom'] as Map?;
      if (lb != null && (lb['presentation'] ?? 'ffbe') == 'ffbe' &&
          (lb['mechanics'] ?? 'ffbe') == 'ffbe' && profile['supported'] == true) {
        widget.set({'lb_custom': {...lb, 'set': profile['set'],
          if (lb['descAuto'] != false) 'desc': profile['description']}});
      }
    } catch (_) {
      if (mounted && request == profileRequest) setState(() => profileError = 'Could not read this LB. Check the local engine and retry.');
    }
  }

  Future<void> _loadUnitFacts() async {
    final app = context.read<AppState>();
    final ff = widget.unit['ffbe'] as Map?;
    final form = ff?['id']?.toString();
    if (form == null) return;
    try { final s = await app.api!.motionSeconds(form, 'limitatk'); if (mounted) setState(() => lbSeconds = s); } catch (_) {}
    try {
      final d = await app.api!.ffbeUnit((ff?['base'] ?? form).toString());
      final f = (d['forms'] as Map?)?[form] as Map?;
      if (mounted) setState(() => beLb = (f?['limitburst'] as Map?)?.cast<String, dynamic>());
    } catch (_) {}
  }

  Future<void> _loadSeq(AppState app, num id) async {
    if (seqFor == id) return;
    seqFor = id; seq = null;
    try { final s = await app.api!.seq(id); if (mounted && seqFor == id) setState(() => seq = s); } catch (_) { if (mounted && seqFor == id) setState(() => seq = {'error': true}); }
  }

  void _enable() {
    final u = widget.unit;
    final own = context.read<AppState>().catalog?['ffbeResonance'] != null && u['ffbe'] != null;
    widget.set({'lb_custom': {
      'presentation': own ? 'ffbe' : 'template', 'field_color_mode': 'element',
      'audio': own ? 'native' : 'disabled', 'audio_codec': 'host', 'mechanics': 'ffbe',
      'from': 440110, 'visuals': 440110, 'target_effect': null, 'clone_sequence': true, 'mute': ['VO_'], 'caption_from': 440260,
      'jp': '${u['jp']}_LB', 'en': "${u['en']}'s Resonance",
      'desc': '', 'descAuto': true, 'set': {'element': 'None'},
      'sequence_edits': {}, 'effect_swaps': [],
    }});
  }

  @override
  Widget build(BuildContext context) {
    final app = context.read<AppState>();
    final cat = app.catalog!;
    final lb = widget.unit['lb_custom'] as Map?;
    if (lb == null) return Center(child: Text('preparing', style: Guide.small()));
    final supportsOwn = cat['ffbeResonance'] != null && widget.unit['ffbe'] != null;
    final own = (lb['presentation'] ?? (supportsOwn ? 'ffbe' : 'template')) == 'ffbe';
    final autoMechanics = own && (lb['mechanics'] ?? 'ffbe') == 'ffbe';
    final autoColor = (lb['field_color_mode'] ?? 'element') == 'element';
    final finish = (cat['skills'] as List).cast<Map<String, dynamic>>().where((s) => s['attr'] == 'FinishBlow').toList();
    final effById = {for (final e in (cat['effects'] as List).cast<Map<String, dynamic>>()) e['id'] as num: e};
    final templates = (cat['lbTemplates'] as List).cast<Map<String, dynamic>>().where((t) => !cgResonanceIds.contains(t['id']));
    final targetEffects = ((cat['targetEffects'] as List?) ?? const []).cast<Map<String, dynamic>>();
    final good = templates.where((t) => t['good'] == true).toList();
    final others = templates.where((t) => t['good'] != true).toList();
    String label(Map<String, dynamic> s) { final o = ownerOf(cat, s['id'] as num); return "${o != null ? "$o's " : ''}${s['name']}"; }
    bool isDamage(Map<String, dynamic> s) => (s['dmgType'] == 'Physic' || s['dmgType'] == 'Magic') && (s['mag'] as num) > 0;
    final damaging = finish.where(isDamage).toList();
    final healing = finish.where((s) => s['dmgType'] == 'None' && s['relation'] == 'Friendlies' && s['effectType'] == 'DamageAndRecovery' && (s['mag'] as num) > 0).toList();
    final buffing = finish.where((s) => s['dmgType'] == 'None' && s['relation'] == 'Friendlies' && !healing.contains(s)).toList();
    final debuffing = finish.where((s) => s['relation'] == 'Enemies' && (s['effects'] as List).any((id) { final e = effById[id as num]; return e != null && ['ParameterVariation', 'AccuracyVariation'].contains(e['type']) && e['status'] != null && e['status'] != 'None'; })).toList();
    final captions = finish.where((s) => (s['id'] as num) >= 440000 && (s['id'] as num) < 441000).toList()..sort((a, b) => label(a).compareTo(label(b)));
    final mech = finish.where((s) => s['id'] == lb['from']).firstOrNull ?? finish.first;
    final kind = isDamage(mech) ? 'damage' : healing.contains(mech) ? 'heal' : buffing.contains(mech) ? 'buff' : 'debuff';
    final st = Map<String, dynamic>.from((lb['set'] as Map?) ?? {});
    final element = (st['element'] ?? mech['element'] ?? 'None').toString();
    final fieldColor = autoMechanics ? (lbProfile?['fieldColor'] ?? ResonanceFieldColor.defaultColor).toString()
        : ResonanceFieldColor.forElements([element]);
    final physical = (st['DamageType'] ?? mech['dmgType']) == 'Physic';
    final vis = (lb['visuals'] ?? lb['from']) as num;
    final tpl = templates.where((t) => t['id'] == vis).firstOrNull;
    final window = (tpl?['window'] as num?)?.toDouble();
    final stretched = lbSeconds != null && window != null && window > 0 && lbSeconds! > window;
    if (showTimeline && !own) _loadSeq(app, vis);

    String autoDesc(Map<String, dynamic>? from, Map<String, dynamic> s) {
      final base = describe(from, s);
      final fx = ((from?['effects'] as List?) ?? []).map((id) => effectLabel(effById[id as num])).whereType<String>();
      return [base, ...fx].join(' ');
    }
    void upd(Map<String, dynamic> patch) {
      final n = {...lb, ...patch};
      final fromLb = own && (n['mechanics'] ?? 'ffbe') == 'ffbe';
      if (fromLb && lbProfile?['supported'] == true && !patch.containsKey('ffbe_lb_id')) n['set'] = lbProfile!['set'];
      if (n['descAuto'] != false) {
        if (fromLb) {
          if (lbProfile?['supported'] == true && !patch.containsKey('ffbe_lb_id')) n['desc'] = lbProfile!['description'];
        } else {
          n['desc'] = autoDesc(finish.where((s) => s['id'] == n['from']).firstOrNull, Map<String, dynamic>.from((n['set'] as Map?) ?? {}));
        }
      }
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
    String secs(num? s) => s == null ? '-' : '${s.toStringAsFixed(1)} s';

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Band('Resonance', color: Guide.gold),
            Box(
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                row('Name', Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  TextFormField(key: ValueKey('lbname-${widget.unit['key']}'), initialValue: (lb['en'] ?? '').toString(), onChanged: (v) => upd({'en': v})),
                  if (beLb != null && (beLb!['name'] ?? '').toString().isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text('In Brave Exvius: ${beLb!['name']}. ${((beLb!['effects'] as List?) ?? []).take(3).join(' ')}', style: Guide.small(), maxLines: 3, overflow: TextOverflow.ellipsis),
                  ],
                ])),
                if (supportsOwn || own) row('Presentation', DropdownButtonFormField<String>(
                  key: ValueKey('presentation-$own'), initialValue: own ? 'ffbe' : 'template', isExpanded: true,
                  items: const [
                    DropdownMenuItem(value: 'ffbe', child: Text('Own FFBE limit burst')),
                    DropdownMenuItem(value: 'template', child: Text('Game sequence (advanced)')),
                  ],
                  onChanged: supportsOwn ? (v) {
                    if (v != null) {
                      upd({'presentation': v,
                        if (v == 'template' && cgResonanceIds.contains(vis)) 'visuals': 414090});
                    }
                  } : null,
                )),
                if (own) ...[
                  row('Animation', Text(
                    'Plays this vision’s full limit-burst motion${lbSeconds != null ? ' (${secs(lbSeconds)})' : ''}, then restores the battle field. Attack particles are still in development.',
                    style: Guide.text(),
                  )),
                  if (supportsOwn) ...[
                    row('Sound', DropdownButtonFormField<String>(
                      key: ValueKey('audio-${lb['audio']}'), initialValue: lb['audio'] == 'native' ? 'native' : 'disabled',
                      items: const [DropdownMenuItem(value: 'native', child: Text('FFBE charging and attack sounds')),
                        DropdownMenuItem(value: 'disabled', child: Text('Off'))],
                      onChanged: (v) { if (v != null) upd({'audio': v, 'audio_codec': 'host'}); },
                    )),
                    row('Mechanics', DropdownButtonFormField<String>(
                      key: ValueKey('mechanics-$autoMechanics'), initialValue: autoMechanics ? 'ffbe' : 'custom',
                      items: const [DropdownMenuItem(value: 'ffbe', child: Text('Use imported LB data')),
                        DropdownMenuItem(value: 'custom', child: Text('Custom mechanics (advanced)'))],
                      onChanged: (v) { if (v != null) upd({'mechanics': v}); },
                    )),
                    if (lbProfile != null) ...[
                      if (((lbProfile!['variants'] as List?) ?? []).length > 1)
                        row('LB variant', DropdownButtonFormField<String>(
                          key: ValueKey('variant-${lbProfile!['lbId']}'), initialValue: lbProfile!['lbId'].toString(), isExpanded: true,
                          items: [for (final v in lbProfile!['variants'] as List)
                            DropdownMenuItem(value: v['id'].toString(), child: Text('${(v['elements'] as List).join(' / ')} · ${v['id']}'))],
                          onChanged: (v) { if (v != null) upd({'ffbe_lb_id': v}); },
                        )),
                      if (autoMechanics && lbProfile!['supported'] == true) ...[
                        row('LB data', Text('${lbProfile!['target']} · ${lbProfile!['hits']} hits · ${(lbProfile!['elements'] as List).isEmpty ? 'Non-elemental' : (lbProfile!['elements'] as List).join(' / ')}', style: Guide.text())),
                        row('Power', Text('Cloud’s total resonance power (${lbProfile!['totalPower']}), split across the LB’s hit weights. Includes Cloud’s level scaling and critical bonus.', style: Guide.small())),
                        row('Movement', Text('FFBE move type ${(lbProfile!['movement'] as Map?)?['type']}; LB offset ${(lbProfile!['movement'] as Map?)?['lbOffset'] ?? 'unavailable — native spacing'}.', style: Guide.small())),
                      ],
                      for (final issue in [...(lbProfile!['issues'] as List? ?? []), ...(lbProfile!['warnings'] as List? ?? [])])
                        Text(issue.toString(), style: Guide.small(Guide.red)),
                    ] else ...[
                      Text(profileError ?? ((cat['ffbeResonance'] as Map?)?['lbProfiles'] == true ? 'Reading LB targeting and hit data…' : 'Update the local engine to resolve LB mechanics.'), style: Guide.small()),
                      if (profileError != null) TextButton(onPressed: _loadProfile, child: const Text('Retry')),
                    ],
                    row('Field colour', Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      DropdownButtonFormField<String>(
                        key: ValueKey('color-mode-$autoColor'), initialValue: autoColor ? 'element' : 'custom',
                        items: const [DropdownMenuItem(value: 'element', child: Text('Match attack element')),
                          DropdownMenuItem(value: 'custom', child: Text('Custom colour'))],
                        onChanged: (v) { if (v != null) upd({'field_color_mode': v, if (v == 'custom' && lb['field_color'] == null) 'field_color': fieldColor}); },
                      ),
                      const SizedBox(height: 8),
                      if (autoColor) Row(children: [Container(width: 20, height: 20, color: Color(int.parse('FF${fieldColor.substring(1)}', radix: 16))), const SizedBox(width: 8), Expanded(child: Text('$fieldColor · Grey for no element; multiple elements blend equally.', style: Guide.small()))])
                      else ResonanceFieldColor(
                      key: ValueKey('field-${widget.unit['key']}'),
                      value: (lb['field_color'] ?? ResonanceFieldColor.defaultColor).toString(),
                      onChanged: (v) => upd({'field_color': v}),
                      ),
                    ])),
                  ] else
                    row('Field colour', Text('Update the local engine to edit and build FFBE Resonances.', style: Guide.small())),
                ],
                if (!own) row('Animation', Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  DropdownButtonFormField<num>(
                    key: ValueKey('vis$vis'), initialValue: templates.any((t) => t['id'] == vis) ? vis : null, isExpanded: true,
                    items: [
                      for (final t in good) DropdownMenuItem(value: t['id'] as num, child: Text('${label(t)} · ${secs(t['length'])} · ${t['who']}', style: Guide.text(), overflow: TextOverflow.ellipsis)),
                      if (others.isNotEmpty) DropdownMenuItem<num>(enabled: false, value: null, child: Text("THE OWNER'S CINEMATIC, NO LIMIT-BURST MOTION", style: Guide.label(Guide.inkFaint))),
                      for (final t in others) DropdownMenuItem(value: t['id'] as num, child: Text('${label(t)} · ${secs(t['length'])} · ${t['who']}', style: Guide.text(Guide.inkSoft), overflow: TextOverflow.ellipsis)),
                    ],
                    onChanged: (v) { if (v != null) upd({'visuals': v, 'effect_swaps': []}); },
                  ),
                  const SizedBox(height: 6),
                  if (tpl?['blurb'] != null) Text(tpl!['blurb'].toString(), style: Guide.small(Guide.ink)),
                  if (tpl != null && tpl['good'] != true) ...[
                    const SizedBox(height: 6),
                    Box(fill: Guide.warn, child: Text("This one is the owner's Resonance. Its CG movie is left out of your copy, but the long wait it filled stays and your unit's own limit-burst motion is not played (or only at the end). Hibernal Fury, Healing Wind and Resolute Bastion play it.", style: Guide.small(Guide.ink))),
                  ] else if (stretched) ...[
                    const SizedBox(height: 6),
                    Box(fill: Guide.warn, child: Text("This unit's limit-burst motion runs ${secs(lbSeconds)}; this animation leaves ${secs(window)} for it, so the timing after it is stretched to fit. Stretched timing has not been checked in the game yet; Hibernal Fury gives the most room.", style: Guide.small(Guide.ink))),
                  ] else if (lbSeconds != null && window != null) ...[
                    const SizedBox(height: 4),
                    Text("The unit's limit-burst motion (${secs(lbSeconds)}) fits the ${secs(window)} this animation gives it.", style: Guide.small(Guide.green)),
                  ],
                  const SizedBox(height: 6),
                  InkWell(
                    onTap: () => setState(() => showTimeline = !showTimeline),
                    child: Text(showTimeline ? 'Hide the timeline' : 'Show the timeline (motions, effects, hits, camera in order)', style: Guide.small(Guide.blue).copyWith(decoration: TextDecoration.underline, decorationColor: Guide.blue)),
                  ),
                  if (showTimeline) ...[const SizedBox(height: 6), _timeline()],
                ])),
                if (!own && tpl?['cinematic'] == true)
                  row('On the targets', Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    DropdownButtonFormField<String>(
                      key: ValueKey('tfx${lb['target_effect']}'), isExpanded: true,
                      initialValue: targetEffects.any((t) => t['path'] == lb['target_effect']) ? (lb['target_effect']?.toString() ?? 'none') : 'none',
                      items: [for (final t in targetEffects) DropdownMenuItem(value: (t['path'] ?? 'none').toString(), child: Text(t['name'].toString(), style: Guide.text(), overflow: TextOverflow.ellipsis))],
                      onChanged: (v) => upd({'target_effect': (v == null || v == 'none') ? null : v}),
                    ),
                    const SizedBox(height: 4),
                    Text("What appears on the enemies or allies when the Resonance lands. The owner's own slashes are left out unless you pick them back.", style: Guide.small()),
                  ])),
                if (!autoMechanics) ...[
                row('It is', Choice<String>(
                  options: const [('damage', 'a damaging ability'), ('heal', 'a healing ability'), ('buff', 'a buffing ability'), ('debuff', 'a debuffing ability')],
                  value: kind, onChanged: setKind,
                )),
                if (kind == 'damage') ...[
                  row('Damage', Choice<bool>(options: const [(true, 'Physical'), (false, 'Magical')], value: physical, onChanged: setDamageType)),
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
                ],
                if (!own) row('Caption lines', Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  DropdownButtonFormField<num>(
                    isExpanded: true,
                    key: ValueKey('cap${lb['caption_from']}'), initialValue: captions.any((s) => s['id'] == lb['caption_from']) ? lb['caption_from'] as num : null,
                    items: [for (final s in captions) DropdownMenuItem(value: s['id'] as num, child: Text("Wol's lines from ${label(s)}", style: Guide.text(), overflow: TextOverflow.ellipsis))],
                    onChanged: (v) { if (v != null) upd({'caption_from': v}); },
                  ),
                  const SizedBox(height: 4),
                  Text('The dialogue windows during the cinematic are the ones written for that Resonance; the demo has no others.', style: Guide.small()),
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
            Text(own || tpl?['good'] == true
                ? "This motion plays in the game inside the chosen Resonance sequence${lbSeconds != null ? ' (${secs(lbSeconds)})' : ''}. The arrows show the unit's other motions."
                : "With the chosen animation this motion is not played; the unit holds a cast pose while the owner's cinematic runs.", style: Guide.small()),
          ]),
        ),
      ]),
    );
  }

  Widget _timeline() {
    if (seq == null) return Text('reading the sequence', style: Guide.small());
    if (seq!['error'] == true) return Text('This animation has no battle sequence in the demo.', style: Guide.small(Guide.red));
    final events = (seq!['events'] as List).cast<Map<String, dynamic>>().where((e) => _eventText(e) != null).toList();
    return Box(
      padding: EdgeInsets.zero,
      child: Column(children: [
        for (final (i, e) in events.indexed)
          Container(
            color: i.isOdd ? Guide.paper2 : Guide.paper,
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SizedBox(width: 48, child: Text(e['t'] != null ? '${(e['t'] as num).toStringAsFixed(2)}s' : '', style: Guide.num(Guide.inkSoft).copyWith(fontSize: 12))),
              Container(width: 3, height: 14, color: _eventColor(e), margin: const EdgeInsets.only(right: 8, top: 2)),
              Expanded(child: Text(_eventText(e)!, style: Guide.small(Guide.ink))),
            ]),
          ),
        Padding(padding: const EdgeInsets.all(8), child: Text("Effects and camera are named, not drawn. Motions use this unit's own sprites in the game.", style: Guide.small())),
      ]),
    );
  }

  String? _eventText(Map<String, dynamic> e) {
    final t = e['type'] as String? ?? '';
    if (t == 'UnitPlayAnimByName') return 'Unit plays ${e['Unit_PlayAnimByName_AnimationName']}';
    if (t.startsWith('EffectSpawn')) return 'Effect ${(e['niagaraAsset'] ?? '').toString().replaceAll('import:', '').replaceAll(RegExp(r'^NS_EF_'), '')}';
    if (t == 'OtherReaction') return 'Hit lands';
    if (t == 'UnitMoveToTarget') return 'Unit dashes to the target';
    if (t == 'UnitMoveToDefaultLocation' || t == 'UnitMoveToLocation') return 'Unit moves back';
    if (t == 'PostSetColorGradingGlobalParameter') return 'Screen tint';
    if (t == 'OtherChangeSubSpaceColor') return 'Domain colour';
    if (t == 'BGChange') return 'Domain appears';
    if (t == 'CameraShake') return 'Camera shake';
    if (t == 'CameraSetZoomInOut') return 'Camera zoom';
    if (t == 'UnitStartAfterimage') return 'Afterimage trail';
    if (t == 'Sound') return '${e['voice'] == true ? 'Voice' : 'Sound'} ${e['cue'] ?? ''}';
    return null;
  }

  Color _eventColor(Map<String, dynamic> e) {
    final t = e['type'] as String? ?? '';
    if (t.startsWith('Unit')) return Guide.blue;
    if (t.startsWith('Effect')) return Guide.purple;
    if (t == 'OtherReaction') return Guide.red;
    if (t.startsWith('Post') || t.startsWith('Other') || t == 'BGChange') return Guide.gold;
    if (t == 'Sound') return Guide.green;
    return Guide.inkFaint;
  }
}
