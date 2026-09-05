import 'package:flutter/material.dart';

import 'theme.dart';

/// Plain names for Brave Exvius animation files.
String animName(String a) => const {
      'idle': 'Idle', 'standby': 'Standby', 'move': 'Move', 'jump': 'Jump', 'atk': 'Attack', 'magicatk': 'Magic', 'magic_atk': 'Magic',
      'limitatk': 'Limit burst', 'limit_atk': 'Limit burst', 'limitmove': 'Limit burst (move)', 'limit_move': 'Limit burst (move)',
      'magic_standby': 'Magic standby', 'win': 'Victory', 'winbefore': 'Victory (before)', 'win_before': 'Victory (before)', 'dying': 'Dying', 'dead': 'Down',
    }[a] ?? a;

/// One framed picture of the game: the unit's animation, with arrows to step through the others and the animation's
/// name under it. `anims` empty = still loading; `url(anim)` gives the engine's animated WebP.
class AnimViewer extends StatefulWidget {
  const AnimViewer({super.key, required this.anims, required this.url, this.initial, this.height = 200, this.loading = false, this.loadingText = 'loading the assets', this.emptyText = 'No sprites for this look yet.', this.onChanged});
  final List<String> anims;
  final String Function(String anim) url;
  final String? initial;
  final double height;
  final bool loading;
  final String loadingText;
  final String emptyText;
  final ValueChanged<String>? onChanged;
  @override
  State<AnimViewer> createState() => _AnimViewerState();
}

class _AnimViewerState extends State<AnimViewer> {
  int i = 0;
  @override
  void initState() { super.initState(); _seed(); }
  @override
  void didUpdateWidget(AnimViewer old) {
    super.didUpdateWidget(old);
    if (old.anims.join(',') != widget.anims.join(',') || old.initial != widget.initial) _seed();
  }
  void _seed() {
    final want = widget.initial;
    final alt = want == null ? -1 : widget.anims.indexWhere((a) => a == want || a.replaceAll('_', '') == want.replaceAll('_', ''));
    i = alt >= 0 ? alt : 0;
  }
  void step(int d) {
    if (widget.anims.isEmpty) return;
    setState(() => i = (i + d) % widget.anims.length);
    if (i < 0) setState(() => i += widget.anims.length);
    widget.onChanged?.call(widget.anims[i]);
  }
  @override
  Widget build(BuildContext context) {
    final has = widget.anims.isNotEmpty;
    final anim = has ? widget.anims[i.clamp(0, widget.anims.length - 1)] : null;
    return Container(
      decoration: BoxDecoration(color: Guide.paper2, border: Border.all(color: Guide.ink, width: 2)),
      height: widget.height,
      child: Stack(children: [
        Positioned.fill(
          child: widget.loading
              ? Center(child: Row(mainAxisSize: MainAxisSize.min, children: [
                  SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Guide.ink)),
                  const SizedBox(width: 10),
                  Text(widget.loadingText, style: Guide.small()),
                ]))
              : !has
                  ? Center(child: Text(widget.emptyText, style: Guide.small()))
                  : Padding(
                      padding: const EdgeInsets.fromLTRB(36, 8, 36, 26),
                      child: Image.network(
                        widget.url(anim!),
                        key: ValueKey(widget.url(anim)),
                        fit: BoxFit.contain,
                        filterQuality: FilterQuality.none,
                        gaplessPlayback: false,
                        loadingBuilder: (c, child, p) => p == null ? child : Center(child: SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Guide.inkFaint))),
                        errorBuilder: (c, e, s) => Center(child: Text('This animation could not be drawn.', style: Guide.small(Guide.red))),
                      ),
                    ),
        ),
        if (has && widget.anims.length > 1) ...[
          Positioned(left: 4, top: 0, bottom: 0, child: Center(child: _arrow(Icons.chevron_left, () => step(-1)))),
          Positioned(right: 4, top: 0, bottom: 0, child: Center(child: _arrow(Icons.chevron_right, () => step(1)))),
        ],
        if (has)
          Positioned(
            left: 0, right: 0, bottom: 6,
            child: Center(
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                color: Guide.paper,
                child: Text('${animName(anim!)}${widget.anims.length > 1 ? '  ${i + 1}/${widget.anims.length}' : ''}', style: Guide.label(Guide.ink)),
              ),
            ),
          ),
      ]),
    );
  }

  Widget _arrow(IconData icon, VoidCallback on) => Material(
        color: Guide.paper,
        shape: Border.fromBorderSide(BorderSide(color: Guide.ink, width: 1.5)),
        child: InkWell(onTap: on, child: Padding(padding: const EdgeInsets.all(2), child: Icon(icon, size: 20, color: Guide.ink))),
      );
}
