import '../api.dart';

/// Support console calls. Staff sign in to a named account; every call carries
/// that account's staff token, and the server takes the agent's name from it.
/// A 401 means the session ended, and the console signs the agent out.
class ConsoleApi {
  ConsoleApi(this.token, this.agent);
  final String token;
  final String agent; // shown to the customer (from the sign-in)

  Map<String, String> get _h => {'Authorization': 'Bearer $token'};

  /// Signs in; returns the session for [name] or throws ApiError (401, 503).
  static Future<ConsoleApi> login(String name, String password) async {
    final r = await apiRequest('POST', '/api/console/login', body: {'name': name, 'token': password});
    return ConsoleApi('${r['token']}', '${r['name']}');
  }

  Future<Map<String, dynamic>> list() async =>
      Map<String, dynamic>.from(await apiRequest('GET', '/api/console/handoffs', headers: _h));

  Future<Map<String, dynamic>> detail(String id, {int after = 0}) async =>
      Map<String, dynamic>.from(await apiRequest('GET', '/api/console/handoffs/$id?after=$after', headers: _h));

  Future<void> claim(String id) => apiRequest('POST', '/api/console/handoffs/$id/claim', headers: _h);

  Future<void> send(String id, String text) =>
      apiRequest('POST', '/api/console/handoffs/$id/messages', body: {'text': text}, headers: _h);

  Future<void> close(String id, String resolution) =>
      apiRequest('POST', '/api/console/handoffs/$id/close', body: {'resolution': resolution}, headers: _h);

  /// Protective only: stops the customer's own pending transfer.
  Future<void> stopTransfer(String id, String assessmentId) => apiRequest('POST',
      '/api/console/handoffs/$id/cancel-transfer', body: {'assessment_id': assessmentId}, headers: _h);
}
