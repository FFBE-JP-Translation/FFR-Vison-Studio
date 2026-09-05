import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../design/theme.dart';
import '../../design/widgets.dart';
import '../../state/app_state.dart';
import '../../state/catalog_helpers.dart';

/// Step 3: stats, type, roles, name and description.
class StatsStep extends StatefulWidget {
  const StatsStep({super.key, required this.unit, required this.set});
  final Map<String, dynamic> unit;
  final void Function(Map<String, dynamic> patch) set;
  @override
  State<StatsStep> createState() => _StatsStepState();
}

class _StatsStepState extends State<StatsStep> {
  Map<String, dynamic>? detail;
  @override
  void initState() {
    super.initState();
    final ff = widget.unit['ffbe'] as Map?;
    if (ff != null) context.read<AppState>().api!.ffbeUnit((ff['base'] ?? ff['id']).toString()).then((d) { if (mounted) setState(() => detail = d); }).catchError((_) {});
  }
  @override
  Widget build(BuildContext context) {
    final cat = context.read<AppState>().catalog!;
    final u = widget.unit;
    final stats = Map<String, dynamic>.from((u['stats'] as Map?) ?? {});
    final visions = (cat['visions'] as List).cast<Map<String, dynamic>>().where((v) => (v['stats'] as Map?)?['MaxHitPoint'] != null).toList()..sort((a, b) => (a['name'] as String).compareTo(b['name'] as String));
    void setStat(String k, num v) => widget.set({'stats': {...stats, k: v.round()}});
    final rolesNow = ((u['roles'] as List?) ?? []).map((e) => e.toString()).toList();
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Band('Stats at level 1', color: Guide.blue),
            Box(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
              child: Column(children: [
                for (final (key, label, min, max) in statFields)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Row(children: [
                      SizedBox(width: 96, child: Text(label, style: Guide.strong())),
                      Expanded(child: Slider(min: min.toDouble(), max: max.toDouble(), value: ((stats[key] as num?) ?? min).toDouble().clamp(min.toDouble(), max.toDouble()), onChanged: (v) => setStat(key, v))),
                      SizedBox(width: 64, child: TextFormField(
                        key: ValueKey('$key-${stats[key]}'), initialValue: '${stats[key] ?? min}', textAlign: TextAlign.right, style: Guide.num(),
                        decoration: const InputDecoration(contentPadding: EdgeInsets.symmetric(horizontal: 6, vertical: 6)),
                        onFieldSubmitted: (v) { final n = int.tryParse(v); if (n != null) setStat(key, n); },
                      )),
                    ]),
                  ),
                const SizedBox(height: 8),
                Row(children: [
                  Text('COPY FROM', style: Guide.label()),
                  const SizedBox(width: 10),
                  DropdownButton<num>(
                    hint: Text('a vision in the game', style: Guide.small()), underline: const SizedBox.shrink(), style: Guide.text(), dropdownColor: Guide.paper, borderRadius: BorderRadius.zero,
                    items: [for (final v in visions) DropdownMenuItem(value: v['id'] as num, child: Text(v['name'] as String))],
                    onChanged: (id) { final v = visions.firstWhere((x) => x['id'] == id); widget.set({'stats': {...stats, ...(v['stats'] as Map)}}); },
                  ),
                  const SizedBox(width: 10),
                  if (detail?['ffrStats'] != null) GuideButton('Brave Exvius-based', small: true, onPressed: () => widget.set({'stats': {...stats, ...(detail!['ffrStats'] as Map)}})),
                ]),
                const SizedBox(height: 4),
                Text('The level curve comes from the unit\'s template; these are the level 1 values.', style: Guide.small()),
              ]),
            ),
          ]),
        ),
        const SizedBox(width: 16),
        SizedBox(
          width: 340,
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Band('Type and roles', color: Guide.ink),
            Box(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('ATTACKS WITH', style: Guide.label()),
                Row(children: [
                  for (final (v, l) in [('Physic', 'Physical'), ('Magic', 'Magic')])
                    Row(mainAxisSize: MainAxisSize.min, children: [Radio<String>(value: v, groupValue: u['attackType'] == 'Magic' ? 'Magic' : 'Physic', onChanged: (x) => widget.set({'attackType': x})), Text(l, style: Guide.text()), const SizedBox(width: 12)]),
                ]),
                const SizedBox(height: 8),
                Text('ROLES', style: Guide.label()),
                for (final (v, l) in roles)
                  Row(mainAxisSize: MainAxisSize.min, children: [
                    Checkbox(value: rolesNow.contains(v), onChanged: (on) { final r = rolesNow.where((x) => x != v).toList(); widget.set({'roles': on == true ? [...r, v] : (r.isEmpty ? ['eUnitRole::Attacker'] : r)}); }),
                    Text(l, style: Guide.text()),
                  ]),
                const SizedBox(height: 8),
                Text('NAME', style: Guide.label()),
                const SizedBox(height: 4),
                TextFormField(key: ValueKey('en-${u['key']}'), initialValue: (u['en'] ?? '').toString(), onChanged: (v) => widget.set({'en': v})),
                const SizedBox(height: 8),
                Text('DESCRIPTION', style: Guide.label()),
                const SizedBox(height: 4),
                TextFormField(key: ValueKey('desc-${u['key']}'), initialValue: (u['desc'] ?? '').toString(), maxLines: 3, onChanged: (v) => widget.set({'desc': v})),
              ]),
            ),
          ]),
        ),
      ]),
    );
  }
}
