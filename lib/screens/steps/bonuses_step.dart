import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../design/theme.dart';
import '../../design/widgets.dart';
import '../../state/app_state.dart';
import '../../state/catalog_helpers.dart';
import 'tiers.dart';

/// Step 2: stat boosts and the game's passives.
class BonusesStep extends StatefulWidget {
  const BonusesStep({super.key, required this.unit, required this.set});
  final Map<String, dynamic> unit;
  final void Function(Map<String, dynamic> patch) set;
  @override
  State<BonusesStep> createState() => _BonusesStepState();
}

class _BonusesStepState extends State<BonusesStep> {
  String q = '';
  final amounts = <int, int>{for (final p in statParams) p.$1: p.$3};
  final _jp = RegExp(r'[぀-ヿ一-鿿]');

  @override
  Widget build(BuildContext context) {
    final app = context.read<AppState>();
    final cat = app.catalog!;
    final passives = (cat['passives'] as List).cast<Map<String, dynamic>>().where((p) => (p['name'] as String?)?.isNotEmpty == true && !_jp.hasMatch(p['name'] as String)).toList()
      ..sort((a, b) => (a['name'] as String).compareTo(b['name'] as String));
    final s = q.trim().toLowerCase();
    final shown = passives.where((p) => s.isEmpty || (p['name'] as String).toLowerCase().contains(s) || (p['desc'] ?? '').toString().toLowerCase().contains(s)).toList();
    final aw = awakening(widget.unit);
    final grantedP = <num>{for (final t in aw) for (final g in t) if (g[0] == 'PassiveSkill') g[1] as num};
    final byId = {for (final p in passives) p['id'] as num: p};

    void add(int tier, Grant g) {
      if (g[0] == 'PassiveSkill' && grantedP.contains(g[1] as num)) return;
      if (aw[tier].length >= tierCap) { _full(context, tier); return; }
      final n = deepCopy(aw); n[tier].add(g); widget.set({'awakening': n});
    }
    void update(int i, int j, Grant g) { final n = deepCopy(aw); n[i][j] = g; widget.set({'awakening': n}); }
    void remove(int i, int j) { final n = deepCopy(aw); n[i].removeAt(j); widget.set({'awakening': n}); }
    void move(Grant g, int i, int j, int to) {
      if (i == to) return;
      if (aw[to].length >= tierCap) { _full(context, to); return; }
      final n = deepCopy(aw); n[i].removeAt(j); n[to].add(g); widget.set({'awakening': n});
    }

    return Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Band('Stat bonuses', color: Guide.blue),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
            child: Text('Type the amount, then drag the black chip onto a tier (or use "add").', style: Guide.small()),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
            child: Wrap(spacing: 8, runSpacing: 8, children: [
              for (final (id, label, _) in statParams)
                Container(
                  decoration: BoxDecoration(border: Border.all(color: Guide.ink, width: 1.5), color: Guide.paper),
                  padding: const EdgeInsets.fromLTRB(2, 2, 2, 2),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    Draggable<DragPayload>(
                      data: DragPayload('grant', ['BaseParameter', id, amounts[id]!]),
                      feedback: Material(color: Colors.transparent, child: _chip('$label +${amounts[id]!}', dragging: true)),
                      child: MouseRegion(cursor: SystemMouseCursors.grab, child: _chip(label)),
                    ),
                    SizedBox(width: 56, child: TextFormField(
                      initialValue: '${amounts[id]}', textAlign: TextAlign.center, style: Guide.num(),
                      decoration: const InputDecoration(contentPadding: EdgeInsets.symmetric(horizontal: 4, vertical: 6), border: InputBorder.none, enabledBorder: InputBorder.none, focusedBorder: InputBorder.none, filled: false),
                      keyboardType: TextInputType.number,
                      onChanged: (v) { final n = int.tryParse(v); if (n != null && n > 0) setState(() => amounts[id] = n); },
                    )),
                    TierMenu(label: 'add', onPick: (t) => add(t, ['BaseParameter', id, amounts[id]!])),
                  ]),
                ),
            ]),
          ),
          const Band('The game\'s passives', color: Guide.purple),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
            child: TextField(decoration: const InputDecoration(hintText: 'Search passives', prefixIcon: Icon(Icons.search, size: 18)), onChanged: (v) => setState(() => q = v)),
          ),
          Expanded(
            child: Container(
              margin: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              decoration: BoxDecoration(border: Border.all(color: Guide.hairline)),
              child: ListView.builder(
                itemCount: shown.length,
                itemBuilder: (_, i) {
                  final p = shown[i];
                  final png = iconPng(cat, p['icon'] as String?);
                  return LibraryRow(
                    zebra: i.isOdd,
                    title: p['name'] as String,
                    detail: (p['desc'] ?? '').toString(),
                    icon: png != null ? Image.network(app.api!.iconUrl(png), width: 22, height: 22) : null,
                    payload: DragPayload('grant', ['PassiveSkill', p['id']]),
                    done: grantedP.contains(p['id'] as num),
                    doneText: 'granted',
                    onAdd: (t) => add(t, ['PassiveSkill', p['id']]),
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
          kinds: const ['PassiveSkill', 'BaseParameter'],
          dragKind: 'grant',
          hint: '8 per tier, abilities included',
          onDrop: (tier, payload) => add(tier, List<dynamic>.from(payload as List)),
          render: (g, i, j) {
            if (g[0] == 'BaseParameter') {
              final label = statParams.where((p) => p.$1 == (g[1] as num).toInt()).map((p) => p.$2).firstOrNull ?? 'stat ${g[1]}';
              return Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: const BoxDecoration(border: Border(top: BorderSide(color: Guide.hairline))),
                child: Row(children: [
                  Expanded(child: Text(label, style: Guide.strong())),
                  Text('+', style: Guide.text()),
                  SizedBox(width: 60, child: TextFormField(
                    key: ValueKey('bp$i-$j-${g[2]}'), initialValue: '${g[2] ?? 0}', textAlign: TextAlign.center, style: Guide.num(),
                    decoration: const InputDecoration(contentPadding: EdgeInsets.symmetric(horizontal: 4, vertical: 6)),
                    onFieldSubmitted: (v) { final n = int.tryParse(v); if (n != null) update(i, j, ['BaseParameter', g[1], n]); },
                  )),
                  GrantTools(tier: i, onMove: (t) => move(g, i, j, t), onRemove: () => remove(i, j)),
                ]),
              );
            }
            final p = byId[g[1] as num];
            final png = iconPng(cat, p?['icon'] as String?);
            return Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: const BoxDecoration(border: Border(top: BorderSide(color: Guide.hairline))),
              child: Row(children: [
                if (png != null) Image.network(app.api!.iconUrl(png), width: 20, height: 20) else const SizedBox(width: 20),
                const SizedBox(width: 8),
                Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(p?['name']?.toString() ?? 'passive ${g[1]}', style: Guide.strong()), Text((p?['desc'] ?? '').toString(), style: Guide.small(), maxLines: 1, overflow: TextOverflow.ellipsis)])),
                GrantTools(tier: i, onMove: (t) => move(g, i, j, t), onRemove: () => remove(i, j)),
              ]),
            );
          },
        ),
      ),
    ]);
  }

  Widget _chip(String label, {bool dragging = false}) => Container(
        decoration: BoxDecoration(color: Guide.ink, boxShadow: dragging ? const [BoxShadow(color: Color(0x40000000), offset: Offset(0, 4), blurRadius: 12)] : null),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        child: Text(label.toUpperCase(), style: Guide.band().copyWith(fontSize: 13)),
      );

  void _full(BuildContext context, int tier) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(backgroundColor: Guide.ink, content: Text('Tier ${tier + 1} already holds $tierCap bonuses. Pick another tier.', style: Guide.text(Guide.paper))));
}
