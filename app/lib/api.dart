import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

/// API base URL.
/// - Web build served by the backend: leave empty, calls go to the same origin.
/// - iOS / Android: build with --dart-define=API_BASE=https://your-domain
const String _apiBase = String.fromEnvironment('API_BASE', defaultValue: '');

Uri _uri(String path) {
  if (_apiBase.isNotEmpty) return Uri.parse('$_apiBase$path');
  if (kIsWeb) return Uri.base.resolve(path);
  return Uri.parse('http://localhost:8000$path');
}

/// The signed-in session. The token lives only in memory: closing the app
/// signs out, and the PIN screen comes back.
class Session {
  static String? token;

  /// Called when the server says the session ended (expired or signed out).
  static VoidCallback? onExpired;

  static Map<String, String> get header => token == null ? const {} : {'Authorization': 'Bearer $token'};
}

class ApiError implements Exception {
  ApiError(this.status, this.detail);
  final int status;
  final dynamic detail;

  String get code => detail is Map ? (detail['code'] ?? '').toString() : detail.toString();

  /// Seconds until a locked account (423) can try again.
  int get retryAfter => detail is Map ? ((detail['retry_after'] as num?)?.toInt() ?? 0) : 0;

  @override
  String toString() => 'ApiError($status, $detail)';
}

/// One JSON request to the API (also used by the support console, which
/// passes its own Authorization header).
Future<dynamic> apiRequest(String method, String path,
    {Map<String, dynamic>? body, Map<String, String> headers = const {}}) async {
  final h = {'Content-Type': 'application/json', ...Session.header, ...headers};
  late http.Response r;
  try {
    r = method == 'GET'
        ? await http.get(_uri(path), headers: h).timeout(const Duration(seconds: 30))
        : await http.post(_uri(path), headers: h, body: jsonEncode(body ?? {})).timeout(const Duration(seconds: 30));
  } catch (e) {
    throw ApiError(0, 'network');
  }
  final data = r.body.isEmpty ? null : jsonDecode(utf8.decode(r.bodyBytes));
  if (r.statusCode >= 400) {
    final e = ApiError(r.statusCode, data is Map ? data['detail'] : data);
    if (e.status == 401 && e.code == 'login_required' && !headers.containsKey('Authorization')) {
      Session.token = null;
      Session.onExpired?.call();
    }
    throw e;
  }
  return data;
}

class Api {
  static Future<dynamic> _send(String method, String path, [Map<String, dynamic>? body]) =>
      apiRequest(method, path, body: body);

  /// Demo personas for the picker; empty on a site without DEMO_MODE.
  static Future<List<dynamic>> users() async {
    try {
      return await _send('GET', '/api/users') as List;
    } on ApiError catch (e) {
      if (e.status == 404) return const [];
      rethrow;
    }
  }

  static Future<Map<String, dynamic>> me() async => Map<String, dynamic>.from(await _send('GET', '/api/me'));
  static Future<Map<String, dynamic>> parse(String text) async =>
      Map<String, dynamic>.from(await _send('POST', '/api/parse', {'text': text}));
  static Future<Map<String, dynamic>> assess(Map<String, dynamic> draft,
          {bool onCall = false, List<String> answers = const []}) async =>
      Map<String, dynamic>.from(await _send('POST', '/api/assess', {
        'draft': draft,
        'on_active_call': onCall,
        'answers': answers,
      }));

  /// [proof] is the device-key signature for a biometric approval:
  /// {'signature': ..., 'public_key': ...}.
  static Future<Map<String, dynamic>> execute(String assessmentId, String method,
          {String? pin, bool acknowledged = false, Map<String, String>? proof}) async =>
      Map<String, dynamic>.from(await _send('POST', '/api/execute', {
        'assessment_id': assessmentId,
        'method': method,
        'pin': ?pin,
        'acknowledged_warning': acknowledged,
        ...?proof,
      }));
  static Future<void> cancel(String assessmentId) async => _send('POST', '/api/cancel', {'assessment_id': assessmentId});

  /// Adaptive scam interview: the next question, or {'done': true}.
  static Future<Map<String, dynamic>> interviewNext(String assessmentId, List<String> asked, List<String> answers) async =>
      Map<String, dynamic>.from(await _send('POST', '/api/interview/next',
          {'assessment_id': assessmentId, 'asked': asked, 'answers': answers}));

  /// The user says a warning was wrong (a label for threshold reviews).
  static Future<void> feedback(String assessmentId, String kind) async =>
      _send('POST', '/api/feedback', {'assessment_id': assessmentId, 'kind': kind});

  /// Model health for ops: drift, level mix, wrong-warning and override rates.
  static Future<Map<String, dynamic>> monitor() async =>
      Map<String, dynamic>.from(await _send('GET', '/api/admin/monitor'));
  static Future<Map<String, dynamic>> dashboard() async =>
      Map<String, dynamic>.from(await _send('GET', '/api/dashboard'));
  static Future<Map<String, dynamic>> metrics() async =>
      Map<String, dynamic>.from(await _send('GET', '/api/metrics'));
  /// PIN unlock: starts the session.
  static Future<void> login(String userId, String pin) async {
    final r = await _send('POST', '/api/login', {'user_id': userId, 'pin': pin});
    Session.token = '${r['token']}';
  }

  /// Demo site only: a session for another demo persona.
  static Future<void> demoSwitch(String userId) async {
    final r = await _send('POST', '/api/demo/switch', {'user_id': userId});
    Session.token = '${r['token']}';
  }

  /// Register this phone's biometric-protected signing key (base64 DER).
  static Future<void> registerDevice(String publicKey) async =>
      _send('POST', '/api/devices', {'public_key': publicKey});
  static Future<void> reset() async => _send('POST', '/api/demo/reset');
  static Future<Map<String, dynamic>> agent(Map<String, dynamic> body) async =>
      Map<String, dynamic>.from(await _send('POST', '/api/agent', body));

  // human handoff
  static Future<Map<String, dynamic>> startHandoff(Map<String, dynamic> body) async =>
      Map<String, dynamic>.from(await _send('POST', '/api/handoff', body));
  static Future<Map<String, dynamic>> pollHandoff(String id, int after) async =>
      Map<String, dynamic>.from(await _send('GET', '/api/handoff/$id?after=$after'));
  static Future<void> handoffMessage(String id, String text) async =>
      _send('POST', '/api/handoff/$id/messages', {'text': text});
  static Future<void> closeHandoff(String id) async => _send('POST', '/api/handoff/$id/close');

  /// Natural server voice (WAV), or null when the server has no TTS or fails.
  static Future<Uint8List?> tts(String text) async {
    try {
      final r = await http
          .post(_uri('/api/tts'),
              headers: {'Content-Type': 'application/json', ...Session.header}, body: jsonEncode({'text': text}))
          .timeout(const Duration(seconds: 20));
      return r.statusCode == 200 && r.bodyBytes.isNotEmpty ? r.bodyBytes : null;
    } catch (_) {
      return null;
    }
  }
}
