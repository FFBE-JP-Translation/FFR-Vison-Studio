import 'package:flutter/material.dart';

/// The strategy-guide spread. Glossy white page on a warm grey desk, black frames around anything that is a
/// picture of the game, saturated colour bands as section headers, condensed uppercase headings, tabular stats.
/// Two printings of the same guide: the day edition (white paper, black ink) and the night edition (charcoal
/// paper, off-white ink). Bands, frames and the GO button keep their colours; only paper and ink swap.
class _Palette {
  const _Palette({required this.desk, required this.paper, required this.paper2, required this.paper3, required this.ink, required this.inkSoft, required this.inkFaint, required this.hairline,
      required this.blue, required this.gold, required this.red, required this.green, required this.purple, required this.consoleBg, required this.consoleFg, required this.warn});
  final Color desk, paper, paper2, paper3, ink, inkSoft, inkFaint, hairline, blue, gold, red, green, purple, consoleBg, consoleFg, warn;
}

const _day = _Palette(
  desk: Color(0xFFCFCBC2), paper: Color(0xFFFFFFFF), paper2: Color(0xFFF4F2ED), paper3: Color(0xFFE9E6DE),
  ink: Color(0xFF121212), inkSoft: Color(0xFF4B4B4B), inkFaint: Color(0xFF8A877F), hairline: Color(0xFFC9C5BB),
  blue: Color(0xFF1F4FD0), gold: Color(0xFFD9A21B), red: Color(0xFFD42B2B), green: Color(0xFF178A45), purple: Color(0xFF6B3FB0),
  consoleBg: Color(0xFF121212), consoleFg: Color(0xFFF4F2ED), warn: Color(0xFFFFF4DE),
);
const _night = _Palette(
  desk: Color(0xFF14151A), paper: Color(0xFF1F2126), paper2: Color(0xFF272A31), paper3: Color(0xFF323640),
  ink: Color(0xFFF1EFE8), inkSoft: Color(0xFFB9B5AC), inkFaint: Color(0xFF7E7A72), hairline: Color(0xFF3C4049),
  blue: Color(0xFF3D6CE8), gold: Color(0xFFE2B134), red: Color(0xFFE0463F), green: Color(0xFF2DAA60), purple: Color(0xFF8C61CF),
  consoleBg: Color(0xFF0E0F12), consoleFg: Color(0xFFCFCBC2), warn: Color(0xFF3A3220),
);

class Guide {
  /// Flip this before rebuilding the tree (AppState.setDark does); every colour below follows.
  static bool dark = false;
  static _Palette get _p => dark ? _night : _day;

  // materials
  static Color get desk => _p.desk;
  static Color get paper => _p.paper;
  static Color get paper2 => _p.paper2;
  static Color get paper3 => _p.paper3;
  static Color get ink => _p.ink;
  static Color get inkSoft => _p.inkSoft;
  static Color get inkFaint => _p.inkFaint;
  static Color get hairline => _p.hairline;
  static Color get consoleBg => _p.consoleBg;
  static Color get consoleFg => _p.consoleFg;
  static Color get warn => _p.warn;
  // bands (one job each)
  static Color get blue => _p.blue; // sections, selection, links
  static Color get gold => _p.gold; // Resonance, rarity
  static Color get red => _p.red; // the GO action, warnings, removal
  static Color get green => _p.green; // success
  static Color get purple => _p.purple; // magic
  /// Text on a band or on the GO button: always white, whatever the paper is.
  static const onBand = Color(0xFFFFFFFF);
  /// Text on a band of colour `c`: white on a saturated band, ink-black on a light one (the night edition's ink band).
  static Color onBandFor(Color c) => c.computeLuminance() > 0.6 ? const Color(0xFF121212) : onBand;

  static const elements = <String, Color>{
    'Fire': Color(0xFFE4572E), 'Ice': Color(0xFF4FB3E8), 'Wind': Color(0xFF4CAF50), 'Earth': Color(0xFFA0743A),
    'Thunder': Color(0xFFF2C230), 'Water': Color(0xFF2E77D0), 'Light': Color(0xFFE8C96A), 'Dark': Color(0xFF7A3FB0), 'None': Color(0xFF9E9E9E),
  };

  static BorderSide get frame => BorderSide(color: ink, width: 2);
  static BorderSide get thin => BorderSide(color: hairline, width: 1);
  static const fast = Duration(milliseconds: 180);

  // type: Barlow for the page, Barlow Condensed for headings and bands
  static const display = 'BarlowCondensed';
  static const body = 'Barlow';

  static TextStyle h1([Color? c]) => TextStyle(fontFamily: display, fontSize: 34, height: 1.0, fontWeight: FontWeight.w700, letterSpacing: 0.4, color: c ?? ink);
  static TextStyle h2([Color? c]) => TextStyle(fontFamily: display, fontSize: 24, height: 1.05, fontWeight: FontWeight.w700, letterSpacing: 0.4, color: c ?? ink);
  static TextStyle band([Color? c]) => TextStyle(fontFamily: display, fontSize: 15, height: 1.0, fontWeight: FontWeight.w700, letterSpacing: 1.2, color: c ?? onBand);
  static TextStyle label([Color? c]) => TextStyle(fontFamily: display, fontSize: 13, height: 1.0, fontWeight: FontWeight.w600, letterSpacing: 1.0, color: c ?? inkSoft);
  static TextStyle text([Color? c]) => TextStyle(fontFamily: body, fontSize: 14, height: 1.4, color: c ?? ink);
  static TextStyle strong([Color? c]) => TextStyle(fontFamily: body, fontSize: 14, height: 1.4, fontWeight: FontWeight.w600, color: c ?? ink);
  static TextStyle small([Color? c]) => TextStyle(fontFamily: body, fontSize: 12.5, height: 1.35, color: c ?? inkSoft);
  static TextStyle num([Color? c]) => TextStyle(fontFamily: body, fontSize: 14, height: 1.2, fontWeight: FontWeight.w600, color: c ?? ink, fontFeatures: const [FontFeature.tabularFigures()]);
  static TextStyle mono([Color? c]) => TextStyle(fontFamily: 'Consolas', fontSize: 12, height: 1.35, color: c ?? ink);

  static ThemeData theme() {
    final base = ThemeData(useMaterial3: true, brightness: dark ? Brightness.dark : Brightness.light, fontFamily: body);
    return base.copyWith(
      scaffoldBackgroundColor: desk,
      colorScheme: (dark ? const ColorScheme.dark() : const ColorScheme.light()).copyWith(primary: blue, secondary: gold, error: red, surface: paper, onSurface: ink),
      textTheme: base.textTheme.apply(bodyColor: ink, displayColor: ink, fontFamily: body),
      splashFactory: NoSplash.splashFactory,
      dividerColor: hairline,
      canvasColor: paper,
      dialogTheme: DialogThemeData(backgroundColor: paper, shape: Border.fromBorderSide(frame)),
      popupMenuTheme: PopupMenuThemeData(color: paper, shape: Border.fromBorderSide(BorderSide(color: ink, width: 1.5)), textStyle: text()),
      dropdownMenuTheme: DropdownMenuThemeData(textStyle: text()),
      tooltipTheme: TooltipThemeData(
        decoration: BoxDecoration(color: dark ? paper3 : ink),
        textStyle: small(dark ? ink : paper),
        waitDuration: const Duration(milliseconds: 400),
      ),
      scrollbarTheme: ScrollbarThemeData(thumbColor: WidgetStateProperty.all(inkFaint), thickness: WidgetStateProperty.all(6), radius: Radius.zero),
      inputDecorationTheme: InputDecorationTheme(
        isDense: true,
        filled: true,
        fillColor: paper,
        contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
        border: OutlineInputBorder(borderRadius: BorderRadius.zero, borderSide: BorderSide(color: ink, width: 1.5)),
        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.zero, borderSide: BorderSide(color: ink, width: 1.5)),
        focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.zero, borderSide: BorderSide(color: blue, width: 2)),
        hintStyle: small(inkFaint),
        labelStyle: small(),
      ),
      sliderTheme: SliderThemeData(activeTrackColor: ink, inactiveTrackColor: hairline, thumbColor: ink, overlayColor: blue.withValues(alpha: 0.1), trackHeight: 3),
      checkboxTheme: CheckboxThemeData(shape: const RoundedRectangleBorder(), side: BorderSide(color: ink, width: 1.5), fillColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? ink : paper), checkColor: WidgetStateProperty.all(paper)),
      radioTheme: RadioThemeData(fillColor: WidgetStateProperty.all(ink)),
    );
  }
}
