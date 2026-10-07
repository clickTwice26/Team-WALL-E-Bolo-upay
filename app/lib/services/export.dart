import 'dart:convert';

import 'package:flutter/services.dart';

import 'export_none.dart' if (dart.library.js_interop) 'export_web.dart' as impl;

/// Study logs leave the phone only when the facilitator exports them: a file
/// download on web, the clipboard elsewhere (paste it into a file or email).
/// Returns true for a download, false for the clipboard.
Future<bool> exportJson(String filename, Map<String, dynamic> data) async {
  final text = const JsonEncoder.withIndent(' ').convert(data);
  if (impl.download(filename, text)) return true;
  await Clipboard.setData(ClipboardData(text: text));
  return false;
}

/// "bolo-audio-P03-20261007-1412.json": sortable, no personal data.
String exportName(String kind, String participant) {
  final t = DateTime.now();
  String two(int n) => n.toString().padLeft(2, '0');
  final safe = participant.replaceAll(RegExp(r'[^A-Za-z0-9_-]'), '');
  return 'bolo-$kind-${safe.isEmpty ? 'anon' : safe}-${t.year}${two(t.month)}${two(t.day)}-${two(t.hour)}${two(t.minute)}.json';
}
