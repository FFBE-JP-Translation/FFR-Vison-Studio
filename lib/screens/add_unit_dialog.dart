import 'dart:io';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../design/anim_viewer.dart';
import '../design/theme.dart';
import '../design/widgets.dart';
import '../state/app_state.dart';
import '../state/catalog_helpers.dart';

Future<void> showAddUnit(BuildContext context) => showDialog<void>(context: context, builder: (_) => const AddUnitDialog());

/// Browse cached idle previews. Only Add unit downloads a complete unit bundle.
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
  final selectedCategories = <String>{};
  File? idlePreview;
  String form = '';
  final name = TextEditingController();
  bool busy = false;
  bool loadingAssets = false;
  String? step;
  double? downloadFraction;
  String? downloadSize;
  String? err;
  int _pickSeq = 0;

  @override
  void initState() {
    super.initState();
    final app = context.read<AppState>();
    final hosted = (app.hostIndex?['units'] as List?)?.cast<Map<String, dynamic>>();
    if (hosted != null) {
      final named = hosted.where((u) => (u['name'] ?? '').toString().isNotEmpty).toList()
        ..sort((x, y) { final a = x['hasSprites'] == true ? 0 : 1, b = y['hasSprites'] == true ? 0 : 1; return a != b ? a - b : x['name'].toString().toLowerCase().compareTo(y['name'].toString().toLowerCase()); });
      setState(() => list = named);
    } else {
      app.api!.ffbeUnits().then((l) => setState(() => list = l.cast<Map<String, dynamic>>())).catchError((e) => setState(() => err = e.toString()));
    }
  }

  /// Select from the startup catalog without downloading the unit's assets.
  Future<void> pick(Map<String, dynamic> u) async {
    if (busy) return;
    final seq = ++_pickSeq;
    setState(() { sel = u; detail = null; idlePreview = null; err = null; loadingAssets = true; });
    final app = context.read<AppState>();
    try {
      final d = catalogUnitDetail(u, (u['previewDetail'] as Map<String, dynamic>?) ?? await app.api!.ffbeUnit(u['id'] as String));
      if (!mounted || seq != _pickSeq) return;
      final forms = (d['forms'] as Map?)?.keys.map((k) => k.toString()).toList() ?? [];
      final packs = ((u['packs'] as List?) ?? []).map((e) => e.toString()).toSet();
      final prefer = forms.where(packs.contains).toList()..sort();
      final plain = prefer.where((x) => ((d['forms'] as Map?)?[x] as Map?)?['shift'] == null).toList();
      final preferred = d['maxForm']?.toString();
      final f = plain.contains(preferred) ? preferred! : plain.isNotEmpty ? plain.last : prefer.isNotEmpty ? prefer.last : (preferred ?? u['id'] as String);
      setState(() { detail = d; form = f; idlePreview = app.idleFile(f); name.text = (d['name'] as String?) ?? (u['name'] as String? ?? ''); });
    } catch (e) {
      if (mounted && seq == _pickSeq) setState(() => err = e.toString());
    } finally {
      if (seq == _pickSeq && mounted) setState(() => loadingAssets = false);
    }
  }

  /// Switching looks reads another idle from the shared startup pack.
  void setForm(String f) {
    if (busy) return;
    final app = context.read<AppState>();
    setState(() { form = f; idlePreview = app.idleFile(f); err = null; });
  }

  @override
  Widget build(BuildContext context) {
    final app = context.read<AppState>();
    final s = q.trim().toLowerCase();
    final matches = list.where((u) => matchesUnitSearch(u, s, selectedCategories)).toList();
    final shown = matches;
    final categoryLabels = (app.hostIndex?['categories'] as Map?) ?? {};
    final availableCategories = list.expand((u) => (u['categories'] as List?) ?? []).map((v) => v.toString()).toSet().where(categoryLabels.containsKey).toList()
      ..sort((a, b) => categoryLabels[a]['name'].toString().compareTo(categoryLabels[b]['name'].toString()));
    final inMod = app.units.map((u) => (u as Map)['ffbe']?['base']?.toString()).toSet();
    final packs = sel == null ? <String>{} : ((sel!['packs'] as List?) ?? []).map((e) => e.toString()).toSet();
    final hasPack = packs.contains(form);
    return PopScope(canPop: !busy, child: Dialog(
      backgroundColor: Colors.transparent,
      insetPadding: const EdgeInsets.all(32),
      child: Paper(
        width: 940,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Band('Add a unit from Brave Exvius'),
          Padding(
            padding: const EdgeInsets.all(16),
            child: SizedBox(
              height: 560,
              child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    TextField(autofocus: true, enabled: !busy, decoration: InputDecoration(hintText: 'Search by name', suffixText: '${matches.length} units'), onChanged: (v) => setState(() => q = v), onSubmitted: (_) { if (shown.isNotEmpty) pick(shown.first); }),
                    if (availableCategories.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      DropdownButtonFormField<String>(
                        key: ValueKey(selectedCategories.join(',')),
                        isExpanded: true,
                        decoration: const InputDecoration(hintText: 'Filter by category'),
                        items: [for (final id in availableCategories.where((id) => !selectedCategories.contains(id)))
                          DropdownMenuItem(value: id, child: Text(categoryLabels[id]['name'].toString(), overflow: TextOverflow.ellipsis))],
                        onChanged: busy ? null : (id) { if (id != null) setState(() => selectedCategories.add(id)); },
                      ),
                      if (selectedCategories.isNotEmpty) Wrap(spacing: 4, children: [for (final id in selectedCategories)
                        InputChip(label: Text(categoryLabels[id]['name'].toString()), onDeleted: busy ? null : () => setState(() => selectedCategories.remove(id)))]),
                    ],
                    const SizedBox(height: 8),
                    Expanded(
                      child: Box(
                        padding: EdgeInsets.zero,
                        child: ListView.builder(
                          itemCount: shown.length,
                          itemBuilder: (_, i) {
                            final u = shown[i];
                            final has = u['hasSprites'] == true || ((u['packs'] as List?)?.isNotEmpty ?? false);
                            final here = inMod.contains(u['id']?.toString());
                            final active = sel?['id'] == u['id'];
                            return Material(
                              color: active ? Guide.paper3 : (i.isOdd ? Guide.paper2 : Guide.paper),
                              child: InkWell(
                                onTap: busy ? null : () => pick(u),
                                child: Padding(
                                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
                                  child: Row(children: [
                                    Frame(padding: 1, width: 1, child: SizedBox(width: 44, height: 30, child: u['iconForm'] != null ? _icon(app, u['iconForm'].toString()) : const SizedBox.shrink())),
                                    const SizedBox(width: 8),
                                    Expanded(
                                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                        Text((u['name'] ?? u['jpname'] ?? u['id']).toString(), style: Guide.strong(has ? Guide.ink : Guide.inkFaint), maxLines: 1, overflow: TextOverflow.ellipsis),
                                        Text('${rarityRange(u['rarity_min'], u['rarity_max'])} · ${((u['roles'] as List?) ?? []).join(', ')}', style: Guide.small(Guide.inkFaint), maxLines: 1, overflow: TextOverflow.ellipsis),
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
                  width: 360,
                  child: sel == null
                      ? Center(child: Text('Pick a unit on the left.', style: Guide.small()))
                      : detail == null && err == null
                          ? Center(child: Row(mainAxisSize: MainAxisSize.min, children: [
                              SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Guide.ink)),
                              const SizedBox(width: 10),
                              Text('loading the assets', style: Guide.small()),
                            ]))
                          : detail == null
                              ? Center(child: Text(err!, style: Guide.small(Guide.red)))
                              : _detail(app, hasPack, packs),
                ),
              ]),
            ),
          ),
          Container(
            decoration: BoxDecoration(border: Border(top: BorderSide(color: Guide.hairline))),
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              if (err != null && detail != null) Expanded(child: Text(err!, style: Guide.small(Guide.red))) else if (busy) Expanded(child: Padding(
                padding: const EdgeInsets.only(right: 16),
                child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${step ?? 'Preparing download'}${downloadSize == null ? '' : ' · $downloadSize'}', style: Guide.small()),
                  const SizedBox(height: 6),
                  LinearProgressIndicator(value: downloadFraction, color: Guide.blue),
                ]),
              )) else const Spacer(),
              GuideButton('Cancel', onPressed: busy ? null : () => Navigator.of(context).pop()),
              const SizedBox(width: 8),
              GoButton(busy ? 'Adding' : 'Add unit', color: Guide.blue, busy: busy, onPressed: detail == null || !hasPack || busy || loadingAssets ? null : () async {
                setState(() { busy = true; err = null; step = null; downloadFraction = null; downloadSize = null; });
                try {
                  await app.addUnit(sel!['id'] as String, form, name.text, onStep: (s) {
                    if (mounted) setState(() { step = s; downloadFraction = null; downloadSize = null; });
                  }, onProgress: (got, total) {
                    if (mounted) { setState(() {
                      downloadFraction = total > 0 ? (got / total).clamp(0.0, 1.0) : null;
                      downloadSize = total > 0 ? '${(downloadFraction! * 100).round()}% · ${(got / 1048576).toStringAsFixed(1)} / ${(total / 1048576).toStringAsFixed(1)} MB' : '${(got / 1048576).toStringAsFixed(1)} MB';
                    }); }
                  });
                  if (context.mounted) { Navigator.of(context).pop(); }
                } catch (e) {
                  if (mounted) setState(() { err = e.toString(); busy = false; });
                }
              }),
            ]),
          ),
        ]),
      ),
    ));
  }

  /// The face icon: from the icons pack on disk, else from the engine (downloaded sprites). Never from the host per row.
  Widget _icon(AppState app, String form) {
    final f = app.iconFile(form);
    if (f.existsSync()) return Image.file(f, width: 44, height: 30, fit: BoxFit.cover, filterQuality: FilterQuality.none, gaplessPlayback: true);
    if (app.api == null) return Center(child: Text('?', style: Guide.small(Guide.inkFaint)));
    return Image.network(app.api!.ffbeIcon(form), width: 44, height: 30, fit: BoxFit.cover, filterQuality: FilterQuality.none, gaplessPlayback: true,
        errorBuilder: (c, e, s) => Center(child: Text('?', style: Guide.small(Guide.inkFaint))));
  }

  Widget _chip(String t, Color c) => Container(
        margin: const EdgeInsets.only(left: 6),
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(border: Border.all(color: c)),
        child: Text(t.toUpperCase(), style: Guide.label(c).copyWith(fontSize: 11)),
      );

  Widget _detail(AppState app, bool hasPack, Set<String> packs) {
    final d = detail!;
    final forms = ((d['forms'] as Map?) ?? {}).map((k, v) => MapEntry(k.toString(), v as Map));
    final st = (d['ffrStats'] as Map?) ?? {};
    Widget stat(String l, dynamic v) => Expanded(child: Row(children: [Text(l, style: Guide.small()), const Spacer(), Text('${v ?? '-'}', style: Guide.num())]));
    Widget row(List<Widget> cells, {bool zebra = false}) => Container(
          color: zebra ? Guide.paper2 : Guide.paper,
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          child: Row(children: [cells[0], const SizedBox(width: 18), cells[1]]),
        );
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(children: [
        Frame(padding: 2, child: SizedBox(width: 56, height: 38, child: _icon(app, form))),
        const SizedBox(width: 10),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text((d['name'] ?? '').toString().toUpperCase(), style: Guide.h2(), maxLines: 1, overflow: TextOverflow.ellipsis),
          if ((d['jpname'] ?? '').toString().isNotEmpty) Text((d['jpname'] ?? '').toString(), style: Guide.small()),
        ])),
      ]),
      const SizedBox(height: 10),
      Text('NAME IN THE GAME', style: Guide.label()),
      const SizedBox(height: 4),
      TextField(controller: name, enabled: !busy),
      const SizedBox(height: 10),
      Text('LOOK', style: Guide.label()),
      const SizedBox(height: 4),
      DropdownButtonFormField<String>(
        key: ValueKey('form$form'), initialValue: forms.containsKey(form) ? form : null, isExpanded: true,
        items: [for (final e in forms.entries) DropdownMenuItem(value: e.key, child: Text('${rarityLabel(e.value['rarity'])}${shiftLabel(e.value['shift'])}${packs.contains(e.key) ? '' : ' (no sprites)'}', style: Guide.text(), overflow: TextOverflow.ellipsis))],
        onChanged: busy ? null : (v) { if (v != null) setForm(v); },
      ),
      const SizedBox(height: 10),
      AnimViewer(
        key: ValueKey('viewer$form'),
        anims: idlePreview != null ? const ['idle'] : const [],
        url: (a) => app.api!.animUrl(form, a),
        initial: 'idle',
        height: 210,
        loading: loadingAssets,
        idlePreview: idlePreview,
        loadingText: 'Loading idle preview',
        emptyText: hasPack ? 'Idle preview unavailable. You can still add this unit.' : 'No sprite pack for this look is on the host yet.',
      ),
      const SizedBox(height: 10),
      if (st.isNotEmpty) Box(
        padding: EdgeInsets.zero,
        child: Column(children: [
          row([stat('HP', st['MaxHitPoint']), stat('Attack', st['Attack'])]),
          row([stat('MP', st['MaxMagicPoint']), stat('Defence', st['Defence'])], zebra: true),
          row([stat('Intelligence', st['Intelligence']), stat('Mind', st['Mind'])]),
        ]),
      ),
      const SizedBox(height: 6),
      if (st.isNotEmpty) Text('Level 1 values for FINAL FANTASY RESONANCE, scaled from the Brave Exvius maximums.', style: Guide.small(Guide.inkFaint)),
      if (st.isEmpty) Text('Add this unit to explore its stats, abilities and other animations.', style: Guide.small(Guide.inkFaint)),
      if (!hasPack) ...[const SizedBox(height: 8), Box(fill: Guide.warn, child: Text('No sprite pack for this look is on the host yet, so it cannot be added. Pick another look, or ask for it to be added.', style: Guide.small(Guide.ink)))],
    ]);
  }

  @override
  void dispose() { name.dispose(); super.dispose(); }
}
