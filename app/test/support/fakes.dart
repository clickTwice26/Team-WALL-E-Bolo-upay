import 'dart:convert';

import 'package:bolo_upay/services/voice.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

/// The API in memory: api.dart calls the top-level http functions, which
/// http.runWithClient routes here, so the app code is unchanged.
class FakeApi {
  final calls = <({String method, String path, Map<String, dynamic> body})>[];
  final routes = <String, Object? Function(Map<String, dynamic> body)>{};

  void on(String route, Object? Function(Map<String, dynamic> body) reply) => routes[route] = reply;

  List<Map<String, dynamic>> bodies(String path) => [for (final c in calls) if (c.path == path) c.body];

  late final client = MockClient((req) async {
    final body = req.body.isEmpty ? <String, dynamic>{} : Map<String, dynamic>.from(jsonDecode(req.body));
    calls.add((method: req.method, path: req.url.path, body: body));
    final reply = routes['${req.method} ${req.url.path}'];
    if (reply == null) return _json({'detail': 'not found'}, 404);
    final out = reply(body);
    return out is http.Response ? out : _json(out, 200);
  });

  /// Runs [body] with every top-level http call going to this fake.
  Future<T> run<T>(Future<T> Function() body) => http.runWithClient(body, () => client);
}

http.Response _json(Object? data, int status) =>
    http.Response.bytes(utf8.encode(jsonEncode(data)), status, headers: {'content-type': 'application/json'});

/// An error reply with FastAPI's {"detail": ...} shape.
http.Response apiError(int status, Object detail) => _json({'detail': detail}, status);

/// Speech without the platform plugins: the test says what is "heard".
class FakeVoice implements Voice {
  @override
  bool available = true;
  @override
  bool lastUnsure = false;
  @override
  double? lastConfidence;
  final spoken = <String>[];

  /// What the next listen() hears, and the recognizer's confidence.
  (String, double?)? next;
  bool _listening = false;

  @override
  Future<bool> init() async => available;

  @override
  Future<void> listen({required bool bangla, required void Function(String text, bool done) onText}) async {
    final n = next;
    next = null;
    if (n == null) {
      _listening = true;
      return;
    }
    lastConfidence = n.$2;
    lastUnsure = n.$2 != null && n.$2! < Voice.minConfidence;
    onText(n.$1, false);
    onText(n.$1, true);
  }

  @override
  Future<void> stop() async => _listening = false;
  @override
  bool get isListening => _listening;
  @override
  Future<void> speak(String text, {required bool bangla}) async => spoken.add(text);
  @override
  Future<void> silence() async {}
}

/// Captures what the app copies to the clipboard (the non-web export path).
class ClipboardSpy {
  ClipboardSpy(WidgetTester tester) {
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') text = (call.arguments as Map)['text'] as String?;
      return null;
    });
  }
  String? text;
}

/// A tall phone-width screen, so every list item is built and tappable.
void phoneScreen(WidgetTester tester) {
  tester.view.physicalSize = const Size(430, 2400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> tapOn(WidgetTester tester, Finder f) async {
  await tester.ensureVisible(f);
  await tester.tap(f);
  await tester.pumpAndSettle();
}
