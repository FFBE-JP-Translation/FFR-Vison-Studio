import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:ffr_vision_studio/services/paths.dart';
import 'package:ffr_vision_studio/state/app_state.dart';

void main() {
  test('local boot loads hosted packs and shares the connected engine asset directory', () async {
    final tmp = Directory.systemTemp.createTempSync('studio-local-boot-');
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final data = p.join(tmp.path, 'checkout', 'data', 'ffbe');
    final cache = p.join(tmp.path, 'checkout', 'build', 'devui', 'ffbe_index_cache.json');
    final index = {'version':'1.0.0.15','units':[{'id':'100030904','name':'Accelle','packs':['100030906']}],
      'unitBundles':{'100030906':{'url':'100030906.ffr','sha256':'fixture'}}};
    var offline = false;
    final requests = <String>[];
    server.listen((request) async {
      requests.add(request.uri.path);
      final response = request.response;
      if (request.uri.path == '/ffbe/index.json' && offline) {
        response.statusCode = 404;
      } else {
        response.headers.contentType = ContentType.json;
        response.write(json.encode(switch (request.uri.path) {
          '/api/status' => {'setupNeeded':false,'ffbeDataDir':data,'unitIndexCache':cache},
          '/ffbe/index.json' => index,
          '/api/ffr/catalog' => <String,dynamic>{},
          '/api/spec' => <dynamic>[],
          _ => <String,dynamic>{},
        }));
      }
      await response.close();
    });
    final base = 'http://127.0.0.1:${server.port}';
    final paths = AppPaths.at(p.join(tmp.path, 'app-home'));
    AppState? app;
    try {
      app = AppState(hostBase:base, appPaths:paths);
      await app.connectLocalApi(base);
      expect(app.phase, Phase.ready);
      expect(app.hostIndex?['units'][0]['packs'], ['100030906']);
      expect(app.unitAssets.dataDir, data);
      expect(json.decode(File(cache).readAsStringSync()), index);
      expect(requests, contains('/ffbe/index.json'));
      app.dispose(); app = null;
      offline = true;
      app = AppState(hostBase:base, appPaths:paths);
      await app.connectLocalApi(base);
      expect(app.hostIndex?['unitBundles'], index['unitBundles']);
      expect(app.banner, contains('cached unit availability'));
    } finally {
      app?.dispose();
      await server.close(force:true);
      tmp.deleteSync(recursive:true);
    }
  });
}
