import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../design/theme.dart';
import '../../design/widgets.dart';
import '../../state/app_state.dart';
import '../../state/catalog_helpers.dart';
import 'tiers.dart';
import 'grant_details.dart';
import 'native_library_row.dart';

class AbilitiesStep extends StatefulWidget {
  const AbilitiesStep({super.key, required this.unit, required this.set});
  final Map<String, dynamic> unit;
  final ValueChanged<Map<String, dynamic>> set;
  @override
  State<AbilitiesStep> createState() => _AbilitiesStepState();
}

class _AbilitiesStepState extends State<AbilitiesStep> {
  String q = '', group = 'native';
  String category(Map s) {
    final supportive = s['relation'] == 'Friendlies' || s['dmgType'] == 'None';
    if (s['attr'] == 'Magic' || s['attr'] == 'MagicSword') {
      final el = s['element'];
      return el != null && el != 'None' ? '$el magic' : supportive ? 'White magic' : 'Magic';
    }
    return supportive ? 'Support abilities' : 'Attack abilities';
  }
  @override
  Widget build(BuildContext context) {
    final app = context.read<AppState>(), unit = widget.unit;
    final cat = app.catalog!;
    final skills = (cat['skills'] as List).cast<Map<String, dynamic>>();
    final lib = skills.where((s) => (s['seq'] as List).isNotEmpty && s['hasUnit'] == 'All' && ['Ability', 'Magic', 'MagicSword'].contains(s['attr']) && (s['id'] as num) < 460000).toList()
      ..sort((a, b) => a['name'].toString().compareTo(b['name'].toString()));
    final studio = ((cat['studioSkills'] as List?) ?? []).cast<Map<String, dynamic>>();
    final aw = awakening(unit);
    final granted = {for (final t in aw) for (final g in t) if (g[0] == 'ActiveSkill') g[1]};
    final mine = Map<String, dynamic>.from(unit['skills'] as Map? ?? {});
    final authored = {for (final x in mine.values) if (x['studio'] != null) x['studio']};
    final query = q.trim().toLowerCase();
    bool matches(Map r) => '${r['name']} ${r['description'] ?? r['desc'] ?? ''}'.toLowerCase().contains(query);
    final natives = (group == 'native' || group == 'all') ? nativeEntries(unit).where((e) => e['kind'] != 'PASSIVE' && matches(e)).toList() : <Map<String, dynamic>>[];
    final shown = lib.where((r) => (group == 'all' || group == 'ffr' || category(r) == group) && matches(r)).toList();
    final studioShown = (group == 'all' || group == 'studio') ? studio.where(matches).toList() : <Map<String, dynamic>>[];

    void add(int tier, int index, DragPayload payload) {
      if (aw[tier].length >= tierCap) { grantMessage(context, 'Tier ${tier + 1} is full. Choose another tier.'); return; }
      num? id;
      var nextSkills = mine;
      if (payload.value is String) {
        final sk = studio.where((r) => r['key'] == payload.value).firstOrNull;
        if (sk == null || authored.contains(sk['key'])) return;
        final base = 445000 + ((unit['id'] as num).toInt() - 13100) * 100;
        for (var slot = 0; slot < 10; slot++) { if (!mine.containsKey('${base + slot * 10}')) { id = base + slot * 10; break; } }
        if (id == null) { grantMessage(context, 'All 10 custom command slots are occupied. Remove a custom move first.'); return; }
        final recipe = sk['recipe'] as Map;
        nextSkills = {...mine, '$id': {'from': recipe['from'], 'visuals': recipe['visuals'] ?? recipe['from'], 'jp': '${unit['jp']}_Studio_$id',
          'en': sk['name'], 'desc': sk['desc'], 'descAuto': false, 'set': Map<String, dynamic>.from(recipe['set'] as Map? ?? {}), 'studio': sk['key']}};
      } else { id = payload.value as num; if (granted.contains(id)) return; }
      final next = deepCopy(aw); next[tier].insert(index.clamp(0, next[tier].length), ['ActiveSkill', id]);
      widget.set({'awakening': next, 'skills': nextSkills});
    }

    final total = natives.length + shown.length + studioShown.length;
    return Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Band('Abilities', color: Guide.blue, trailing: unit['ffbe'] == null ? null : NativeImportButton(unit: unit, group: 'abilities', set: widget.set)),
        Padding(padding: const EdgeInsets.all(12), child: Row(children: [
          Expanded(child: TextField(decoration: const InputDecoration(hintText: 'Search abilities', prefixIcon: Icon(Icons.search, size: 18)), onChanged: (v) => setState(() => q = v))),
          const SizedBox(width: 10), SizedBox(width: 170, child: DropdownButton<String>(value: group, isExpanded: true, style: Guide.text(), dropdownColor: Guide.paper,
            items: [for (final e in {'native': 'Native Abilities', 'all': 'All abilities', 'ffr': 'FFR abilities', if (studio.isNotEmpty) 'studio': 'Studio moves', for (final name in lib.map(category).toSet()) name: name}.entries)
              DropdownMenuItem(value: e.key, child: Text(e.value, overflow: TextOverflow.ellipsis))], onChanged: (v) => setState(() => group = v ?? 'native'))),
        ])),
        Padding(padding: const EdgeInsets.fromLTRB(12, 0, 12, 10), child: Text('Import the full native list, or use a left handle to place an ability. Native limit bursts are available on the Resonance tab.', style: Guide.small())),
        Expanded(child: total == 0 ? Center(child: Text(group == 'native' && query.isEmpty ? 'This vision has no native abilities.' : 'No matching abilities.', style: Guide.small()))
          : ListView.builder(padding: const EdgeInsets.symmetric(horizontal: 12), itemCount: total, itemBuilder: (_, i) {
            if (i < natives.length) return NativeLibraryRow(key: ValueKey(natives[i]['sourceKey']), unit: unit, entry: natives[i], set: widget.set, zebra: i.isOdd);
            final j = i - natives.length;
            if (j < studioShown.length) {
              final sk = studioShown[j];
              return LibraryRow(title: sk['name'].toString(), detail: '${sk['desc']} · Studio move', zebra: i.isOdd,
                leading: ElementSwatch(sk['recipe']?['set']?['element']), payload: DragPayload('skill', sk['key']), done: authored.contains(sk['key']),
                onAdd: (t) => add(t, aw[t].length, DragPayload('skill', sk['key'])));
            }
            final row = shown[j - studioShown.length];
            final data = grantData(unit, cat, {'kind': 'ActiveSkill', 'id': row['id']});
            return LibraryRow(title: data.name, detail: '${data.description.isEmpty ? describe(row) : data.description} · ${data.cost} MP', zebra: i.isOdd,
              icon: GrantIcon(data: data, api: app.api!, catalog: cat), payload: DragPayload('skill', row['id']), done: granted.contains(row['id']),
              onInfo: () => showGrantInfo(context, unit, data), onAdd: (t) => add(t, aw[t].length, DragPayload('skill', row['id'])));
          })),
      ])),
      Container(width: 1, color: Guide.hairline),
      Expanded(child: LearnedTiers(unit: unit, set: widget.set, onLibraryDrop: add)),
    ]);
  }
}
