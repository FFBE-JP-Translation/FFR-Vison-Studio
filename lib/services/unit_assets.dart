import 'dart:io';
import 'package:path/path.dart' as p;
import 'downloader.dart';

/// Browsing uses the startup idle pack; full unit data is fetched on Add unit.
class UnitAssets {
  UnitAssets({required this.downloader, required this.dataDir, required this.downloadDir, required this.idleDir});
  final Downloader downloader;
  final String dataDir;
  final String downloadDir;
  final String idleDir;
  final Map<String, Future<void>> _pending = {};

  File? idle(String form) {
    if (!RegExp(r'^\d+$').hasMatch(form)) throw const FormatException('Invalid unit form');
    final file = File(p.join(idleDir, '$form.webp'));
    return file.existsSync() ? file : null;
  }

  Future<void> ensure(String form, Map<String, dynamic> info, {void Function(String)? onStep, void Function(int, int)? onProgress, Future<void> Function()? onIndexed}) =>
      _pending.putIfAbsent(form, () => _ensure(form, info, onStep, onProgress, onIndexed).whenComplete(() { _pending.remove(form); }));

  Future<void> _ensure(String form, Map<String, dynamic> info, void Function(String)? onStep, void Function(int, int)? onProgress, Future<void> Function()? onIndexed) async {
    if (!RegExp(r'^\d+$').hasMatch(form)) throw const FormatException('Invalid unit form');
    final modern = info['format'] == 'ffr-unit-1';
    final requiredMetadata = ['unit_records/${info['unitId']}.json', 'lb_profiles/$form.json', 'audio/lb/$form.json', if (info['nativeKit'] != null) 'native_kits/$form.json'];
    final spriteDir = p.join(dataDir, 'sprites', form);
    final marker = File(p.join(spriteDir, '.complete'));
    final expected = info['sha256'] as String?;
    bool exists(String rel) => File(p.join(spriteDir, rel)).existsSync();
    final sheets = exists('unit_anime_$form.png') && exists('unit_cgg_$form.csv');
    final marked = marker.existsSync() && marker.readAsStringSync() == expected;
    final metadata = !modern || requiredMetadata
        .every((rel) => File(p.join(dataDir, rel)).existsSync());
    final recordings = ((info['sounds'] as List?) ?? []).every((s) => File(p.join(dataDir, 'audio', 'samples', '${s['sha256']}.hca')).existsSync());
    if (sheets && metadata && recordings && ((!modern && expected == null) || marked)) return;
    onStep?.call('Downloading unit data');
    final f = await downloader.download(info['url'] as String, p.join(downloadDir, '$form.${modern ? 'ffr' : 'zip'}'), sha256: expected, onProgress: onProgress);
    onStep?.call('Unpacking unit data');
    final staging = Directory(p.join(downloadDir, 'unpack-$form'));
    if (!p.isWithin(p.absolute(downloadDir), p.absolute(staging.path))) throw const FormatException('Invalid unpack directory');
    if (staging.existsSync()) staging.deleteSync(recursive: true);
    await Downloader.unzip(f, staging.path);
    final extractedSprites = modern ? p.join(staging.path, 'sprites', form) : staging.path;
    for (final name in ['unit_anime_$form.png', 'unit_cgg_$form.csv']) {
      if (!File(p.join(extractedSprites, name)).existsSync()) throw StateError('The unit pack for $form is incomplete');
    }
    if (modern) {
      for (final rel in requiredMetadata) {
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
    final sounds = (info['sounds'] as List?) ?? [];
    for (final (i, sound) in sounds.indexed) {
      onStep?.call('Downloading limit burst sounds (${i + 1}/${sounds.length})');
      final hash = sound['sha256'] as String;
      if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(hash)) throw const FormatException('Invalid sound checksum');
      await downloader.download(sound['url'] as String, p.join(dataDir, 'audio', 'samples', '$hash.hca'), sha256: hash, onProgress: onProgress);
    }
    onStep?.call('Preparing unit');
    await onIndexed?.call();
    marker.writeAsStringSync(expected ?? 'legacy');
    staging.deleteSync(recursive: true);
  }
}
