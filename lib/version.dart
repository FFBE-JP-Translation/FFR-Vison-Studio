/// Stamped at release time by tools/release/build_host_pack.py --build-app (--dart-define). A developer build is build 0.
const appVersion = String.fromEnvironment('APP_VERSION', defaultValue: '1.0.0');
const appBuild = String.fromEnvironment('APP_BUILD', defaultValue: '0');
const appTag = '$appVersion.$appBuild';
const appLabel = 'version $appVersion · build $appBuild';

/// Dotted numeric tags ("1.0.0.4"): negative when a is older than b, 0 when equal.
int compareTags(String a, String b) {
  final x = a.split('.').map((s) => int.tryParse(s) ?? 0).toList();
  final y = b.split('.').map((s) => int.tryParse(s) ?? 0).toList();
  for (var i = 0; i < (x.length > y.length ? x.length : y.length); i++) {
    final p = i < x.length ? x[i] : 0, q = i < y.length ? y[i] : 0;
    if (p != q) return p - q;
  }
  return 0;
}
