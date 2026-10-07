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

class ApiError implements Exception {
  ApiError(this.status, this.detail);
  final int status;
  final dynamic detail;

  String get code => detail is Map ? (detail['code'] ?? '').toString() : detail.toString();

  @override
  String toString() => 'ApiError($status, $detail)';
}

class Api {
  static Future<dynamic> _send(String method, String path, [Map<String, dynamic>? body]) async {
    final headers = {'Content-Type': 'application/json'};
    late http.Response r;
    try {
      r = method == 'GET'
          ? await http.get(_uri(path), headers: headers).timeout(const Duration(seconds: 30))
          : await http
              .post(_uri(path), headers: headers, body: jsonEncode(body ?? {}))
              .timeout(const Duration(seconds: 30));
    } catch (e) {
      throw ApiError(0, 'network');
    }
    final data = r.body.isEmpty ? null : jsonDecode(utf8.decode(r.bodyBytes));
    if (r.statusCode >= 400) {
      throw ApiError(r.statusCode, data is Map ? data['detail'] : data);
    }
    return data;
  }

  static Future<List<dynamic>> users() async => await _send('GET', '/api/users') as List;
  static Future<Map<String, dynamic>> user(String id) async =>
      Map<String, dynamic>.from(await _send('GET', '/api/users/$id'));
  static Future<Map<String, dynamic>> parse(String userId, String text) async =>
      Map<String, dynamic>.from(await _send('POST', '/api/parse', {'user_id': userId, 'text': text}));
  static Future<Map<String, dynamic>> assess(String userId, Map<String, dynamic> draft,
          {bool onCall = false, List<String> answers = const []}) async =>
      Map<String, dynamic>.from(await _send('POST', '/api/assess', {
        'user_id': userId,
        'draft': draft,
        'on_active_call': onCall,
        'answers': answers,
      }));
  static Future<Map<String, dynamic>> execute(String userId, String assessmentId, String method,
          {String? pin, bool acknowledged = false}) async =>
      Map<String, dynamic>.from(await _send('POST', '/api/execute', {
        'user_id': userId,
        'assessment_id': assessmentId,
        'method': method,
        if (pin != null) 'pin': pin,
        'acknowledged_warning': acknowledged,
      }));
  static Future<void> cancel(String userId, String assessmentId) async =>
      _send('POST', '/api/cancel', {'user_id': userId, 'assessment_id': assessmentId});
  static Future<Map<String, dynamic>> dashboard() async =>
      Map<String, dynamic>.from(await _send('GET', '/api/dashboard'));
  static Future<Map<String, dynamic>> metrics() async =>
      Map<String, dynamic>.from(await _send('GET', '/api/metrics'));
  static Future<void> login(String userId, String pin) async =>
      _send('POST', '/api/login', {'user_id': userId, 'pin': pin});
  static Future<void> reset() async => _send('POST', '/api/demo/reset');

  /// Natural server voice (WAV), or null when the server has no TTS or fails.
  static Future<Uint8List?> tts(String text) async {
    try {
      final r = await http
          .post(_uri('/api/tts'), headers: {'Content-Type': 'application/json'}, body: jsonEncode({'text': text}))
          .timeout(const Duration(seconds: 20));
      return r.statusCode == 200 && r.bodyBytes.isNotEmpty ? r.bodyBytes : null;
    } catch (_) {
      return null;
    }
  }
}
