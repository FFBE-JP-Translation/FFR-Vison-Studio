import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/rendering.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ffr_vision_studio/design/theme.dart';
import 'package:ffr_vision_studio/services/api.dart';
import 'package:ffr_vision_studio/screens/steps/ffbe_kit.dart';

class KitApi extends Api {
  KitApi() : super('http://unused');
  String? applied;
  bool removed = false;
  @override
  Future<Map<String,dynamic>> importKit(Map<String,dynamic> unit) async => unit;
  @override
  Future<Map<String,dynamic>> previewKit(Map<String,dynamic> unit) async => {'source':'GL_2024','entries':[
    {'id':1,'kind':'ABILITY','name':'Refresh','status':'ready','class':'partial','origin':'learned',
      'sourceKey':'GL_2024/ability/1','description':'Restore MP once.', 'issues':[], 'changes':['Repeating recovery becomes immediate.']},
    {'id':2,'kind':'ABILITY','name':'Unavailable skill','status':'held','class':'unsupported',
      'sourceKey':'GL_2024/ability/2','issues':['No compatible component remains.']},
  ]};
  @override
  Future<Map<String,dynamic>> kitLoadout(Map<String,dynamic> unit,String sourceKey,{String? replaceId,bool remove=false}) async {
    applied=sourceKey; removed=remove;
    return {...unit,'skills':remove ? <String,dynamic>{} : {'485000':{'en':'Refresh','ffbe':{'source':sourceKey}}}};
  }
}

void main() {
  testWidgets('reviewed full kit equips and removes a skill while keeping incompatible rows visible', (tester) async {
    for (final font in ['Barlow-Regular', 'BarlowCondensed-Bold']) {
      final loader = FontLoader(font.split('-').first)..addFont(rootBundle.load('assets/fonts/$font.ttf'));
      await loader.load();
    }
    tester.view.physicalSize=const Size(1000,700); tester.view.devicePixelRatio=1;
    addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
    final api=KitApi(); Map<String,dynamic>? saved; final boundary=GlobalKey();
    await tester.pumpWidget(MaterialApp(theme:Guide.theme(),home:Scaffold(body:RepaintBoundary(key:boundary,
      child:Material(color:Guide.paper,child:FfbeKit(unit:{'skills':{},'ffbe':{'id':'340000107'}},api:api,onChanged:(v)=>saved=v))))));
    await tester.pumpAndSettle();
    expect(find.textContaining('1 available'),findsOneWidget);
    expect(find.text('Unavailable skill'),findsOneWidget);
    await tester.tap(find.text('Refresh')); await tester.pumpAndSettle();
    expect(find.text('Restore MP once.'),findsOneWidget);
    await tester.tap(find.text('Use in test loadout')); await tester.pumpAndSettle();
    expect(api.applied,'GL_2024/ability/1'); expect(saved?['skills'],isNotEmpty);
    expect(find.text('Remove from test loadout'),findsOneWidget);
    await tester.runAsync(() async {
      final image=await (boundary.currentContext!.findRenderObject() as RenderRepaintBoundary).toImage();
      final bytes=await image.toByteData(format:ui.ImageByteFormat.png);
      final file=File('../../build/devui/reviewed-vision-kit.png');
      await file.parent.create(recursive:true); await file.writeAsBytes(bytes!.buffer.asUint8List()); image.dispose();
    });
    await tester.tap(find.text('Remove from test loadout')); await tester.pumpAndSettle();
    expect(api.removed,isTrue); expect(saved?['skills'],isEmpty);
    await tester.tap(find.text('Unavailable skill')); await tester.pumpAndSettle();
    expect(find.text('No compatible component remains.'),findsOneWidget);
    expect(tester.takeException(),isNull);
  });
}
