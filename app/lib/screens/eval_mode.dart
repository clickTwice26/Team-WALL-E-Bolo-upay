import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../api.dart';
import '../services/export.dart';
import '../services/voice.dart';
import '../state.dart';
import '../strings.dart';
import '../theme.dart';

/// Build with --dart-define=EVAL_MODE=true to open straight into this screen
/// after the PIN (study phones); otherwise it is in the demo settings sheet.
const kEvalMode = bool.fromEnvironment('EVAL_MODE');

/// Dialect areas and recording conditions (also the Accuracy screen's labels).
const studyDialects = {
  'dhaka': ('ঢাকা', 'Dhaka'), 'chattogram': ('চট্টগ্রাম', 'Chattogram'), 'sylhet': ('সিলেট', 'Sylhet'),
  'barishal': ('বরিশাল', 'Barishal'), 'rajshahi': ('রাজশাহী', 'Rajshahi'), 'khulna': ('খুলনা', 'Khulna'),
  'rangpur': ('রংপুর', 'Rangpur'), 'mymensingh': ('ময়মনসিংহ', 'Mymensingh'), 'other': ('অন্যান্য', 'Other'),
};
const audioConditions = {'quiet': ('শান্ত ঘর', 'Quiet room'), 'street': ('রাস্তা', 'Street'), 'bus_tv': ('বাস / টিভির শব্দ', 'Bus / TV noise')};

/// Sessions recorded since the app started (one per participant x condition).
/// Kept in memory only, until the facilitator exports them.
final List<Map<String, dynamic>> evalSessions = [];

/// Real-audio evaluation (R1, docs/AUDIO_EVAL.md). The participant speaks each
/// prompt; the app logs the STT transcript, its confidence and the parse
/// result, which is the real device pipeline. Audio is never saved.
class EvalScreen extends StatefulWidget {
  const EvalScreen({super.key});
  @override
  State<EvalScreen> createState() => _EvalScreenState();
}

class _EvalScreenState extends State<EvalScreen> {
  static const _ages = {'18-30': ('১৮–৩০', '18–30'), '30-50': ('৩০–৫০', '30–50'), '50+': ('৫০+', '50+')};
  static const _genders = {'female': ('নারী', 'Female'), 'male': ('পুরুষ', 'Male'), 'other': ('অন্যান্য', 'Other')};
  static const _dialects = studyDialects;
  static const _conditions = audioConditions;
  static const _modes = {'read': ('নিজে পড়ে বলেন', 'Reads the prompt'), 'repeat': ('শুনে বলেন', 'Repeats after facilitator')};

  final _pid = TextEditingController();
  final _device = TextEditingController();
  final _typed = TextEditingController();
  String? age, gender, dialect, condition, mode = 'read';
  bool consent = false;

  List<Map<String, dynamic>> prompts = [];
  Map<String, dynamic>? session; // the running one
  final Map<String, int> _attempts = {};
  int i = 0;
  bool listening = false, busy = false, finished = false;
  String heard = '';
  String? note;
  Map<String, dynamic>? last; // last attempt at the current prompt

  bool get bn => appState.bangla;
  bool get _ready => _pid.text.trim().isNotEmpty && age != null && gender != null && dialect != null && condition != null && consent;
  Map<String, dynamic> get _prompt => prompts[i];

  @override
  void dispose() {
    Voice.instance.stop();
    super.dispose();
  }

  Future<void> _start() async {
    setState(() => busy = true);
    try {
      final data = Map<String, dynamic>.from(await apiRequest('GET', '/api/eval/prompts'));
      // the expected labels are for demo user u1's contacts
      if (appState.userId != data['user']) await appState.switchUser('${data['user']}');
      final all = [for (final p in data['prompts'] as List) Map<String, dynamic>.from(p)];
      final pid = _pid.text.trim();
      all.shuffle(Random(Object.hash(pid, condition))); // no fatigue bias by prompt type, same order on a rerun
      session = {
        'participant': pid, 'age_band': age, 'gender': gender, 'dialect': dialect, 'condition': condition,
        'mode': mode, 'device': _device.text.trim(), 'platform': kIsWeb ? 'web' : defaultTargetPlatform.name,
        'stt_locale': 'bn-BD', 'consent': true, 'started_at': DateTime.now().toUtc().toIso8601String(),
        'order': [for (final p in all) p['id']], 'records': <Map<String, dynamic>>[],
      };
      evalSessions.add(session!);
      setState(() {
        prompts = all;
        i = 0;
        finished = false;
        _clear();
      });
    } on ApiError catch (e) {
      setState(() => note = e.status == 404
          ? tr(bn, 'মূল্যায়ন মোড শুধু ডেমো সার্ভারে (DEMO_MODE=true)।', 'Evaluation mode needs a demo server (DEMO_MODE=true).')
          : tr(bn, 'প্রম্পট আনা যায়নি (${e.status})।', 'Could not load the prompts (${e.status}).'));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void _clear() {
    heard = '';
    last = null;
    note = null;
    _typed.clear();
  }

  Future<void> _mic() async {
    final v = Voice.instance;
    if (listening) {
      await v.stop();
      setState(() => listening = false);
      return;
    }
    if (!await v.init()) {
      setState(() => note = tr(bn, 'এই ডিভাইসে ভয়েস চালু নেই।', 'Voice input is not available on this device.'));
      return;
    }
    await v.silence();
    setState(() {
      listening = true;
      heard = '';
      note = null;
    });
    await v.listen(
      bangla: true, // the study is Bangla speech (bn-BD), whatever the UI language
      onText: (t, done) {
        if (!mounted) return;
        setState(() {
          heard = t;
          if (done) listening = false;
        });
        if (done) _record(t, 'voice');
      },
    );
  }

  /// One attempt: transcript, confidence and what the parser made of it.
  /// "typed" rows are for testing without a mic and are not counted.
  Future<void> _record(String text, String input) async {
    final p = _prompt, v = Voice.instance, t = text.trim();
    if (input == 'typed' && t.isEmpty) return;
    final conf = input == 'voice' ? v.lastConfidence : null;
    final rec = <String, dynamic>{
      'prompt_id': p['id'], 'kind': p['kind'], 'reference': p['text'], 'expected': p['expected'],
      'attempt': _attempts.update('${p['id']}', (n) => n + 1, ifAbsent: () => 1), 'input': input,
      'transcript': t, 'confidence': conf, 'has_confidence': conf != null,
      'unsure': input == 'voice' && v.lastUnsure, 'at': DateTime.now().toUtc().toIso8601String(), 'parse': null,
    };
    setState(() => busy = true);
    if (t.isNotEmpty) {
      try {
        final r = await Api.parse(t);
        rec['parse'] = {
          'status': r['status'], 'intent': r['intent'], 'amount': r['amount'],
          'recipient': (r['recipient'] as Map?)?['id'] ?? r['new_number'],
          'candidates': [for (final c in (r['recipient_candidates'] as List? ?? [])) c['id'] ?? c['phone']],
          'llm_used': (r['parsers'] as Map?)?['llm_used'] ?? false,
        };
      } on ApiError catch (e) {
        rec['error'] = e.status;
      }
    }
    (session!['records'] as List).add(rec);
    if (mounted) {
      setState(() {
        last = rec;
        busy = false;
      });
    }
  }

  void _next({bool skip = false}) {
    if (skip) {
      (session!['records'] as List).add(
          {'prompt_id': _prompt['id'], 'kind': _prompt['kind'], 'skipped': true, 'at': DateTime.now().toUtc().toIso8601String()});
    }
    Voice.instance.stop();
    setState(() {
      listening = false;
      _clear();
      if (i + 1 < prompts.length) {
        i++;
      } else {
        finished = true;
      }
    });
  }

  void _newCondition() => setState(() {
        session = null;
        prompts = [];
        condition = null;
        finished = false;
        _attempts.clear();
      });

  Future<void> _export() async {
    if (evalSessions.isEmpty) return;
    final file = await exportJson(exportName('audio', _pid.text.trim()), {
      'kind': 'bolo_upay_audio_eval', 'version': 1, 'sample': false,
      'exported_at': DateTime.now().toUtc().toIso8601String(), 'sessions': evalSessions,
    });
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(file
            ? tr(bn, 'JSON ফাইল ডাউনলোড হয়েছে।', 'JSON file downloaded.')
            : tr(bn, 'JSON ক্লিপবোর্ডে কপি হয়েছে: একটি ফাইলে পেস্ট করে সংরক্ষণ করুন।',
                'JSON copied to the clipboard: paste it into a file and save it.'))));
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: appState,
      builder: (context, _) => Scaffold(
        appBar: AppBar(
          title: Text(tr(bn, 'মূল্যায়ন মোড (অডিও)', 'Evaluation mode (audio)')),
          actions: [
            IconButton(
              tooltip: tr(bn, 'লগ এক্সপোর্ট', 'Export log'),
              onPressed: evalSessions.isEmpty ? null : _export,
              icon: const Icon(Icons.download_rounded),
            ),
          ],
        ),
        body: SafeArea(
          child: ListView(padding: const EdgeInsets.all(16), children: [
            if (session == null) ..._setup() else if (finished) ..._finished() else ..._run(),
            if (note != null) ...[const SizedBox(height: 12), Text(note!, style: const TextStyle(color: BrandColors.red))],
          ]),
        ),
      ),
    );
  }

  Widget _choices(String label, Map<String, (String, String)> options, String? value, ValueChanged<String> onPick) =>
      Padding(
        padding: const EdgeInsets.only(top: 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: const TextStyle(color: BrandColors.muted, fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          Wrap(spacing: 6, runSpacing: 6, children: [
            for (final e in options.entries)
              ChoiceChip(
                label: Text(bn ? e.value.$1 : e.value.$2),
                selected: value == e.key,
                onSelected: (_) => setState(() => onPick(e.key)),
              ),
          ]),
        ]),
      );

  List<Widget> _setup() => [
        Text(tr(bn, 'আসল কণ্ঠে পরীক্ষা', 'Real speech test'), style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
        const SizedBox(height: 6),
        Text(tr(bn, 'অডিও কখনো সংরক্ষণ হয় না। শুধু শোনা লেখা, তার কনফিডেন্স আর অ্যাপ কী বুঝল তা এই ফোনে লগ হয়।',
            'Audio is never saved. Only the recognised text, its confidence and what the app understood are logged on this phone.')),
        const SizedBox(height: 12),
        TextField(
          controller: _pid,
          onChanged: (_) => setState(() => consent = false), // a new person signs again
          decoration: InputDecoration(
              labelText: tr(bn, 'অংশগ্রহণকারীর কোড (যেমন P03, নাম নয়)', 'Participant code (e.g. P03, not a name)')),
        ),
        _choices(tr(bn, 'বয়স', 'Age band'), _ages, age, (v) => age = v),
        _choices(tr(bn, 'লিঙ্গ', 'Gender'), _genders, gender, (v) => gender = v),
        _choices(tr(bn, 'আঞ্চলিক ভাষা', 'Dialect'), _dialects, dialect, (v) => dialect = v),
        _choices(tr(bn, 'পরিবেশ', 'Condition'), _conditions, condition, (v) => condition = v),
        _choices(tr(bn, 'কীভাবে বলবেন', 'How they speak'), _modes, mode, (v) => mode = v),
        TextField(
          controller: _device,
          decoration: InputDecoration(labelText: tr(bn, 'ফোন (মডেল, অ্যান্ড্রয়েড ভার্সন)', 'Phone (model, Android version)')),
        ),
        CheckboxListTile(
          value: consent,
          contentPadding: EdgeInsets.zero,
          controlAffinity: ListTileControlAffinity.leading,
          onChanged: (v) => setState(() => consent = v ?? false),
          title: Text(tr(bn, 'অংশগ্রহণকারী লিখিত সম্মতিপত্রে সই করেছেন', 'The participant signed the consent form')),
        ),
        const SizedBox(height: 8),
        FilledButton(
          onPressed: _ready && !busy ? _start : null,
          child: Text(tr(bn, 'শুরু করুন', 'Start')),
        ),
        if (evalSessions.isNotEmpty) ...[
          const SizedBox(height: 12),
          Text(tr(bn, 'এই ফোনে ${bnDigits('${evalSessions.length}')}টি সেশন লগ আছে। বন্ধ করার আগে এক্সপোর্ট করুন।',
              '${evalSessions.length} session(s) logged on this phone. Export before closing the app.')),
        ],
      ];

  List<Widget> _run() {
    final p = _prompt, free = p['kind'] == 'free';
    final s = session!;
    final parse = last?['parse'] as Map?;
    return [
      Text('${s['participant']} · ${bn ? _conditions[s['condition']]!.$1 : _conditions[s['condition']]!.$2} · '
          '${bn ? bnDigits('${i + 1}/${prompts.length}') : '${i + 1}/${prompts.length}'}',
          style: const TextStyle(color: BrandColors.muted, fontWeight: FontWeight.w600)),
      const SizedBox(height: 6),
      LinearProgressIndicator(value: i / prompts.length, minHeight: 4),
      const SizedBox(height: 14),
      Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(free ? tr(bn, 'নিজের ভাষায় বলুন', 'Say it in your own words') : tr(bn, 'এটি বলুন', 'Say this'),
                style: const TextStyle(color: BrandColors.muted)),
            const SizedBox(height: 6),
            Text(free ? (bn ? p['task_bn'] : p['task_en']) : p['text'],
                style: TextStyle(fontSize: free ? 19 : 26, fontWeight: FontWeight.w700)),
            if (!free && p['typed'] != p['text'])
              Text('${tr(bn, 'টাইপ করা টেস্ট', 'Typed test')}: ${p['typed']}', style: const TextStyle(color: BrandColors.muted, fontSize: 12)),
          ]),
        ),
      ),
      const SizedBox(height: 16),
      Center(
        child: GestureDetector(
          onTap: busy ? null : _mic,
          child: CircleAvatar(
            radius: 42,
            backgroundColor: listening ? BrandColors.red : BrandColors.navy,
            child: Icon(listening ? Icons.stop_rounded : Icons.mic_rounded, color: Colors.white, size: 40),
          ),
        ),
      ),
      const SizedBox(height: 8),
      Text(listening ? tr(bn, 'শুনছি...', 'Listening...') : (heard.isEmpty ? tr(bn, 'মাইকে চাপ দিয়ে বলুন', 'Tap the mic and speak') : '"$heard"'),
          textAlign: TextAlign.center, style: const TextStyle(fontSize: 16)),
      if (busy) const Padding(padding: EdgeInsets.only(top: 8), child: LinearProgressIndicator(minHeight: 2)),
      if (last != null) ...[
        const SizedBox(height: 12),
        Card(
          color: BrandColors.bg,
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Text([
              '${tr(bn, 'চেষ্টা', 'Attempt')} ${last!['attempt']} · ${last!['input']}',
              '${tr(bn, 'কনফিডেন্স', 'Confidence')}: ${last!['confidence'] == null ? tr(bn, 'দেয়নি', 'none') : (last!['confidence'] as num).toStringAsFixed(2)}'
                  '${last!['unsure'] == true ? ' · ${tr(bn, 'অনিশ্চিত', 'unsure')}' : ''}',
              if (parse != null)
                '${parse['status']} · ${parse['intent']} · ${parse['amount'] == null ? '–' : taka(parse['amount'], bn)} · ${parse['recipient'] ?? '–'}'
              else
                tr(bn, 'কিছু শোনা যায়নি বা পার্স হয়নি', 'Nothing heard or not parsed'),
            ].join('\n')),
          ),
        ),
      ],
      const SizedBox(height: 12),
      Row(children: [
        Expanded(
            child: OutlinedButton(
                onPressed: last == null || busy ? null : () => setState(_clear),
                child: Text(tr(bn, 'আবার বলুন', 'Again')))),
        const SizedBox(width: 8),
        Expanded(child: TextButton(onPressed: busy ? null : () => _next(skip: true), child: Text(tr(bn, 'বাদ দিন', 'Skip')))),
        const SizedBox(width: 8),
        Expanded(child: FilledButton(onPressed: last == null || busy ? null : _next, child: Text(tr(bn, 'পরেরটি', 'Next')))),
      ]),
      const SizedBox(height: 8),
      ExpansionTile(
        key: const ValueKey('typed'), // stays open when the result card appears above it
        tilePadding: EdgeInsets.zero,
        title: Text(tr(bn, 'মাইক ছাড়া পরীক্ষা (গণনা হবে না)', 'Test without a mic (not counted)'), style: const TextStyle(fontSize: 13)),
        children: [
          TextField(
            controller: _typed,
            onSubmitted: (t) => _record(t, 'typed'),
            decoration: InputDecoration(
              hintText: tr(bn, 'লিখে দিন', 'Type it'),
              suffixIcon: IconButton(icon: const Icon(Icons.send_rounded), onPressed: () => _record(_typed.text, 'typed')),
            ),
          ),
        ],
      ),
    ];
  }

  List<Widget> _finished() {
    final n = (session!['records'] as List).where((r) => r['skipped'] != true).length;
    return [
      const Icon(Icons.check_circle_rounded, size: 72, color: BrandColors.green),
      const SizedBox(height: 8),
      Text(tr(bn, 'সেশন শেষ: ${bnDigits('$n')}টি রেকর্ড।', 'Session done: $n recordings.'),
          textAlign: TextAlign.center, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
      const SizedBox(height: 16),
      FilledButton.icon(onPressed: _export, icon: const Icon(Icons.download_rounded), label: Text(tr(bn, 'লগ এক্সপোর্ট', 'Export log'))),
      const SizedBox(height: 8),
      OutlinedButton(onPressed: _newCondition, child: Text(tr(bn, 'পরের পরিবেশ (একই অংশগ্রহণকারী)', 'Next condition (same participant)'))),
    ];
  }
}
