import 'package:ffr_vision_studio/design/anim_viewer.dart';
import 'package:ffr_vision_studio/state/catalog_helpers.dart';
import 'package:ffr_vision_studio/version.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('saved CG resonances use the own LB while preserving custom settings', () {
    for (final id in cgResonanceIds) {
      final unit = <String, dynamic>{'ffbe': {'id': '123'}, 'lb_custom': {
        'from': 440110, 'visuals': id, 'presentation': 'template', 'field_color': '#123456'}};
      final upgraded = migrateCgResonance(unit);
      expect(upgraded['lb_custom']['presentation'], 'ffbe');
      expect(upgraded['lb_custom']['field_color'], '#123456');
      expect(unit['lb_custom']['presentation'], 'template');
      expect(identical(migrateCgResonance(upgraded), upgraded), isTrue);
    }
    final safe = <String, dynamic>{'ffbe': {'id': '123'}, 'lb_custom': {
      'from': 440110, 'visuals': 414090, 'presentation': 'template'}};
    expect(identical(migrateCgResonance(safe), safe), isTrue);
  });

  test('rarity labels: stars for numbers, NV and NV+ as written', () {
    expect(rarityLabel(5), '5★');
    expect(rarityLabel('7'), '7★');
    expect(rarityLabel('NV'), 'NV');
    expect(rarityLabel('NV+'), 'NV+');
    expect(rarityLabel(null), '-');
    expect(rarityRange(5, 7), '5★ → 7★');
    expect(rarityRange('NV', 'NV+'), 'NV → NV+');
    expect(rarityRange('NV', 'NV'), 'NV');
  });

  test('animation order puts idle first and the limit burst before victory', () {
    final ordered = orderAnims(['win', 'limitatk', 'zzz_custom', 'idle', 'atk']);
    expect(ordered, ['idle', 'atk', 'limitatk', 'win', 'zzz_custom']);
    expect(animName('limitatk'), 'Limit burst');
    expect(animName('magic_atk'), 'Magic');
    expect(animName('unknown_thing'), 'unknown_thing');
  });

  test('describe reads a damaging row', () {
    final row = {'dmgType': 'Magic', 'target': 'Random', 'relation': 'Enemies', 'element': 'Ice', 'hits': 5, 'mag': 3.0, 'breakDmg': 0, 'name': 'Hibernal Fury'};
    expect(describe(row), 'Deal Ice magic damage to random enemies (5 hits).');
    expect(describe(row, {'element': 'None', 'TargetType': 'Single'}), 'Deal magic damage to one enemy (5 hits).');
  });

  test('version tags compare numerically, part by part', () {
    expect(compareTags('1.0.0.4', '1.0.0.3') > 0, true);
    expect(compareTags('1.0.0.10', '1.0.0.9') > 0, true);
    expect(compareTags('1.0.0', '1.0.0.0'), 0);
    expect(compareTags('0.9.9.99', '1.0.0.0') < 0, true);
  });
}
