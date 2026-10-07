import 'package:flutter/foundation.dart';

import 'api.dart';
import 'services/call_state.dart';

/// App-wide state: selected demo user, language and demo toggles.
class AppState extends ChangeNotifier {
  AppState() {
    CallState.instance.inCall.addListener(notifyListeners);
  }

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

  /// Demo site: the server lists demo personas only with DEMO_MODE.
  bool get demo => users.isNotEmpty;

  /// The "simulate call" toggle exists only on web and on a demo site.
  bool get callToggle => kIsWeb || demo;

  /// R11: the phone's own call state (Android with permission), null when not measured.
  bool? get nativeCall => CallState.instance.inCall.value;

  /// On a call: the native value, or the demo toggle (which can only add a call, for demos).
  bool get onCall => (nativeCall ?? false) || (callToggle && simulateCall);

  /// "native" when the phone measured it, unless the demo toggle added a call it did not see.
  String get callSource {
    final n = nativeCall;
    if (n == null) return 'simulated';
    return n || !(callToggle && simulateCall) ? 'native' : 'simulated';
  }

  /// A fresh native reading right before a risk check.
  Future<void> refreshCall() => CallState.instance.current();

  num get balance => (profile?['balance'] as num?) ?? 0;
  List<Map<String, dynamic>> get contacts =>
      ((profile?['contacts'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e)).toList();

  /// Saved bill accounts (DESCO, Titas, WASA ...): the payees of a bill payment.
  List<Map<String, dynamic>> get billers =>
      ((profile?['billers'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e)).toList();
}

final appState = AppState();
