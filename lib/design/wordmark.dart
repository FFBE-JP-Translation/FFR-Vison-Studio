import 'package:flutter/material.dart';

import 'theme.dart';

/// The studio's mark: Rain's pixel face in an ink frame on FF blue, beside the two-line wordmark.
/// One drawing for the header (small) and the setup page (large); nothing else may restyle it.
class Wordmark extends StatelessWidget {
  const Wordmark({super.key, this.size = 34, this.onTap, this.subtitle});
  final double size; // height of the face frame; the type scales with it
  final VoidCallback? onTap;
  final String? subtitle;
  @override
  Widget build(BuildContext context) {
    final big = size * 0.72; // "VISION STUDIO"
    final small = size * 0.30; // "FFR"
    final mark = Row(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.center, children: [
      Container(
        width: size * 1.3,
        height: size,
        decoration: BoxDecoration(color: Guide.blue, border: Border.fromBorderSide(Guide.frame)),
        clipBehavior: Clip.hardEdge,
        child: Image.asset('assets/brand/rain_icon.png', fit: BoxFit.cover, filterQuality: FilterQuality.none, alignment: const Alignment(0, -0.2)),
      ),
      SizedBox(width: size * 0.32),
      Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(mainAxisSize: MainAxisSize.min, children: [
          Container(color: Guide.blue, padding: EdgeInsets.symmetric(horizontal: size * 0.16, vertical: size * 0.04), child: Text('FFR', style: Guide.band().copyWith(fontSize: small, height: 1.1, letterSpacing: small * 0.12))),
          SizedBox(width: size * 0.18),
          Text('BRAVE EXVIUS VISIONS FOR THE DEMO', style: Guide.label(Guide.inkSoft).copyWith(fontSize: small * 0.82, letterSpacing: small * 0.08)),
        ]),
        SizedBox(height: size * 0.05),
        Text('VISION STUDIO', style: Guide.h1().copyWith(fontSize: big, height: 1.0, letterSpacing: -big * 0.01)),
      ]),
    ]);
    final child = subtitle == null
        ? mark
        : Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [mark, SizedBox(height: size * 0.3), Text(subtitle!, style: Guide.small())]);
    return onTap == null ? child : MouseRegion(cursor: SystemMouseCursors.click, child: GestureDetector(onTap: onTap, child: child));
  }
}
