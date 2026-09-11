import 'package:flutter/material.dart';
import '../../design/theme.dart';
import '../../design/widgets.dart';
import '../../services/api.dart';

/// Source icons remain recognizable even when a mechanic cannot be imported.
class FfbeAbilityIcon extends StatelessWidget {
  const FfbeAbilityIcon({super.key, required this.api, this.icon, this.size = 28});
  final Api api;
  final String? icon;
  final double size;
  @override
  Widget build(BuildContext context) {
    Widget missing() => Tooltip(message: 'FFBE icon unavailable in the local data',
      child: Icon(Icons.image_not_supported_outlined, size: size, color: Guide.inkSoft));
    if (icon == null || icon!.isEmpty) return missing();
    return Image.network(api.ffbeAbilityIcon(icon!), width: size, height: size,
      filterQuality: FilterQuality.none, semanticLabel: 'FFBE ability icon',
      errorBuilder: (_, error, stack) => missing());
  }
}

class FfbeKit extends StatefulWidget {
  const FfbeKit({super.key, required this.unit, required this.api, required this.onChanged});
  final Map<String, dynamic> unit;
  final Api api;
  final ValueChanged<Map<String, dynamic>> onChanged;
  @override
  State<FfbeKit> createState() => _FfbeKitState();
}

class _FfbeKitState extends State<FfbeKit> {
  late Map<String, dynamic> draft;
  Map<String, dynamic>? kit;
  final replacements = <String, String>{};
  bool busy = false;
  String? error;
  String query = '';
  String filter = 'all';
  @override
  void initState() { super.initState(); draft = widget.unit; load(); }

  Future<void> load() async {
    setState(() { busy = true; error = null; });
    try {
      final value = await widget.api.importKit(draft);
      final preview = await widget.api.previewKit(value);
      if (!mounted) return;
      setState(() { draft = value; kit = preview; });
      widget.onChanged(value);
    } catch (e) { if (mounted) setState(() => error = e.toString()); }
    finally { if (mounted) setState(() => busy = false); }
  }

  String identity(Map row) => row['sourceKey']?.toString() ?? (row['source'] as Map?)?['key']?.toString() ?? '${row['kind']}/${row['id']}';
  Map? equipped(Map row) {
    for (final group in ['skills', 'convertedPassives']) {
      for (final s in ((draft[group] as Map?) ?? {}).values) {
        if ((s['ffbe'] as Map?)?['source'] == identity(row)) return s as Map;
      }
    }
    final lb = draft['lb_custom'] as Map?;
    if ((lb?['ffbe'] as Map?)?['source'] == identity(row)) return lb;
    return null;
  }

  Future<void> use(Map<String, dynamic> row, {bool remove = false}) async {
    setState(() { busy = true; error = null; });
    try {
      final value = await widget.api.kitLoadout(draft, identity(row), replaceId: replacements[identity(row)], remove: remove);
      if (!mounted) return;
      setState(() { draft = value; replacements.clear(); });
      widget.onChanged(value);
    } catch (e) { if (mounted) setState(() => error = e.toString()); }
    finally { if (mounted) setState(() => busy = false); }
  }

  @override
  Widget build(BuildContext context) {
    final rows = ((kit?['entries'] as List?) ?? []).cast<Map<String, dynamic>>();
    final visible = rows.where((r) => '${r['name']} ${r['id']} ${r['kind']} ${r['description']}'.toLowerCase().contains(query.toLowerCase()) &&
      (filter == 'all' || filter == 'equipped' && equipped(r) != null || filter == 'held' && r['status'] != 'ready' || r['kind'] == filter)).toList();
    final ready = rows.where((r) => r['status'] == 'ready').length;
    final count = rows.where((r) => equipped(r) != null).length;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Band('Imported FFBE skills', color: Guide.blue),
      Padding(padding: const EdgeInsets.all(12), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('$ready available · $count in test loadout · ${rows.length - ready} incompatible', style: Guide.strong()),
        Text('${kit?['source'] ?? ''} · Form ${draft['ffbe']['id']} · Includes learned, enhanced, linked skills and limit bursts.', style: Guide.small()),
        const SizedBox(height: 4),
        Text('Your reviewed effect mappings are applied. Partial skills keep their compatible effects. Choose moves below, then Save and Build / Install to test them in FFR.', style: Guide.small()),
        Text('The game supports ten custom command slots and eight grants per awakening tier. The full kit stays here when you swap moves. Gameplay, complete FFBE sound and effect animations still need testing.', style: Guide.small()),
        const SizedBox(height: 8),
        Row(children: [
          Expanded(child: TextField(decoration: const InputDecoration(hintText: 'Search the complete kit', prefixIcon: Icon(Icons.search)), onChanged: (v) => setState(() => query = v))),
          const SizedBox(width: 12),
          DropdownButton<String>(value: filter, items: [for (final e in {'all': 'All skills', 'equipped': 'Test loadout', 'ABILITY': 'Abilities', 'MAGIC': 'Magic', 'PASSIVE': 'Passives', 'LB': 'Limit bursts', 'held': 'Incompatible'}.entries)
            DropdownMenuItem(value: e.key, child: Text(e.value))], onChanged: (v) => setState(() => filter = v ?? 'all')),
          const SizedBox(width: 8),
          OutlinedButton(onPressed: busy ? null : load, child: const Text('Refresh kit')),
        ]),
        for (final issue in (kit?['issues'] as List?) ?? []) Text(issue.toString(), style: Guide.small()),
        if (error != null) SelectableText(error!, style: Guide.small()),
      ])),
      if (busy) const LinearProgressIndicator(minHeight: 2),
      Expanded(child: kit == null ? Center(child: Text(busy ? 'Importing this form’s complete kit…' : 'The kit could not be loaded.', style: Guide.text()))
        : visible.isEmpty ? Center(child: Text('No matching skills.', style: Guide.text()))
        : ListView.builder(itemCount: visible.length, itemBuilder: (_, i) => entry(visible[i]))),
    ]);
  }

  Widget entry(Map<String, dynamic> row) {
    final id = identity(row);
    final existing = equipped(row);
    final isLb = row['kind'] == 'LB';
    final group = row['kind'] == 'PASSIVE' ? 'convertedPassives' : 'skills';
    final slots = (draft[group] as Map?) ?? {};
    return Container(decoration: BoxDecoration(border: Border(bottom: BorderSide(color: Guide.hairline))),
      child: ExpansionTile(key: ValueKey(id),
        leading: FfbeAbilityIcon(api: widget.api, icon: row['icon'] as String?),
        title: Text(row['name']?.toString() ?? '${row['id']}', style: Guide.strong()),
        subtitle: Text('${row['kind']} · ${row['origin'] ?? 'learned'} · ${existing != null ? isLb ? 'current Resonance' : 'in test loadout' : row['status'] == 'ready' ? row['class'] == 'partial' ? 'available · partial conversion' : 'available' : 'incompatible'}', style: Guide.small()),
        childrenPadding: const EdgeInsets.fromLTRB(56, 0, 16, 12), expandedCrossAxisAlignment: CrossAxisAlignment.start,
        expandedAlignment: Alignment.centerLeft,
        children: [
          Text(row['description']?.toString() ?? '', style: Guide.strong()),
          if (row['effects'] is List && (row['effects'] as List).isNotEmpty) Text('FFBE: ${(row['effects'] as List).join(' · ')}', style: Guide.small()),
          for (final issue in (row['issues'] as List?) ?? []) Text(issue.toString(), style: Guide.small()),
          for (final change in (row['changes'] as List?) ?? []) Text(change.toString(), style: Guide.small()),
          SelectableText(id, style: Guide.small()),
          if (row['status'] == 'ready') ...[
            const SizedBox(height: 8),
            if (existing == null && !isLb) DropdownButton<String>(value: replacements[id] ?? '', isExpanded: true,
              items: [const DropdownMenuItem(value: '', child: Text('Use an empty loadout slot')),
                for (final slot in slots.entries) DropdownMenuItem(value: slot.key.toString(), child: Text('Replace ${slot.value['en'] ?? slot.key}'))],
              onChanged: busy ? null : (v) => setState(() { if (v == null || v.isEmpty) { replacements.remove(id); } else { replacements[id] = v; } })),
            OutlinedButton(onPressed: busy || existing != null && isLb ? null : () => use(row, remove: existing != null),
              child: Text(existing != null ? isLb ? 'Current Resonance' : 'Remove from test loadout' : isLb ? 'Use as Resonance' : 'Use in test loadout')),
          ],
        ],
      ));
  }
}
