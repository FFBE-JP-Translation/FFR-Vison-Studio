import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../design/theme.dart';
import '../design/widgets.dart';
import '../state/app_state.dart';
import 'add_unit_dialog.dart';
import 'build_status.dart';

/// Left page: your visions as guide entries. Right page: install.
class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Expanded(
        flex: 7,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Band('Your visions', trailing: Text('${app.units.length} in the mod', style: Guide.band().copyWith(letterSpacing: 0.4, fontSize: 13))),
          Expanded(
            child: app.units.isEmpty
                ? _empty(context)
                : GridView.builder(
                    padding: const EdgeInsets.all(16),
                    gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(maxCrossAxisExtent: 300, mainAxisExtent: 112, crossAxisSpacing: 12, mainAxisSpacing: 12),
                    itemCount: app.units.length + 1,
                    itemBuilder: (_, i) => i == app.units.length ? _addEntry(context) : _entry(context, app, app.units[i] as Map<String, dynamic>),
                  ),
          ),
        ]),
      ),
      Container(width: 2, color: Guide.ink),
      Expanded(
        flex: 5,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Band('Install', color: Guide.red),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Box(
                  padding: EdgeInsets.zero,
                  child: Column(children: [
                    StatRow('Game', app.gameRunning ? 'running' : 'closed', trailing: Icon(app.gameRunning ? Icons.warning_amber : Icons.check, size: 16, color: app.gameRunning ? Guide.gold : Guide.green)),
                    StatRow('Mod in the game', app.modInstalled ? 'installed' : 'not installed', zebra: true),
                    StatRow('Units ready', '${app.units.length}'),
                  ]),
                ),
                const SizedBox(height: 14),
                Text(app.gameRunning
                    ? 'Close the game to install. You can keep editing meanwhile.'
                    : 'Builds the mod from your units and copies it into the game. The new visions are sold in the Mitra item shop.', style: Guide.text()),
                const SizedBox(height: 14),
                Row(children: [
                  GoButton(app.building ? 'Working' : 'Install into the game', busy: app.building, onPressed: app.units.isEmpty || app.gameRunning || app.building ? null : () => app.startBuild(install: true)),
                ]),
                const SizedBox(height: 10),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  GuideButton('Build without installing', onPressed: app.units.isEmpty || app.building ? null : () => app.startBuild(install: false)),
                  GuideButton('Install the last build', onPressed: app.gameRunning || app.building ? null : app.installLast),
                  GuideButton('Advanced studio', icon: Icons.open_in_new, onPressed: app.api == null ? null : () => launchUrl(Uri.parse(app.api!.advancedUrl()))),
                ]),
                const SizedBox(height: 6),
                Text('Advanced opens the full studio in your browser: Brave Exvius kit imports, sprite settings, animation edits. It works on the same units.', style: Guide.small()),
                if (app.buildState != null) ...[const SizedBox(height: 18), const BuildStatus()],
              ]),
            ),
          ),
        ]),
      ),
    ]);
  }

  Widget _empty(BuildContext context) => Padding(
        padding: const EdgeInsets.all(24),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('No visions yet.', style: Guide.h2()),
          const SizedBox(height: 8),
          Text('Add a unit from Brave Exvius, give it abilities, bonuses, stats and a Resonance from what the game already has, then install. Ten minutes for the first one.', style: Guide.text()),
          const SizedBox(height: 16),
          GoButton('Add a unit', color: Guide.blue, icon: Icons.add, onPressed: () => showAddUnit(context)),
        ]),
      );

  Widget _addEntry(BuildContext context) => Material(
        color: Guide.paper,
        shape: const Border.fromBorderSide(BorderSide(color: Guide.ink, width: 1.5)),
        child: InkWell(
          onTap: () => showAddUnit(context),
          hoverColor: Guide.paper2,
          child: Center(child: Row(mainAxisSize: MainAxisSize.min, children: [const Icon(Icons.add, color: Guide.ink), const SizedBox(width: 8), Text('ADD A UNIT', style: Guide.band(Guide.ink))])),
        ),
      );

  Widget _entry(BuildContext context, AppState app, Map<String, dynamic> u) {
    final aw = (u['awakening'] as List? ?? []).cast<List>();
    final abilities = aw.fold<int>(0, (n, t) => n + t.where((g) => g[0] == 'ActiveSkill').length);
    final bonuses = aw.fold<int>(0, (n, t) => n + t.where((g) => g[0] != 'ActiveSkill').length);
    final lb = u['lb_custom'] as Map?;
    return Material(
      color: Guide.paper,
      shape: const Border.fromBorderSide(BorderSide(color: Guide.ink, width: 1.5)),
      child: InkWell(
        onTap: () => app.select(u['key'] as String),
        hoverColor: Guide.paper2,
        child: Padding(
          padding: const EdgeInsets.all(10),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Frame(padding: 2, child: PixelImage(app.api!.unitIcon(u['key'] as String, 'face'), width: 72, height: 72)),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text((u['en'] as String? ?? '').toUpperCase(), style: Guide.h2().copyWith(fontSize: 20), maxLines: 1, overflow: TextOverflow.ellipsis),
                const SizedBox(height: 2),
                Text('${u['attackType'] == 'Magic' ? 'Magic' : 'Physical'} · ${((u['roles'] as List?) ?? []).map((r) => r.toString().replaceAll('eUnitRole::', '')).join(', ')}', style: Guide.small(), maxLines: 1, overflow: TextOverflow.ellipsis),
                const SizedBox(height: 6),
                Text('$abilities abilities · $bonuses bonuses', style: Guide.small(Guide.ink)),
                Text('Resonance: ${lb != null ? lb['en'] : 'borrowed'}', style: Guide.small(), maxLines: 1, overflow: TextOverflow.ellipsis),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}
