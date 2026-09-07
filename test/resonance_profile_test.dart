import 'package:ffr_vision_studio/design/theme.dart';
import 'package:ffr_vision_studio/screens/steps/resonance_step.dart';
import 'package:ffr_vision_studio/services/api.dart';
import 'package:ffr_vision_studio/state/app_state.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

class ProfileApi extends Api {
  ProfileApi() : super('http://unused');
  @override
  Future<double?> motionSeconds(String id, String motion) async => 4.2;
  @override
  Future<Map<String, dynamic>> ffbeUnit(String id) async => {'forms': <String, dynamic>{}};
  @override
  Future<Map<String, dynamic>> ffbeLb(String form, {String? lbId, String source = 'JP'}) async {
    final ice = lbId == '8';
    return {'lbId': ice ? '8' : '7', 'supported': true, 'target': 'One enemy', 'hits': 24,
      'elements': [ice ? 'Ice' : 'Fire'], 'fieldColor': ice ? '#00FFFF' : '#EE5555', 'totalPower': 36,
      'movement': {'type': 1, 'lbOffset': [40, 0]}, 'issues': [], 'warnings': [],
      'set': {'TargetType': 'Single', 'hitCount': 24, 'element': ice ? 'Ice' : 'Fire', 'magnification': 36},
      'description': '24 hits of ${ice ? 'Ice' : 'Fire'} physical damage to one enemy.',
      'variants': [{'id': '7', 'elements': ['Fire']}, {'id': '8', 'elements': ['Ice']}]};
  }
}

class ProfileState extends ChangeNotifier implements AppState {
  @override
  Api? api = ProfileApi();
  @override
  JsonMap? catalog = {
    'ffbeResonance': {'lbProfiles': true}, 'effects': [], 'icons': [], 'lbTemplates': [], 'visions': [],
    'skills': <Map<String, dynamic>>[{'id': 440110, 'name': 'Climhazzard', 'attr': 'FinishBlow',
      'dmgType': 'Physic', 'mag': 36, 'hits': 10, 'element': 'Thunder', 'relation': 'Enemies',
      'effectType': 'DamageAndRecovery', 'target': 'Single', 'effects': <num>[]}],
  };
  @override
  Future<List<String>> animsFor(String form) async => [];
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  testWidgets('LB data replaces donor mechanics and variant changes keep custom colour', (tester) async {
    tester.view.physicalSize = const Size(1600, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final app = ProfileState();
    addTearDown(app.dispose);
    Map<String, dynamic> unit = {'key': 'test', 'jp': 'test', 'en': 'Test', 'ffbe': {'id': '123'},
      'lb_custom': {'from': 440110, 'presentation': 'ffbe', 'mechanics': 'ffbe', 'descAuto': true,
        'field_color_mode': 'custom', 'field_color': '#AB1234', 'set': {'element': 'Thunder'}}};
    await tester.pumpWidget(ChangeNotifierProvider<AppState>.value(value: app,
      child: MaterialApp(theme: Guide.theme(), home: Scaffold(body: StatefulBuilder(
        builder: (context, setState) => ResonanceStep(unit: unit, set: (patch) => setState(() => unit = {...unit, ...patch})),
      )))));
    await tester.pumpAndSettle();
    expect((unit['lb_custom'] as Map)['set']['hitCount'], 24);
    expect((unit['lb_custom'] as Map)['set']['element'], 'Fire');
    expect(find.text('Numbers like'), findsNothing);
    await tester.tap(find.text('Fire · 7'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ice · 8').last);
    await tester.pumpAndSettle();
    expect((unit['lb_custom'] as Map)['ffbe_lb_id'], '8');
    expect((unit['lb_custom'] as Map)['set']['element'], 'Ice');
    expect((unit['lb_custom'] as Map)['field_color'], '#AB1234');
    expect((unit['lb_custom'] as Map)['desc'], contains('Ice'));
    expect(tester.takeException(), isNull);
  });
}
