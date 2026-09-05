import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/app_state.dart';
import 'theme.dart';

/// Day / night edition switch. Two small framed cells; the active one is inked.
class ThemeToggle extends StatelessWidget {
  const ThemeToggle({super.key});
  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    Widget cell(IconData icon, bool on, VoidCallback tap, String tip) => Tooltip(
          message: tip,
          child: Material(
            color: on ? Guide.ink : Guide.paper,
            child: InkWell(onTap: tap, child: Padding(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5), child: Icon(icon, size: 15, color: on ? Guide.paper : Guide.inkSoft))),
          ),
        );
    return Container(
      decoration: BoxDecoration(border: Border.all(color: Guide.ink, width: 1.5)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        cell(Icons.light_mode_outlined, !app.dark, () => app.setDark(false), 'Day edition'),
        Container(width: 1.5, height: 26, color: Guide.ink),
        cell(Icons.dark_mode_outlined, app.dark, () => app.setDark(true), 'Night edition'),
      ]),
    );
  }
}
