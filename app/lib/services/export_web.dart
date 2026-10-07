import 'dart:async';
import 'dart:js_interop';

import 'package:web/web.dart' as web;

/// Web: save the JSON as a file through a temporary download link.
bool download(String filename, String text) {
  try {
    final blob = web.Blob([text.toJS].toJS, web.BlobPropertyBag(type: 'application/json'));
    final url = web.URL.createObjectURL(blob);
    final a = web.HTMLAnchorElement()
      ..href = url
      ..download = filename;
    web.document.body?.append(a);
    a.click();
    a.remove();
    // revoking at once can cancel the download in some browsers
    Timer(const Duration(seconds: 5), () => web.URL.revokeObjectURL(url));
    return true;
  } catch (_) {
    return false;
  }
}
