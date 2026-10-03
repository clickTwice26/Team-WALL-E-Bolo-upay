import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../services/biometric.dart';
import '../services/voice.dart';
import '../state.dart';
import '../strings.dart';
import '../theme.dart';
import '../widgets/pin_pad.dart';

enum _Step { input, parsing, clarify, assessing, interview, review, hold, auth, working, done }

/// The Bolo upay flow:
/// speak -> parse -> (clarify) -> risk check -> (scam interview) -> confirm
/// -> (hold) -> PIN / biometric -> result.
class AssistantScreen extends StatefulWidget {
  const AssistantScreen({super.key, this.initialText});
  final String? initialText;

  @override
  State<AssistantScreen> createState() => _AssistantScreenState();
}

class _AssistantScreenState extends State<AssistantScreen> {
  final _text = TextEditingController();
  final _answer = TextEditingController();
  final _amountField = TextEditingController();
  final _phoneField = TextEditingController();

  _Step step = _Step.input;
  bool listening = false;
  String? message;
  Map<String, dynamic>? parsed;
  Map<String, dynamic>? draft; // intent, amount, recipient_phone, is_return_claim, command_text
  Map<String, dynamic>? recipient; // display info
  Map<String, dynamic>? assessment;
  List<String> answers = [];
  int questionIndex = 0;
  bool acknowledged = false;
  int holdLeft = 0;
  Timer? _timer;
  String? pinError;
  bool biometricOk = false;
  Map<String, dynamic>? doneInfo;

  bool get bn => appState.bangla;
  String get uid => appState.userId;

  @override
  void initState() {
    super.initState();
    Biometric.available().then((v) => setState(() => biometricOk = v));
    if (widget.initialText != null) {
      _text.text = widget.initialText!;
      WidgetsBinding.instance.addPostFrameCallback((_) => _submit());
    } else {
      WidgetsBinding.instance.addPostFrameCallback((_) => _say(tr(bn, 'বলুন, কাকে কত টাকা পাঠাবেন?', 'Say who to send money to, and how much.')));
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    Voice.instance.stop();
    Voice.instance.silence();
    super.dispose();
  }

  void _say(String s) => Voice.instance.speak(s, bangla: bn);

  // ---------------- voice ----------------
  Future<void> _toggleMic(TextEditingController target, {VoidCallback? onDone}) async {
    if (listening) {
      await Voice.instance.stop();
      setState(() => listening = false);
      return;
    }
    await Voice.instance.silence();
    final ok = await Voice.instance.init();
    if (!ok) {
      setState(() => message = tr(bn, 'এই ডিভাইসে ভয়েস চালু নেই। লিখে দিন।',
          'Voice input is not available here. Please type instead.'));
      return;
    }
    setState(() {
      listening = true;
      message = null;
    });
    await Voice.instance.listen(
      bangla: bn,
      onText: (t, done) {
        if (!mounted) return;
        setState(() {
          target.text = t;
          if (done) listening = false;
        });
        if (done && t.trim().isNotEmpty) onDone?.call();
      },
    );
  }

  // ---------------- parse ----------------
  Future<void> _submit() async {
    final t = _text.text.trim();
    if (t.isEmpty) return;
    setState(() {
      step = _Step.parsing;
      message = null;
    });
    try {
      final p = await Api.parse(uid, t);
      parsed = p;
      draft = {
        'intent': p['intent'],
        'amount': p['amount'],
        'recipient_phone': (p['recipient'] as Map?)?['phone'] ?? p['new_number'],
        'is_return_claim': p['is_return_claim'] ?? false,
        'command_text': t,
      };
      recipient = p['recipient'] != null
          ? Map<String, dynamic>.from(p['recipient'])
          : (p['new_number'] != null ? {'name': null, 'phone': p['new_number']} : null);
      final status = p['status'] as String;
      if (status == 'ok') {
        if (p['intent'] == 'check_balance') {
          await appState.refresh();
          final s = tr(bn, 'আপনার ব্যালেন্স ${taka(appState.balance, true)}',
              'Your balance is ${taka(appState.balance, false)}');
          _say(s);
          setState(() {
            doneInfo = {'kind': 'balance', 'text': s};
            step = _Step.done;
          });
          return;
        }
        await _assess();
      } else if (status == 'unsupported' || status == 'unknown') {
        final q = bn ? p['question_bn'] : p['question_en'];
        _say(q ?? '');
        setState(() {
          message = q;
          step = _Step.input;
        });
      } else {
        final q = bn ? p['question_bn'] : p['question_en'];
        _say(q ?? '');
        setState(() => step = _Step.clarify);
      }
    } on ApiError catch (e) {
      _fail(e);
    }
  }

  void _fail(ApiError e) {
    setState(() {
      step = _Step.input;
      message = e.status == 0
          ? tr(bn, 'সার্ভারে সংযোগ হচ্ছে না। আবার চেষ্টা করুন।', 'Cannot reach the server. Try again.')
          : tr(bn, 'কিছু একটা সমস্যা হয়েছে (${e.status})।', 'Something went wrong (${e.status}).');
    });
  }

  bool get _clarifyReady =>
      draft?['amount'] != null && draft?['recipient_phone'] != null && draft?['intent'] != null;

  // ---------------- risk ----------------
  Future<void> _assess() async {
    setState(() => step = _Step.assessing);
    try {
      final a = await Api.assess(uid, draft!, onCall: appState.simulateCall, answers: answers);
      assessment = a;
      final level = a['level'];
      if (level == 'BLOCKED') {
        final m = bn ? a['message_bn'] : a['message_en'];
        _say(m);
        setState(() {
          message = m;
          step = _Step.input;
        });
        return;
      }
      if (a['needs_interview'] == true) {
        questionIndex = 0;
        _answer.clear();
        setState(() => step = _Step.interview);
        _askQuestion();
        return;
      }
      setState(() {
        step = _Step.review;
        acknowledged = false;
        pinError = null;
      });
      _readBack();
    } on ApiError catch (e) {
      _fail(e);
    }
  }

  void _readBack() {
    final a = assessment!;
    final amt = taka(draft!['amount'], bn);
    final who = _recipientName();
    final base = draft!['intent'] == 'mobile_recharge'
        ? tr(bn, '$who নম্বরে $amt রিচার্জ।', 'Recharge $amt to $who.')
        : tr(bn, '$who কে $amt পাঠানো হবে।', 'Sending $amt to $who.');
    final lvl = a['level'];
    final warn = lvl == 'GREEN' ? '' : ' ${bn ? a['advice_bn'] : a['advice_en']}';
    _say('$base$warn');
  }

  String _recipientName() {
    final r = recipient;
    if (r == null) return '';
    if (r['relation'] == 'self') return tr(bn, 'আপনার নিজের', 'your own number');
    if (r['name'] == null) return bn ? bnDigits(maskPhone(r['phone'])) : maskPhone(r['phone']);
    return bn ? (r['name_bn'] ?? r['name']) : r['name'];
  }

  // ---------------- interview ----------------
  List get _questions => (assessment?['interview'] as List?) ?? [];

  void _askQuestion() {
    final q = _questions[questionIndex];
    _say(bn ? q['bn'] : q['en']);
  }

  Future<void> _submitAnswer(String a) async {
    if (a.trim().isEmpty) return;
    answers = [...answers, a.trim()];
    _answer.clear();
    if (questionIndex + 1 < _questions.length) {
      setState(() => questionIndex++);
      _askQuestion();
    } else {
      await _assess();
    }
  }

  // ---------------- confirm / hold / auth ----------------
  void _continueFromReview() {
    final level = assessment!['level'];
    if (level == 'RED') {
      final secs = (assessment!['hold_seconds'] as num?)?.toInt() ?? 30;
      setState(() {
        step = _Step.hold;
        holdLeft = secs;
      });
      _timer?.cancel();
      _timer = Timer.periodic(const Duration(seconds: 1), (t) {
        if (!mounted) return t.cancel();
        setState(() => holdLeft = holdLeft > 0 ? holdLeft - 1 : 0);
        if (holdLeft == 0) t.cancel();
      });
    } else {
      setState(() => step = _Step.auth);
    }
  }

  Future<void> _useBiometric() async {
    final ok = await Biometric.authenticate(tr(bn, 'লেনদেন নিশ্চিত করুন', 'Confirm the transaction'));
    if (ok) await _execute('biometric');
  }

  Future<void> _execute(String method, {String? pin}) async {
    setState(() {
      step = _Step.working;
      pinError = null;
    });
    try {
      final r = await Api.execute(uid, assessment!['assessment_id'], method,
          pin: pin, acknowledged: acknowledged);
      await appState.refresh();
      final tx = Map<String, dynamic>.from(r['transaction']);
      final s = tr(bn, 'সফল হয়েছে! নতুন ব্যালেন্স ${taka(tx['balance'], true)}',
          'Done! New balance ${taka(tx['balance'], false)}');
      _say(s);
      setState(() {
        doneInfo = {'kind': 'sent', 'text': s, 'tx': tx};
        step = _Step.done;
      });
    } on ApiError catch (e) {
      if (e.status == 401) {
        final left = e.detail is Map ? e.detail['attempts_left'] : 0;
        setState(() {
          step = left == 0 ? _Step.done : _Step.auth;
          pinError = tr(bn, 'ভুল পিন। আর ${bnDigits('$left')} বার চেষ্টা করা যাবে।', 'Wrong PIN. $left attempts left.');
          if (left == 0) {
            doneInfo = {'kind': 'locked', 'text': tr(bn, 'অনেকবার ভুল পিন। লেনদেন বাতিল।', 'Too many wrong PINs. Cancelled.')};
          }
        });
      } else if (e.status == 425) {
        setState(() => step = _Step.hold);
      } else {
        _fail(e);
      }
    }
  }

  Future<void> _cancel() async {
    if (assessment != null) {
      try {
        await Api.cancel(uid, assessment!['assessment_id']);
      } on ApiError catch (_) {}
    }
    final red = assessment?['level'] == 'RED' || assessment?['level'] == 'YELLOW';
    final s = red
        ? tr(bn, 'লেনদেন বাতিল করা হয়েছে। আপনি নিরাপদে আছেন।', 'Cancelled. Your money is safe.')
        : tr(bn, 'লেনদেন বাতিল করা হয়েছে।', 'Cancelled.');
    _say(s);
    setState(() {
      doneInfo = {'kind': 'cancelled', 'text': s, 'protected': red};
      step = _Step.done;
    });
  }

  void _restart() {
    _timer?.cancel();
    setState(() {
      step = _Step.input;
      parsed = null;
      draft = null;
      recipient = null;
      assessment = null;
      answers = [];
      doneInfo = null;
      message = null;
      _text.clear();
    });
  }

  // ================= UI =================
  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: appState,
      builder: (context, _) => Scaffold(
        appBar: AppBar(
          title: const Text('বলো upay', style: TextStyle(fontWeight: FontWeight.w700)),
          actions: [
            TextButton(
              onPressed: appState.toggleLanguage,
              child: Text(bn ? 'EN' : 'বাংলা', style: const TextStyle(color: Colors.white)),
            ),
          ],
        ),
        body: SafeArea(
          child: AnimatedSwitcher(
            duration: const Duration(milliseconds: 220),
            child: SingleChildScrollView(
              key: ValueKey(step),
              padding: const EdgeInsets.all(16),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 560),
                child: _body(),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _body() => switch (step) {
        _Step.input => _inputView(),
        _Step.parsing || _Step.assessing || _Step.working => _loading(),
        _Step.clarify => _clarifyView(),
        _Step.interview => _interviewView(),
        _Step.review => _reviewView(),
        _Step.hold => _holdView(),
        _Step.auth => _authView(),
        _Step.done => _doneView(),
      };

  Widget _loading() => Padding(
        padding: const EdgeInsets.only(top: 120),
        child: Center(
          child: Column(children: [
            const CircularProgressIndicator(),
            const SizedBox(height: 16),
            Text(step == _Step.assessing
                ? tr(bn, 'নিরাপত্তা যাচাই হচ্ছে...', 'Running safety check...')
                : tr(bn, 'একটু অপেক্ষা করুন...', 'Please wait...')),
          ]),
        ),
      );

  Widget _micButton(TextEditingController target, {VoidCallback? onDone, double size = 96}) {
    return GestureDetector(
      onTap: () => _toggleMic(target, onDone: onDone),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 300),
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: listening ? BrandColors.red : BrandColors.navy,
          boxShadow: [
            BoxShadow(
              color: (listening ? BrandColors.red : BrandColors.navy).withValues(alpha: 0.35),
              blurRadius: listening ? 28 : 14,
              spreadRadius: listening ? 6 : 1,
            )
          ],
        ),
        child: Icon(listening ? Icons.stop_rounded : Icons.mic_rounded, color: Colors.white, size: size * 0.45),
      ),
    );
  }

  Widget _inputView() {
    final examples = bn
        ? ['আম্মুকে ৫০০ টাকা পাঠাও', 'রহিম ভাইকে দেড় হাজার টাকা দাও', 'আমার নম্বরে ৫০ টাকা রিচার্জ', 'ব্যালেন্স কত?']
        : ['Ammu ke 500 taka pathao', 'Rahim bhai ke der hajar dao', 'amar number e 50 taka recharge', 'balance koto'];
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const SizedBox(height: 8),
      Text(tr(bn, 'বলুন, কাকে কত টাকা পাঠাবেন', 'Say who to pay and how much'),
          textAlign: TextAlign.center, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700)),
      const SizedBox(height: 6),
      Text(tr(bn, 'বাংলা, ইংরেজি বা বাংলিশ, যেভাবে খুশি', 'Bangla, English or Banglish'),
          textAlign: TextAlign.center, style: const TextStyle(color: BrandColors.muted)),
      const SizedBox(height: 28),
      Center(child: _micButton(_text, onDone: _submit)),
      const SizedBox(height: 10),
      Text(
          listening
              ? tr(bn, 'শুনছি...', 'Listening...')
              : tr(bn, 'মাইকে চাপ দিয়ে বলুন', 'Tap the mic and speak'),
          textAlign: TextAlign.center,
          style: TextStyle(color: listening ? BrandColors.red : BrandColors.muted, fontWeight: FontWeight.w600)),
      const SizedBox(height: 24),
      TextField(
        controller: _text,
        minLines: 1,
        maxLines: 3,
        textInputAction: TextInputAction.send,
        onSubmitted: (_) => _submit(),
        decoration: InputDecoration(
          filled: true,
          fillColor: Colors.white,
          hintText: tr(bn, 'অথবা এখানে লিখুন (ভুল শুনলে ঠিক করে দিন)', 'Or type here (fix anything misheard)'),
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide.none),
          suffixIcon: IconButton(icon: const Icon(Icons.send_rounded), onPressed: _submit),
        ),
      ),
      if (message != null) ...[
        const SizedBox(height: 12),
        _note(message!, BrandColors.amberBg, BrandColors.amber, Icons.info_outline),
      ],
      const SizedBox(height: 20),
      Text(tr(bn, 'উদাহরণ', 'Try saying'), style: const TextStyle(fontWeight: FontWeight.w600, color: BrandColors.muted)),
      const SizedBox(height: 8),
      Wrap(spacing: 8, runSpacing: 8, children: [
        for (final e in examples)
          ActionChip(
            label: Text(e),
            backgroundColor: Colors.white,
            onPressed: () {
              _text.text = e;
              _submit();
            },
          ),
      ]),
      const SizedBox(height: 20),
      _privacyNote(),
    ]);
  }

  Widget _privacyNote() => _note(
      tr(bn, 'আপনার কথা শুধু লেখায় রূপান্তর হয়। অডিও সংরক্ষণ হয় না। AI কখনো নিজে টাকা পাঠায় না, আপনার পিন লাগবেই।',
          'Only the transcript is used, audio is never stored. The AI never sends money on its own: your PIN is always required.'),
      Colors.white,
      BrandColors.muted,
      Icons.lock_outline);

  Widget _note(String text, Color bg, Color fg, IconData icon) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(12)),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(icon, color: fg, size: 20),
          const SizedBox(width: 10),
          Expanded(child: Text(text, style: TextStyle(color: fg == BrandColors.muted ? BrandColors.text : fg))),
        ]),
      );

  Widget _heardCard() => Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(children: [
            const Icon(Icons.record_voice_over_outlined, color: BrandColors.navy),
            const SizedBox(width: 10),
            Expanded(child: Text('"${_text.text}"', style: const TextStyle(fontStyle: FontStyle.italic))),
            TextButton(onPressed: _restart, child: Text(tr(bn, 'আবার বলুন', 'Redo'))),
          ]),
        ),
      );

  Widget _clarifyView() {
    final p = parsed!;
    final status = p['status'];
    final q = bn ? p['question_bn'] : p['question_en'];
    final children = <Widget>[
      _heardCard(),
      const SizedBox(height: 16),
      Text(q ?? '', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
      const SizedBox(height: 12),
    ];

    if (status == 'clarify_amount' || status == 'need_amount') {
      final cands = ((p['amount_candidates'] as List?) ?? []).cast<num>();
      children.add(Wrap(spacing: 10, runSpacing: 10, children: [
        for (final c in cands)
          ChoiceChip(
            label: Text(taka(c, bn), style: const TextStyle(fontSize: 18)),
            selected: draft!['amount'] == c,
            onSelected: (_) => setState(() => draft!['amount'] = c.toInt()),
          ),
      ]));
      children.add(const SizedBox(height: 12));
      children.add(TextField(
        controller: _amountField,
        keyboardType: TextInputType.number,
        decoration: InputDecoration(
            filled: true,
            fillColor: Colors.white,
            prefixText: '৳ ',
            hintText: tr(bn, 'পরিমাণ লিখুন', 'Type the amount'),
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide.none)),
        onChanged: (v) => setState(() => draft!['amount'] = int.tryParse(v.trim())),
      ));
    }

    if (status == 'clarify_recipient' || status == 'confirm_recipient' ||
        (status == 'need_recipient') || draft!['recipient_phone'] == null) {
      final cands = status == 'confirm_recipient'
          ? [p['recipient']]
          : (status == 'clarify_recipient' ? (p['recipient_candidates'] as List) : appState.contacts);
      children.add(const SizedBox(height: 8));
      for (final c in cands) {
        final m = Map<String, dynamic>.from(c);
        final selected = draft!['recipient_phone'] == m['phone'] && status != 'confirm_recipient'
            ? true
            : (status == 'confirm_recipient' && recipient?['confirmed'] == true);
        children.add(Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Card(
            child: ListTile(
              leading: CircleAvatar(
                  backgroundColor: BrandColors.yellow,
                  child: Text(((bn ? m['name_bn'] : m['name']) ?? '?').toString().characters.first,
                      style: const TextStyle(color: BrandColors.navy, fontWeight: FontWeight.w700))),
              title: Text((bn ? m['name_bn'] : m['name']) ?? maskPhone(m['phone'])),
              subtitle: Text('${m['relation'] ?? ''} · ${maskPhone(m['phone'])}'),
              trailing: Icon(selected ? Icons.check_circle : Icons.radio_button_unchecked,
                  color: selected ? BrandColors.green : BrandColors.muted),
              onTap: () => setState(() {
                draft!['recipient_phone'] = m['phone'];
                recipient = {...m, 'confirmed': true};
              }),
            ),
          ),
        ));
      }
      if (status == 'need_recipient') {
        children.add(TextField(
          controller: _phoneField,
          keyboardType: TextInputType.phone,
          decoration: InputDecoration(
              filled: true,
              fillColor: Colors.white,
              hintText: tr(bn, 'অথবা নম্বর লিখুন (01XXXXXXXXX)', 'Or type a number (01XXXXXXXXX)'),
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide.none)),
          onChanged: (v) {
            final d = v.replaceAll(RegExp(r'\D'), '');
            setState(() {
              if (RegExp(r'^01[3-9]\d{8}$').hasMatch(d)) {
                draft!['recipient_phone'] = d;
                recipient = {'name': null, 'phone': d};
              }
            });
          },
        ));
      }
    }

    final confirmed = (recipient?['confirmed'] ?? false) == true;
    final ready = status == 'confirm_recipient' ? (confirmed && _clarifyReady) : _clarifyReady;
    children.addAll([
      const SizedBox(height: 20),
      FilledButton(onPressed: ready ? _assess : null, child: Text(tr(bn, 'এগিয়ে যান', 'Continue'))),
      const SizedBox(height: 8),
      OutlinedButton(onPressed: _restart, child: Text(tr(bn, 'বাতিল', 'Cancel'))),
    ]);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children);
  }

  Widget _interviewView() {
    final q = _questions[questionIndex];
    final quick = bn
        ? ['না, কেউ ফোন করেনি', 'আমি নিজেই পাঠাচ্ছি', 'হ্যাঁ, উপায় অফিস থেকে ফোন দিয়েছে', 'হ্যাঁ, ওটিপি চেয়েছে']
        : ['No, nobody called', 'I am sending it myself', 'Yes, someone from upay office called', 'Yes, they asked for my OTP'];
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _levelBanner('YELLOW', tr(bn, 'পাঠানোর আগে ছোট্ট ৩টি প্রশ্ন', 'Three quick questions before sending')),
      const SizedBox(height: 16),
      Text(tr(bn, 'প্রশ্ন ${bnDigits('${questionIndex + 1}')}/${bnDigits('${_questions.length}')}',
          'Question ${questionIndex + 1}/${_questions.length}'),
          style: const TextStyle(color: BrandColors.muted, fontWeight: FontWeight.w600)),
      const SizedBox(height: 6),
      Text(bn ? q['bn'] : q['en'], style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
      const SizedBox(height: 20),
      Center(child: _micButton(_answer, onDone: () => _submitAnswer(_answer.text), size: 80)),
      const SizedBox(height: 16),
      TextField(
        controller: _answer,
        onSubmitted: _submitAnswer,
        decoration: InputDecoration(
          filled: true,
          fillColor: Colors.white,
          hintText: tr(bn, 'উত্তর বলুন বা লিখুন', 'Speak or type your answer'),
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide.none),
          suffixIcon: IconButton(icon: const Icon(Icons.send_rounded), onPressed: () => _submitAnswer(_answer.text)),
        ),
      ),
      const SizedBox(height: 12),
      Wrap(spacing: 8, runSpacing: 8, children: [
        for (final a in quick) ActionChip(label: Text(a), backgroundColor: Colors.white, onPressed: () => _submitAnswer(a)),
      ]),
      const SizedBox(height: 16),
      _note(tr(bn, 'আমরা আপনার ফোন কল শুনি না। শুধু আপনার উত্তর দেখে প্রতারণার লক্ষণ খুঁজি।',
          'We never listen to your calls. Only your answers are checked for scam signs.'),
          Colors.white, BrandColors.muted, Icons.privacy_tip_outlined),
    ]);
  }

  Widget _levelBanner(String level, String title, [String? sub]) => Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(color: levelBg(level), borderRadius: BorderRadius.circular(14)),
        child: Row(children: [
          Icon(
              level == 'GREEN'
                  ? Icons.verified_user_rounded
                  : level == 'RED'
                      ? Icons.gpp_bad_rounded
                      : Icons.warning_amber_rounded,
              color: levelColor(level),
              size: 30),
          const SizedBox(width: 12),
          Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16, color: levelColor(level))),
            if (sub != null) Text(sub, style: const TextStyle(color: BrandColors.text)),
          ])),
        ]),
      );

  Widget _summaryCard() {
    final d = draft!;
    final r = recipient ?? {};
    final name = _recipientName();
    final isNew = parsed?['recipient_match'] == 'new_number';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(children: [
          Text(d['intent'] == 'mobile_recharge' ? tr(bn, 'মোবাইল রিচার্জ', 'Mobile Recharge') : tr(bn, 'সেন্ড মানি', 'Send Money'),
              style: const TextStyle(color: BrandColors.muted, fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          Text(taka(d['amount'], bn), style: const TextStyle(fontSize: 40, fontWeight: FontWeight.w800, color: BrandColors.navy)),
          const SizedBox(height: 12),
          CircleAvatar(
              radius: 26,
              backgroundColor: isNew ? BrandColors.redBg : BrandColors.yellow,
              child: Icon(isNew ? Icons.person_off_outlined : Icons.person, color: BrandColors.navy)),
          const SizedBox(height: 6),
          Text(name, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
          if (r['phone'] != null)
            Text(bn ? bnDigits(maskPhone(r['phone'])) : maskPhone(r['phone']), style: const TextStyle(color: BrandColors.muted)),
          if (isNew)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(tr(bn, 'নতুন নম্বর: আপনার কন্টাক্টে নেই', 'New number: not in your contacts'),
                  style: const TextStyle(color: BrandColors.red, fontWeight: FontWeight.w600)),
            ),
        ]),
      ),
    );
  }

  Widget _reviewView() {
    final a = assessment!;
    final level = a['level'] as String;
    final reasons = ((a['reasons'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e)).toList();
    final mistake = a['mistake'] as Map?;
    final title = switch (level) {
      'GREEN' => tr(bn, 'নিরাপদ মনে হচ্ছে', 'Looks safe'),
      'YELLOW' => tr(bn, 'সাবধান, একটু যাচাই করুন', 'Careful, please double-check'),
      _ => tr(bn, 'প্রতারণার ঝুঁকি বেশি!', 'High scam risk!'),
    };
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _levelBanner(level, title, bn ? a['advice_bn'] : a['advice_en']),
      const SizedBox(height: 14),
      _summaryCard(),
      if (mistake != null) ...[
        const SizedBox(height: 12),
        Card(
          color: BrandColors.amberBg,
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text(bn ? mistake['bn'] : mistake['en'], style: const TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 10),
              Row(children: [
                Expanded(
                    child: FilledButton(
                        onPressed: () {
                          draft!['amount'] = mistake['suggested'];
                          answers = [];
                          _assess();
                        },
                        child: Text(taka(mistake['suggested'], bn)))),
                const SizedBox(width: 10),
                Expanded(
                    child: OutlinedButton(
                        onPressed: () => setState(() => assessment = {...a, 'mistake': null}),
                        child: Text(tr(bn, '${taka(draft!['amount'], true)} ঠিক আছে', 'Keep ${taka(draft!['amount'], false)}')))),
              ]),
            ]),
          ),
        ),
      ],
      if (reasons.isNotEmpty && level != 'GREEN') ...[
        const SizedBox(height: 14),
        Text(tr(bn, 'কেন এই সতর্কতা', 'Why this warning'), style: const TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(height: 6),
        for (final r in reasons)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Icon(Icons.circle, size: 8, color: levelColor(level)),
              const SizedBox(width: 8),
              Expanded(child: Text(_reasonText(r))),
            ]),
          ),
      ],
      const SizedBox(height: 18),
      if (level == 'RED') ...[
        FilledButton(
          style: FilledButton.styleFrom(backgroundColor: BrandColors.red),
          onPressed: _cancel,
          child: Text(tr(bn, 'বাতিল করুন (পরামর্শ)', 'Cancel (recommended)')),
        ),
        const SizedBox(height: 8),
        OutlinedButton(onPressed: _continueFromReview, child: Text(tr(bn, 'তবুও পাঠাতে চাই', 'I still want to send'))),
      ] else ...[
        FilledButton(onPressed: mistake == null ? _continueFromReview : null, child: Text(tr(bn, 'নিশ্চিত করুন', 'Confirm'))),
        const SizedBox(height: 8),
        OutlinedButton(onPressed: _cancel, child: Text(tr(bn, 'বাতিল', 'Cancel'))),
      ],
    ]);
  }

  String _reasonText(Map<String, dynamic> r) {
    final base = (bn ? r['bn'] : r['en']).toString();
    final phrase = r['phrase'];
    if (phrase == null) return base;
    return bn ? '$base (আপনি বলেছেন: "$phrase")' : '$base (you said: "$phrase")';
  }

  Widget _holdView() {
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _levelBanner('RED', tr(bn, 'লেনদেন সাময়িক আটকে রাখা হয়েছে', 'Transfer on hold')),
      const SizedBox(height: 16),
      Center(
        child: SizedBox(
          width: 120,
          height: 120,
          child: Stack(alignment: Alignment.center, children: [
            CircularProgressIndicator(
              value: holdLeft == 0 ? 1 : 1 - holdLeft / ((assessment!['hold_seconds'] as num?) ?? 30),
              strokeWidth: 8,
              color: BrandColors.red,
              backgroundColor: BrandColors.redBg,
            ),
            Text(bn ? bnDigits('$holdLeft') : '$holdLeft', style: const TextStyle(fontSize: 34, fontWeight: FontWeight.w800)),
          ]),
        ),
      ),
      const SizedBox(height: 16),
      _note(
          tr(bn, 'এই সময়ে ফোন কেটে দিন। যাকে টাকা পাঠাচ্ছেন, তার পরিচিত নম্বরে নিজে ফোন করে নিশ্চিত হোন। উপায় কখনো পিন বা ওটিপি চায় না। হেল্পলাইন: ১৬২৬৮',
              'Use this time to hang up. Call the person on a number you already know. upay never asks for your PIN or OTP. Helpline: 16268'),
          BrandColors.redBg,
          BrandColors.red,
          Icons.phone_disabled_outlined),
      const SizedBox(height: 12),
      CheckboxListTile(
        value: acknowledged,
        onChanged: (v) => setState(() => acknowledged = v ?? false),
        controlAffinity: ListTileControlAffinity.leading,
        title: Text(tr(bn, 'আমি সতর্কবার্তা পড়েছি এবং প্রাপককে নিজে যাচাই করেছি',
            'I read the warning and verified the recipient myself')),
      ),
      const SizedBox(height: 8),
      FilledButton(
        style: FilledButton.styleFrom(backgroundColor: BrandColors.red),
        onPressed: _cancel,
        child: Text(tr(bn, 'বাতিল করুন', 'Cancel transfer')),
      ),
      const SizedBox(height: 8),
      OutlinedButton(
        onPressed: holdLeft == 0 && acknowledged ? () => setState(() => step = _Step.auth) : null,
        child: Text(holdLeft == 0 ? tr(bn, 'পিন দিয়ে পাঠান', 'Continue with PIN') : tr(bn, 'অপেক্ষা করুন...', 'Please wait...')),
      ),
    ]);
  }

  Widget _authView() {
    final level = assessment!['level'];
    final canBio = level == 'GREEN' && biometricOk;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _summaryCard(),
      const SizedBox(height: 16),
      Text(level == 'GREEN' ? tr(bn, 'পিন দিন বা ফিঙ্গারপ্রিন্ট দিন', 'Enter PIN or use biometrics') : tr(bn, 'এই লেনদেনে পিন লাগবে', 'PIN required for this transfer'),
          textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
      const SizedBox(height: 4),
      Text(tr(bn, 'ডেমো পিন: ১২৩৪', 'Demo PIN: 1234'), textAlign: TextAlign.center, style: const TextStyle(color: BrandColors.muted)),
      const SizedBox(height: 8),
      PinPad(bangla: bn, error: pinError, onSubmit: (p) => _execute('pin', pin: p)),
      if (canBio) ...[
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: _useBiometric,
          icon: const Icon(Icons.fingerprint),
          label: Text(tr(bn, 'ফেস আইডি / ফিঙ্গারপ্রিন্ট', 'Face ID / Fingerprint')),
        ),
      ],
      const SizedBox(height: 8),
      TextButton(onPressed: _cancel, child: Text(tr(bn, 'বাতিল', 'Cancel'))),
    ]);
  }

  Widget _doneView() {
    final info = doneInfo ?? {};
    final kind = info['kind'];
    final ok = kind == 'sent' || kind == 'balance';
    final protected = info['protected'] == true;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const SizedBox(height: 40),
      Icon(
          ok
              ? Icons.check_circle_rounded
              : protected
                  ? Icons.shield_rounded
                  : Icons.cancel_rounded,
          size: 90,
          color: ok
              ? BrandColors.green
              : protected
                  ? BrandColors.navy
                  : BrandColors.muted),
      const SizedBox(height: 16),
      Text(info['text'] ?? '', textAlign: TextAlign.center, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
      const SizedBox(height: 30),
      FilledButton(onPressed: _restart, child: Text(tr(bn, 'নতুন লেনদেন', 'New transaction'))),
      const SizedBox(height: 8),
      OutlinedButton(onPressed: () => Navigator.of(context).maybePop(), child: Text(tr(bn, 'হোমে ফিরুন', 'Back to home'))),
    ]);
  }
}
