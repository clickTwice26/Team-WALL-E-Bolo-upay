/// Bangla / English helpers.
const _bnDigits = ['০', '১', '২', '৩', '৪', '৫', '৬', '৭', '৮', '৯'];

String bnDigits(String s) =>
    s.replaceAllMapped(RegExp(r'\d'), (m) => _bnDigits[int.parse(m[0]!)]);

String groupDigits(num n) {
  final s = n.round().toString();
  final buf = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) buf.write(',');
    buf.write(s[i]);
  }
  return buf.toString();
}

/// "৳১,৫০০" in Bangla mode, "৳1,500" in English mode.
String taka(num n, bool bn) => '৳${bn ? bnDigits(groupDigits(n)) : groupDigits(n)}';

String maskPhone(String p) =>
    p.length == 11 ? '${p.substring(0, 3)}****${p.substring(7)}' : p;

String tr(bool bn, String bangla, String english) => bn ? bangla : english;
