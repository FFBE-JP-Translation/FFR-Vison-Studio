import 'package:flutter/material.dart';

import 'theme.dart';

/// A row of framed options, the chosen one inked. Replaces radio buttons in the guide.
class Choice<T> extends StatelessWidget {
  const Choice({super.key, required this.options, required this.value, required this.onChanged});
  final List<(T, String)> options;
  final T value;
  final ValueChanged<T> onChanged;
  @override
  Widget build(BuildContext context) => Wrap(spacing: 6, runSpacing: 6, children: [
        for (final (v, label) in options)
          Material(
            color: v == value ? Guide.ink : Guide.paper,
            shape: Border.fromBorderSide(BorderSide(color: v == value ? Guide.ink : Guide.hairline, width: 1.5)),
            child: InkWell(
              onTap: () => onChanged(v),
              child: Padding(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6), child: Text(label, style: Guide.small(v == value ? Guide.paper : Guide.ink))),
            ),
          ),
      ]);
}
