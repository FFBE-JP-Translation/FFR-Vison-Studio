import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:ffr_vision_studio/design/theme.dart';
import 'package:ffr_vision_studio/screens/steps/abilities_step.dart';
import 'package:ffr_vision_studio/screens/steps/bonuses_step.dart';
import 'package:ffr_vision_studio/screens/steps/tiers.dart';
import 'package:ffr_vision_studio/screens/steps/grant_details.dart';
import 'package:ffr_vision_studio/services/api.dart';
import 'package:ffr_vision_studio/state/app_state.dart';

const longDescription = 'Deals eight hits of physical damage to one enemy. Restores resonance to the main cast. Compatible parts of this native ability are retained, while unsupported components remain recorded in the source information for review.';
Map<String, dynamic> fixture() => {
  'id': 13500, 'key': 'sora', 'en': 'Sora (KHIII)', 'jp': 'Sora', 'ffbe': {'id': '340000107'},
  'ffbeLibrary': [
    {'sourceKey': 'GL/ability/1', 'kind': 'ABILITY', 'name': 'Falling Slash', 'description': longDescription, 'status': 'ready', 'cost': 48, 'level': 1, 'origin': 'learned', 'effects': ['Physical damage (42x) to one enemy'], 'changes': ['Recovery becomes immediate.']},
    {'sourceKey': 'GL/passive/2', 'kind': 'PASSIVE', 'name': 'Brave Heart', 'description': 'Increases attack by 20%.', 'status': 'ready', 'cost': 2},
    {'sourceKey': 'GL/ability/3', 'kind': 'ABILITY', 'name': 'Unsupported move', 'description': 'No compatible effect remains.', 'status': 'held', 'issues': ['This effect is unavailable in FFR.']},
  ],
  'skills': {'485000': {'en': 'Falling Slash', 'desc': longDescription, 'ffbe': {'source': 'GL/ability/1'}, 'set': {'Cost': 48}}},
  'convertedPassives': {'50000': {'en': 'Brave Heart', 'desc': 'Increases attack by 20%.', 'ffbe': {'source': 'GL/passive/2'}, 'set': {'equipCost': 2}}},
  'awakening': [[['ActiveSkill', 485000], ['PassiveSkill', 50000]], [['BaseParameter', 1, 50]], [], []], 'synchro': [],
};

class EditorApi extends Api {
  EditorApi() : super('http://unused');
  String? importedGroup;
  @override
  Future<Map<String, dynamic>> grants(Map<String, dynamic> unit, Map<String, dynamic> action) async {
    final next = json.decode(json.encode(unit)) as Map<String, dynamic>;
    if (action['action'] == 'info') return {'conversion': {'set': {'TargetType': 'Single', 'hitCount': 8, 'element': 'None'}, 'snapshot': {'source': 'Original FFBE source'}}, 'recipe': {}};
    if (action['action'] == 'import') {
      importedGroup = action['group'];
      next['nativeImports'] = ['GL/ability/1', 'GL/ability/3', 'GL/passive/2'];
    }
    if (action['action'] == 'edit') {
      final ref = action['ref'] as Map, edits = action['edits'] as Map;
      final recipe = next['skills']['${ref['id']}'];
      recipe['en'] = edits['name']; recipe['desc'] = edits['description'];
      recipe['set'] = {'Cost': edits['cost'], 'SkillIcon.TagName': edits['icon']};
    }
    return next;
  }
}

class EditorState extends ChangeNotifier implements AppState {
  @override
  Api? api = EditorApi();
  @override
  JsonMap? catalog = {
    'skills': <Map<String, dynamic>>[{'id': 100000, 'name': 'Fire', 'desc': 'Deals fire damage.', 'cost': 5, 'seq': [1], 'hasUnit': 'All', 'attr': 'Magic', 'dmgType': 'Magic', 'relation': 'Enemies', 'element': 'Fire'}],
    'passives': <Map<String, dynamic>>[{'id': 1001, 'name': 'Attack Up', 'desc': 'Increases attack.', 'equipCost': 1}],
    'studioSkills': [], 'icons': <Map<String, dynamic>>[{'tag':'UI.Skill.Action.Icon.Attack'}, {'tag':'UI.Skill.Action.Icon.Fire'},
      {'tag':'UI.Skill.Action.Icon.FFBE.ability_77', 'row':'FFBE · ability 77', 'ffbeIcon':'ability_77.png'}], 'effects': [],
    'ffbeIconAliases': {'700000077':'ability_77.png'},
  };
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  test('native FFBE icons resolve client IDs and retain explicit editor choices', () {
    final state = EditorState();
    final unit = fixture();
    unit['ffbeLibrary'][0]['icon'] = '700000077';
    final ref = <String,dynamic>{'sourceKey':'GL/ability/1'};
    expect(grantData(unit, state.catalog!, ref).icon, 'UI.Skill.Action.Icon.FFBE.ability_77');
    unit['nativeEdits'] = {'GL/ability/1': {'icon':'UI.Skill.Action.Icon.Fire'}};
    expect(grantData(unit, state.catalog!, ref).icon, 'UI.Skill.Action.Icon.Fire');
    state.dispose();
  });
  setUpAll(() async {
    for (final font in ['Barlow-Regular', 'BarlowCondensed-Bold']) {
      final loader = FontLoader(font.split('-').first)..addFont(rootBundle.load('assets/fonts/$font.ttf'));
      await loader.load();
    }
    await (FontLoader('MaterialIcons')..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
  });
  tearDown(() => Guide.dark = false);

  test('reorder preserves all grant kinds and supports a full tier', () {
    final aw = [<dynamic>[for (var i = 0; i < 8; i++) ['ActiveSkill', i]], <dynamic>[['PassiveSkill', 1001]], <dynamic>[], <dynamic>[]];
    final moved = reorderGrant(aw, 0, 0, 0, 8);
    expect(moved[0].last, ['ActiveSkill', 0]); expect(aw[0].first, ['ActiveSkill', 0]);
    final across = reorderGrant(moved, 0, 7, 1, 0);
    expect(across[1], [['ActiveSkill', 0], ['PassiveSkill', 1001]]);
    expect(() => reorderGrant(aw, 1, 0, 0, 1), throwsStateError);
  });

  testWidgets('native filter, import, shared grants, handle-only dragging, and editing', (tester) async {
    tester.view.physicalSize = const Size(1120, 850); tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
    final app = EditorState(); addTearDown(app.dispose);
    var unit = fixture();
    await tester.pumpWidget(ChangeNotifierProvider<AppState>.value(value: app, child: MaterialApp(theme: Guide.theme(), home: Scaffold(body: StatefulBuilder(
      builder: (_, state) => AbilitiesStep(unit: unit, set: (patch) => state(() => unit = {...unit, ...patch})))))));
    await tester.pumpAndSettle();
    expect(find.text('Native Abilities'), findsOneWidget);
    expect(find.text('Brave Heart'), findsOneWidget); // bonus is visible on Abilities
    expect(find.text('HP'), findsOneWidget);
    expect(find.text('FFBE skills · test loadout'), findsNothing);
    final before = json.encode(unit['awakening']);
    final name = find.descendant(of: find.byType(LearnedTiers), matching: find.text('Falling Slash'));
    await tester.drag(name, const Offset(0, 190)); await tester.pumpAndSettle();
    expect(json.encode(unit['awakening']), before);
    final handles = find.descendant(of: find.byType(LearnedTiers), matching: find.byType(Draggable<DragPayload>));
    final from = tester.getCenter(handles.first);
    final to = tester.getCenter(find.byKey(const ValueKey('tier-1-position-0')));
    await tester.dragFrom(from, to - from); await tester.pumpAndSettle();
    expect(unit['awakening'][1][0], ['ActiveSkill', 485000]);
    expect(unit['awakening'][0], [['PassiveSkill', 50000]]);
    await tester.tap(find.byTooltip('Information about Falling Slash')); await tester.pumpAndSettle();
    expect(find.text('Hits: 8'), findsOneWidget);
    expect(find.text('Physical damage (42x) to one enemy'), findsOneWidget);
    await tester.tap(find.text('Close')); await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Edit Falling Slash')); await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextFormField, 'Name'), 'My Falling Slash');
    await tester.enterText(find.widgetWithText(TextFormField, 'Description'), 'My description');
    await tester.enterText(find.widgetWithText(TextFormField, 'Cost (MP)'), '7');
    final picker = find.descendant(of: find.byType(DropdownMenu<String>), matching: find.byType(TextField));
    await tester.tap(picker); await tester.enterText(picker, 'ability 77'); await tester.pumpAndSettle();
    await tester.tap(find.text('FFBE · ability 77').last); await tester.pumpAndSettle();
    await tester.tap(find.text('Save changes')); await tester.pumpAndSettle();
    expect(unit['skills']['485000']['en'], 'My Falling Slash');
    expect(unit['skills']['485000']['set']['Cost'], 7);
    expect(unit['skills']['485000']['set']['SkillIcon.TagName'], 'UI.Skill.Action.Icon.FFBE.ability_77');
    await tester.tap(find.text('Import native')); await tester.pumpAndSettle();
    expect((app.api as EditorApi).importedGroup, 'abilities');
    expect(unit['nativeImports'], contains('GL/ability/3'));
    expect(tester.takeException(), isNull);
  });

  testWidgets('both tabs render at desktop and narrow widths in light and dark; stats stay legible', (tester) async {
    tester.view.devicePixelRatio = 1; addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
    final app = EditorState(); addTearDown(app.dispose);
    final boundary = GlobalKey();
    for (final dark in [false, true]) {
      for (final width in [1120.0, 850.0, 620.0]) {
        Guide.dark = dark;
        tester.view.physicalSize = Size(width, 820);
        for (final bonuses in [false, true]) {
          var unit = fixture();
          await tester.pumpWidget(ChangeNotifierProvider<AppState>.value(value: app, child: MaterialApp(theme: Guide.theme(), home: Scaffold(
            body: RepaintBoundary(key: boundary, child: StatefulBuilder(builder: (_, state) => Material(color: Guide.paper,
              child: bonuses ? BonusesStep(key: ValueKey('$dark-$width-b'), unit: unit, set: (patch) => state(() => unit = {...unit, ...patch}))
                : AbilitiesStep(key: ValueKey('$dark-$width-a'), unit: unit, set: (patch) => state(() => unit = {...unit, ...patch})))))))));
          await tester.pumpAndSettle();
          expect(find.text(bonuses ? 'Native Bonuses' : 'Native Abilities'), findsOneWidget);
          expect(find.descendant(of: find.byType(LearnedTiers), matching: find.text('Falling Slash')), findsOneWidget);
          expect(find.descendant(of: find.byType(LearnedTiers), matching: find.text('Brave Heart')), findsOneWidget);
          if (bonuses) {
            await tester.tap(find.byType(DropdownButton<String>)); await tester.pumpAndSettle();
            await tester.tap(find.text('Stat bonuses').last); await tester.pumpAndSettle();
            final label = tester.widget<Text>(find.text('Intelligence'));
            final ink = Guide.ink;
            expect(label.style!.color, Guide.onBandFor(ink));
            expect((label.style!.color!.computeLuminance() - ink.computeLuminance()).abs(), greaterThan(.6));
          }
          expect(tester.takeException(), isNull, reason: '$dark / $width / bonuses=$bonuses');
          if (width == 1120 || dark && bonuses) {
            await tester.runAsync(() async {
              final image = await (boundary.currentContext!.findRenderObject() as RenderRepaintBoundary).toImage();
              final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
              final file = File('../../build/native-editor/${dark ? 'dark' : 'light'}-${bonuses ? 'bonuses' : 'abilities'}-${width.toInt()}.png');
              await file.parent.create(recursive: true); await file.writeAsBytes(bytes!.buffer.asUint8List()); image.dispose();
            });
          }
        }
      }
    }
  });

  testWidgets('only overflowing descriptions get an expansion tooltip', (tester) async {
    await tester.pumpWidget(MaterialApp(theme: Guide.theme(), home: Scaffold(body: Column(children: [
      SizedBox(width: 400, child: DescriptionRow(title: 'Short', description: 'Short description.', leading: const SizedBox(), trailing: const SizedBox())),
      SizedBox(width: 400, child: DescriptionRow(title: 'Long', description: longDescription, leading: const SizedBox(), trailing: const SizedBox())),
    ]))));
    expect(find.byType(Tooltip), findsOneWidget);
    expect(tester.widget<Tooltip>(find.byType(Tooltip)).message, longDescription);
  });
}
