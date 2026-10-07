import 'package:flutter/material.dart';

import '../screens/eval_mode.dart' show audioConditions, studyDialects;
import '../strings.dart';
import '../theme.dart';

/// Accuracy screen, "Real audio" (R1): the phone's speech recognition plus
/// the parser on real Bangla speech, from model/audio_metrics.json. Says so
/// plainly when the study has not run yet or the numbers are the sample.
class RealAudioCard extends StatelessWidget {
  const RealAudioCard({super.key, required this.metrics, required this.bangla});
  final Map<String, dynamic>? metrics;
  final bool bangla;

  String _pct(dynamic v) {
    if (v == null) return '–';
    final s = '${((v as num) * 100).toStringAsFixed(1)}%';
    return bangla ? bnDigits(s) : s;
  }

  String _label(Map<String, (String, String)> names, String key) =>
      names[key] == null ? key : (bangla ? names[key]!.$1 : names[key]!.$2);

  Widget _cell(String t, {bool bold = false, Color? color}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Text(t, style: TextStyle(fontSize: 13, fontWeight: bold ? FontWeight.w700 : FontWeight.w400, color: color)),
      );

  TableRow _row(String label, Map m, {bool bold = false}) {
    final swa = m['silent_wrong_amount_rate'] as num?;
    return TableRow(children: [
      _cell(label, bold: bold),
      _cell(_pct(m['wer'])),
      _cell(_pct(m['amount_accuracy'])),
      _cell(_pct(m['recipient_accuracy'])),
      _cell(_pct(swa), bold: true, color: swa == null ? null : (swa <= 0.01 ? BrandColors.green : BrandColors.red)),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final bn = bangla;
    final m = metrics;
    final title = Text(tr(bn, '১খ. আসল কণ্ঠে (রিয়েল অডিও)', '1b. Real Bangla speech (real audio)'),
        style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16));
    if (m == null) {
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        title,
        const SizedBox(height: 8),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Text(tr(bn,
                'এখনো চালানো হয়নি। আসল মানুষের কণ্ঠে পরীক্ষা (১২+ জন × ৩ পরিবেশ) বাকি; নিয়ম docs/AUDIO_EVAL.md-এ। ওপরের সংখ্যা টাইপ করা কমান্ডের।',
                'Not run yet. The real-speech study (12+ speakers × 3 conditions) is still to do; see docs/AUDIO_EVAL.md. The numbers above are for typed commands.')),
          ),
        ),
      ]);
    }
    final o = Map<String, dynamic>.from(m['overall'] ?? {});
    final design = Map<String, dynamic>.from(m['design'] ?? {});
    final target = Map<String, dynamic>.from(m['target'] ?? {});
    final byCond = Map<String, dynamic>.from(m['by_condition'] ?? {});
    final byDialect = Map<String, dynamic>.from(m['by_dialect'] ?? {});
    String n(Object? v) => bn ? bnDigits('$v') : '$v';
    final header = TableRow(children: [
      const SizedBox(),
      for (final h in [('WER', 'WER'), ('টাকা', 'Amount'), ('প্রাপক', 'Recipient'), ('নীরবে ভুল টাকা', 'Silent wrong ৳')])
        _cell(bn ? h.$1 : h.$2, bold: true),
    ]);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      title,
      if (m['sample'] == true)
        Text(tr(bn, 'নমুনা (সিনথেটিক লগ), আসল ফলাফল নয়', 'SAMPLE (synthetic log), not real results'),
            style: const TextStyle(color: BrandColors.red, fontSize: 12, fontWeight: FontWeight.w600)),
      const SizedBox(height: 8),
      Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(tr(bn, '${n(design['speakers'])} জন বক্তা, ${n(o['utterances'])}টি বাক্য, কনফিডেন্স গড় ${n(o['mean_confidence'] ?? '–')}',
                '${design['speakers']} speakers, ${o['utterances']} utterances, mean confidence ${o['mean_confidence'] ?? '–'}'),
                style: const TextStyle(fontSize: 13)),
            const SizedBox(height: 6),
            Table(
              columnWidths: const {0: FlexColumnWidth(1.6), 1: FlexColumnWidth(1), 2: FlexColumnWidth(1), 3: FlexColumnWidth(1), 4: FlexColumnWidth(1.2)},
              children: [
                header,
                _row(tr(bn, 'সব মিলিয়ে', 'Overall'), o, bold: true),
                // quiet -> street -> bus/TV: the order noise gets worse
                for (final c in [...audioConditions.keys, ...byCond.keys.where((k) => !audioConditions.containsKey(k))])
                  if (byCond[c] != null) _row(_label(audioConditions, c), byCond[c] as Map),
                for (final e in byDialect.entries) _row(_label(studyDialects, e.key), e.value as Map),
              ],
            ),
            const SizedBox(height: 8),
            Text(
                tr(bn,
                    'লক্ষ্য: না জিজ্ঞেস করে ভুল টাকা ≤ ১% (${target['met'] == true ? 'পূরণ হয়েছে' : 'পূরণ হয়নি'})। জিজ্ঞেস করার হার ${_pct(o['clarification_rate'])}।'
                        '${design['meets_design'] == true ? '' : ' ১২+ জন × ৩ পরিবেশ এখনো পূর্ণ হয়নি।'}',
                    'Target: silent wrong amount ≤ 1% (${target['met'] == true ? 'met' : 'not met'}). Asked to clarify ${_pct(o['clarification_rate'])}.'
                        '${design['meets_design'] == true ? '' : ' The 12+ speakers × 3 conditions design is not complete yet.'}'),
                style: const TextStyle(color: BrandColors.muted, fontSize: 12)),
          ]),
        ),
      ),
    ]);
  }
}
