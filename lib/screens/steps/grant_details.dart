import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../design/theme.dart';
import '../../services/api.dart';
import '../../state/app_state.dart';
import '../../state/catalog_helpers.dart';
import 'ffbe_kit.dart';

List<Map<String, dynamic>> nativeEntries(Map unit) => ((unit['ffbeLibrary'] as List?) ?? []).cast<Map<String, dynamic>>().where((e) => e['kind'] != 'LB').toList();
Map? nativeEquipped(Map unit, dynamic key) {
  for (final group in ['skills', 'convertedPassives']) {
    for (final recipe in ((unit[group] as Map?) ?? {}).values) {
      if (recipe['ffbe']?['source'] == key) return recipe as Map;
    }
  }
  return null;
}

class GrantData {
  GrantData({required this.ref, required this.name, required this.description, required this.cost, required this.passive,
    this.icon, this.sourceIcon, this.available = true, this.entry = const {}});
  final Map<String, dynamic> ref;
  final String name, description;
  final int cost;
  final bool passive, available;
  final String? icon, sourceIcon;
  final Map entry;
}

GrantData grantData(Map unit, Map<String, dynamic> catalog, Map<String, dynamic> ref) {
  final key = ref['sourceKey'];
  Map row = {}, custom = {}, edits = {};
  bool passive = ref['kind'] == 'PassiveSkill';
  if (key != null) {
    row = nativeEntries(unit).where((e) => e['sourceKey'] == key).firstOrNull ?? {};
    passive = row['kind'] == 'PASSIVE';
    custom = nativeEquipped(unit, key) ?? {};
    edits = unit['nativeEdits']?[key] as Map? ?? {};
  } else {
    custom = unit[passive ? 'convertedPassives' : 'skills']?['${ref['id']}'] as Map? ?? {};
    final sourceKey = custom['ffbe']?['source'];
    if (sourceKey != null) row = nativeEntries(unit).where((e) => e['sourceKey'] == sourceKey).firstOrNull ?? {};
    if (row.isEmpty) row = ((catalog[passive ? 'passives' : 'skills'] as List?) ?? []).cast<Map>().where((e) => e['id'] == (custom['from'] ?? ref['id'])).firstOrNull ?? {};
  }
  final setting = custom['set'] as Map? ?? {};
  final rawSource = custom['ffbe']?['icon'] ?? (row['sourceKey'] != null ? row['icon'] : null);
  final sourceName = catalog['ffbeIconAliases']?[rawSource?.toString()] ?? rawSource;
  final sourceTag = ((catalog['icons'] as List?) ?? []).cast<Map>().where((i) => i['ffbeIcon'] != null && i['ffbeIcon'] == sourceName).firstOrNull?['tag'];
  final choice = edits['icon'] ?? custom['iconChoice'];
  final icon = (choice is String && choice.isNotEmpty) ? choice : sourceTag ?? setting['SkillIcon.TagName'] ?? row['ffrIcon'] ?? (row['sourceKey'] == null ? row['icon'] : null);
  return GrantData(ref: ref, name: (edits['name'] ?? custom['en'] ?? row['name'] ?? 'Entry ${ref['id']}').toString(),
    description: (edits['description'] ?? custom['desc'] ?? row['description'] ?? row['desc'] ?? '').toString(),
    cost: ((edits['cost'] ?? setting[passive ? 'equipCost' : 'Cost'] ?? row[passive ? 'equipCost' : 'cost'] ?? row['cost'] ?? 0) as num).toInt(),
    passive: passive, icon: icon?.toString(), sourceIcon: (custom['ffbe']?['icon'] ?? (row['sourceKey'] != null ? row['icon'] : null))?.toString(),
    available: row['status'] != 'held', entry: row);
}

class GrantIcon extends StatelessWidget {
  const GrantIcon({super.key, required this.data, required this.api, required this.catalog});
  final GrantData data;
  final Api api;
  final Map<String, dynamic> catalog;
  @override
  Widget build(BuildContext context) {
    final png = iconPng(catalog, data.icon);
    if (png != null) {
      return Image.network(api.iconUrl(png), width: 24, height: 24,
        errorBuilder: (_, error, stack) => Icon(Icons.auto_awesome, size: 22, color: Guide.inkSoft));
    }
    if (data.sourceIcon != null) return FfbeAbilityIcon(api: api, icon: data.sourceIcon, size: 24);
    return Icon(data.passive ? Icons.shield_outlined : Icons.auto_awesome, size: 22, color: Guide.inkSoft);
  }
}

void grantMessage(BuildContext context, String message) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(
  backgroundColor: Guide.ink, content: Text(message, style: Guide.text(Guide.paper))));

Future<void> editGrant(BuildContext context, Map<String, dynamic> unit, GrantData data, ValueChanged<Map<String, dynamic>> save) async {
  final app = context.read<AppState>();
  final next = await showDialog<Map<String, dynamic>>(context: context, builder: (_) => _GrantEdit(unit: unit, data: data, api: app.api!, catalog: app.catalog!));
  if (next != null && context.mounted) save(next);
}

class _GrantEdit extends StatefulWidget {
  const _GrantEdit({required this.unit, required this.data, required this.api, required this.catalog});
  final Map<String, dynamic> unit, catalog;
  final GrantData data;
  final Api api;
  @override
  State<_GrantEdit> createState() => _GrantEditState();
}

class _GrantEditState extends State<_GrantEdit> {
  final form = GlobalKey<FormState>();
  late final name = TextEditingController(text: widget.data.name);
  late final description = TextEditingController(text: widget.data.description);
  late final cost = TextEditingController(text: '${widget.data.cost}');
  late String icon = widget.data.icon ?? '';
  bool busy = false;
  String? error;
  @override
  void dispose() { name.dispose(); description.dispose(); cost.dispose(); super.dispose(); }
  Future<void> save() async {
    if (!form.currentState!.validate()) return;
    setState(() { busy = true; error = null; });
    try {
      final result = await widget.api.grants(widget.unit, {'action': 'edit', 'ref': widget.data.ref,
        'edits': {'name': name.text.trim(), 'description': description.text, 'cost': int.parse(cost.text), 'icon': icon}});
      if (mounted) Navigator.pop(context, result);
    } catch (e) { if (mounted) setState(() { busy = false; error = e.toString(); }); }
  }
  @override
  Widget build(BuildContext context) {
    final icons = ((widget.catalog['icons'] as List?) ?? []).cast<Map>().where((i) => (i['tag'] as String).startsWith('UI.Skill.Action.')).toList();
    if (icon.isNotEmpty && !icons.any((i) => i['tag'] == icon)) {
      final current = (widget.catalog['icons'] as List).cast<Map>().where((i) => i['tag'] == icon).firstOrNull;
      if (current != null) icons.insert(0, current);
    }
    return AlertDialog(title: Text('Edit ${widget.data.passive ? 'bonus' : 'ability'}', style: Guide.h2()),
      content: SizedBox(width: 520, child: SingleChildScrollView(child: Form(key: form, child: Column(mainAxisSize: MainAxisSize.min, children: [
        TextFormField(controller: name, autofocus: true, decoration: const InputDecoration(labelText: 'Name'), validator: (v) => v == null || v.trim().isEmpty ? 'Enter a name' : null),
        const SizedBox(height: 18),
        LayoutBuilder(builder: (context, constraints) => DropdownMenu<String>(
          initialSelection: icons.any((i) => i['tag'] == icon) ? icon : '', width: constraints.maxWidth,
          label: const Text('Icon — type to search'), menuHeight: 300, enableFilter: true, enableSearch: true,
          enabled: !busy, requestFocusOnTap: true,
          dropdownMenuEntries: [const DropdownMenuEntry(value: '', label: 'Original icon'),
            for (final i in icons) DropdownMenuEntry(value: i['tag'] as String,
              leadingIcon: i['png'] == null ? null : Image.network(widget.api.iconUrl(i['png']), width: 24, height: 24,
                errorBuilder: (_, e, s) => const SizedBox(width: 24)),
              label: i['ffbeIcon'] != null ? i['row'] as String : (i['tag'] as String).replaceFirst('UI.Skill.Action.Icon.', '').replaceFirst('UI.Skill.Command.Icon.', ''))],
          onSelected: (v) { if (v != null) setState(() => icon = v); })),
        const SizedBox(height: 18),
        TextFormField(controller: description, minLines: 3, maxLines: 7, decoration: const InputDecoration(labelText: 'Description')),
        const SizedBox(height: 18),
        TextFormField(controller: cost, keyboardType: TextInputType.number, decoration: InputDecoration(labelText: 'Cost (${widget.data.passive ? 'SP' : 'MP'})'),
          validator: (v) { final n = int.tryParse(v ?? ''); return n == null || n < 0 || n > 9999 ? 'Enter a whole number from 0 to 9999' : null; }),
        if (error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(error!, style: Guide.small(Guide.red))),
      ])))), actions: [TextButton(onPressed: busy ? null : () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: busy ? null : save, child: Text(busy ? 'Saving…' : 'Save changes'))]);
  }
}

Future<void> showGrantInfo(BuildContext context, Map<String, dynamic> unit, GrantData data) async {
  final api = context.read<AppState>().api!;
  final future = api.grants(unit, {'action': 'info', 'ref': data.ref});
  await showDialog<void>(context: context, builder: (ctx) => AlertDialog(
    title: Text(data.name, style: Guide.h2()), content: SizedBox(width: 640, child: SingleChildScrollView(child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
      Text('${data.passive ? 'Bonus' : 'Ability'} · ${data.cost} ${data.passive ? 'SP' : 'MP'}', style: Guide.small()),
      const SizedBox(height: 12), SelectableText(data.description, style: Guide.text()),
      if (data.entry['sourceKey'] != null) ...[
        const SizedBox(height: 16), Text('FFBE source', style: Guide.strong()),
        SelectableText('${data.entry['sourceKey']} · ${data.entry['origin'] ?? 'learned'} · Level ${data.entry['level'] ?? '—'}', style: Guide.small()),
        for (final effect in (data.entry['effects'] as List?) ?? []) Padding(padding: const EdgeInsets.only(top: 4), child: Text(effect.toString(), style: Guide.small())),
        if (!data.available) Padding(padding: const EdgeInsets.only(top: 16), child: Text('Unavailable conversion', style: Guide.strong(Guide.red))),
        for (final reason in [...((data.entry['issues'] as List?) ?? []), ...((data.entry['changes'] as List?) ?? [])])
          Padding(padding: const EdgeInsets.only(top: 8), child: Text(reason.toString(), style: Guide.small())),
      ],
      FutureBuilder<Map<String, dynamic>>(future: future, builder: (_, snap) {
        if (snap.hasError) return Padding(padding: const EdgeInsets.only(top: 12), child: Text('Details could not load: ${snap.error}', style: Guide.small(Guide.red)));
        if (!snap.hasData) return const Padding(padding: EdgeInsets.all(16), child: LinearProgressIndicator());
        final conversion = snap.data!['conversion'] as Map?;
        final settings = (snap.data!['recipe']?['set'] ?? conversion?['set'] ?? {}) as Map;
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (settings.isNotEmpty) ...[
            const SizedBox(height: 16), Text('In FFR', style: Guide.strong()),
            for (final field in {'TargetType': 'Target', 'defaultTargetRelation': 'Side', 'element': 'Element', 'DamageType': 'Damage type', 'hitCount': 'Hits', 'magnification': 'Power', 'breakDamageValue': 'Break power', 'accuracy': 'Accuracy'}.entries)
              if (settings[field.key] != null) Text('${field.value}: ${settings[field.key]}', style: Guide.small()),
          ],
          const SizedBox(height: 12), ExpansionTile(tilePadding: EdgeInsets.zero, title: Text('All ability data', style: Guide.strong()),
            children: [Align(alignment: Alignment.centerLeft, child: SelectableText(const JsonEncoder.withIndent('  ').convert(snap.data), style: Guide.mono()))]),
        ]);
      }),
    ]))), actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Close'))]));
}

Future<int?> editStat(BuildContext context, String name, int amount) async {
  final controller = TextEditingController(text: '$amount');
  final form = GlobalKey<FormState>();
  final result = await showDialog<int>(context: context, builder: (ctx) => AlertDialog(title: Text('Edit $name bonus'),
    content: Form(key: form, child: TextFormField(controller: controller, autofocus: true, keyboardType: TextInputType.number,
      decoration: const InputDecoration(labelText: 'Amount'), validator: (v) => int.tryParse(v ?? '') == null ? 'Enter a whole number' : null)),
    actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')), FilledButton(onPressed: () { if (form.currentState!.validate()) Navigator.pop(ctx, int.parse(controller.text)); }, child: const Text('Save changes'))]));
  // The dialog route disposes its text field after its closing transition.
  await Future<void>.delayed(const Duration(milliseconds: 250));
  controller.dispose();
  return result;
}

Future<void> showStatInfo(BuildContext context, String name, dynamic value) => showDialog<void>(context: context, builder: (ctx) => AlertDialog(
  title: Text('$name bonus'), content: Text('Increases $name by $value when this awakening tier is learned.'),
  actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Close'))]));

class NativeImportButton extends StatefulWidget {
  const NativeImportButton({super.key, required this.unit, required this.group, required this.set});
  final Map<String, dynamic> unit;
  final String group;
  final ValueChanged<Map<String, dynamic>> set;
  @override
  State<NativeImportButton> createState() => _NativeImportButtonState();
}

class _NativeImportButtonState extends State<NativeImportButton> {
  bool busy = false;
  @override
  Widget build(BuildContext context) => TextButton(style: TextButton.styleFrom(minimumSize: const Size(0, 32), tapTargetSize: MaterialTapTargetSize.shrinkWrap), onPressed: busy ? null : () async {
    final unit = widget.unit;
    setState(() => busy = true);
    try {
      final result = await context.read<AppState>().api!.grants(unit, {'action': 'import', 'group': widget.group});
      if (!mounted) return;
      if (!identical(widget.unit, unit)) throw StateError('The vision changed during import. Please try again.');
      widget.set(result);
    } catch (e) { if (context.mounted) grantMessage(context, e.toString()); }
    finally { if (mounted) setState(() => busy = false); }
  }, child: Row(mainAxisSize: MainAxisSize.min, children: [Text(busy ? 'Importing…' : 'Import native', style: Guide.band()),
    const SizedBox(width: 6), const Icon(Icons.arrow_forward, color: Guide.onBand, size: 18)]));
}
