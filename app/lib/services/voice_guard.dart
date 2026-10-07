import 'call_state.dart';
import 'voice.dart';

/// R10 voice guard: coercion cues measured on the phone and sent as scores and
/// yes/no only, never audio and never a voice print. It is an extra check next
/// to the PIN, never instead of it: voices can be cloned, so a matching voice
/// never lowers the risk; only a mismatch or a second voice raises it.
///
/// Measured now (Android):
///  - hesitation: the share of the spoken command spent in long pauses, from the
///    recognizer's sound levels ([pauseRatio]); the recognizer holds the
///    microphone, so no second recorder can run, and no audio is kept.
///  - speaker_echo: in a call (R11) with the loudspeaker on, the classic
///    "a scammer talks the victim through it on speaker" pattern.
/// Not measured yet: voice_mismatch and second_voice need an on-device speaker
/// model; until one lands, [speaker] answers null ("not measured"). What is left
/// is listed in docs/VOICE_GUARD.md.
class VoiceGuard {
  VoiceGuard._();
  static final VoiceGuard instance = VoiceGuard._();

  /// The on-device speaker model. Swap in a real one (TFLite) without touching the flow.
  SpeakerCheck speaker = const NotMeasured();

  double? _hesitation;

  /// A new payment command: keep the pause ratio only if the command was just spoken
  /// (by the mic button or through the Bolo agent); a typed command is not measured.
  void beginCommand() {
    final heard = Voice.instance.lastHeardAt;
    final fresh = heard != null && DateTime.now().difference(heard) < const Duration(seconds: 30);
    _hesitation = fresh ? Voice.instance.lastPauseRatio : null;
  }

  /// The `voice_signals` for /api/assess, or null when nothing was measured (web).
  Future<Map<String, dynamic>?> signals() async {
    final inCall = CallState.instance.inCall.value; // native only: the demo toggle has no speaker
    final echo = inCall == null ? null : inCall && (await CallState.instance.speakerOn() ?? false);
    final out = <String, dynamic>{
      'hesitation': _hesitation == null ? null : double.parse(_hesitation!.toStringAsFixed(3)),
      'speaker_echo': echo,
      'voice_mismatch': await speaker.voiceMismatch(),
      'second_voice': await speaker.secondVoice(),
    };
    return out.values.every((v) => v == null) ? null : out;
  }

  /// Share of the speech window (first to last loud sample) spent in pauses of
  /// at least [minPauseMs]. [samples] are (milliseconds, sound level) pairs as the
  /// recognizer reports them. Null when there is too little to judge: a short
  /// command, or no clear voice above the room noise.
  static double? pauseRatio(List<(int, double)> samples, {int minPauseMs = 300, int minSpanMs = 1500}) {
    if (samples.length < 10) return null;
    final levels = [for (final s in samples) s.$2]..sort();
    final lo = levels[(levels.length * 0.1).floor()], hi = levels[(levels.length * 0.9).floor()];
    if (hi - lo < 3) return null; // flat levels: no clear speech
    final cut = lo + 0.35 * (hi - lo); // quiet = closer to the noise floor than to speech
    final first = samples.indexWhere((s) => s.$2 > cut), last = samples.lastIndexWhere((s) => s.$2 > cut);
    final span = samples[last].$1 - samples[first].$1;
    if (span < minSpanMs) return null;
    var paused = 0, start = -1;
    for (var i = first; i <= last; i++) {
      final quiet = samples[i].$2 <= cut;
      if (quiet && start < 0) start = i;
      if (!quiet && start >= 0) {
        final len = samples[i].$1 - samples[start].$1;
        if (len >= minPauseMs) paused += len; // short gaps between words are normal speech
        start = -1;
      }
    }
    return (paused / span).clamp(0.0, 1.0);
  }
}

/// The speaker model's answers for the last command: true, false, or null = not measured.
/// A real implementation runs a small speaker-embedding model on the phone against an
/// opt-in voice print kept in secure storage; neither ever leaves the phone.
abstract class SpeakerCheck {
  /// The command was not spoken by the enrolled owner.
  Future<bool?> voiceMismatch();

  /// Two different speakers were heard in the command.
  Future<bool?> secondVoice();
}

/// Until the on-device model lands: nothing is measured, so nothing changes the risk.
class NotMeasured implements SpeakerCheck {
  const NotMeasured();
  @override
  Future<bool?> voiceMismatch() async => null;
  @override
  Future<bool?> secondVoice() async => null;
}
