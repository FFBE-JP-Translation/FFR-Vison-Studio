import 'package:flutter/material.dart';

import 'theme.dart';

/// A full-width colour band with a condensed uppercase title: the guide's section header.
class Band extends StatelessWidget {
  const Band(this.title, {super.key, this.color, this.trailing, this.number});
  final String title;
  final Color? color;
  final Widget? trailing;
  final String? number;
  @override
  Widget build(BuildContext context) {
    final color = this.color ?? Guide.blue;
    return Container(
      color: color,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      child: Row(children: [
        if (number != null) ...[
          Container(
            width: 22, height: 22, alignment: Alignment.center,
            decoration: BoxDecoration(color: Guide.paper),
            child: Text(number!, style: Guide.band(color).copyWith(fontSize: 14)),
          ),
          const SizedBox(width: 10),
        ],
        Expanded(child: Text(title.toUpperCase(), style: Guide.band(Guide.onBandFor(color)))),
        if (trailing != null) trailing!,
      ]),
    );
  }
}

/// A black frame around a picture of the game (sprite, icon, screenshot), like a screenshot in a printed guide.
class Frame extends StatelessWidget {
  const Frame({super.key, required this.child, this.padding = 4, this.fill, this.width = 2});
  final Widget child;
  final double padding;
  final Color? fill;
  final double width;
  @override
  Widget build(BuildContext context) => Container(
        decoration: BoxDecoration(color: fill ?? Guide.paper2, border: Border.all(color: Guide.ink, width: width)),
        padding: EdgeInsets.all(padding),
        child: child,
      );
}

/// A boxed block of the page: hairline or ink border, paper fill.
class Box extends StatelessWidget {
  const Box({super.key, required this.child, this.ink = false, this.fill, this.padding = const EdgeInsets.all(12)});
  final Widget child;
  final bool ink;
  final Color? fill;
  final EdgeInsets padding;
  @override
  Widget build(BuildContext context) => Container(
        decoration: BoxDecoration(color: fill ?? Guide.paper, border: Border.all(color: ink ? Guide.ink : Guide.hairline, width: ink ? 2 : 1)),
        padding: padding,
        child: child,
      );
}

/// Primary action: a red band with white condensed caps and a black frame. `busy` shows progress in place.
class GoButton extends StatelessWidget {
  const GoButton(this.label, {super.key, this.onPressed, this.busy = false, this.color, this.icon});
  final String label;
  final VoidCallback? onPressed;
  final bool busy;
  final Color? color;
  final IconData? icon;
  @override
  Widget build(BuildContext context) {
    final enabled = onPressed != null && !busy;
    final solid = enabled || busy; // a working button stays solid; only a disabled one fades
    return AnimatedOpacity(
      duration: Guide.fast,
      opacity: solid ? 1 : 0.55,
      child: Material(
        color: solid ? (color ?? Guide.red) : Guide.paper3,
        shape: Border.fromBorderSide(Guide.frame),
        child: InkWell(
          onTap: enabled ? onPressed : null,
          hoverColor: Colors.black.withValues(alpha: 0.12),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              if (busy) ...[
                const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2.5, color: Guide.onBand)),
                const SizedBox(width: 10),
              ] else if (icon != null) ...[
                Icon(icon, size: 18, color: solid ? Guide.onBand : Guide.ink),
                const SizedBox(width: 8),
              ],
              Text(label.toUpperCase(), style: Guide.band(solid ? Guide.onBand : Guide.inkSoft).copyWith(fontSize: 17)),
            ]),
          ),
        ),
      ),
    );
  }
}

/// Secondary action: paper with an ink frame.
class GuideButton extends StatelessWidget {
  const GuideButton(this.label, {super.key, this.onPressed, this.icon, this.danger = false, this.small = false});
  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;
  final bool danger;
  final bool small;
  @override
  Widget build(BuildContext context) {
    final enabled = onPressed != null;
    final c = danger ? Guide.red : Guide.ink;
    return Opacity(
      opacity: enabled ? 1 : 0.5,
      child: Material(
        color: Guide.paper,
        shape: Border.fromBorderSide(BorderSide(color: c, width: 1.5)),
        child: InkWell(
          onTap: onPressed,
          hoverColor: Guide.paper2,
          child: Padding(
            padding: EdgeInsets.symmetric(horizontal: small ? 8 : 12, vertical: small ? 4 : 7),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              if (icon != null) ...[Icon(icon, size: 15, color: c), const SizedBox(width: 6)],
              Text(label, style: (small ? Guide.small(c) : Guide.strong(c))),
            ]),
          ),
        ),
      ),
    );
  }
}

/// A square swatch in an element's colour, next to a skill name.
class ElementSwatch extends StatelessWidget {
  const ElementSwatch(this.element, {super.key, this.size = 10});
  final String? element;
  final double size;
  @override
  Widget build(BuildContext context) => Container(
        width: size, height: size,
        decoration: BoxDecoration(color: Guide.elements[element ?? 'None'] ?? Guide.elements['None'], border: Border.all(color: Guide.ink, width: 1)),
      );
}

/// Key / value row of a stat box.
class StatRow extends StatelessWidget {
  const StatRow(this.label, this.value, {super.key, this.zebra = false, this.trailing});
  final String label;
  final String value;
  final bool zebra;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) => Container(
        color: zebra ? Guide.paper2 : Guide.paper,
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        child: Row(children: [
          Expanded(child: Text(label, style: Guide.text())),
          Text(value, style: Guide.num()),
          if (trailing != null) ...[const SizedBox(width: 8), trailing!],
        ]),
      );
}

/// The page tabs on the top edge of the right-hand page.
class PageTabs extends StatelessWidget {
  const PageTabs({super.key, required this.tabs, required this.index, required this.onSelect});
  final List<String> tabs;
  final int index;
  final ValueChanged<int> onSelect;
  @override
  Widget build(BuildContext context) {
    return Row(children: [
      for (var i = 0; i < tabs.length; i++) ...[
        Material(
          color: i == index ? Guide.ink : Guide.paper2,
          child: InkWell(
            onTap: () => onSelect(i),
            hoverColor: i == index ? Guide.ink : Guide.paper3,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              child: Text('${i + 1}  ${tabs[i].toUpperCase()}', style: Guide.band(i == index ? Guide.paper : Guide.inkSoft).copyWith(fontSize: 14)),
            ),
          ),
        ),
        const SizedBox(width: 3),
      ],
    ]);
  }
}

/// Status pill used in checklists: waiting / working / done / failed.
enum StepMark { waiting, working, done, failed }

class StatusCell extends StatelessWidget {
  const StatusCell(this.state, {super.key, this.text, this.progress});
  final StepMark state;
  final String? text;
  final double? progress;
  @override
  Widget build(BuildContext context) {
    switch (state) {
      case StepMark.waiting:
        return Text(text ?? 'waiting', style: Guide.small(Guide.inkFaint));
      case StepMark.working:
        return Row(mainAxisSize: MainAxisSize.min, children: [
          SizedBox(width: 120, child: LinearProgressIndicator(value: progress, minHeight: 6, color: Guide.blue, backgroundColor: Guide.paper3)),
          const SizedBox(width: 10),
          Text(text ?? '', style: Guide.small()),
        ]);
      case StepMark.done:
        return Row(mainAxisSize: MainAxisSize.min, children: [Icon(Icons.check, size: 16, color: Guide.green), const SizedBox(width: 6), Text(text ?? 'done', style: Guide.small(Guide.green))]);
      case StepMark.failed:
        return Row(mainAxisSize: MainAxisSize.min, children: [Icon(Icons.close, size: 16, color: Guide.red), const SizedBox(width: 6), Flexible(child: Text(text ?? 'failed', style: Guide.small(Guide.red)))]);
    }
  }
}

/// Pixel art drawn without smoothing, scaled up, on a framed paper-grey field.
class PixelImage extends StatelessWidget {
  const PixelImage(this.url, {super.key, this.width = 96, this.height = 96, this.scale = 1});
  final String url;
  final double width;
  final double height;
  final double scale;
  @override
  Widget build(BuildContext context) => Image.network(
        url,
        width: width, height: height,
        fit: BoxFit.contain,
        filterQuality: FilterQuality.none,
        gaplessPlayback: true,
        errorBuilder: (a, b, c) => Container(width: width, height: height, color: Guide.paper3, alignment: Alignment.center, child: Text('no image', style: Guide.small(Guide.inkFaint))),
      );
}

/// The two-page spread: a paper page floating on the desk.
class Paper extends StatelessWidget {
  const Paper({super.key, required this.child, this.width});
  final Widget child;
  final double? width;
  @override
  Widget build(BuildContext context) => Container(
        width: width,
        decoration: BoxDecoration(
          color: Guide.paper,
          boxShadow: const [BoxShadow(color: Color(0x40000000), offset: Offset(0, 6), blurRadius: 24)],
        ),
        child: child,
      );
}
