import '../api.dart';

/// Support console calls. Every call carries the access code; a 401 means the
/// code is wrong or changed, and the console signs the agent out.
class ConsoleApi {
  ConsoleApi(this.token, this.agent);
  final String token;
  final String agent; // shown to the customer

  Map<String, String> get _h => {'X-Console-Token': token};

  static Future<String> login(String name, String token) async =>
      '${(await apiRequest('POST', '/api/console/login', body: {'name': name, 'token': token}))['name']}';

  Future<Map<String, dynamic>> list() async =>
      Map<String, dynamic>.from(await apiRequest('GET', '/api/console/handoffs', headers: _h));

  Future<Map<String, dynamic>> detail(String id, {int after = 0}) async =>
      Map<String, dynamic>.from(await apiRequest('GET', '/api/console/handoffs/$id?after=$after', headers: _h));

  Future<void> claim(String id) =>
      apiRequest('POST', '/api/console/handoffs/$id/claim', body: {'agent': agent}, headers: _h);

  Future<void> send(String id, String text) =>
      apiRequest('POST', '/api/console/handoffs/$id/messages', body: {'agent': agent, 'text': text}, headers: _h);

  Future<void> close(String id, String resolution) => apiRequest('POST', '/api/console/handoffs/$id/close',
      body: {'agent': agent, 'resolution': resolution}, headers: _h);

  /// Protective only: stops the customer's own pending transfer.
  Future<void> stopTransfer(String id, String assessmentId) => apiRequest('POST',
      '/api/console/handoffs/$id/cancel-transfer', body: {'agent': agent, 'assessment_id': assessmentId}, headers: _h);
}
