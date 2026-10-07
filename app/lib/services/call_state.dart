import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../strings.dart';

/// R11: is the phone in a call right now? On Android, MainActivity.kt reads the
/// telephony call state plus the audio mode that WhatsApp and IMO calls set.
/// Only yes/no crosses the channel: never a number, never audio.
///
/// [inCall] is null when not measured (web, iOS, refused permission, or a build
/// without the channel); the app then falls back to the demo toggle.
class CallState {
  CallState._();
  static final CallState instance = CallState._();

  static const _methods = MethodChannel('bolo/call_state');
  // a separate name: an EventChannel on 'bolo/call_state' would replace the method handler
  static const _events = EventChannel('bolo/call_state/events');

  /// Live value; null = not measured.
  final ValueNotifier<bool?> inCall = ValueNotifier(null);
  StreamSubscription<dynamic>? _sub;
  bool _asked = false;

  static bool get supported => !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  /// Once per app run: explain why, ask Android for the permission, then follow
  /// the call state. A "not now" or a refusal leaves [inCall] null.
  Future<void> start(BuildContext context, {required bool bangla}) async {
    if (!supported || _asked) return;
    _asked = true;
    try {
      var ok = await _methods.invokeMethod<bool>('permission') ?? false;
      if (!ok) {
        if (!context.mounted || await _explain(context, bangla) != true) return;
        ok = await _methods.invokeMethod<bool>('requestPermission') ?? false;
      }
      if (!ok) return;
      _sub = _events.receiveBroadcastStream().listen((v) => inCall.value = v is bool ? v : null,
          onError: (_) => inCall.value = null);
    } on PlatformException {
      inCall.value = null;
    } on MissingPluginException {
      inCall.value = null;
    }
  }

  /// A fresh reading right before a risk check (the live stream polls the audio mode).
  Future<bool?> current() async {
    if (_sub == null) return null;
    try {
      inCall.value = await _methods.invokeMethod<bool>('inCall');
    } on PlatformException {
      // keep the last live value
    }
    return inCall.value;
  }

  /// Call audio on the loudspeaker (R10 speaker_echo), or null when not measured.
  Future<bool?> speakerOn() async {
    if (_sub == null) return null;
    try {
      return await _methods.invokeMethod<bool>('speakerOn');
    } on PlatformException {
      return null;
    }
  }

  Future<bool?> _explain(BuildContext context, bool bn) => showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text(tr(bn, 'আপনি ফোন কলে আছেন কিনা দেখার অনুমতি', 'Allow call detection')),
          content: Text(tr(
              bn,
              'প্রতারকেরা প্রায়ই ফোনে কথা বলতে বলতে টাকা পাঠাতে বলে। টাকা পাঠানোর সময় আপনি কলে '
                  '(ফোন, WhatsApp বা IMO) আছেন কিনা, বলো upay শুধু এটুকুই দেখবে। কে ফোন করেছে, নম্বর বা '
                  'কী কথা হচ্ছে, তা কখনো দেখা বা শোনা হয় না।\n\nঅ্যান্ড্রয়েড এই অনুমতিকে "ফোন কল করা ও '
                  'পরিচালনা" বলে, কিন্তু অ্যাপটি কোনো কল করে না।',
              'Scammers often keep people on the phone while they send money. While you pay, Bolo upay '
                  'only checks whether you are on a call (phone, WhatsApp or IMO). It never sees who called, '
                  'the number, or what is said.\n\nAndroid calls this permission "make and manage phone '
                  'calls", but the app never makes or manages calls.')),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr(bn, 'এখন না', 'Not now'))),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: Text(tr(bn, 'অনুমতি দিন', 'Allow'))),
          ],
        ),
      );
}
