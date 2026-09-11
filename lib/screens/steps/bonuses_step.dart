import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../design/theme.dart';
import '../../design/widgets.dart';
import '../../state/app_state.dart';
import '../../state/catalog_helpers.dart';
import 'tiers.dart';
import 'grant_details.dart';
import 'native_library_row.dart';

class BonusesStep extends StatefulWidget {
  const BonusesStep({super.key, required this.unit, required this.set});
  final Map<String, dynamic> unit;
  final ValueChanged<Map<String, dynamic>> set;
  @override
  State<BonusesStep> createState() => _BonusesStepState();
}

class _BonusesStepState extends State<BonusesStep> {
  String q = '', group = 'native';
  final amounts = <int, int>{for (final p in statParams) p.$1: p.$3};
  @override
  Widget build(BuildContext context) {
    final app = context.read<AppState>(), unit = widget.unit;
    final cat = app.catalog!, aw = awakening(unit);
    final passives = ((cat['passives'] as List?) ?? []).cast<Map<String, dynamic>>().where((p) => (p['name'] ?? '').toString().isNotEmpty).toList()
      ..sort((a, b) => a['name'].toString().compareTo(b['name'].toString()));
    final query = q.trim().toLowerCase();
    bool matches(Map r) => '${r['name']} ${r['description'] ?? r['desc'] ?? ''}'.toLowerCase().contains(query);
    final natives = (group == 'native' || group == 'all') ? nativeEntries(unit).where((e) => e['kind'] == 'PASSIVE' && matches(e)).toList() : <Map<String, dynamic>>[];
    final shown = (group == 'ffr' || group == 'all') ? passives.where(matches).toList() : <Map<String, dynamic>>[];
    final granted = {for (final t in aw) for (final g in t) if (g[0] == 'PassiveSkill') g[1]};
    void add(int tier, int index, DragPayload payload) {
      if (payload.kind != 'grant') return;
      final grant = List<dynamic>.from(payload.value as List);
      if (grant[0] == 'PassiveSkill' && granted.contains(grant[1])) return;
      if (aw[tier].length >= tierCap) { grantMessage(context, 'Tier ${tier + 1} is full. Choose another tier.'); return; }
      final next = deepCopy(aw); next[tier].insert(index.clamp(0, next[tier].length), grant); widget.set({'awakening': next});
    }
    return Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Band('Bonuses', color: Guide.purple, trailing: unit['ffbe'] == null ? null : NativeImportButton(unit: unit, group: 'bonuses', set: widget.set)),
        Padding(padding: const EdgeInsets.all(12), child: Row(children: [
          Expanded(child: TextField(decoration: const InputDecoration(hintText: 'Search bonuses', prefixIcon: Icon(Icons.search, size: 18)), onChanged: (v) => setState(() => q = v))),
          const SizedBox(width: 10), SizedBox(width: 160, child: DropdownButton<String>(value: group, isExpanded: true, style: Guide.text(), dropdownColor: Guide.paper,
            items: [for (final e in {'native': 'Native Bonuses', 'all': 'All bonuses', 'ffr': 'FFR bonuses', 'stats': 'Stat bonuses'}.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
            onChanged: (v) => setState(() => group = v ?? 'native'))),
        ])),
        Expanded(child: ListView(padding: const EdgeInsets.fromLTRB(12, 0, 12, 12), children: [
          if (natives.isEmpty && shown.isEmpty && group != 'stats' && group != 'all') Padding(padding: const EdgeInsets.all(16), child: Text(query.isEmpty && group == 'native' ? 'This vision has no native bonuses.' : 'No matching bonuses.', style: Guide.small())),
          for (final (i, entry) in natives.indexed) NativeLibraryRow(key: ValueKey(entry['sourceKey']), unit: unit, entry: entry, set: widget.set, zebra: i.isOdd),
          for (final (i, row) in shown.indexed) Builder(builder: (_) {
            final data = grantData(unit, cat, {'kind': 'PassiveSkill', 'id': row['id']});
            return LibraryRow(title: data.name, detail: '${data.description} · ${data.cost} SP', zebra: i.isOdd,
              icon: GrantIcon(data: data, api: app.api!, catalog: cat), payload: DragPayload('grant', ['PassiveSkill', row['id']]), done: granted.contains(row['id']),
              onInfo: () => showGrantInfo(context, unit, data), onAdd: (t) => add(t, aw[t].length, DragPayload('grant', ['PassiveSkill', row['id']])));
          }),
          if (group == 'stats' || group == 'all') ...[
            Padding(padding: const EdgeInsets.symmetric(vertical: 10), child: Text('Set the amount, then drag the left handle or use “add”.', style: Guide.small())),
            Wrap(spacing: 8, runSpacing: 8, children: [for (final (id, label, _) in statParams.where((p) => p.$2.toLowerCase().contains(query))) Container(
              decoration: BoxDecoration(border: Border.all(color: Guide.hairline), color: Guide.paper),
              padding: const EdgeInsets.all(2), child: Row(mainAxisSize: MainAxisSize.min, children: [
                GrantHandle(payload: DragPayload('grant', ['BaseParameter', id, amounts[id]!]), title: '$label +${amounts[id]}'),
                Container(color: Guide.ink, padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 8), child: Text(label, style: Guide.band(Guide.onBandFor(Guide.ink)))),
                SizedBox(width: 50, child: TextFormField(initialValue: '${amounts[id]}', textAlign: TextAlign.center, style: Guide.num(),
                  decoration: const InputDecoration(contentPadding: EdgeInsets.all(4), border: InputBorder.none, enabledBorder: InputBorder.none, filled: false),
                  keyboardType: TextInputType.number, onChanged: (v) { final n = int.tryParse(v); if (n != null) setState(() => amounts[id] = n); })),
                TierMenu(onPick: (t) => add(t, aw[t].length, DragPayload('grant', ['BaseParameter', id, amounts[id]!]))),
              ]))]),
          ],
        ])),
      ])),
      Container(width: 1, color: Guide.hairline),
      Expanded(child: LearnedTiers(unit: unit, set: widget.set, onLibraryDrop: add)),
    ]);
  }
}
