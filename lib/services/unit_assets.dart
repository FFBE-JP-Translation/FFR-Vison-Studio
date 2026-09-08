import 'dart:io';
import 'package:path/path.dart' as p;
import 'downloader.dart';

/// The idle preview can be displayed while the full .ffr unit is downloading.
class UnitAssets {
  UnitAssets({required this.downloader, required this.dataDir, required this.downloadDir});
  final Downloader downloader;
  final String dataDir;
  final String downloadDir;
  final Map<String, Future<void>> _pending = {};

  Future<File?> idle(String form, Map<String, dynamic> info) async {
    if (!RegExp(r'^\d+$').hasMatch(form)) throw const FormatException('Invalid unit form');
    final preview = info['idle'] as Map?;
    if (preview == null) return null;
    return downloader.download(preview['url'] as String, p.join(downloadDir, 'idle-$form.webp'), sha256: preview['sha256'] as String?);
  }

  Future<void> ensure(String form, Map<String, dynamic> info, {void Function(String)? onStep, Future<void> Function()? onIndexed}) =>
      _pending.putIfAbsent(form, () => _ensure(form, info, onStep, onIndexed).whenComplete(() { _pending.remove(form); }));

  Future<void> _ensure(String form, Map<String, dynamic> info, void Function(String)? onStep, Future<void> Function()? onIndexed) async {
    if (!RegExp(r'^\d+$').hasMatch(form)) throw const FormatException('Invalid unit form');
    final modern = info['format'] == 'ffr-unit-1';
    final spriteDir = p.join(dataDir, 'sprites', form);
    final marker = File(p.join(spriteDir, '.complete'));
    final expected = info['sha256'] as String?;
    bool exists(String rel) => File(p.join(spriteDir, rel)).existsSync();
    final sheets = exists('unit_anime_$form.png') && exists('unit_cgg_$form.csv');
    final marked = marker.existsSync() && marker.readAsStringSync() == expected;
    final metadata = !modern || ['unit_records/${info['unitId']}.json', 'lb_profiles/$form.json', 'audio/lb/$form.json']
        .every((rel) => File(p.join(dataDir, rel)).existsSync());
    final recordings = ((info['sounds'] as List?) ?? []).every((s) => File(p.join(dataDir, 'audio', 'samples', '${s['sha256']}.hca')).existsSync());
    if (sheets && metadata && recordings && ((!modern && expected == null) || marked)) return;
    onStep?.call('Downloading unit data');
    final f = await downloader.download(info['url'] as String, p.join(downloadDir, '$form.${modern ? 'ffr' : 'zip'}'), sha256: expected);
    final staging = Directory(p.join(downloadDir, 'unpack-$form'));
    if (!p.isWithin(p.absolute(downloadDir), p.absolute(staging.path))) throw const FormatException('Invalid unpack directory');
    if (staging.existsSync()) staging.deleteSync(recursive: true);
    await Downloader.unzip(f, staging.path);
    final extractedSprites = modern ? p.join(staging.path, 'sprites', form) : staging.path;
    for (final name in ['unit_anime_$form.png', 'unit_cgg_$form.csv']) {
      if (!File(p.join(extractedSprites, name)).existsSync()) throw StateError('The unit pack for $form is incomplete');
    }
    if (modern) {
      for (final rel in ['unit_records/${info['unitId']}.json', 'lb_profiles/$form.json', 'audio/lb/$form.json']) {
        if (!File(p.join(staging.path, rel)).existsSync()) throw StateError('The unit pack is missing $rel');
      }
    }
    final into = modern ? dataDir : spriteDir;
    for (final file in staging.listSync(recursive: true).whereType<File>()) {
      final dest = File(p.join(into, p.relative(file.path, from: staging.path)));
      dest.parent.createSync(recursive: true);
      file.copySync(dest.path);
    }
    // Recordings are shared by checksum, even when multiple LBs use them.
    for (final sound in (info['sounds'] as List?) ?? []) {
      onStep?.call('Downloading limit burst sounds');
      final hash = sound['sha256'] as String;
      if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(hash)) throw const FormatException('Invalid sound checksum');
      await downloader.download(sound['url'] as String, p.join(dataDir, 'audio', 'samples', '$hash.hca'), sha256: hash);
    }
    await onIndexed?.call();
    marker.writeAsStringSync(expected ?? 'legacy');
    staging.deleteSync(recursive: true);
  }
}
