import 'package:flutter/material.dart';

import '../../design/theme.dart';
import '../../design/widgets.dart';
import '../../state/catalog_helpers.dart';

typedef Grant = List<dynamic>;

List<List<dynamic>> awakening(Map<String, dynamic> unit) => ((unit['awakening'] as List?) ?? [[], [], [], []]).map((t) => List<dynamic>.from(t as List)).toList();

List<List<dynamic>> deepCopy(List<List<dynamic>> aw) => aw.map((t) => t.map((g) => List<dynamic>.from(g as List)).toList()).toList();

bool sameGrant(dynamic a, dynamic b) => a[0] == b[0] && (a[1] as num) == (b[1] as num);

/// The four awakening tiers as drop targets. `kinds` picks which grants this step shows; `render` draws one.
class Tiers extends StatefulWidget {
  const Tiers({super.key, required this.unit, required this.kinds, required this.render, required this.onDrop, required this.hint, required this.dragKind});
  final Map<String, dynamic> unit;
  final List<String> kinds;
  final Widget Function(Grant g, int tier, int index) render;
  final void Function(int tier, Object payload) onDrop;
  final String hint;
  final String dragKind;
  @override
  State<Tiers> createState() => _TiersState();
}

class _TiersState extends State<Tiers> {
  int? over;
  @override
  Widget build(BuildContext context) {
    final aw = awakening(widget.unit);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Band('Learned by awakening tier', color: Guide.ink, trailing: Text(widget.hint.toUpperCase(), style: Guide.band(Guide.paper3).copyWith(fontSize: 11, letterSpacing: 0.6))),
      Expanded(
        child: ListView(
          padding: const EdgeInsets.all(12),
          children: [
            for (var i = 0; i < aw.length; i++) ...[
              DragTarget<DragPayload>(
                onWillAcceptWithDetails: (d) => d.data.kind == widget.dragKind,
                onMove: (_) => setState(() => over = i),
                onLeave: (_) => setState(() => over = null),
                onAcceptWithDetails: (d) { setState(() => over = null); widget.onDrop(i, d.data.value); },
                builder: (ctx, cand, rej) {
                  final mine = <(Grant, int)>[for (var j = 0; j < aw[i].length; j++) if (widget.kinds.contains(aw[i][j][0])) (aw[i][j], j)];
                  final full = aw[i].length >= tierCap;
                  return AnimatedContainer(
                    duration: Guide.fast,
                    decoration: BoxDecoration(color: over == i ? const Color(0xFFE8EEFB) : Guide.paper, border: Border.all(color: over == i ? Guide.blue : Guide.ink, width: over == i ? 2 : 1.5)),
                    margin: const EdgeInsets.only(bottom: 10),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                      Container(
                        color: Guide.paper2,
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                        child: Row(children: [
                          Text('TIER ${i + 1}', style: Guide.label(Guide.ink)),
                          const SizedBox(width: 10),
                          Text(i == 0 ? 'available at level 1' : 'level ${[1, 31, 61, 91][i]} and up', style: Guide.small()),
                          const Spacer(),
                          Text('${aw[i].length}/$tierCap${full ? ' full' : ''}', style: Guide.num(full ? Guide.red : Guide.inkSoft).copyWith(fontSize: 12)),
                        ]),
                      ),
                      if (mine.isEmpty)
                        Padding(padding: const EdgeInsets.all(12), child: Text(over == i ? 'Drop to learn it here' : 'Nothing here yet. Drag from the left, or use "add".', style: Guide.small(Guide.inkFaint)))
                      else
                        for (final (g, j) in mine) widget.render(g, i, j),
                    ]),
                  );
                },
              ),
            ],
          ],
        ),
      ),
    ]);
  }
}

class DragPayload {
  DragPayload(this.kind, this.value);
  final String kind;
  final Object value;
}

/// Small "add at tier…" menu used beside library rows.
class TierMenu extends StatelessWidget {
  const TierMenu({super.key, required this.onPick, this.label = 'add'});
  final ValueChanged<int> onPick;
  final String label;
  @override
  Widget build(BuildContext context) => PopupMenuButton<int>(
        tooltip: 'Add to a tier',
        color: Guide.paper,
        shape: const Border.fromBorderSide(BorderSide(color: Guide.ink, width: 1.5)),
        onSelected: onPick,
        itemBuilder: (_) => [for (var t = 0; t < 4; t++) PopupMenuItem(value: t, height: 32, child: Text('Tier ${t + 1}', style: Guide.text()))],
        child: Container(
          decoration: BoxDecoration(border: Border.all(color: Guide.ink, width: 1.5)),
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          child: Row(mainAxisSize: MainAxisSize.min, children: [Text(label, style: Guide.small(Guide.ink)), const Icon(Icons.arrow_drop_down, size: 16, color: Guide.ink)]),
        ),
      );
}

/// Move / remove controls at the end of a learned row.
class GrantTools extends StatelessWidget {
  const GrantTools({super.key, required this.tier, required this.onMove, required this.onRemove});
  final int tier;
  final ValueChanged<int> onMove;
  final VoidCallback onRemove;
  @override
  Widget build(BuildContext context) => Row(mainAxisSize: MainAxisSize.min, children: [
        PopupMenuButton<int>(
          tooltip: 'Learned at',
          color: Guide.paper,
          shape: const Border.fromBorderSide(BorderSide(color: Guide.ink, width: 1.5)),
          onSelected: onMove,
          itemBuilder: (_) => [for (var t = 0; t < 4; t++) PopupMenuItem(value: t, height: 32, enabled: t != tier, child: Text('Tier ${t + 1}', style: Guide.text(t == tier ? Guide.inkFaint : Guide.ink)))],
          child: Padding(padding: const EdgeInsets.symmetric(horizontal: 6), child: Text('tier ${tier + 1} ▾', style: Guide.small(Guide.blue))),
        ),
        IconButton(icon: const Icon(Icons.close, size: 16), color: Guide.inkSoft, tooltip: 'Remove', onPressed: onRemove, padding: EdgeInsets.zero, constraints: const BoxConstraints(minWidth: 28, minHeight: 28)),
      ]);
}

/// A draggable library row: icon, title, one line of detail, and the add menu.
class LibraryRow extends StatelessWidget {
  const LibraryRow({super.key, required this.title, required this.detail, this.icon, this.leading, required this.payload, required this.onAdd, this.done = false, this.doneText = 'learned', this.zebra = false});
  final String title;
  final String detail;
  final Widget? icon;
  final Widget? leading;
  final DragPayload payload;
  final ValueChanged<int> onAdd;
  final bool done;
  final String doneText;
  final bool zebra;
  @override
  Widget build(BuildContext context) {
    final row = Container(
      color: zebra ? Guide.paper2 : Guide.paper,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      child: Row(children: [
        if (leading != null) ...[leading!, const SizedBox(width: 8)],
        if (icon != null) ...[icon!, const SizedBox(width: 8)],
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: Guide.strong(done ? Guide.inkFaint : Guide.ink), maxLines: 1, overflow: TextOverflow.ellipsis),
          Text(detail, style: Guide.small(done ? Guide.inkFaint : Guide.inkSoft), maxLines: 2, overflow: TextOverflow.ellipsis),
        ])),
        const SizedBox(width: 8),
        if (done) Text(doneText, style: Guide.small(Guide.inkFaint)) else TierMenu(onPick: onAdd),
      ]),
    );
    if (done) return row;
    return Draggable<DragPayload>(
      data: payload,
      feedback: Material(color: Colors.transparent, child: Container(width: 320, decoration: BoxDecoration(color: Guide.paper, border: Border.all(color: Guide.ink, width: 2), boxShadow: const [BoxShadow(color: Color(0x40000000), offset: Offset(0, 4), blurRadius: 12)]), padding: const EdgeInsets.all(8), child: Text(title, style: Guide.strong()))),
      childWhenDragging: Opacity(opacity: 0.4, child: row),
      child: MouseRegion(cursor: SystemMouseCursors.grab, child: row),
    );
  }
}
