import 'dart:convert';

import 'package:bolo_upay/screens/eval_mode.dart';
import 'package:bolo_upay/services/voice.dart';
import 'package:bolo_upay/state.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fakes.dart';

/// R1 evaluation mode: logs transcript, confidence and parse per prompt
/// (never audio) and exports them as JSON.
void main() {
  late FakeApi api;
  late FakeVoice voice;

  setUp(() {
    api = FakeApi();
    voice = FakeVoice();
    Voice.instance = voice;
    appState.bangla = false;
    evalSessions.clear();
    api.on('GET /api/eval/prompts', (_) => {
          'user': 'u1',
          'prompts': [
            {'id': 'C27', 'kind': 'read', 'text': 'আম্মুকে ৫০০ টাকা পাঠাও', 'typed': 'আম্মুকে ৫০০ টাকা পাঠাও',
             'expected': {'intent': 'send_money', 'amount': 500, 'recipient': 'c1'}},
            {'id': 'F3', 'kind': 'free', 'task_bn': 'নিজের ফোনে ৫০ টাকা রিচার্জ করতে বলুন।',
             'task_en': 'Recharge your own phone with 50 taka.',
             'expected': {'intent': 'mobile_recharge', 'amount': 50, 'recipient': 'self'}},
          ],
        });
    api.on('POST /api/parse', (b) => {
          'status': 'ok', 'intent': 'send_money', 'amount': '${b['text']}'.contains('৫০০') ? 500 : 50,
          'recipient': {'id': 'c1'}, 'new_number': null, 'recipient_candidates': [], 'parsers': {'llm_used': false},
        });
  });
  tearDown(() => appState.bangla = true);

  Future<void> setUpSession(WidgetTester tester) async {
    await tester.pumpWidget(const MaterialApp(home: EvalScreen()));
    await tester.enterText(find.byType(TextField).first, 'P07');
    for (final label in ['30–50', 'Female', 'Sylhet', 'Street']) {
      await tapOn(tester, find.text(label));
    }
  }

  testWidgets('needs signed consent before it starts', (tester) async {
    phoneScreen(tester);
    await api.run(() async {
      await setUpSession(tester);
      final start = find.widgetWithText(FilledButton, 'Start');
      expect(tester.widget<FilledButton>(start).onPressed, isNull);
      await tapOn(tester, find.text('The participant signed the consent form'));
      expect(tester.widget<FilledButton>(start).onPressed, isNotNull);
    });
  });

  testWidgets('logs each attempt with confidence and parse, then exports JSON', (tester) async {
    phoneScreen(tester);
    final clip = ClipboardSpy(tester);
    await api.run(() async {
      await setUpSession(tester);
      await tapOn(tester, find.text('The participant signed the consent form'));
      await tapOn(tester, find.text('Start'));
      expect(find.textContaining('P07 · Street · 1/2'), findsOneWidget);

      voice.next = ('আম্মুকে ৫০০ টাকা পাঠাও', 0.92);
      await tapOn(tester, find.byIcon(Icons.mic_rounded));
      expect(find.textContaining('Confidence: 0.92'), findsOneWidget);

      // the speaker stumbled: say it again; a low score is flagged unsure
      await tapOn(tester, find.text('Again'));
      voice.next = ('আম্মুকে ৫০ টাকা', 0.41);
      await tapOn(tester, find.byIcon(Icons.mic_rounded));
      expect(find.textContaining('unsure'), findsOneWidget);
      expect(find.textContaining('Attempt 2'), findsOneWidget);

      await tapOn(tester, find.text('Next'));
      await tapOn(tester, find.text('Skip'));
      expect(find.text('Session done: 2 recordings.'), findsOneWidget);
      await tapOn(tester, find.text('Export log'));
    });

    expect(api.bodies('/api/parse').map((b) => b['text']), ['আম্মুকে ৫০০ টাকা পাঠাও', 'আম্মুকে ৫০ টাকা']);
    final log = jsonDecode(clip.text!) as Map<String, dynamic>;
    expect(log['kind'], 'bolo_upay_audio_eval');
    final s = (log['sessions'] as List).single as Map;
    expect([s['participant'], s['age_band'], s['gender'], s['dialect'], s['condition'], s['consent']],
        ['P07', '30-50', 'female', 'sylhet', 'street', true]);
    final recs = (s['records'] as List).cast<Map>();
    expect(recs, hasLength(3));
    expect([recs[0]['attempt'], recs[0]['confidence'], recs[0]['unsure'], recs[0]['input']], [1, 0.92, false, 'voice']);
    expect(recs[0]['parse'], containsPair('amount', 500));
    expect([recs[1]['attempt'], recs[1]['unsure'], recs[1]['parse']['amount']], [2, true, 50]);
    expect(recs[2]['skipped'], true);
    expect(clip.text, isNot(contains('"audio')), reason: 'no audio field is ever logged');
  });

  testWidgets('says so when the server is not a demo site', (tester) async {
    phoneScreen(tester);
    api.on('GET /api/eval/prompts', (_) => apiError(404, 'not found'));
    await api.run(() async {
      await setUpSession(tester);
      await tapOn(tester, find.text('The participant signed the consent form'));
      await tapOn(tester, find.text('Start'));
    });
    expect(find.textContaining('DEMO_MODE=true'), findsOneWidget);
  });
}
