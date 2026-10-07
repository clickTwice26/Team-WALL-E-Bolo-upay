import 'package:flutter/material.dart';

import '../widgets/agent_icon.dart';

import '../api.dart';
import '../services/biometric.dart';
import '../state.dart';
import '../strings.dart';
import '../theme.dart';
import '../widgets/pin_pad.dart';

/// Yellow splash, then PIN unlock with the blue sky, clouds and yellow badge.
/// Uses our own Bolo upay mic mark, not the upay logo.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.onUnlocked});
  final VoidCallback onUnlocked;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  bool splash = true;
  String? error;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    Future.delayed(const Duration(milliseconds: 1400), () {
      if (mounted) setState(() => splash = false);
    });
  }

  Future<void> _submit(String pin) async {
    final bn = appState.bangla;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await Api.login(appState.userId, pin);
      await appState.refresh();
      Biometric.enroll(); // in the background: registers this phone's signing key
      widget.onUnlocked();
    } on ApiError catch (e) {
      final mins = (e.retryAfter / 60).ceil();
      setState(() => error = switch (e.status) {
            401 => tr(bn, 'ভুল পিন। ডেমো পিন ১২৩৪', 'Wrong PIN. Demo PIN is 1234'),
            423 => tr(bn, 'অনেকবার ভুল পিন। ${bnDigits('$mins')} মিনিট পর আবার চেষ্টা করুন।',
                'Too many wrong PINs. Try again in $mins minutes.'),
            _ => tr(bn, 'সার্ভারে সংযোগ হচ্ছে না', 'Cannot reach the server'),
          });
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Widget _badge(double size) => Container(
        width: size,
        height: size,
        decoration: const BoxDecoration(color: BrandColors.yellow, shape: BoxShape.circle),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          AgentIcon(size: size * 0.5),
          Text('বলো', style: TextStyle(color: BrandColors.navy, fontWeight: FontWeight.w800, fontSize: size * 0.16, height: 1)),
        ]),
      );

  Widget _cloud(double left, double top, double size) =>
      Positioned(left: left, top: top, child: Container(width: size, height: size, decoration: const BoxDecoration(color: Color(0xFFE9ECF2), shape: BoxShape.circle)));

  Widget _cloudW(double left, double top, double size) =>
      Positioned(left: left, top: top, child: Container(width: size, height: size, decoration: const BoxDecoration(color: Colors.white, shape: BoxShape.circle)));

  @override
  Widget build(BuildContext context) {
    if (splash) {
      return Scaffold(
        backgroundColor: BrandColors.yellow,
        body: Center(
          child: Container(
            width: 170,
            height: 170,
            decoration: const BoxDecoration(color: Colors.white, shape: BoxShape.circle),
            child: Column(mainAxisAlignment: MainAxisAlignment.center, children: const [
              AgentIcon(size: 96),
              Text('বলো upay', style: TextStyle(color: BrandColors.navy, fontWeight: FontWeight.w800, fontSize: 22)),
            ]),
          ),
        ),
      );
    }
    return ListenableBuilder(
      listenable: appState,
      builder: (context, _) {
        final bn = appState.bangla;
        final w = MediaQuery.of(context).size.width.clamp(0, 600).toDouble();
        return Scaffold(
          backgroundColor: Colors.white,
          body: Column(children: [
            SizedBox(
              height: 330,
              child: Stack(clipBehavior: Clip.hardEdge, children: [
                Positioned.fill(child: Container(color: BrandColors.navy)),
                Positioned(
                  right: 16,
                  top: MediaQuery.of(context).padding.top + 12,
                  child: TextButton(
                    onPressed: appState.toggleLanguage,
                    child: Text(bn ? 'English' : 'বাংলা', style: const TextStyle(color: Colors.white, fontSize: 16)),
                  ),
                ),
                for (final r in [140.0, 110.0])
                  Positioned(
                    left: w / 2 - r,
                    top: 175 - r,
                    child: Container(
                      width: r * 2,
                      height: r * 2,
                      decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: Colors.white24)),
                    ),
                  ),
                Positioned(left: w / 2 - 85, top: 90, child: _badge(170)),
                // clouds
                _cloud(-40, 230, 150), _cloud(w - 120, 215, 170), _cloud(w * 0.25, 250, 140),
                _cloudW(-60, 260, 170), _cloudW(w * 0.18, 240, 170), _cloudW(w * 0.5, 255, 160), _cloudW(w - 140, 250, 190),
                Positioned(left: 0, right: 0, bottom: 0, height: 30, child: Container(color: Colors.white)),
              ]),
            ),
            Expanded(
              child: SingleChildScrollView(
                child: Column(children: [
                  const SizedBox(height: 18),
                  if (busy) const LinearProgressIndicator(minHeight: 2),
                  PinPad(
                    bangla: bn,
                    error: error,
                    title: tr(bn, '৪ ডিজিট পিন', '4 Digit PIN'),
                    trailing: TextButton(
                      onPressed: () => ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(content: Text(tr(bn, 'ডেমো পিন: ১২৩৪', 'Demo PIN: 1234')))),
                      child: Text(tr(bn, 'পিন ভুলে গেছেন?', 'Forgot PIN?'),
                          style: const TextStyle(color: BrandColors.navy, fontSize: 16)),
                    ),
                    onSubmit: _submit,
                    autoFillPin: '1234',
                  ),
                ]),
              ),
            ),
          ]),
        );
      },
    );
  }
}
