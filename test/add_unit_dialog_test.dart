import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:ffr_vision_studio/design/anim_viewer.dart';
import 'package:ffr_vision_studio/screens/add_unit_dialog.dart';
import 'package:ffr_vision_studio/services/paths.dart';
import 'package:ffr_vision_studio/state/app_state.dart';
import 'package:ffr_vision_studio/state/catalog_helpers.dart';

Map<String, dynamic> unit(String name, String base, String shift) => {
  'id': base, 'name': name, 'hasSprites': true, 'rarity_min': 'NV', 'rarity_max': 'NV',
  'forms': [base, shift], 'packs': [base, shift],
  'shift': {shift: {'kind': 'brave_shift', 'base': base}},
  // Deliberately reproduce a base-only detail cached by an older engine.
  'previewDetail': {'id': base, 'name': name, 'maxForm': base, 'forms': {base: {'rarity': 'NV'}}},
};

class TestApp extends AppState {
  TestApp(String root) : super(hostBase: 'http://127.0.0.1:1', appPaths: AppPaths.at(root)) {
    hostIndex = {'units': [unit('2B -Neo Vision-', '401013807', '401013817'), unit('Sora (KHIII)', '340000107', '340000117')]};
    final idle = File('$root/idle.png');
    idle.writeAsBytesSync(base64Decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5ZkAAAAASUVORK5CYII='));
  }
  final previews = <String>[];
  final imports = <List<String>>[];
  Completer<void> download = Completer<void>();
  @override
  File? idleFile(String form) { previews.add(form); return File('${paths.root}/idle.png'); }
  @override
  Future<JsonMap> addUnit(String ffbeId, String form, String name, {void Function(String)? onStep, void Function(int, int)? onProgress}) async {
    imports.add([ffbeId, form, name]);
    onStep?.call('Downloading unit data');
    onProgress?.call(512, 1024);
    await download.future;
    selectedKey = 'new-unit';
    return {'key': selectedKey};
  }
}

void main() {
  test('Brave Shift dependencies survive partial details for both reported units', () {
    for (final u in [unit('2B', '401013807', '401013817'), unit('Sora', '340000107', '340000117')]) {
      final detail = catalogUnitDetail(u, u['previewDetail']);
      final shift = u['forms'][1] as String;
      expect(detail['forms'][shift]['shift']['kind'], 'brave_shift');
      expect(unitFormDependencies({'units': [u]}, u['id'], shift), [shift, u['id']]);
      expect(unitFormDependencies({'units': [u]}, u['id'], u['id']), [u['id']]);
    }
  });

  testWidgets('browse local idles, import on Add, show progress and preserve selection on retry', (tester) async {
    final tmp = Directory.systemTemp.createTempSync('ffr-picker-');
    final app = TestApp(tmp.path);
    addTearDown(() { app.dispose(); tmp.deleteSync(recursive: true); });
    tester.view.physicalSize = const Size(1200, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(ChangeNotifierProvider<AppState>.value(value: app, child: MaterialApp(home: Builder(builder: (context) => Scaffold(
      body: TextButton(onPressed: () => showAddUnit(context), child: const Text('Open')),
    )))));
    await tester.tap(find.text('Open')); await tester.pumpAndSettle();
    for (final name in ['2B -Neo Vision-', 'Sora (KHIII)']) {
      await tester.tap(find.text(name)); await tester.pumpAndSettle();
      await tester.tap(find.byType(DropdownButtonFormField<String>)); await tester.pumpAndSettle();
      await tester.tap(find.text('NV · Brave Shift').last); await tester.pumpAndSettle();
      expect(tester.widget<AnimViewer>(find.byType(AnimViewer)).idlePreview, isNotNull);
    }
    expect(app.previews, ['401013807', '401013817', '340000107', '340000117']);
    expect(app.imports, isEmpty);
    await tester.enterText(find.byType(TextField).last, 'My Sora');
    await tester.tap(find.text('ADD UNIT')); await tester.pump();
    expect(app.imports.single, ['340000107', '340000117', 'My Sora']);
    expect(find.byType(AddUnitDialog), findsOneWidget);
    expect(tester.widget<LinearProgressIndicator>(find.byType(LinearProgressIndicator)).value, .5);
    expect(tester.widget<DropdownButtonFormField<String>>(find.byType(DropdownButtonFormField<String>)).onChanged, isNull);
    await tester.tap(find.text('2B -Neo Vision-')); await tester.pump();
    expect(app.previews.last, '340000117');
    app.download.completeError(StateError('Connection interrupted'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Connection interrupted'), findsOneWidget);
    expect(find.text('My Sora'), findsOneWidget);
    app.download = Completer<void>();
    await tester.tap(find.text('ADD UNIT')); await tester.pump();
    app.download.complete(); await tester.pumpAndSettle();
    expect(find.byType(AddUnitDialog), findsNothing);
    expect(app.selectedKey, 'new-unit');
    expect(app.imports.length, 2);
    expect(tester.takeException(), isNull);
  });
}
