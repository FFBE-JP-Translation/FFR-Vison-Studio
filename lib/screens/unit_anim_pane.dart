import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../design/anim_viewer.dart';
import '../state/app_state.dart';

/// The unit's Brave Exvius motions (its chosen look), fetched once per look from the engine.
class UnitAnimPane extends StatefulWidget {
  const UnitAnimPane({super.key, required this.unit, this.initial = 'idle', this.height = 200});
  final Map<String, dynamic> unit;
  final String initial;
  final double height;
  @override
  State<UnitAnimPane> createState() => _UnitAnimPaneState();
}

class _UnitAnimPaneState extends State<UnitAnimPane> {
  List<String>? anims;
  bool loading = true;
  String? form;

  @override
  void initState() { super.initState(); _load(); }
  @override
  void didUpdateWidget(UnitAnimPane old) {
    super.didUpdateWidget(old);
    if ((widget.unit['ffbe'] as Map?)?['id']?.toString() != form) _load();
  }

  Future<void> _load() async {
    final ff = widget.unit['ffbe'] as Map?;
    form = ff?['id']?.toString();
    if (form == null) { setState(() { anims = []; loading = false; }); return; }
    setState(() => loading = true);
    try {
      final a = await context.read<AppState>().animsFor(form!);
      if (mounted) setState(() { anims = a; loading = false; });
    } catch (_) {
      if (mounted) setState(() { anims = []; loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = context.read<AppState>();
    final f = form;
    return AnimViewer(
      key: ValueKey('pane$f${widget.initial}'),
      anims: anims ?? const [],
      url: (a) => f == null ? '' : app.api!.animUrl(f, a),
      initial: widget.initial,
      height: widget.height,
      loading: loading,
      loadingText: 'loading the motions',
      emptyText: 'No sprites for this unit on this machine.',
    );
  }
}
