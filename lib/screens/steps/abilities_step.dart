import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../design/theme.dart';
import '../../design/widgets.dart';
import '../../state/app_state.dart';
import '../../state/catalog_helpers.dart';
import 'tiers.dart';

/// Step 1: the game's own abilities, granted by id to awakening tiers.
class AbilitiesStep extends StatefulWidget {
  const AbilitiesStep({super.key, required this.unit, required this.set});
  final Map<String, dynamic> unit;
  final void Function(Map<String, dynamic> patch) set;
  @override
  State<AbilitiesStep> createState() => _AbilitiesStepState();
}

class _AbilitiesStepState extends State<AbilitiesStep> {
  String q = '';
  String group = 'all';

  String _group(Map<String, dynamic> s) {
    final attr = s['attr'];
    final supportive = s['relation'] == 'Friendlies' || s['dmgType'] == 'None';
    if (attr == 'Magic' || attr == 'MagicSword') {
      final el = s['element'];
      if (el != null && el != 'None') return '$el magic';
      return supportive ? 'White magic' : 'Magic';
    }
    return supportive ? 'Support abilities' : 'Attack abilities';
  }

  @override
  Widget build(BuildContext context) {
    final app = context.read<AppState>();
    final cat = app.catalog!;
    final skills = (cat['skills'] as List).cast<Map<String, dynamic>>();
    final lib = skills.where((s) => (s['seq'] as List).isNotEmpty && s['hasUnit'] == 'All' && ['Ability', 'Magic', 'MagicSword'].contains(s['attr']) && (s['id'] as num) < 460000).toList()
      ..sort((a, b) { final g = _group(a).compareTo(_group(b)); return g != 0 ? g : (a['name'] as String).compareTo(b['name'] as String); });
    final groups = lib.map(_group).toSet().toList();
    final s = q.trim().toLowerCase();
    final shown = lib.where((x) => (group == 'all' || _group(x) == group) && (s.isEmpty || (x['name'] as String).toLowerCase().contains(s) || describe(x).toLowerCase().contains(s))).toList();
    final aw = awakening(widget.unit);
    final granted = <num>{for (final t in aw) for (final g in t) if (g[0] == 'ActiveSkill') g[1] as num};
    final byId = {for (final x in skills) x['id'] as num: x};

    void add(int tier, num id) {
      if (granted.contains(id)) return;
      if (aw[tier].length >= tierCap) { _full(context, tier); return; }
      final n = deepCopy(aw); n[tier].add(['ActiveSkill', id]); widget.set({'awakening': n});
    }
    void move(Grant g, int from, int to) {
      if (from == to) return;
      if (aw[to].length >= tierCap) { _full(context, to); return; }
      final n = deepCopy(aw); n[from].removeWhere((x) => sameGrant(x, g)); n[to].add(g); widget.set({'awakening': n});
    }
    void remove(int i, int j) { final n = deepCopy(aw); n[i].removeAt(j); widget.set({'awakening': n}); }

    return Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Band('The game\'s abilities', color: Guide.blue),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
            child: Row(children: [
              Expanded(child: TextField(decoration: const InputDecoration(hintText: 'Search abilities', prefixIcon: Icon(Icons.search, size: 18)), onChanged: (v) => setState(() => q = v))),
              const SizedBox(width: 8),
              DropdownButton<String>(
                value: group, underline: const SizedBox.shrink(), style: Guide.text(), dropdownColor: Guide.paper, borderRadius: BorderRadius.zero,
                items: [const DropdownMenuItem(value: 'all', child: Text('All groups')), for (final g in groups) DropdownMenuItem(value: g, child: Text(g))],
                onChanged: (v) => setState(() => group = v ?? 'all'),
              ),
            ]),
          ),
          Padding(padding: const EdgeInsets.fromLTRB(12, 0, 12, 6), child: Text('Drag one onto a tier, or use "add". Every ability here already has its animation, icon and hit effects in the game.', style: Guide.small())),
          Expanded(
            child: Container(
              margin: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              decoration: BoxDecoration(border: Border.all(color: Guide.hairline)),
              child: shown.isEmpty
                  ? Center(child: Text('Nothing matches.', style: Guide.small()))
                  : ListView.builder(
                      itemCount: shown.length,
                      itemBuilder: (_, i) {
                        final x = shown[i];
                        final png = iconPng(cat, x['icon'] as String?);
                        final done = granted.contains(x['id'] as num);
                        return LibraryRow(
                          zebra: i.isOdd,
                          title: x['name'] as String,
                          detail: '${describe(x)}${(x['cost'] as num? ?? 0) > 0 ? ' · ${x['cost']} MP' : ''} · ${_group(x)}',
                          leading: ElementSwatch(x['element'] as String?),
                          icon: png != null ? Frame(padding: 1, width: 1, child: Image.network(app.api!.iconUrl(png), width: 22, height: 22)) : null,
                          payload: DragPayload('skill', x['id'] as num),
                          done: done,
                          onAdd: (t) => add(t, x['id'] as num),
                        );
                      },
                    ),
            ),
          ),
        ]),
      ),
      Container(width: 1, color: Guide.hairline),
      SizedBox(
        width: 380,
        child: Tiers(
          unit: widget.unit,
          kinds: const ['ActiveSkill'],
          dragKind: 'skill',
          hint: 'tier 1 is there at level 1',
          onDrop: (tier, payload) => add(tier, payload as num),
          render: (g, i, j) {
            final custom = (widget.unit['skills'] as Map?)?['${g[1]}'] as Map?;
            final x = byId[g[1] as num];
            final tag = (custom?['set'] as Map?)?['SkillIcon.TagName'] as String? ?? x?['icon'] as String?;
            final png = iconPng(cat, tag);
            return Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(border: Border(top: BorderSide(color: Guide.hairline))),
              child: Row(children: [
                if (png != null) Image.network(app.api!.iconUrl(png), width: 20, height: 20) else const SizedBox(width: 20),
                const SizedBox(width: 8),
                Expanded(child: custom != null
                    ? Row(children: [Text(custom['en'].toString(), style: Guide.strong()), const SizedBox(width: 6), Text('CUSTOM', style: Guide.label(Guide.purple).copyWith(fontSize: 10))])
                    : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(x?['name']?.toString() ?? 'skill ${g[1]}', style: Guide.strong()), Text(describe(x), style: Guide.small(), maxLines: 1, overflow: TextOverflow.ellipsis)])),
                GrantTools(tier: i, onMove: (t) => move(g, i, t), onRemove: () => remove(i, j)),
              ]),
            );
          },
        ),
      ),
    ]);
  }

  void _full(BuildContext context, int tier) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(backgroundColor: Guide.ink, content: Text('Tier ${tier + 1} already holds $tierCap bonuses. Pick another tier.', style: Guide.text(Guide.paper))));
}
