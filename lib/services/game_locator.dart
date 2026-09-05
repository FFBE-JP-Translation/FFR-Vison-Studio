import 'dart:io';

import 'package:path/path.dart' as p;
import 'package:win32_registry/win32_registry.dart';

/// Finds FINAL FANTASY RESONANCE DEMO on this machine.
///
/// Order: Steam's registry entry and every library folder it lists, then a scan of every drive's
/// `steamapps\common` and a few common install roots, then nothing (the UI asks for a folder).
class GameLocator {
  static const dirName = 'FINAL FANTASY RESONANCE DEMO';
  static const marker = r'FFRS\Content\Paks\FFRS-Windows.utoc';

  static bool isGameRoot(String? dir) =>
      dir != null && dir.isNotEmpty && File(p.join(dir, marker)).existsSync();

  static List<String> steamLibraries() {
    final libs = <String>[];
    for (final (hive, key, value) in [
      (RegistryHive.currentUser, r'Software\Valve\Steam', 'SteamPath'),
      (RegistryHive.localMachine, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
    ]) {
      try {
        final k = Registry.openPath(hive, path: key);
        final v = k.getStringValue(value);
        k.close();
        if (v != null && Directory(v).existsSync()) libs.add(p.normalize(v));
      } catch (_) {}
    }
    final out = [...libs];
    for (final base in libs) {
      final vdf = File(p.join(base, 'steamapps', 'libraryfolders.vdf'));
      if (!vdf.existsSync()) continue;
      for (final line in vdf.readAsLinesSync()) {
        final t = line.trim();
        if (!t.startsWith('"path"')) continue;
        final parts = t.split('"');
        if (parts.length < 4) continue;
        final path = p.normalize(parts[3].replaceAll(r'\\', r'\'));
        if (Directory(path).existsSync() && !out.contains(path)) out.add(path);
      }
    }
    return out;
  }

  /// The game folder, or null.
  static Future<String?> detect() async {
    for (final lib in steamLibraries()) {
      final c = p.join(lib, 'steamapps', 'common', dirName);
      if (isGameRoot(c)) return c;
    }
    // Every drive: X:\SteamLibrary, X:\Steam, X:\Games\Steam, X:\Program Files (x86)\Steam ...
    for (final letter in 'CDEFGHIJKLMNOPQRSTUVWXYZ'.split('')) {
      final drive = '$letter:\\';
      if (!Directory(drive).existsSync()) continue;
      for (final sub in [
        'SteamLibrary', 'Steam', r'Games\Steam', r'Program Files (x86)\Steam', r'Program Files\Steam', 'Games', ''
      ]) {
        final c = p.join(drive, sub, 'steamapps', 'common', dirName);
        if (isGameRoot(c)) return c;
      }
    }
    return null;
  }

  static bool isRunning() {
    try {
      final r = Process.runSync('tasklist', ['/FI', 'IMAGENAME eq FFRS-Win64-Shipping.exe']);
      return (r.stdout as String).toLowerCase().contains('ffrs-win64-shipping.exe');
    } catch (_) {
      return false;
    }
  }
}
