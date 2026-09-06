import 'package:ffr_vision_studio/services/downloader.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('rate limits and host errors are worth waiting out, missing files are not', () {
    expect(Downloader.transient(429), isTrue);
    expect(Downloader.transient(503), isTrue);
    expect(Downloader.transient(404), isFalse);
    expect(Downloader.transient(403), isFalse);
  });

  test('the wait follows Retry-After when the host says, else doubles', () {
    expect(Downloader.backoff(0, {'retry-after': '7'}), const Duration(seconds: 7));
    expect(Downloader.backoff(0, {'retry-after': '600'}), const Duration(seconds: 60));
    expect(Downloader.backoff(0, {}), const Duration(seconds: 2));
    expect(Downloader.backoff(2, {}), const Duration(seconds: 8));
  });
}
