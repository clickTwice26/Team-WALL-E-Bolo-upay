import 'package:biometric_signature/biometric_signature.dart';
import 'package:flutter/foundation.dart';
import 'package:local_auth/local_auth.dart';

import '../api.dart';

/// Face ID / Touch ID / fingerprint on iOS and Android.
/// Not available in the web build, which falls back to PIN.
///
/// A biometric approval is a signature, not a yes/no: after a PIN login the
/// phone creates a P-256 key in the Secure Enclave / Android Keystore that
/// only unlocks with the user's biometric, and registers its public key with
/// the server. To approve a transfer the phone signs the server's one-time
/// challenge with that key, and the server checks the signature.
class Biometric {
  static final _auth = LocalAuthentication();
  static final _keys = BiometricSignature();
  static const _alias = 'bolo_upay_pay';

  static Future<bool> available() async {
    if (kIsWeb) return false;
    try {
      return await _auth.isDeviceSupported() && await _auth.canCheckBiometrics;
    } catch (_) {
      return false;
    }
  }

  /// After a PIN login: make sure this phone's signing key exists and is
  /// registered for the signed-in user. Failure only means "use the PIN".
  static Future<void> enroll() async {
    if (!await available()) return;
    try {
      String? publicKey;
      if (await _keys.biometricKeyExists(keyAlias: _alias, checkValidity: true)) {
        publicKey = (await _keys.getKeyInfo(keyAlias: _alias)).publicKey;
      } else {
        await _keys.deleteKeys(keyAlias: _alias); // an invalidated key (biometrics changed)
        final r = await _keys.createKeys(
          keyAlias: _alias,
          config: CreateKeysConfig(
            signatureType: SignatureType.ecdsa,
            enforceBiometric: false,
            requireAuthentication: true,
            setInvalidatedByBiometricEnrollment: true,
            useDeviceCredentials: false,
          ),
        );
        if (r.code == BiometricError.success) publicKey = r.publicKey;
      }
      if (publicKey != null && publicKey.isNotEmpty) await Api.registerDevice(publicKey);
    } catch (_) {
      // no key, no registration: the server will ask for the PIN instead
    }
  }

  /// Shows the biometric prompt and signs [payload] with the device key.
  /// Returns {'signature', 'public_key'} for /api/execute, or null.
  static Future<Map<String, String>?> sign(String payload, String reason) async {
    if (!await available()) return null;
    try {
      final r = await _keys.createSignature(
        payload: payload,
        keyAlias: _alias,
        promptMessage: reason,
        config: CreateSignatureConfig(allowDeviceCredentials: false),
      );
      final sig = r.signature, key = r.publicKey;
      if (r.code != BiometricError.success || sig == null || key == null) return null;
      return {'signature': sig, 'public_key': key};
    } catch (_) {
      return null;
    }
  }
}
