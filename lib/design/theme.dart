import 'package:flutter/material.dart';

/// The strategy-guide spread. Glossy white page on a warm grey desk, black frames around anything that is a
/// picture of the game, saturated colour bands as section headers, condensed uppercase headings, tabular stats.
class Guide {
  // materials
  static const desk = Color(0xFFCFCBC2);
  static const paper = Color(0xFFFFFFFF);
  static const paper2 = Color(0xFFF4F2ED);
  static const paper3 = Color(0xFFE9E6DE);
  static const ink = Color(0xFF121212);
  static const inkSoft = Color(0xFF4B4B4B);
  static const inkFaint = Color(0xFF8A877F);
  static const hairline = Color(0xFFC9C5BB);
  // bands (one job each)
  static const blue = Color(0xFF1F4FD0); // sections, selection, links
  static const gold = Color(0xFFD9A21B); // Resonance, rarity
  static const red = Color(0xFFD42B2B); // the GO action, warnings, removal
  static const green = Color(0xFF178A45); // success
  static const purple = Color(0xFF6B3FB0); // magic

  static const elements = <String, Color>{
    'Fire': Color(0xFFE4572E), 'Ice': Color(0xFF4FB3E8), 'Wind': Color(0xFF4CAF50), 'Earth': Color(0xFFA0743A),
    'Thunder': Color(0xFFF2C230), 'Water': Color(0xFF2E77D0), 'Light': Color(0xFFE8C96A), 'Dark': Color(0xFF7A3FB0), 'None': Color(0xFF9E9E9E),
  };

  static const frame = BorderSide(color: ink, width: 2);
  static const thin = BorderSide(color: hairline, width: 1);
  static const fast = Duration(milliseconds: 180);

  // type: Barlow for the page, Barlow Condensed for headings and bands
  static const display = 'BarlowCondensed';
  static const body = 'Barlow';

  static TextStyle h1([Color c = ink]) => TextStyle(fontFamily: display, fontSize: 34, height: 1.0, fontWeight: FontWeight.w700, letterSpacing: 0.4, color: c);
  static TextStyle h2([Color c = ink]) => TextStyle(fontFamily: display, fontSize: 24, height: 1.05, fontWeight: FontWeight.w700, letterSpacing: 0.4, color: c);
  static TextStyle band([Color c = paper]) => TextStyle(fontFamily: display, fontSize: 15, height: 1.0, fontWeight: FontWeight.w700, letterSpacing: 1.2, color: c);
  static TextStyle label([Color c = inkSoft]) => TextStyle(fontFamily: display, fontSize: 13, height: 1.0, fontWeight: FontWeight.w600, letterSpacing: 1.0, color: c);
  static TextStyle text([Color c = ink]) => TextStyle(fontFamily: body, fontSize: 14, height: 1.4, color: c);
  static TextStyle strong([Color c = ink]) => TextStyle(fontFamily: body, fontSize: 14, height: 1.4, fontWeight: FontWeight.w600, color: c);
  static TextStyle small([Color c = inkSoft]) => TextStyle(fontFamily: body, fontSize: 12.5, height: 1.35, color: c);
  static TextStyle num([Color c = ink]) => TextStyle(fontFamily: body, fontSize: 14, height: 1.2, fontWeight: FontWeight.w600, color: c, fontFeatures: const [FontFeature.tabularFigures()]);
  static TextStyle mono([Color c = ink]) => TextStyle(fontFamily: 'Consolas', fontSize: 12, height: 1.35, color: c);

  static ThemeData theme() {
    final base = ThemeData(useMaterial3: true, brightness: Brightness.light, fontFamily: body);
    return base.copyWith(
      scaffoldBackgroundColor: desk,
      colorScheme: const ColorScheme.light(primary: blue, secondary: gold, error: red, surface: paper, onSurface: ink),
      textTheme: base.textTheme.apply(bodyColor: ink, displayColor: ink, fontFamily: body),
      splashFactory: NoSplash.splashFactory,
      dividerColor: hairline,
      tooltipTheme: TooltipThemeData(
        decoration: const BoxDecoration(color: ink),
        textStyle: small(paper),
        waitDuration: const Duration(milliseconds: 400),
      ),
      scrollbarTheme: ScrollbarThemeData(thumbColor: WidgetStateProperty.all(inkFaint), thickness: WidgetStateProperty.all(6), radius: Radius.zero),
      inputDecorationTheme: InputDecorationTheme(
        isDense: true,
        filled: true,
        fillColor: paper,
        contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
        border: const OutlineInputBorder(borderRadius: BorderRadius.zero, borderSide: BorderSide(color: ink, width: 1.5)),
        enabledBorder: const OutlineInputBorder(borderRadius: BorderRadius.zero, borderSide: BorderSide(color: ink, width: 1.5)),
        focusedBorder: const OutlineInputBorder(borderRadius: BorderRadius.zero, borderSide: BorderSide(color: blue, width: 2)),
        hintStyle: small(inkFaint),
        labelStyle: small(),
      ),
      sliderTheme: const SliderThemeData(activeTrackColor: ink, inactiveTrackColor: hairline, thumbColor: ink, overlayColor: Color(0x1A1F4FD0), trackHeight: 3),
      checkboxTheme: CheckboxThemeData(shape: const RoundedRectangleBorder(), side: const BorderSide(color: ink, width: 1.5), fillColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? ink : paper), checkColor: WidgetStateProperty.all(paper)),
      radioTheme: RadioThemeData(fillColor: WidgetStateProperty.all(ink)),
    );
  }
}
