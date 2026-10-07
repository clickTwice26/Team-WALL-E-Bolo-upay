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

  Future<void> load() async {
    try {
      users = (await Api.users()).map((e) => Map<String, dynamic>.from(e)).toList();
      await refresh();
      error = null;
    } on ApiError catch (e) {
      error = e.status == 0 ? 'network' : e.toString();
    }
    notifyListeners();
  }

  Future<void> refresh() async {
    profile = await Api.user(userId);
    notifyListeners();
  }

  Future<void> switchUser(String id) async {
    userId = id;
    balanceVisible = false;
    await refresh();
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
