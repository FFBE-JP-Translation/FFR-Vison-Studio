import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../design/theme.dart';
import '../design/widgets.dart';
import '../design/wordmark.dart';
import '../state/app_state.dart';
import '../version.dart';

/// Version, what the app talks to, the legal lines, and the font licence.
Future<void> showAbout(BuildContext context) {
  final app = context.read<AppState>();
  return showDialog<void>(
    context: context,
    builder: (c) => Dialog(
      backgroundColor: Colors.transparent,
      insetPadding: const EdgeInsets.all(32),
      child: Paper(
        width: 640,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Band('About', color: Guide.ink),
          Padding(
            padding: const EdgeInsets.all(20),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              const Wordmark(size: 40),
              const SizedBox(height: 14),
              Box(
                padding: EdgeInsets.zero,
                child: Column(children: [
                  StatRow('App', appLabel),
                  StatRow('Engine', app.engineVersion == null ? '-' : _prettyTag(app.engineVersion!), zebra: true),
                  StatRow('Download host', app.downloadPage),
                  StatRow('Game folder', app.gameRoot ?? 'not found', zebra: true),
                  StatRow('App data', app.paths.root),
                ]),
              ),
              const SizedBox(height: 12),
              Text('Fan project. Not affiliated with Square Enix. FINAL FANTASY, FINAL FANTASY RESONANCE and FINAL FANTASY BRAVE EXVIUS are trademarks of Square Enix Holdings Co., Ltd. The app talks only to its own download hosts and to the engine on this machine; nothing is reported anywhere.', style: Guide.small()),
              const SizedBox(height: 12),
              Text('FONTS', style: Guide.label()),
              const SizedBox(height: 4),
              Text('Barlow and Barlow Condensed by Jeremy Tribby, SIL Open Font License 1.1.', style: Guide.small()),
              const SizedBox(height: 4),
              SizedBox(
                height: 110,
                child: Box(
                  fill: Guide.paper2,
                  padding: const EdgeInsets.all(8),
                  child: FutureBuilder<String>(
                    future: rootBundle.loadString('assets/fonts/OFL.txt'),
                    builder: (c, s) => SingleChildScrollView(child: Text(s.data ?? 'loading the licence', style: Guide.mono(Guide.inkSoft).copyWith(fontSize: 10.5))),
                  ),
                ),
              ),
            ]),
          ),
          Container(height: 1, color: Guide.hairline),
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 14),
            child: Row(children: [
              GuideButton('Download page', small: true, icon: Icons.open_in_new, onPressed: () => launchUrl(Uri.parse(app.downloadPage))),
              const SizedBox(width: 8),
              GuideButton('Open logs folder', small: true, icon: Icons.folder_open, onPressed: app.openLogs),
              const Spacer(),
              GuideButton('Close', onPressed: () => Navigator.pop(c)),
            ]),
          ),
        ]),
      ),
    ),
  );
}

String _prettyTag(String tag) {
  final parts = tag.split('.');
  return parts.length == 4 ? 'version ${parts.take(3).join('.')} · build ${parts[3]}' : tag;
}
