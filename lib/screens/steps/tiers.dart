import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../design/theme.dart';
import '../../design/widgets.dart';
import '../../state/app_state.dart';
import '../../state/catalog_helpers.dart';
import 'grant_details.dart';

typedef Grant = List<dynamic>;
List<List<dynamic>> awakening(Map unit) => ((unit['awakening'] as List?) ?? [[], [], [], []]).map((t) => List<dynamic>.from(t as List)).toList();
List<List<dynamic>> deepCopy(List<List<dynamic>> aw) => [for (final t in aw) [for (final g in t) List<dynamic>.from(g as List)]];
bool sameGrant(Grant a, Grant b) => a[0] == b[0] && a[1] == b[1];

/// Drop indices are insertion positions in the original destination tier.
List<List<dynamic>> reorderGrant(List<List<dynamic>> aw, int from, int index, int to, int position) {
  if (from != to && aw[to].length >= tierCap) throw StateError('This tier is full. Move an entry out first.');
  final next = deepCopy(aw);
  final grant = next[from].removeAt(index);
  final at = position - (from == to && index < position ? 1 : 0);
  next[to].insert(at.clamp(0, next[to].length), grant);
  return next;
}

class DragPayload {
  DragPayload(this.kind, this.value);
  final String kind;
  final Object value;
}

/// Only the left handle initiates a drag; text and controls remain selectable.
class GrantHandle extends StatelessWidget {
  const GrantHandle({super.key, required this.payload, required this.title, this.enabled = true});
  final DragPayload payload;
  final String title;
  final bool enabled;
  @override
  Widget build(BuildContext context) {
    final handle = SizedBox(width: 26, height: 38, child: Icon(Icons.drag_indicator, size: 18, color: enabled ? Guide.inkSoft : Guide.inkFaint));
    if (!enabled) return handle;
    return Tooltip(message: 'Drag $title', child: Draggable<DragPayload>(data: payload,
      feedback: Material(color: Guide.paper, child: Container(width: 280, padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(border: Border.all(color: Guide.blue, width: 2)), child: Text(title, style: Guide.strong()))),
      childWhenDragging: Opacity(opacity: .3, child: handle),
      child: MouseRegion(cursor: SystemMouseCursors.grab, child: handle)));
  }
}

/// Hover expands only descriptions that exceed their visible line count.
class DescriptionRow extends StatelessWidget {
  const DescriptionRow({super.key, required this.title, required this.description, required this.leading, required this.trailing, this.subtitle, this.lines = 2});
  final String title, description;
  final String? subtitle;
  final Widget leading, trailing;
  final int lines;
  @override
  Widget build(BuildContext context) => LayoutBuilder(builder: (context, constraints) {
    final width = (constraints.maxWidth - 62 - 96).clamp(1.0, double.infinity);
    final painter = TextPainter(text: TextSpan(text: description, style: Guide.small()), maxLines: lines,
      textDirection: Directionality.of(context), textScaler: MediaQuery.textScalerOf(context))..layout(maxWidth: width);
    final overflow = painter.didExceedMaxLines;
    painter.dispose();
    final row = Row(children: [SizedBox(width: 62, child: leading), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(title, style: Guide.strong(), maxLines: 2, overflow: TextOverflow.ellipsis),
      if (subtitle != null) Text(subtitle!, style: Guide.small(Guide.inkFaint), maxLines: 1, overflow: TextOverflow.ellipsis),
      if (description.isNotEmpty) Text(description, style: Guide.small(), maxLines: lines, overflow: TextOverflow.ellipsis),
    ])), SizedBox(width: 96, child: trailing)]);
    return overflow ? Tooltip(message: description, child: row) : row;
  });
}

class TierMenu extends StatelessWidget {
  const TierMenu({super.key, required this.onPick, this.label = 'add'});
  final ValueChanged<int> onPick;
  final String label;
  @override
  Widget build(BuildContext context) => PopupMenuButton<int>(tooltip: 'Add to a tier', color: Guide.paper,
    onSelected: onPick, itemBuilder: (_) => [for (var t = 0; t < 4; t++) PopupMenuItem(value: t, child: Text('Tier ${t + 1}', style: Guide.text()))],
    child: Padding(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      child: Row(mainAxisSize: MainAxisSize.min, children: [Text(label, style: Guide.small(Guide.blue)), Icon(Icons.arrow_drop_down, size: 16, color: Guide.blue)])));
}

class LibraryRow extends StatelessWidget {
  const LibraryRow({super.key, required this.title, required this.detail, this.icon, this.leading, required this.payload,
    required this.onAdd, this.done = false, this.doneText = 'learned', this.zebra = false, this.onInfo, this.enabled = true});
  final String title, detail, doneText;
  final Widget? icon, leading;
  final DragPayload payload;
  final ValueChanged<int> onAdd;
  final VoidCallback? onInfo;
  final bool done, zebra, enabled;
  @override
  Widget build(BuildContext context) => Container(color: zebra ? Guide.paper2 : Guide.paper,
    padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 7),
    child: DescriptionRow(title: title, description: detail,
      leading: Row(children: [GrantHandle(payload: payload, title: title, enabled: enabled && !done), icon ?? leading ?? const SizedBox(width: 24)]),
      trailing: Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        if (done || !enabled) Expanded(child: Text(done ? doneText : 'unavailable', style: Guide.small(Guide.inkFaint), textAlign: TextAlign.end))
        else TierMenu(onPick: onAdd),
        if (onInfo != null) SizedBox(width: 28, height: 34, child: IconButton(tooltip: 'Ability information', onPressed: onInfo, icon: const Icon(Icons.info_outline, size: 17),
          padding: EdgeInsets.zero, style: IconButton.styleFrom(tapTargetSize: MaterialTapTargetSize.shrinkWrap))),
      ])));
}

/// Both editor tabs share the complete grant list, ordering and controls.
class LearnedTiers extends StatefulWidget {
  const LearnedTiers({super.key, required this.unit, required this.set, required this.onLibraryDrop});
  final Map<String, dynamic> unit;
  final ValueChanged<Map<String, dynamic>> set;
  final void Function(int tier, int index, DragPayload payload) onLibraryDrop;
  @override
  State<LearnedTiers> createState() => _LearnedTiersState();
}

class _LearnedTiersState extends State<LearnedTiers> {
  bool busy = false;
  Future<void> action(Map<String, dynamic> body) async {
    if (busy) return;
    final before = widget.unit;
    setState(() => busy = true);
    try {
      final next = await context.read<AppState>().api!.grants(before, body);
      if (!mounted) return;
      if (!identical(widget.unit, before)) throw StateError('The vision changed during this action. Please try again.');
      widget.set(next);
    } catch (e) { if (mounted) grantMessage(context, e.toString()); }
    finally { if (mounted) setState(() => busy = false); }
  }

  void drop(int tier, int index, DragPayload payload) {
    if (busy) return;
    try {
      if (payload.kind == 'learned') {
        final location = payload.value as List<int>;
        widget.set({'awakening': reorderGrant(awakening(widget.unit), location[0], location[1], tier, index)});
      } else if (payload.kind == 'native') {
        action({'action': 'assign', 'sourceKey': payload.value, 'tier': tier, 'index': index});
      } else { widget.onLibraryDrop(tier, index, payload); }
    } catch (e) { grantMessage(context, e.toString()); }
  }

  Widget target(int tier, int index, Widget child) => DragTarget<DragPayload>(
    onWillAcceptWithDetails: (_) => !busy,
    onAcceptWithDetails: (d) => drop(tier, index, d.data),
    builder: (_, over, rejected) => Container(key: ValueKey('tier-$tier-position-$index'),
      decoration: BoxDecoration(border: Border(top: BorderSide(color: over.isEmpty ? Guide.hairline : Guide.blue, width: over.isEmpty ? 1 : 3))), child: child));

  Widget learned(Grant grant, int tier, int index) {
    final app = context.read<AppState>();
    final data = grantData(widget.unit, app.catalog!, {'kind': grant[0], 'id': grant[1]});
    final stat = grant[0] == 'BaseParameter';
    final name = stat ? statParams.where((p) => p.$1 == grant[1]).firstOrNull?.$2 ?? 'Stat' : data.name;
    final description = stat ? 'Increase $name by ${grant[2]}.' : data.description;
    return target(tier, index, Padding(padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 3),
      child: DescriptionRow(title: name, description: description,
        subtitle: stat ? 'Stat bonus' : '${data.passive ? 'Bonus' : 'Ability'} · ${data.cost} ${data.passive ? 'SP' : 'MP'}',
        leading: Row(children: [GrantHandle(payload: DragPayload('learned', [tier, index]), title: name, enabled: !busy),
          stat ? Icon(Icons.add, size: 22, color: Guide.blue) : GrantIcon(data: data, api: app.api!, catalog: app.catalog!)]),
        trailing: Row(children: [
          tool(Icons.edit_outlined, 'Edit $name', () async {
            if (stat) {
              final amount = await editStat(context, name, (grant[2] as num).toInt());
              if (amount != null && mounted) { final aw = deepCopy(awakening(widget.unit)); aw[tier][index][2] = amount; widget.set({'awakening': aw}); }
            } else { await editGrant(context, widget.unit, data, widget.set); }
          }),
          tool(Icons.info_outline, 'Information about $name', () => stat ? showStatInfo(context, name, grant[2]) : showGrantInfo(context, widget.unit, data)),
          tool(Icons.close, 'Remove $name', () => action({'action': 'remove', 'tier': tier, 'index': index})),
        ]))));
  }

  Widget tool(IconData icon, String label, VoidCallback onPressed) => SizedBox(width: 32, height: 36, child: IconButton(tooltip: label, onPressed: busy ? null : onPressed,
    icon: Icon(icon, size: 17, color: Guide.inkSoft), padding: EdgeInsets.zero, style: IconButton.styleFrom(tapTargetSize: MaterialTapTargetSize.shrinkWrap)));

  @override
  Widget build(BuildContext context) {
    final aw = awakening(widget.unit);
    final app = context.read<AppState>();
    final pending = nativeEntries(widget.unit).where((e) => ((widget.unit['nativeImports'] as List?) ?? []).contains(e['sourceKey']) && nativeEquipped(widget.unit, e['sourceKey']) == null).toList();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Band('Learned by awakening tier', color: Guide.blue, trailing: const SizedBox(height: 32)),
      Padding(padding: const EdgeInsets.all(10), child: Text('Abilities and bonuses · Drag the left handle to reorder or change tiers.', style: Guide.small())),
      if (busy) const LinearProgressIndicator(minHeight: 2),
      Expanded(child: ListView(padding: const EdgeInsets.fromLTRB(10, 0, 10, 10), children: [
        for (var t = 0; t < aw.length; t++) Container(margin: const EdgeInsets.only(bottom: 12),
          decoration: BoxDecoration(border: Border.all(color: Guide.hairline)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Container(color: Guide.paper2, padding: const EdgeInsets.all(9), child: Row(children: [
              Text('TIER ${t + 1}', style: Guide.label()), const SizedBox(width: 12),
              Text('Level ${[1, 31, 61, 91][t]}', style: Guide.small()), const Spacer(), Text('${aw[t].length}/$tierCap', style: Guide.num()),
            ])),
            for (var j = 0; j < aw[t].length; j++) learned(List<dynamic>.from(aw[t][j] as List), t, j),
            target(t, aw[t].length, Padding(padding: EdgeInsets.all(aw[t].isEmpty ? 14 : 6),
              child: Text(aw[t].isEmpty ? 'Drop here to learn at this tier' : 'Drop here to place last', style: Guide.small(Guide.inkFaint)))),
          ])),
        if (pending.isNotEmpty) ...[
          Band('Awaiting assignment · ${pending.length}', color: Guide.purple),
          Padding(padding: const EdgeInsets.all(10), child: Text('The full import stays here. A vision has 10 custom command slots and 8 entries per tier. Remove an assigned native move to free its slot. Unavailable conversions keep their review notes.', style: Guide.small())),
          for (final (i, entry) in pending.indexed) Builder(builder: (context) {
            final data = grantData(widget.unit, app.catalog!, {'sourceKey': entry['sourceKey']});
            return Container(color: i.isOdd ? Guide.paper2 : Guide.paper, padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 3),
              child: DescriptionRow(title: data.name, description: data.description,
                subtitle: data.available ? data.passive ? 'Bonus · Drag to a tier' : 'Ability · Drag to a tier' : 'Unavailable conversion',
                leading: Row(children: [GrantHandle(payload: DragPayload('native', entry['sourceKey']), title: data.name, enabled: data.available && !busy), GrantIcon(data: data, api: app.api!, catalog: app.catalog!)]),
                trailing: Row(children: [tool(Icons.edit_outlined, 'Edit ${data.name}', () => editGrant(context, widget.unit, data, widget.set)),
                  tool(Icons.info_outline, 'Information about ${data.name}', () => showGrantInfo(context, widget.unit, data)),
                  if (data.available) SizedBox(width: 32, child: PopupMenuButton<int>(tooltip: 'Assign to tier', padding: EdgeInsets.zero,
                    icon: Icon(Icons.add, size: 18, color: Guide.blue), onSelected: busy ? null : (t) => action({'action': 'assign', 'sourceKey': entry['sourceKey'], 'tier': t}),
                    itemBuilder: (_) => [for (var t = 0; t < 4; t++) PopupMenuItem(value: t, child: Text('Tier ${t + 1}'))])),
                ])));
          }),
        ],
      ])),
    ]);
  }
}
