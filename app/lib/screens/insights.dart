import 'package:flutter/material.dart';

import '../agent/agent.dart';
import '../api.dart';
import '../state.dart';
import '../strings.dart';
import '../theme.dart';

String _pct(dynamic v) => v == null ? '–' : '${((v as num) * 100).toStringAsFixed(1)}%';

/// What each risk-model input means, in plain words (Bangla, English).
const _featureNames = {
  'is_new_recipient': ('নতুন প্রাপক', 'New recipient'),
  'log_recipient_ratio': ('এই প্রাপকের জন্য পরিমাণ বেশি', 'Amount high for this recipient'),
  'is_night': ('গভীর রাত', 'Late at night'),
  'recent_sends_30m': ('৩০ মিনিটে কয়েকবার পাঠানো', 'Several sends in 30 minutes'),
  'balance_fraction': ('ব্যালেন্সের বড় অংশ', 'Large share of balance'),
  'on_active_call': ('ফোন কল চলছে', 'On a phone call'),
  'return_claim_no_inflow': ('"ফেরত দিন", কিন্তু টাকা আসেনি', '"Send it back", but nothing came'),
  'scam_score': ('কথায় প্রতারণার লক্ষণ', 'Scam phrases in what was said'),
  'is_recharge': ('মোবাইল রিচার্জ', 'Mobile recharge'),
  'sends_24h': ('২৪ ঘণ্টায় কতবার পাঠানো', 'Payments in the last 24 hours'),
  'new_recipients_7d': ('৭ দিনে নতুন প্রাপক', 'New recipients in 7 days'),
  'inflow_then_outflow': ('অচেনা টাকা এসে আবার চলে যাচ্ছে', 'Stranger\'s money passed on'),
  'amount_z_user': ('আপনার জন্য অস্বাভাবিক পরিমাণ', 'Amount unusual for you'),
  'log_recipient_age': ('এই প্রাপককে কতদিন ধরে টাকা দেন', 'How long you have paid this number'),
  'hour_unusual_for_user': ('আপনার জন্য অস্বাভাবিক সময়', 'Unusual time for you'),
  'recipient_paid_you_7d': ('প্রাপক সম্প্রতি আপনাকে টাকা দিয়েছে', 'Recipient paid you recently'),
  'is_cash_out': ('ক্যাশ আউট', 'Cash out'),
  'is_payment': ('বিল বা মার্চেন্ট পেমেন্ট', 'Bill or merchant payment'),
};

const _modelNames = {
  'logistic_regression_9_features': ('আগের মডেল (৯টি তথ্য)', 'Previous model (9 inputs)'),
  'gradient_boosting_9_features': ('গ্রেডিয়েন্ট বুস্টিং (৯টি তথ্য)', 'Gradient boosting (9 inputs)'),
  'logistic_regression_all_features': ('লজিস্টিক রিগ্রেশন (সব তথ্য)', 'Logistic regression (all inputs)'),
  'gradient_boosting_all_features_calibrated': ('বলো upay মডেল (সব তথ্য, ক্যালিব্রেটেড)', 'Bolo upay model (all inputs, calibrated)'),
};

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
              const _Impact(),
              const SizedBox(height: 16),
              const _ModelHealth(),
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
          final importance = Map<String, dynamic>.from(rm['feature_importance'] ?? {});
          final comparison = Map<String, dynamic>.from(rm['comparison'] ?? {});
          final seqm = Map<String, dynamic>.from(s.data!['sequence_metrics'] ?? {});
          final topImpact = importance.isEmpty ? 1.0 : (importance.values.first as num).toDouble();
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
            Text('${tr(bn, 'থ্রেশহোল্ড', 'Thresholds')}: YELLOW ${rm['thresholds']?['yellow']} · RED ${rm['thresholds']?['red']}',
                style: const TextStyle(color: BrandColors.muted, fontSize: 12)),
            if (comparison.isNotEmpty) ...[
              const SizedBox(height: 16),
              Text(tr(bn, '৩. মডেলের তুলনা (একই টেস্ট সেট)', '3. Models compared (same test set)'),
                  style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
              const SizedBox(height: 8),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Table(
                    columnWidths: const {0: FlexColumnWidth(2.6), 1: FlexColumnWidth(1), 2: FlexColumnWidth(1)},
                    children: [
                      const TableRow(children: [
                        SizedBox(),
                        Text('PR-AUC', style: TextStyle(fontWeight: FontWeight.w700)),
                        Text('Brier', style: TextStyle(fontWeight: FontWeight.w700)),
                      ]),
                      for (final e in comparison.entries)
                        TableRow(children: [
                          Padding(
                            padding: const EdgeInsets.symmetric(vertical: 6),
                            child: Text(bn ? (_modelNames[e.key]?.$1 ?? e.key) : (_modelNames[e.key]?.$2 ?? e.key)),
                          ),
                          Padding(padding: const EdgeInsets.symmetric(vertical: 6), child: Text('${e.value['pr_auc']}')),
                          Padding(padding: const EdgeInsets.symmetric(vertical: 6), child: Text('${e.value['brier']}')),
                        ]),
                    ],
                  ),
                ),
              ),
              Text(tr(bn, 'PR-AUC বেশি = ভালো; Brier কম = সম্ভাবনা বেশি নির্ভুল।', 'Higher PR-AUC is better; lower Brier means truer probabilities.'),
                  style: const TextStyle(color: BrandColors.muted, fontSize: 12)),
              if (seqm['gru_over_last_20_plus_features'] != null)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text(
                      tr(bn,
                          'সিকোয়েন্স মডেল (শেষ ২০টি লেনদেনের ওপর GRU): PR-AUC ${seqm['gru_over_last_20_plus_features']['pr_auc']}। '
                              '${seqm['adopted'] == true ? 'গ্রহণ করা হয়েছে।' : 'গ্রহণ করা হয়নি: ০.০১-এর বেশি উন্নতি হয়নি।'}',
                          'Sequence model (GRU over the last 20 payments): PR-AUC ${seqm['gru_over_last_20_plus_features']['pr_auc']}. '
                              '${seqm['adopted'] == true ? 'Adopted.' : 'Not adopted: it did not improve PR-AUC by more than 0.01.'}'),
                      style: const TextStyle(fontSize: 13)),
                ),
            ],
            const SizedBox(height: 16),
            Text(tr(bn, '৪. মডেল কী দেখে (গড় SHAP প্রভাব)', '4. What the model looks at (average SHAP impact)'),
                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
            const SizedBox(height: 8),
            Card(
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Column(children: [
                  for (final e in importance.entries)
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 5),
                      child: Row(children: [
                        Expanded(
                          flex: 5,
                          child: Text(bn ? (_featureNames[e.key]?.$1 ?? e.key) : (_featureNames[e.key]?.$2 ?? e.key),
                              style: const TextStyle(fontSize: 13)),
                        ),
                        Expanded(
                          flex: 4,
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(3),
                            child: LinearProgressIndicator(
                              value: ((e.value as num) / topImpact).clamp(0.0, 1.0).toDouble(),
                              minHeight: 8,
                              backgroundColor: BrandColors.bg,
                              color: BrandColors.navy,
                            ),
                          ),
                        ),
                      ]),
                    ),
                ]),
              ),
            ),
            Text(tr(bn, 'প্রতিটি সতর্কতার কারণ ওই লেনদেনের SHAP মান থেকে আসে।', 'Each warning\'s reasons come from that payment\'s own SHAP values.'),
                style: const TextStyle(color: BrandColors.muted, fontSize: 12)),
            const SizedBox(height: 12),
            Text('${rm['dataset']?['note'] ?? ''}\n${pm['note'] ?? ''}', style: const TextStyle(color: BrandColors.muted, fontSize: 12)),
          ]);
        },
      ),
    );
  }
}

/// Model health (failure policy): drift against training, overrides of RED,
/// warnings users called wrong, and alerts for the threshold review.
class _ModelHealth extends StatelessWidget {
  const _ModelHealth();

  @override
  Widget build(BuildContext context) {
    final bn = appState.bangla;
    return FutureBuilder<Map<String, dynamic>>(
      future: Api.monitor(),
      builder: (context, s) {
        if (!s.hasData) return const SizedBox.shrink();
        final m = s.data!;
        final drift = Map<String, dynamic>.from(m['drift_psi'] ?? {});
        final alerts = List<String>.from(m['alerts'] ?? const []);
        return Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(tr(bn, 'মডেলের স্বাস্থ্য (শেষ ${bnDigits('${m['window_days']}')} দিন)', 'Model health (last ${m['window_days']} days)'),
                  style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
              const SizedBox(height: 6),
              Text(tr(bn, 'যাচাই: ${bnDigits('${m['checks']}')} · RED-এর পরও পাঠানো: ${_pct(m['red_override_rate'])} · ভুল সতর্কতার রিপোর্ট: ${_pct(m['wrong_warning_rate'])}',
                  'Checks: ${m['checks']} · RED still sent: ${_pct(m['red_override_rate'])} · Warnings reported wrong: ${_pct(m['wrong_warning_rate'])}')),
              if (drift.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(tr(bn, 'ট্রেনিংয়ের তুলনায় পরিবর্তন (PSI, ০.২-এর বেশি হলে সতর্কতা)', 'Shift since training (PSI, alert above 0.2)'),
                    style: const TextStyle(color: BrandColors.muted, fontSize: 12)),
                for (final e in drift.entries.take(5))
                  Row(children: [
                    Expanded(child: Text(e.key, style: const TextStyle(fontSize: 13))),
                    Text('${e.value}',
                        style: TextStyle(
                            fontWeight: FontWeight.w700,
                            color: (e.value as num) > 0.2 ? BrandColors.red : BrandColors.green)),
                  ]),
              ],
              for (final a in alerts)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Icon(Icons.warning_amber_rounded, size: 18, color: BrandColors.amber),
                    const SizedBox(width: 6),
                    Expanded(child: Text(a, style: const TextStyle(fontSize: 13))),
                  ]),
                ),
            ]),
          ),
        );
      },
    );
  }
}

/// Impact simulator: transfers -> scams -> flagged -> stopped -> Tk protected,
/// the honest users it bothers, and call-centre disputes avoided. Always
/// labelled as a simulation on synthetic data.
class _Impact extends StatefulWidget {
  const _Impact();
  @override
  State<_Impact> createState() => _ImpactState();
}

class _ImpactState extends State<_Impact> {
  static const _prevalences = [0.258, 0.05, 0.01];
  static const _volumes = [1000, 100000, 1000000];
  double prevalence = 0.01;
  int transfers = 1000;
  late Future<Map<String, dynamic>> _f = Api.impact(transfers, prevalence);

  void _set({double? p, int? t}) => setState(() {
        prevalence = p ?? prevalence;
        transfers = t ?? transfers;
        _f = Api.impact(transfers, prevalence);
      });

  String _n(num v, bool bn) {
    final s = v >= 100 ? v.round().toString() : v.toStringAsFixed(1);
    final grouped = s.replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+(?!\d))'), (m) => '${m[1]},');
    return bn ? bnDigits(grouped) : grouped;
  }

  @override
  Widget build(BuildContext context) {
    final bn = appState.bangla;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(tr(bn, 'প্রভাব (সিমুলেশন)', 'Impact (simulation)'), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
          Text(tr(bn, 'সিনথেটিক ডেটায় সিমুলেশন, আসল ফলাফল নয়', 'Simulation on synthetic data, not real results'),
              style: const TextStyle(color: BrandColors.red, fontSize: 12, fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          Wrap(spacing: 6, runSpacing: 6, children: [
            for (final p in _prevalences)
              ChoiceChip(
                  label: Text(tr(bn, 'স্ক্যাম ${bnDigits((p * 100).toStringAsFixed(p < 0.1 ? 0 : 1))}%', 'Scams ${(p * 100).toStringAsFixed(p < 0.1 ? 0 : 1)}%')),
                  selected: prevalence == p,
                  onSelected: (_) => _set(p: p)),
            for (final t in _volumes)
              ChoiceChip(label: Text(_n(t, bn)), selected: transfers == t, onSelected: (_) => _set(t: t)),
          ]),
          const SizedBox(height: 8),
          FutureBuilder<Map<String, dynamic>>(
            future: _f,
            builder: (context, s) {
              if (!s.hasData) {
                return s.hasError ? const SizedBox.shrink() : const LinearProgressIndicator(minHeight: 2);
              }
              final shield = Map<String, dynamic>.from(s.data!['shield'] ?? {});
              final me = Map<String, dynamic>.from(shield['bolo_upay']?['mid'] ?? {});
              final old = Map<String, dynamic>.from(shield['previous_model']?['mid'] ?? {});
              final d = Map<String, dynamic>.from(s.data!['disputes'] ?? {});
              Widget row(String label, num v, {num? before, Color color = BrandColors.text}) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 3),
                    child: Row(children: [
                      Expanded(child: Text(label, style: const TextStyle(fontSize: 13))),
                      Text(_n(v, bn), style: TextStyle(fontWeight: FontWeight.w700, color: color)),
                      if (before != null)
                        SizedBox(
                            width: 84,
                            child: Text(tr(bn, ' (আগে ${_n(before, bn)})', ' (was ${_n(before, false)})'),
                                textAlign: TextAlign.right, style: const TextStyle(color: BrandColors.muted, fontSize: 12))),
                    ]),
                  );
              return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                row(tr(bn, 'লেনদেন', 'Transfers'), transfers),
                row(tr(bn, 'স্ক্যাম', 'Scams among them'), me['scams'] ?? 0),
                row(tr(bn, 'ধরা পড়েছে', 'Flagged'), me['scams_flagged'] ?? 0, before: old['scams_flagged']),
                row(tr(bn, 'আটকানো (RED)', 'Held (RED)'), me['scams_held_red'] ?? 0, before: old['scams_held_red']),
                row(tr(bn, 'থামানো গেছে', 'Stopped'), me['scams_stopped'] ?? 0, before: old['scams_stopped']),
                row(tr(bn, 'রক্ষা পাওয়া টাকা (৳)', 'Money protected (৳)'), me['tk_protected'] ?? 0,
                    before: old['tk_protected'], color: BrandColors.green),
                const Divider(),
                row(tr(bn, 'সৎ লেনদেনে সতর্কতা', 'Honest payments warned'), me['honest_warned'] ?? 0, color: BrandColors.amber),
                row(tr(bn, 'সৎ লেনদেন আটকানো', 'Honest payments held'), me['honest_held_red'] ?? 0, color: BrandColors.amber),
                row(tr(bn, 'বাদ দেওয়া সৎ লেনদেন', 'Honest payments given up'), me['honest_payments_abandoned'] ?? 0,
                    color: BrandColors.amber),
                const Divider(),
                Text(
                    tr(bn,
                        'ভুল নম্বর/পরিমাণের অভিযোগ এড়ানো (উপায়, বছরে): ${_n(d['low']?['avoided_per_year'] ?? 0, true)}–${_n(d['high']?['avoided_per_year'] ?? 0, true)}, '
                            'খরচ সাশ্রয় ৳${_n(d['low']?['cost_saved_tk_per_year'] ?? 0, true)}–${_n(d['high']?['cost_saved_tk_per_year'] ?? 0, true)}',
                        'Wrong-number/amount disputes avoided (upay, per year): ${_n(d['low']?['avoided_per_year'] ?? 0, false)}–${_n(d['high']?['avoided_per_year'] ?? 0, false)}, '
                            'cost saved ৳${_n(d['low']?['cost_saved_tk_per_year'] ?? 0, false)}–${_n(d['high']?['cost_saved_tk_per_year'] ?? 0, false)}'),
                    style: const TextStyle(fontSize: 13)),
                const SizedBox(height: 4),
                Text(
                    tr(bn, 'মাঝারি অনুমান দেখানো হয়েছে; সব অনুমান data/impact_assumptions.json-এ।',
                        'Mid assumptions shown; every assumption is in data/impact_assumptions.json.'),
                    style: const TextStyle(color: BrandColors.muted, fontSize: 12)),
              ]);
            },
          ),
        ]),
      ),
    );
  }
}
