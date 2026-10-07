import 'package:flutter/foundation.dart';

import 'api.dart';

/// App-wide state: selected demo user, language and demo toggles.
class AppState extends ChangeNotifier {
  List<Map<String, dynamic>> users = [];
  Map<String, dynamic>? profile;
  String userId = 'u1';
  bool bangla = true;
  bool simulateCall = false;
  bool balanceVisible = false;
  String? error;

  /// Demo personas (before the PIN screen), and the profile once signed in.
  Future<void> load() async {
    try {
      users = (await Api.users()).map((e) => Map<String, dynamic>.from(e)).toList();
      if (Session.token != null) await refresh();
      error = null;
    } on ApiError catch (e) {
      error = e.status == 0 ? 'network' : e.toString();
    }
    notifyListeners();
  }

  /// The signed-in user's profile (needs a session).
  Future<void> refresh() async {
    profile = await Api.me();
    userId = '${profile!['id']}';
    notifyListeners();
  }

  /// Demo only: the server gives a session for the other persona.
  Future<void> switchUser(String id) async {
    await Api.demoSwitch(id);
    userId = id;
    balanceVisible = false;
    await refresh();
  }

  /// The session ended: forget the profile until the next PIN unlock.
  void signedOut() {
    profile = null;
    balanceVisible = false;
    notifyListeners();
  }

  void toggleLanguage() {
    bangla = !bangla;
    notifyListeners();
  }

  void setLanguage(bool bn) {
    bangla = bn;
    notifyListeners();
  }

  void setBalanceVisible(bool v) {
    balanceVisible = v;
    notifyListeners();
  }

  void setSimulateCall(bool v) {
    simulateCall = v;
    notifyListeners();
  }

  void toggleBalance() {
    balanceVisible = !balanceVisible;
    notifyListeners();
  }

  num get balance => (profile?['balance'] as num?) ?? 0;
  List<Map<String, dynamic>> get contacts =>
      ((profile?['contacts'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e)).toList();
}

final appState = AppState();
