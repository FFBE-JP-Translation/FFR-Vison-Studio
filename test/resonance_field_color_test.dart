import 'package:ffr_vision_studio/design/resonance_field_color.dart';
import 'package:ffr_vision_studio/design/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('attack elements blend once each and neutral uses grey', () {
    expect(ResonanceFieldColor.forElements([]), '#808080');
    expect(ResonanceFieldColor.forElements(['None']), '#808080');
    expect(ResonanceFieldColor.forElements(['Ice', 'Thunder']), '#80FF80');
    expect(ResonanceFieldColor.forElements(['Ice', 'Ice', 'Thunder']), '#80FF80');
    expect(ResonanceFieldColor.forElements(['Water']), '#5588FF');
  });
  testWidgets(
    'incomplete edits do not replace the saved colour; presets and custom hex do',
    (tester) async {
      var saved = ResonanceFieldColor.defaultColor;
      await tester.pumpWidget(
        MaterialApp(
          theme: Guide.theme(),
          home: Scaffold(
            body: StatefulBuilder(
              builder: (context, setState) => SizedBox(
                width: 300,
                child: ResonanceFieldColor(
                  value: saved,
                  onChanged: (value) => setState(() => saved = value),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.enterText(find.byType(TextField), '#AA');
      await tester.pump();
      expect(saved, ResonanceFieldColor.defaultColor);
      expect(
        find.text('Enter # and six hex digits, e.g. #FFAA33.'),
        findsOneWidget,
      );
      await tester.enterText(find.byType(TextField), '#aa44cc');
      await tester.pump();
      expect(saved, '#AA44CC');
      await tester.tap(find.text('Blue'));
      await tester.pump();
      expect(saved, '#5588FF');
      expect(find.text('#5588FF'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('switching visions replaces the field value', (tester) async {
    Widget build(String value) => MaterialApp(
      theme: Guide.theme(),
      home: Scaffold(
        body: ResonanceFieldColor(value: value, onChanged: (_) {}),
      ),
    );
    await tester.pumpWidget(build('#FFAA33'));
    await tester.enterText(find.byType(TextField), '#AA');
    await tester.pumpWidget(build('#55CC88'));
    expect(find.text('#55CC88'), findsOneWidget);
  });
}
