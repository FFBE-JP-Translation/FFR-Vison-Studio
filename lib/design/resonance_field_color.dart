import 'package:flutter/material.dart';

import 'theme.dart';

/// Saves complete colours only; an unfinished hex edit stays local to the field.
class ResonanceFieldColor extends StatefulWidget {
  const ResonanceFieldColor({
    super.key,
    required this.value,
    required this.onChanged,
  });

  final String value;
  final ValueChanged<String> onChanged;

  static const defaultColor = '#FFAA33';
  static const presets = {
    'Orange': defaultColor,
    'Blue': '#5588FF',
    'Violet': '#AA66EE',
    'Green': '#55CC88',
    'Red': '#EE5555',
  };

  @override
  State<ResonanceFieldColor> createState() => _ResonanceFieldColorState();
}

class _ResonanceFieldColorState extends State<ResonanceFieldColor> {
  late final TextEditingController _hex = TextEditingController(
    text: widget.value,
  );
  static final _valid = RegExp(r'^#[0-9A-Fa-f]{6}$');

  @override
  void didUpdateWidget(covariant ResonanceFieldColor oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.value != widget.value &&
        _hex.text.toUpperCase() != widget.value.toUpperCase()) {
      _hex.text = widget.value;
    }
  }

  @override
  void dispose() {
    _hex.dispose();
    super.dispose();
  }

  void _choose(String value) {
    setState(() => _hex.text = value);
    widget.onChanged(value);
  }

  @override
  Widget build(BuildContext context) {
    final valid = _valid.hasMatch(_hex.text);
    final saved = _valid.hasMatch(widget.value)
        ? widget.value.toUpperCase()
        : ResonanceFieldColor.defaultColor;
    final display = valid ? _hex.text : saved;
    final color = Color(int.parse('FF${display.substring(1)}', radix: 16));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            for (final preset in ResonanceFieldColor.presets.entries)
              ChoiceChip(
                label: Text(preset.key),
                showCheckmark: false,
                selectedColor: Guide.ink,
                backgroundColor: Guide.paper,
                labelStyle: Guide.small(
                  valid && display.toUpperCase() == preset.value
                      ? Guide.paper
                      : Guide.ink,
                ),
                shape: const RoundedRectangleBorder(),
                side: BorderSide(color: Guide.inkSoft, width: 1.5),
                avatar: Container(
                  width: 16,
                  height: 16,
                  decoration: BoxDecoration(
                    color: Color(
                      int.parse('FF${preset.value.substring(1)}', radix: 16),
                    ),
                    border: Border.all(color: Guide.inkSoft),
                  ),
                ),
                selected: valid && display.toUpperCase() == preset.value,
                onSelected: (_) => _choose(preset.value),
              ),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Semantics(
              label: 'Field hue $display',
              child: Container(
                width: 44,
                height: 44,
                margin: const EdgeInsets.only(right: 10),
                decoration: BoxDecoration(
                  color: color,
                  border: Border.all(color: Guide.ink, width: 2),
                ),
              ),
            ),
            Expanded(
              child: TextField(
                controller: _hex,
                decoration: InputDecoration(
                  labelText: 'Custom colour',
                  hintText: '#FFAA33',
                  errorText: valid
                      ? null
                      : 'Enter # and six hex digits, e.g. #FFAA33.',
                  errorMaxLines: 2,
                ),
                onChanged: (value) {
                  setState(() {});
                  if (_valid.hasMatch(value)) {
                    widget.onChanged(value.toUpperCase());
                  }
                },
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Text(
          'Tints the battle during this vision’s limit burst. Lighting affects the final colour. Orange is the default.',
          style: Guide.small(),
        ),
      ],
    );
  }
}
