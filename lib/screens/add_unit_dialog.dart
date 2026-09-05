import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../design/anim_viewer.dart';
import '../design/theme.dart';
import '../design/widgets.dart';
import '../state/app_state.dart';
import '../state/catalog_helpers.dart';

Future<void> showAddUnit(BuildContext context) => showDialog<void>(context: context, builder: (_) => const AddUnitDialog());

/// Pick a Brave Exvius unit. Picking one fetches its sprites (a small download) so the look can be previewed here.
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
  bool loadingAssets = false;
  String? step;
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

  /// Select a unit: read its record, pick the best look that has a sprite pack, fetch that pack, then show the animations.
  Future<void> pick(Map<String, dynamic> u) async {
    final seq = ++_pickSeq;
    setState(() { sel = u; detail = null; err = null; loadingAssets = true; });
    final app = context.read<AppState>();
    try {
      var d = await app.api!.ffbeUnit(u['id'] as String);
      if (seq != _pickSeq) return;
      final forms = (d['forms'] as Map?)?.keys.map((k) => k.toString()).toList() ?? [];
      final packs = ((u['packs'] as List?) ?? []).map((e) => e.toString()).toSet();
      final prefer = forms.where(packs.contains).toList();
      final f = prefer.isNotEmpty ? prefer.last : (d['maxForm']?.toString() ?? u['id'] as String);
      setState(() { detail = d; form = f; name.text = (d['name'] as String?) ?? (u['name'] as String? ?? ''); });
      if (packs.contains(f)) {
        await app.ensureSprites(f);
        if (seq != _pickSeq) return;
        d = await app.api!.ffbeUnit(u['id'] as String); // now with the animation list for the fetched look
        if (seq != _pickSeq) return;
        setState(() => detail = d);
      }
    } catch (e) {
      if (seq == _pickSeq) setState(() => err = e.toString());
    } finally {
      if (seq == _pickSeq && mounted) setState(() => loadingAssets = false);
    }
  }

  /// Switching the look fetches that look's sprites too.
  Future<void> setForm(String f) async {
    final app = context.read<AppState>();
    final packs = ((sel!['packs'] as List?) ?? []).map((e) => e.toString()).toSet();
    setState(() { form = f; loadingAssets = packs.contains(f); });
    if (!packs.contains(f)) return;
    final seq = _pickSeq;
    try {
      await app.ensureSprites(f);
      if (seq != _pickSeq) return;
      final d = await app.api!.ffbeUnit(sel!['id'] as String);
      if (seq == _pickSeq) setState(() => detail = d);
    } catch (e) {
      if (seq == _pickSeq) setState(() => err = e.toString());
    } finally {
      if (seq == _pickSeq && mounted) setState(() => loadingAssets = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = context.read<AppState>();
    final s = q.trim().toLowerCase();
    final shown = (s.isEmpty ? list : list.where((u) => (u['name'] ?? '').toString().toLowerCase().contains(s) || (u['jpname'] ?? '').toString().contains(s) || (u['id'] ?? '').toString().startsWith(s))).take(200).toList();
    final inMod = app.units.map((u) => (u as Map)['ffbe']?['base']?.toString()).toSet();
    final packs = sel == null ? <String>{} : ((sel!['packs'] as List?) ?? []).map((e) => e.toString()).toSet();
    final hasPack = packs.contains(form);
    return Dialog(
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
                    TextField(autofocus: true, decoration: InputDecoration(hintText: 'Search by name', suffixText: '${list.length} units'), onChanged: (v) => setState(() => q = v)),
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
                                onTap: () => pick(u),
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
              if (err != null && detail != null) Expanded(child: Text(err!, style: Guide.small(Guide.red))) else if (step != null && busy) Expanded(child: Text(step!, style: Guide.small())) else const Spacer(),
              GuideButton('Cancel', onPressed: busy ? null : () => Navigator.of(context).pop()),
              const SizedBox(width: 8),
              GoButton(busy ? 'Adding' : 'Add unit', color: Guide.blue, busy: busy, onPressed: detail == null || !hasPack || busy || loadingAssets ? null : () async {
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

  /// The face icon: from the host (every unit has one there), else from the engine (downloaded sprites).
  Widget _icon(AppState app, String form) => Image.network(
        app.hostIconUrl(form),
        width: 44, height: 30, fit: BoxFit.cover, filterQuality: FilterQuality.none, gaplessPlayback: true,
        errorBuilder: (c, e, s) => Image.network(app.api!.ffbeIcon(form), width: 44, height: 30, fit: BoxFit.cover, filterQuality: FilterQuality.none,
            errorBuilder: (c, e, s) => Center(child: Text('?', style: Guide.small(Guide.inkFaint)))),
      );

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
    final anims = ((forms[form]?['sprites'] as List?) ?? []).map((e) => e.toString()).toList();
    final ordered = orderAnims(anims);
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
      Row(children: [
        Expanded(flex: 3, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('NAME IN THE GAME', style: Guide.label()),
          const SizedBox(height: 4),
          TextField(controller: name),
        ])),
        const SizedBox(width: 10),
        Expanded(flex: 2, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('LOOK', style: Guide.label()),
          const SizedBox(height: 4),
          DropdownButtonFormField<String>(
            key: ValueKey('form$form'), initialValue: forms.containsKey(form) ? form : null, isExpanded: true,
            items: [for (final e in forms.entries) DropdownMenuItem(value: e.key, child: Text('${rarityLabel(e.value['rarity'])}${packs.contains(e.key) ? '' : ' (no sprites)'}', style: Guide.text(), overflow: TextOverflow.ellipsis))],
            onChanged: (v) { if (v != null) setForm(v); },
          ),
        ])),
      ]),
      const SizedBox(height: 10),
      AnimViewer(
        key: ValueKey('viewer$form'),
        anims: hasPack ? ordered : const [],
        url: (a) => app.api!.animUrl(form, a),
        initial: 'idle',
        height: 210,
        loading: loadingAssets,
        emptyText: hasPack ? 'No animations for this look.' : 'No sprite pack for this look is on the host yet.',
      ),
      const SizedBox(height: 10),
      Box(
        padding: EdgeInsets.zero,
        child: Column(children: [
          row([stat('HP', st['MaxHitPoint']), stat('Attack', st['Attack'])]),
          row([stat('MP', st['MaxMagicPoint']), stat('Defence', st['Defence'])], zebra: true),
          row([stat('Intelligence', st['Intelligence']), stat('Mind', st['Mind'])]),
        ]),
      ),
      const SizedBox(height: 6),
      Text('Level 1 values for FINAL FANTASY RESONANCE, scaled from the Brave Exvius maximums.', style: Guide.small(Guide.inkFaint)),
      if (!hasPack) ...[const SizedBox(height: 8), Box(fill: Guide.warn, child: Text('No sprite pack for this look is on the host yet, so it cannot be added. Pick another look, or ask for it to be added.', style: Guide.small(Guide.ink)))],
    ]);
  }

  @override
  void dispose() { name.dispose(); super.dispose(); }
}
