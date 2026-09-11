import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../state/app_state.dart';
import 'grant_details.dart';
import 'tiers.dart';

class NativeLibraryRow extends StatefulWidget {
  const NativeLibraryRow({super.key, required this.unit, required this.entry, required this.set, this.zebra = false});
  final Map<String, dynamic> unit, entry;
  final ValueChanged<Map<String, dynamic>> set;
  final bool zebra;
  @override
  State<NativeLibraryRow> createState() => _NativeLibraryRowState();
}

class _NativeLibraryRowState extends State<NativeLibraryRow> {
  bool busy = false;
  @override
  Widget build(BuildContext context) {
    final app = context.read<AppState>();
    final key = widget.entry['sourceKey'];
    final data = grantData(widget.unit, app.catalog!, {'sourceKey': key});
    final equipped = nativeEquipped(widget.unit, key) != null;
    final imported = ((widget.unit['nativeImports'] as List?) ?? []).contains(key);
    final variant = widget.entry['variantLabel'] as String? ?? '';
    return LibraryRow(title: variant.isEmpty ? data.name : '${data.name} · $variant', detail: data.description, zebra: widget.zebra,
      icon: GrantIcon(data: data, api: app.api!, catalog: app.catalog!),
      payload: DragPayload('native', key), done: equipped || imported, doneText: equipped ? 'learned' : 'imported',
      enabled: data.available && !busy,
      onInfo: () => showGrantInfo(context, widget.unit, data), onAdd: (t) async {
        final unit = widget.unit;
        setState(() => busy = true);
        try {
          final next = await app.api!.grants(unit, {'action': 'assign', 'sourceKey': key, 'tier': t});
          if (!mounted) return;
          if (!identical(widget.unit, unit)) throw StateError('The vision changed. Please try adding this ability again.');
          widget.set(next);
        } catch (e) { if (context.mounted) grantMessage(context, e.toString()); }
        finally { if (mounted) setState(() => busy = false); }
      });
  }
}
