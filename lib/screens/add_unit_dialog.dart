import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../design/theme.dart';
import '../design/widgets.dart';
import '../state/app_state.dart';

Future<void> showAddUnit(BuildContext context) => showDialog<void>(context: context, builder: (_) => const AddUnitDialog());

/// Pick a Brave Exvius unit. Units whose sprite pack is not on the host yet are shown, marked, and cannot be added.
class AddUnitDialog extends StatefulWidget {
  const AddUnitDialog({super.key});
  @override
  State<AddUnitDialog> createState() => _AddUnitDialogState();
}

class _AddUnitDialogState extends State<AddUnitDialog> {
  List<Map<String, dynamic>> list = [];
  Map<String, dynamic>? sel;
  Map<String, dynamic>? detail;
  String q = '';
  String form = '';
  final name = TextEditingController();
  bool busy = false;
  String? step;
  String? err;

  @override
  void initState() {
    super.initState();
    final app = context.read<AppState>();
    final hosted = (app.hostIndex?['units'] as List?)?.cast<Map<String, dynamic>>();
    if (hosted != null) {
      // Named units only, the ones whose sprites are on the host first.
      final named = hosted.where((u) => (u['name'] ?? '').toString().isNotEmpty).toList()
        ..sort((x, y) { final a = x['hasSprites'] == true ? 0 : 1, b = y['hasSprites'] == true ? 0 : 1; return a != b ? a - b : x['name'].toString().toLowerCase().compareTo(y['name'].toString().toLowerCase()); });
      setState(() => list = named);
    } else {
      app.api!.ffbeUnits().then((l) => setState(() => list = l.cast<Map<String, dynamic>>())).catchError((e) => setState(() => err = e.toString()));
    }
  }

  Future<void> pick(Map<String, dynamic> u) async {
    setState(() { sel = u; detail = null; err = null; });
    try {
      final d = await context.read<AppState>().api!.ffbeUnit(u['id'] as String);
      final forms = (d['forms'] as Map?)?.keys.map((k) => k.toString()).toList() ?? [];
      final packs = ((u['packs'] as List?) ?? []).map((e) => e.toString()).toSet();
      final prefer = forms.where(packs.contains).toList();
      setState(() {
        detail = d;
        form = prefer.isNotEmpty ? prefer.last : (d['maxForm']?.toString() ?? u['id'] as String);
        name.text = (d['name'] as String?) ?? (u['name'] as String? ?? '');
      });
    } catch (e) {
      setState(() => err = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = context.read<AppState>();
    final s = q.trim().toLowerCase();
    final shown = (s.isEmpty ? list : list.where((u) => (u['name'] ?? '').toString().toLowerCase().contains(s) || (u['jpname'] ?? '').toString().contains(s) || (u['id'] ?? '').toString().startsWith(s))).take(200).toList();
    final inMod = app.units.map((u) => (u as Map)['ffbe']?['base']?.toString()).toSet();
    final hasPack = sel == null ? false : ((sel!['hasSprites'] == true) || ((sel!['packs'] as List?)?.isNotEmpty ?? false) || sel!['spriteSource'] != null);
    return Dialog(
      backgroundColor: Colors.transparent,
      insetPadding: const EdgeInsets.all(32),
      child: Paper(
        width: 900,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Band('Add a unit from Brave Exvius'),
          Padding(
            padding: const EdgeInsets.all(16),
            child: SizedBox(
              height: 520,
              child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    TextField(autofocus: true, decoration: InputDecoration(hintText: 'Search by name', suffixText: '${list.length} units'), onChanged: (v) => setState(() => q = v)),
                    const SizedBox(height: 8),
                    Expanded(
                      child: Box(
                        padding: EdgeInsets.zero,
                        child: ListView.builder(
                          itemCount: shown.length,
                          itemBuilder: (_, i) {
                            final u = shown[i];
                            final has = u['hasSprites'] == true || ((u['packs'] as List?)?.isNotEmpty ?? false) || u['spriteSource'] != null;
                            final here = inMod.contains(u['id']?.toString());
                            final active = sel?['id'] == u['id'];
                            return Material(
                              color: active ? Guide.paper3 : (i.isOdd ? Guide.paper2 : Guide.paper),
                              child: InkWell(
                                onTap: () => pick(u),
                                child: Padding(
                                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
                                  child: Row(children: [
                                    if (u['iconForm'] != null) Frame(padding: 1, width: 1, child: PixelImage(app.api!.ffbeIcon(u['iconForm'].toString()), width: 34, height: 34)) else const SizedBox(width: 38),
                                    const SizedBox(width: 8),
                                    Expanded(
                                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                        Text((u['name'] ?? u['jpname'] ?? u['id']).toString(), style: Guide.strong(has ? Guide.ink : Guide.inkFaint), maxLines: 1, overflow: TextOverflow.ellipsis),
                                        Text('${u['rarity_min']}★ → ${u['rarity_max'] == 'NV' ? 'NV' : '${u['rarity_max']}★'} · ${((u['roles'] as List?) ?? []).join(', ')}', style: Guide.small(Guide.inkFaint), maxLines: 1, overflow: TextOverflow.ellipsis),
                                      ]),
                                    ),
                                    if (here) _chip('in mod', Guide.blue) else if (!has) _chip('no sprites yet', Guide.inkFaint),
                                  ]),
                                ),
                              ),
                            );
                          },
                        ),
                      ),
                    ),
                  ]),
                ),
                const SizedBox(width: 16),
                SizedBox(
                  width: 340,
                  child: sel == null
                      ? Center(child: Text('Pick a unit on the left.', style: Guide.small()))
                      : detail == null && err == null
                          ? const Center(child: SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2, color: Guide.ink)))
                          : _detail(app, hasPack),
                ),
              ]),
            ),
          ),
          Container(
            decoration: const BoxDecoration(border: Border(top: BorderSide(color: Guide.hairline))),
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              if (err != null) Expanded(child: Text(err!, style: Guide.small(Guide.red))) else const Spacer(),
              GuideButton('Cancel', onPressed: busy ? null : () => Navigator.of(context).pop()),
              const SizedBox(width: 8),
              GoButton(busy ? (step ?? 'Adding') : 'Add unit', color: Guide.blue, busy: busy, onPressed: detail == null || !hasPack || busy ? null : () async {
                setState(() { busy = true; err = null; });
                try {
                  await app.addUnit(sel!['id'] as String, form, name.text, onStep: (s) => setState(() => step = s));
                  if (context.mounted) Navigator.of(context).pop();
                } catch (e) {
                  setState(() { err = e.toString(); busy = false; });
                }
              }),
            ]),
          ),
        ]),
      ),
    );
  }

  Widget _chip(String t, Color c) => Container(
        margin: const EdgeInsets.only(left: 6),
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(border: Border.all(color: c)),
        child: Text(t.toUpperCase(), style: Guide.label(c).copyWith(fontSize: 11)),
      );

  Widget _detail(AppState app, bool hasPack) {
    final d = detail!;
    final forms = ((d['forms'] as Map?) ?? {}).map((k, v) => MapEntry(k.toString(), v as Map));
    final packs = ((sel!['packs'] as List?) ?? []).map((e) => e.toString()).toSet();
    final lb = forms[form]?['limitburst'] as Map?;
    final st = (d['ffrStats'] as Map?) ?? {};
    return SingleChildScrollView(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Frame(child: PixelImage(app.api!.ffbeIcon(form), width: 56, height: 56)),
          const SizedBox(width: 10),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text((d['name'] ?? '').toString().toUpperCase(), style: Guide.h2()), Text((d['jpname'] ?? '').toString(), style: Guide.small())])),
        ]),
        if (!hasPack) ...[const SizedBox(height: 10), Box(fill: const Color(0xFFFFF4DE), child: Text('No sprite pack for this unit is on the host yet, so it cannot be added. Ask for it to be added to the pack.', style: Guide.small(Guide.ink)))],
        const SizedBox(height: 12),
        Text('NAME IN THE GAME', style: Guide.label()),
        const SizedBox(height: 4),
        TextField(controller: name),
        const SizedBox(height: 12),
        Text('LOOK (RARITY)', style: Guide.label()),
        const SizedBox(height: 4),
        DropdownButtonFormField<String>(
          key: ValueKey('form$form'), initialValue: forms.containsKey(form) ? form : null,
          items: [for (final e in forms.entries) DropdownMenuItem(value: e.key, child: Text('${e.value['rarity'] == 'NV' ? 'Neo Vision' : '${e.value['rarity']}★'}${packs.contains(e.key) || sel!['spriteSource'] != null ? '' : ' (no sprites)'}', style: Guide.text()))],
          onChanged: (v) => setState(() => form = v ?? form),
        ),
        const SizedBox(height: 12),
        Box(
          padding: EdgeInsets.zero,
          child: Column(children: [
            StatRow('HP', '${st['MaxHitPoint'] ?? '-'}'), StatRow('MP', '${st['MaxMagicPoint'] ?? '-'}', zebra: true), StatRow('Attack', '${st['Attack'] ?? '-'}'), StatRow('Defence', '${st['Defence'] ?? '-'}', zebra: true),
            StatRow('Intelligence', '${st['Intelligence'] ?? '-'}'), StatRow('Mind', '${st['Mind'] ?? '-'}', zebra: true),
          ]),
        ),
        const SizedBox(height: 10),
        Text('${(d['abilities'] as List?)?.length ?? 0} abilities · ${(d['passives'] as List?)?.length ?? 0} passives in Brave Exvius · Limit burst: ${lb?['name'] ?? '-'}', style: Guide.small()),
        const SizedBox(height: 6),
        Text('The unit arrives with its look and stats. Abilities, bonuses and the Resonance are chosen from the game next.', style: Guide.small()),
        if (hasPack) ...[const SizedBox(height: 10), Frame(child: PixelImage(app.api!.ffbePreview(form, 'idle'), width: 300, height: 140))],
      ]),
    );
  }

  @override
  void dispose() { name.dispose(); super.dispose(); }
}
