import 'package:flutter/material.dart';

import '../agent/agent.dart';
import '../api.dart';
import '../state.dart';
import '../strings.dart';
import '../theme.dart';

String _pct(dynamic v) => v == null ? '–' : '${((v as num) * 100).toStringAsFixed(1)}%';

Widget _stat(String label, String value, {Color color = BrandColors.navy, String? sub}) => Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: const TextStyle(color: BrandColors.muted, fontSize: 13)),
          const SizedBox(height: 4),
          Text(value, style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: color)),
          if (sub != null) Text(sub, style: const TextStyle(color: BrandColors.muted, fontSize: 12)),
        ]),
      ),
    );

Widget _grid(List<Widget> children) => LayoutBuilder(
      builder: (context, c) {
        final cols = c.maxWidth > 700 ? 4 : 2;
        final w = (c.maxWidth - (cols - 1) * 10) / cols;
        return Wrap(spacing: 10, runSpacing: 10, children: [for (final ch in children) SizedBox(width: w, child: ch)]);
      },
    );

/// Ops dashboard: what the scam shield did in demo sessions.
class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  Future<Map<String, dynamic>>? _f;

  @override
  void initState() {
    super.initState();
    _load();
    Agent.instance.registerRefresh('dashboard', () async => setState(_load));
  }

  void _load() => _f = Api.dashboard()..then(_publish, onError: (_) {});

  /// What the agent can tell the user about this page.
  void _publish(Map<String, dynamic> d) {
    final lv = Map<String, dynamic>.from(d['by_level']);
    final cats = Map<String, dynamic>.from(d['scam_categories']).keys.take(3).join(', ');
    Agent.instance.publish('dashboard', {
      'id': 'dashboard',
      'summary_bn': 'অপস ড্যাশবোর্ড: মোট ${d['total']}টি যাচাই, ${d['sent']}টি পাঠানো, সতর্কতার পর '
          '${d['cancelled_after_warning']}টি বাতিল, রক্ষা পেয়েছে ${taka(d['amount_protected'] ?? 0, true)}। '
          'GREEN ${lv['GREEN']}, YELLOW ${lv['YELLOW']}, RED ${lv['RED']}।${cats.isEmpty ? '' : ' প্রতারণার ধরন: $cats।'}',
      'summary_en': 'Ops dashboard: ${d['total']} checks, ${d['sent']} sent, ${d['cancelled_after_warning']} '
          'cancelled after a warning, ${taka(d['amount_protected'] ?? 0, false)} protected. '
          'GREEN ${lv['GREEN']}, YELLOW ${lv['YELLOW']}, RED ${lv['RED']}.${cats.isEmpty ? '' : ' Scam patterns: $cats.'}',
      'content': {for (final k in ['total', 'sent', 'cancelled_after_warning', 'amount_protected', 'by_level']) k: d[k]},
      'actions': <String>[],
    });
  }

  @override
  Widget build(BuildContext context) {
    final bn = appState.bangla;
    return Scaffold(
      appBar: AppBar(title: Text(tr(bn, 'অপস ড্যাশবোর্ড', 'Ops dashboard'))),
      body: RefreshIndicator(
        onRefresh: () async => setState(_load),
        child: FutureBuilder<Map<String, dynamic>>(
          future: _f,
          builder: (context, s) {
            if (!s.hasData) {
              final e = s.error;
              final staffOnly = e is ApiError && e.status == 403;
              return Center(
                  child: !s.hasError
                      ? const CircularProgressIndicator()
                      : Text(staffOnly
                          ? tr(bn, 'অপস ড্যাশবোর্ড শুধু উপায়ের কর্মীদের জন্য।', 'The ops dashboard is for upay staff only.')
                          : '$e'));
            }
            final d = s.data!;
            final lv = Map<String, dynamic>.from(d['by_level']);
            final cats = Map<String, dynamic>.from(d['scam_categories']);
            final recent = (d['recent'] as List).map((e) => Map<String, dynamic>.from(e)).toList();
            return ListView(padding: const EdgeInsets.all(16), children: [
              _grid([
                _stat(tr(bn, 'মোট যাচাই', 'Checked'), '${d['total']}'),
                _stat(tr(bn, 'সতর্কতার পর বাতিল', 'Cancelled after warning'), '${d['cancelled_after_warning']}', color: BrandColors.green),
                _stat(tr(bn, 'রক্ষা পাওয়া টাকা', 'Money protected'), taka(d['amount_protected'] ?? 0, bn), color: BrandColors.green),
                _stat(tr(bn, 'পাঠানো হয়েছে', 'Sent'), '${d['sent']}'),
                _stat('GREEN', '${lv['GREEN']}', color: BrandColors.green),
                _stat('YELLOW', '${lv['YELLOW']}', color: BrandColors.amber),
                _stat('RED', '${lv['RED']}', color: BrandColors.red),
              ]),
              const SizedBox(height: 16),
              Text(tr(bn, 'প্রতারণার ধরন', 'Scam patterns detected'), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
              const SizedBox(height: 6),
              Card(
                child: Column(children: [
                  if (cats.isEmpty)
                    Padding(padding: const EdgeInsets.all(14), child: Text(tr(bn, 'এখনো কিছু নেই', 'None yet'))),
                  for (final e in cats.entries) ListTile(dense: true, title: Text(e.key), trailing: Text('${e.value}')),
                ]),
              ),
              const SizedBox(height: 16),
              Text(tr(bn, 'সাম্প্রতিক সিদ্ধান্ত', 'Recent decisions'), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
              const SizedBox(height: 6),
              Card(
                child: Column(children: [
                  for (final r in recent)
                    ListTile(
                      dense: true,
                      leading: Icon(Icons.circle, color: levelColor(r['level'] ?? ''), size: 14),
                      title: Text('${r['intent']} · ${taka(r['amount'] ?? 0, bn)} → ${r['recipient']}'),
                      subtitle: Text('${r['outcome']} · p=${(r['probability'] ?? 0).toStringAsFixed(2)}'
                          '${(r['categories'] as List).isNotEmpty ? ' · ${(r['categories'] as List).join(', ')}' : ''}'),
                    ),
                ]),
              ),
              const SizedBox(height: 10),
              Text(d['note'] ?? '', style: const TextStyle(color: BrandColors.muted, fontSize: 12)),
            ]);
          },
        ),
      ),
    );
  }
}

/// Accuracy report: measured numbers from the evaluation scripts.
class AccuracyScreen extends StatefulWidget {
  const AccuracyScreen({super.key});
  @override
  State<AccuracyScreen> createState() => _AccuracyScreenState();
}

class _AccuracyScreenState extends State<AccuracyScreen> {
  Future<Map<String, dynamic>>? _f;

  @override
  void initState() {
    super.initState();
    _load();
    Agent.instance.registerRefresh('accuracy', () async => setState(_load));
  }

  void _load() => _f = Api.metrics()..then(_publish, onError: (_) {});

  void _publish(Map<String, dynamic> m) {
    final pm = Map<String, dynamic>.from(m['parser_metrics'] ?? {});
    final tp = Map<String, dynamic>.from(Map<String, dynamic>.from(m['risk_metrics'] ?? {})['test_pipeline'] ?? {});
    final ml = Map<String, dynamic>.from(tp['ml_plus_interview_plus_rules'] ?? {});
    final base = Map<String, dynamic>.from(tp['baseline_rules_only'] ?? {});
    Agent.instance.publish('accuracy', {
      'id': 'accuracy',
      'summary_bn': 'অ্যাকুরেসি রিপোর্ট: ${pm['test_set_size']}টি কমান্ডে ইনটেন্ট ${_pct(pm['intent_accuracy'])}, '
          'টাকার পরিমাণ ${_pct(pm['amount_accuracy'])}, প্রাপক ${_pct(pm['recipient_accuracy'])}, না জিজ্ঞেস করে ভুল '
          'পরিমাণ ${_pct(pm['silent_wrong_amount_rate'])}। স্ক্যাম ধরা পড়েছে ${_pct(ml['scam_flagged_rate'])} '
          '(শুধু রুলে ${_pct(base['scam_flagged_rate'])}), সৎ লেনদেন আটকানো ${_pct(ml['legit_red_rate'])}।',
      'summary_en': 'Accuracy report: on ${pm['test_set_size']} commands intent ${_pct(pm['intent_accuracy'])}, '
          'amount ${_pct(pm['amount_accuracy'])}, recipient ${_pct(pm['recipient_accuracy'])}, silent wrong amount '
          '${_pct(pm['silent_wrong_amount_rate'])}. Scams flagged ${_pct(ml['scam_flagged_rate'])} (rules only '
          '${_pct(base['scam_flagged_rate'])}), honest transfers held ${_pct(ml['legit_red_rate'])}.',
      'content': {'parser': pm['intent_accuracy'], 'scam_flagged': ml['scam_flagged_rate'], 'legit_held': ml['legit_red_rate']},
      'actions': <String>[],
    });
  }

  @override
  Widget build(BuildContext context) {
    final bn = appState.bangla;
    return Scaffold(
      appBar: AppBar(title: Text(tr(bn, 'অ্যাকুরেসি রিপোর্ট', 'Accuracy report'))),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _f,
        builder: (context, s) {
          if (!s.hasData) {
            return Center(child: s.hasError ? Text('${s.error}') : const CircularProgressIndicator());
          }
          final pm = Map<String, dynamic>.from(s.data!['parser_metrics'] ?? {});
          final rm = Map<String, dynamic>.from(s.data!['risk_metrics'] ?? {});
          final tp = Map<String, dynamic>.from(rm['test_pipeline'] ?? {});
          final ml = Map<String, dynamic>.from(tp['ml_plus_interview_plus_rules'] ?? {});
          final base = Map<String, dynamic>.from(tp['baseline_rules_only'] ?? {});
          final coef = Map<String, dynamic>.from(rm['coefficients'] ?? {});
          final failures = (pm['failures'] as List?) ?? [];
          return ListView(padding: const EdgeInsets.all(16), children: [
            Text(tr(bn, '১. কমান্ড বোঝা (${pm['test_set_size']}টি লেবেল করা কমান্ড)', '1. Understanding commands (${pm['test_set_size']} labelled commands)'),
                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
            const SizedBox(height: 8),
            _grid([
              _stat(tr(bn, 'ইনটেন্ট', 'Intent'), _pct(pm['intent_accuracy'])),
              _stat(tr(bn, 'টাকার পরিমাণ', 'Amount'), _pct(pm['amount_accuracy'])),
              _stat(tr(bn, 'প্রাপক', 'Recipient'), _pct(pm['recipient_accuracy'])),
              _stat(tr(bn, 'ভুল পরিমাণ (না জিজ্ঞেস করে)', 'Silent wrong amount'), _pct(pm['silent_wrong_amount_rate']),
                  color: BrandColors.green, sub: tr(bn, 'লক্ষ্য: ০%', 'Target: 0%')),
            ]),
            if (failures.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(tr(bn, 'ব্যর্থ কেস: ${failures.length}', 'Failed cases: ${failures.length}')),
            ],
            const SizedBox(height: 20),
            Text(tr(bn, '২. স্ক্যাম শিল্ড (সিনথেটিক টেস্ট সেট)', '2. Scam shield (synthetic test set)'),
                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
            const SizedBox(height: 8),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Table(
                  columnWidths: const {0: FlexColumnWidth(2.2), 1: FlexColumnWidth(1), 2: FlexColumnWidth(1)},
                  children: [
                    TableRow(children: [
                      const SizedBox(),
                      Text(tr(bn, 'বলো upay', 'Bolo upay'), style: const TextStyle(fontWeight: FontWeight.w700)),
                      Text(tr(bn, 'শুধু রুল', 'Rules only'), style: const TextStyle(fontWeight: FontWeight.w700)),
                    ]),
                    for (final row in [
                      ('scam_flagged_rate', tr(bn, 'স্ক্যাম ধরা পড়েছে', 'Scams flagged')),
                      ('scam_red_rate', tr(bn, 'স্ক্যাম আটকানো (RED)', 'Scams held (RED)')),
                      ('legit_red_rate', tr(bn, 'সৎ লেনদেন ভুলে আটকানো', 'Honest transfers held')),
                      ('legit_flagged_rate', tr(bn, 'সৎ লেনদেনে সতর্কতা', 'Honest transfers warned')),
                    ])
                      TableRow(children: [
                        Padding(padding: const EdgeInsets.symmetric(vertical: 6), child: Text(row.$2)),
                        Padding(padding: const EdgeInsets.symmetric(vertical: 6), child: Text(_pct(ml[row.$1]))),
                        Padding(padding: const EdgeInsets.symmetric(vertical: 6), child: Text(_pct(base[row.$1]))),
                      ]),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 8),
            Text('AUC: LR ${rm['test_auc']?['logistic_regression']} · GBM ${rm['test_auc']?['gradient_boosting']}  ·  '
                '${tr(bn, 'থ্রেশহোল্ড', 'thresholds')} ${rm['thresholds']}'),
            const SizedBox(height: 16),
            Text(tr(bn, '৩. মডেল কী দেখে (লজিস্টিক রিগ্রেশন ওজন)', '3. What the model looks at (logistic regression weights)'),
                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
            const SizedBox(height: 8),
            Card(
              child: Column(children: [
                for (final e in (coef.entries.toList()..sort((a, b) => (b.value as num).compareTo(a.value as num))))
                  ListTile(
                    dense: true,
                    title: Text(e.key),
                    trailing: Text((e.value as num).toStringAsFixed(2),
                        style: TextStyle(color: (e.value as num) > 0 ? BrandColors.red : BrandColors.green, fontWeight: FontWeight.w700)),
                  ),
              ]),
            ),
            const SizedBox(height: 12),
            Text('${rm['dataset']?['note'] ?? ''}\n${pm['note'] ?? ''}', style: const TextStyle(color: BrandColors.muted, fontSize: 12)),
          ]);
        },
      ),
    );
  }
}
