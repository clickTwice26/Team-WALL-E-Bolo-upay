import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../strings.dart';
import '../theme.dart';

/// upay-style PIN entry: dots in a pill, a round blue arrow to submit, and an
/// iOS-like keypad with letters. Digits are never spoken; each tap vibrates.
class PinPad extends StatefulWidget {
  const PinPad({
    super.key,
    required this.bangla,
    required this.onSubmit,
    this.length = 4,
    this.error,
    this.title,
    this.trailing,
  });

  final bool bangla;
  final int length;
  final String? error;
  final String? title;
  final Widget? trailing;
  final ValueChanged<String> onSubmit;

  @override
  State<PinPad> createState() => _PinPadState();
}

class _PinPadState extends State<PinPad> {
  String _pin = '';

  static const _letters = {
    '2': 'ABC', '3': 'DEF', '4': 'GHI', '5': 'JKL',
    '6': 'MNO', '7': 'PQRS', '8': 'TUV', '9': 'WXYZ',
  };

  void _tap(String d) {
    HapticFeedback.lightImpact();
    if (_pin.length >= widget.length) return;
    setState(() => _pin += d);
  }

  void _back() {
    HapticFeedback.selectionClick();
    if (_pin.isNotEmpty) setState(() => _pin = _pin.substring(0, _pin.length - 1));
  }

  void _submit() {
    if (_pin.length != widget.length) return;
    final p = _pin;
    setState(() => _pin = '');
    widget.onSubmit(p);
  }

  Widget _key(String d) => Expanded(
        child: Padding(
          padding: const EdgeInsets.all(3),
          child: Material(
            color: Colors.white,
            elevation: 0.6,
            borderRadius: BorderRadius.circular(6),
            child: InkWell(
              borderRadius: BorderRadius.circular(6),
              onTap: () => _tap(d),
              child: SizedBox(
                height: 50,
                child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                  Text(widget.bangla ? bnDigits(d) : d,
                      style: const TextStyle(fontSize: 24, height: 1.1, color: Colors.black)),
                  if (_letters[d] != null)
                    Text(_letters[d]!,
                        style: const TextStyle(fontSize: 9, letterSpacing: 2, fontWeight: FontWeight.w700, color: Colors.black87)),
                ]),
              ),
            ),
          ),
        ),
      );

  Widget _plain(Widget child, {VoidCallback? onTap}) => Expanded(
        child: InkWell(onTap: onTap, child: SizedBox(height: 56, child: Center(child: child))),
      );

  @override
  Widget build(BuildContext context) {
    final full = _pin.length == widget.length;
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 20),
        child: Row(children: [
          Expanded(
            child: Text(widget.title ?? (widget.bangla ? '৪ ডিজিট পিন' : '4 Digit PIN'),
                style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w500)),
          ),
          if (widget.trailing != null) widget.trailing!,
        ]),
      ),
      const SizedBox(height: 18),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 20),
        child: Row(children: [
          Expanded(
            child: Container(
              height: 58,
              decoration: BoxDecoration(color: const Color(0xFFF1F3F7), borderRadius: BorderRadius.circular(30)),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: List.generate(
                  widget.length,
                  (i) => Container(
                    width: 16,
                    height: 16,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: i < _pin.length ? BrandColors.navy : const Color(0xFFAFC0DE),
                    ),
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(width: 14),
          Material(
            color: full ? BrandColors.navy : BrandColors.navy.withValues(alpha: 0.45),
            shape: const CircleBorder(),
            child: InkWell(
              customBorder: const CircleBorder(),
              onTap: full ? _submit : null,
              child: const SizedBox(
                  width: 66, height: 66, child: Icon(Icons.arrow_forward_rounded, color: Colors.white, size: 30)),
            ),
          ),
        ]),
      ),
      if (widget.error != null)
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 10, 20, 0),
          child: Text(widget.error!, style: const TextStyle(color: BrandColors.red)),
        ),
      const SizedBox(height: 22),
      Container(
        color: const Color(0xFFD1D4DB),
        padding: const EdgeInsets.fromLTRB(4, 6, 4, 8),
        child: Column(children: [
          for (final row in const [
            ['1', '2', '3'],
            ['4', '5', '6'],
            ['7', '8', '9']
          ])
            Row(children: [for (final d in row) _key(d)]),
          Row(children: [
            _plain(const Text('+ * #', style: TextStyle(fontSize: 20, color: Colors.black87))),
            _key('0'),
            _plain(const Icon(Icons.backspace_outlined, color: Colors.black87), onTap: _back),
          ]),
        ]),
      ),
    ]);
  }
}
