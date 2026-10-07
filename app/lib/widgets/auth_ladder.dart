import 'package:flutter/material.dart';

import '../strings.dart';
import '../theme.dart';

/// The three approval steps, lowest risk first. The server sends the step a
/// transfer needs (`auth_required`) and enforces it on /api/execute, so this
/// widget only shows what the server already decided.
const _steps = [
  ('biometric_or_pin', 'GREEN', Icons.fingerprint_rounded),
  ('pin', 'YELLOW', Icons.dialpad_rounded),
  ('hold_then_pin', 'RED', Icons.hourglass_top_rounded),
];

String _stepTitle(String step, bool bn, int holdSeconds) => switch (step) {
      'biometric_or_pin' => tr(bn, 'ফিঙ্গারপ্রিন্ট বা পিন', 'Fingerprint or PIN'),
      'pin' => tr(bn, 'পিন', 'PIN'),
      _ => tr(bn, '${bnDigits('$holdSeconds')} সেকেন্ড অপেক্ষা, সতর্কতা, পিন', '${holdSeconds}s hold, warning, PIN'),
    };

String _stepRisk(String step, bool bn) => switch (step) {
      'biometric_or_pin' => tr(bn, 'কম ঝুঁকি', 'Low risk'),
      'pin' => tr(bn, 'মাঝারি ঝুঁকি', 'Medium risk'),
      _ => tr(bn, 'বেশি ঝুঁকি', 'High risk'),
    };

/// Shows which approval this transfer needs on a 3-step ladder:
/// fingerprint or PIN → PIN → hold + warning + PIN. Tap it to see why.
class AuthLadder extends StatelessWidget {
  const AuthLadder({
    super.key,
    required this.authRequired,
    required this.bangla,
    this.reasons = const [],
    this.holdSeconds = 30,
    this.biometricAvailable = true,
  });

  /// `auth_required` from /api/assess: biometric_or_pin | pin | hold_then_pin.
  final String authRequired;
  final bool bangla;

  /// The warning's reasons ({'bn', 'en'}), shown in the explanation.
  final List<Map<String, dynamic>> reasons;
  final int holdSeconds;

  /// False on the web build and on phones without biometrics: the first step
  /// then reads "PIN" for this transfer.
  final bool biometricAvailable;

  int get _current => _steps.indexWhere((s) => s.$1 == authRequired).clamp(0, _steps.length - 1);

  @override
  Widget build(BuildContext context) {
    final bn = bangla;
    final cur = _current;
    final level = _steps[cur].$2;
    return Semantics(
      button: true,
      label: tr(bn, 'অনুমোদনের ধাপ: ${_stepTitle(_steps[cur].$1, bn, holdSeconds)}',
          'Approval needed: ${_stepTitle(_steps[cur].$1, bn, holdSeconds)}'),
      child: Material(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        child: InkWell(
          key: const ValueKey('auth_ladder'),
          borderRadius: BorderRadius.circular(14),
          onTap: () => showAuthLadderSheet(context,
              authRequired: authRequired, bangla: bn, reasons: reasons, holdSeconds: holdSeconds),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                Icon(Icons.verified_user_outlined, size: 18, color: levelColor(level)),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(tr(bn, 'ঝুঁকি অনুযায়ী অনুমোদন', 'Approval matches the risk'),
                      style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14)),
                ),
                Text(tr(bn, 'কেন?', 'Why?'),
                    style: const TextStyle(color: BrandColors.navy, fontWeight: FontWeight.w600, fontSize: 13)),
                const Icon(Icons.chevron_right_rounded, size: 18, color: BrandColors.navy),
              ]),
              const SizedBox(height: 10),
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                for (var i = 0; i < _steps.length; i++) ...[
                  Expanded(child: _step(i, cur, bn)),
                  if (i < _steps.length - 1)
                    Padding(
                      padding: const EdgeInsets.only(top: 17),
                      child: Icon(Icons.arrow_forward_rounded, size: 14,
                          color: i < cur ? levelColor(_steps[cur].$2) : BrandColors.muted.withValues(alpha: 0.5)),
                    ),
                ],
              ]),
            ]),
          ),
        ),
      ),
    );
  }

  Widget _step(int i, int cur, bool bn) {
    final (id, level, icon) = _steps[i];
    final on = i == cur;
    final c = on ? levelColor(level) : BrandColors.muted;
    final title = i == 0 && !biometricAvailable && on ? tr(bn, 'পিন', 'PIN') : _stepTitle(id, bn, holdSeconds);
    return Column(children: [
      Container(
        width: 40,
        height: 40,
        decoration: BoxDecoration(
          color: on ? levelBg(level) : BrandColors.bg,
          shape: BoxShape.circle,
          border: Border.all(color: on ? c : BrandColors.bg, width: 2),
        ),
        child: Icon(icon, size: 22, color: c.withValues(alpha: on ? 1 : 0.6)),
      ),
      const SizedBox(height: 4),
      Text(title,
          textAlign: TextAlign.center,
          style: TextStyle(
              fontSize: 12, height: 1.2, fontWeight: on ? FontWeight.w700 : FontWeight.w500,
              color: on ? BrandColors.text : BrandColors.muted)),
      Text(_stepRisk(id, bn),
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 11, color: on ? c : BrandColors.muted.withValues(alpha: 0.8))),
    ]);
  }
}

/// Why this transfer needs this approval, and what moves a transfer up the ladder.
Future<void> showAuthLadderSheet(BuildContext context,
    {required String authRequired,
    required bool bangla,
    List<Map<String, dynamic>> reasons = const [],
    int holdSeconds = 30}) {
  final bn = bangla;
  final step = _steps.firstWhere((s) => s.$1 == authRequired, orElse: () => _steps.first);
  final why = switch (step.$1) {
    'biometric_or_pin' => tr(bn, 'এই লেনদেনে ঝুঁকির কোনো লক্ষণ পাওয়া যায়নি, তাই ফিঙ্গারপ্রিন্ট বা পিন যথেষ্ট।',
        'This transfer shows no risk signs, so a fingerprint or your PIN is enough.'),
    'pin' => tr(bn, 'কিছু অস্বাভাবিক লক্ষণ আছে, তাই শুধু ফিঙ্গারপ্রিন্ট যথেষ্ট নয়: পিন লাগবে।',
        'Something looks unusual, so a fingerprint alone is not enough: your PIN is needed.'),
    _ => tr(bn, 'প্রতারণার জোরালো লক্ষণ আছে। ${bnDigits('$holdSeconds')} সেকেন্ড অপেক্ষা আপনাকে ফোন কেটে যাচাই করার সময় দেয়। তারপর সতর্কবার্তায় টিক দিয়ে পিন দিলে পাঠাতে পারবেন।',
        'There are strong scam signs. The $holdSeconds-second hold gives you time to hang up and check. After that you can still send by ticking the warning and entering your PIN.'),
  };
  return showModalBottomSheet(
    context: context,
    showDragHandle: true,
    isScrollControlled: true,
    builder: (ctx) => SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: MediaQuery.of(ctx).size.height * 0.8),
        child: ListView(shrinkWrap: true, padding: const EdgeInsets.fromLTRB(20, 0, 20, 20), children: [
          Text(tr(bn, 'কেন এই অনুমোদন?', 'Why this approval?'),
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          Text(why),
          if (reasons.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text(tr(bn, 'এই লেনদেনে যা পাওয়া গেছে', 'What this transfer showed'),
                style: const TextStyle(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            for (final r in reasons)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Padding(
                      padding: const EdgeInsets.only(top: 7),
                      child: Icon(Icons.circle, size: 7, color: levelColor(step.$2))),
                  const SizedBox(width: 8),
                  Expanded(child: Text('${bn ? r['bn'] : r['en']}')),
                ]),
              ),
          ],
          const SizedBox(height: 16),
          Text(tr(bn, 'কী লেনদেনকে উপরের ধাপে তোলে', 'What moves a transfer up'),
              style: const TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          _rung(bn, 'pin', holdSeconds,
              tr(bn, 'নতুন নম্বর, আপনার জন্য অস্বাভাবিক পরিমাণ বা সময়, চলমান ফোন কল, অল্প সময়ে অনেক লেনদেন, বা পরিমাণে সম্ভাব্য ভুল (একটা বাড়তি শূন্য)।',
                  'A new number, an amount or time of day unusual for you, an active phone call, many payments in a short time, or a likely typo (an extra zero).')),
          _rung(bn, 'hold_then_pin', holdSeconds,
              tr(bn, 'কেউ পিন বা ওটিপি চেয়েছে, উপায় অফিসের লোক সেজে ফোন, লটারি বা ফি, টাকা না এসেও "ভুলে পাঠিয়েছি, ফেরত দিন", নতুন নম্বর থেকে "আত্মীয় বিপদে", বা রাতে নতুন এজেন্টে প্রায় সব টাকা ক্যাশ আউট।',
                  'Someone asked for your PIN or OTP, a caller posing as upay staff, a lottery or fee, "sent by mistake, send it back" when no money came, a "relative in trouble" from a new number, or cashing out most of the balance at night at a new agent.')),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: BrandColors.bg, borderRadius: BorderRadius.circular(12)),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Icon(Icons.dns_outlined, size: 20, color: BrandColors.navy),
              const SizedBox(width: 8),
              Expanded(
                child: Text(tr(bn, 'এই ধাপ উপায়ের সার্ভার ঠিক করে ও যাচাই করে। অ্যাপ বা এআই এজেন্ট এটা এড়াতে পারে না।',
                    "upay's server decides and checks this step. Neither the app nor the AI agent can skip it.")),
              ),
            ]),
          ),
        ]),
      ),
    ),
  );
}

Widget _rung(bool bn, String step, int holdSeconds, String text) {
  final s = _steps.firstWhere((x) => x.$1 == step);
  return Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Icon(s.$3, size: 20, color: levelColor(s.$2)),
      const SizedBox(width: 8),
      Expanded(
        child: Text.rich(TextSpan(children: [
          TextSpan(text: '${_stepTitle(step, bn, holdSeconds)}: ', style: const TextStyle(fontWeight: FontWeight.w700)),
          TextSpan(text: text),
        ])),
      ),
    ]),
  );
}
