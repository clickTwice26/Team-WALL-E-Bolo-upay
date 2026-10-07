import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../api.dart';

/// Speech-to-text and text-to-speech. Raw audio never leaves the device:
/// only the transcript is sent to the API, and the user can edit it first.
///
/// Speaking tries the server's natural voice first (Gemini TTS, when the
/// server has a key) and falls back to the best voice on the device.
class Voice {
  Voice._();
  static final Voice instance = Voice._();

  final SpeechToText _stt = SpeechToText();
  final FlutterTts _tts = FlutterTts();
  final AudioPlayer _player = AudioPlayer();
  final Map<bool, Map<String, String>> _voices = {};
  bool _ready = false;
  bool available = false;

  /// The recognizer reported low confidence for the last final result
  /// (the app then asks the user to check the words before using them).
  bool lastUnsure = false;
  static const minConfidence = 0.6;

  /// Bumped by every speak()/silence(): a slow server reply for an older
  /// sentence must not start playing over a newer one.
  int _seq = 0;
  int _serverFailures = 0;

  Future<bool> init() async {
    if (_ready) return available;
    _ready = true;
    try {
      available = await _stt.initialize(onError: (_) {}, onStatus: (_) {});
    } catch (_) {
      available = false;
    }
    return available;
  }

  String _locale(bool bangla) => bangla ? (kIsWeb ? 'bn-BD' : 'bn_BD') : (kIsWeb ? 'en-US' : 'en_US');

  Future<void> listen({required bool bangla, required void Function(String text, bool done) onText}) async {
    if (!await init()) return;
    await _stt.listen(
      onResult: (SpeechRecognitionResult r) {
        if (r.finalResult) lastUnsure = r.hasConfidenceRating && r.confidence < minConfidence;
        onText(r.recognizedWords, r.finalResult);
      },
      listenOptions: SpeechListenOptions(
        localeId: _locale(bangla),
        partialResults: true,
        cancelOnError: true,
        listenFor: const Duration(seconds: 20),
        pauseFor: const Duration(seconds: 3),
      ),
    );
  }

  Future<void> stop() async {
    if (_stt.isListening) await _stt.stop();
  }

  bool get isListening => _stt.isListening;

  /// The most natural installed voice for the language ("Microsoft ... Online
  /// (Natural)", "Google বাংলা", enhanced iOS voices), or null.
  Future<Map<String, String>?> _bestVoice(bool bangla) async {
    if (_voices.containsKey(bangla)) return _voices[bangla];
    final lang = bangla ? 'bn' : 'en';
    Map<String, String>? best;
    var bestScore = -1;
    try {
      final voices = (await _tts.getVoices as List?) ?? const [];
      for (final v in voices) {
        final name = '${v['name'] ?? ''}';
        final locale = '${v['locale'] ?? ''}'.toLowerCase().replaceAll('_', '-');
        if (name.isEmpty || !locale.startsWith(lang)) continue;
        final n = name.toLowerCase();
        var score = 0;
        if (n.contains('natural') || n.contains('neural')) score += 100;
        if (n.contains('online')) score += 40;
        if (n.contains('google')) score += 30;
        if (n.contains('premium') || n.contains('enhanced')) score += 30;
        if (locale.endsWith('bd') || locale.endsWith('us') || locale.endsWith('gb')) score += 10;
        if (score > bestScore) {
          bestScore = score;
          best = {'name': name, 'locale': '${v['locale']}'};
        }
      }
    } catch (_) {}
    // browsers load voices lazily: only remember an answer once there is one
    if (best != null) _voices[bangla] = best;
    return best;
  }

  Future<void> speak(String text, {required bool bangla}) async {
    final seq = ++_seq;
    if (text.trim().isEmpty) return;
    await _stopAudio();
    if (_serverFailures < 2 && text.length <= 400) {
      final wav = await Api.tts(text);
      if (seq != _seq) return;
      if (wav != null) {
        _serverFailures = 0;
        try {
          await _player.play(BytesSource(wav, mimeType: 'audio/wav'));
          return;
        } catch (_) {
          // fall through to the device voice
        }
      } else {
        _serverFailures++; // after two misses in a row, stop asking the server
      }
    }
    if (seq != _seq) return;
    try {
      await _tts.setLanguage(bangla ? 'bn-BD' : 'en-US');
      final voice = await _bestVoice(bangla);
      if (voice != null) await _tts.setVoice(voice);
      await _tts.setSpeechRate(kIsWeb ? 0.95 : 0.45);
      await _tts.setPitch(1.0);
      if (seq != _seq) return;
      await _tts.speak(text);
    } catch (_) {
      // a device without a Bangla voice still shows the text on screen
    }
  }

  Future<void> _stopAudio() async {
    try {
      await _player.stop();
    } catch (_) {}
    try {
      await _tts.stop();
    } catch (_) {}
  }

  Future<void> silence() async {
    _seq++;
    await _stopAudio();
  }
}
