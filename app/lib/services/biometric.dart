import 'package:flutter/foundation.dart';
import 'package:local_auth/local_auth.dart';

/// Face ID / Touch ID / fingerprint on iOS and Android.
/// Not available in the web build, which falls back to PIN.
class Biometric {
  static final _auth = LocalAuthentication();

  static Future<bool> available() async {
    if (kIsWeb) return false;
    try {
      return await _auth.isDeviceSupported() && await _auth.canCheckBiometrics;
    } catch (_) {
      return false;
    }
  }

  static Future<bool> authenticate(String reason) async {
    if (kIsWeb) return false;
    try {
      return await _auth.authenticate(localizedReason: reason, biometricOnly: true);
    } catch (_) {
      return false;
    }
  }
}
