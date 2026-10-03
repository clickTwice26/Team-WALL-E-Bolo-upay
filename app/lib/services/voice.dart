import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';

/// Speech-to-text and text-to-speech. Raw audio never leaves the device:
/// only the transcript is sent to the API, and the user can edit it first.
class Voice {
  Voice._();
  static final Voice instance = Voice._();

  final SpeechToText _stt = SpeechToText();
  final FlutterTts _tts = FlutterTts();
  bool _ready = false;
  bool available = false;

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
      onResult: (SpeechRecognitionResult r) => onText(r.recognizedWords, r.finalResult),
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

  Future<void> speak(String text, {required bool bangla}) async {
    try {
      await _tts.stop();
      await _tts.setLanguage(bangla ? 'bn-BD' : 'en-US');
      await _tts.setSpeechRate(kIsWeb ? 0.9 : 0.45);
      await _tts.speak(text);
    } catch (_) {
      // a device without a Bangla voice still shows the text on screen
    }
  }

  Future<void> silence() async {
    try {
      await _tts.stop();
    } catch (_) {}
  }
}
