import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../strings.dart';
import '../theme.dart';

/// Large-key PIN pad. Digits are never spoken aloud; each tap vibrates.
class PinPad extends StatefulWidget {
  const PinPad({super.key, required this.bangla, required this.onSubmit, this.length = 4, this.error});

  final bool bangla;
  final int length;
  final String? error;
  final ValueChanged<String> onSubmit;

  @override
  State<PinPad> createState() => _PinPadState();
}

class _PinPadState extends State<PinPad> {
  String _pin = '';

  void _tap(String d) {
    HapticFeedback.lightImpact();
    if (_pin.length >= widget.length) return;
    setState(() => _pin += d);
    if (_pin.length == widget.length) {
      final p = _pin;
      Future.delayed(const Duration(milliseconds: 120), () {
        if (mounted) setState(() => _pin = '');
        widget.onSubmit(p);
      });
    }
  }

  void _back() {
    HapticFeedback.selectionClick();
    if (_pin.isNotEmpty) setState(() => _pin = _pin.substring(0, _pin.length - 1));
  }

  Widget _key(String label, {VoidCallback? onTap, Widget? child}) => Expanded(
        child: Padding(
          padding: const EdgeInsets.all(3),
          child: Material(
            color: label.isEmpty ? Colors.transparent : Colors.white,
            elevation: label.isEmpty ? 0 : 1,
            borderRadius: BorderRadius.circular(8),
            child: InkWell(
              borderRadius: BorderRadius.circular(8),
              onTap: onTap,
              child: SizedBox(
                height: 54,
                child: Center(
                  child: child ??
                      Text(widget.bangla ? bnDigits(label) : label,
                          style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w600)),
                ),
              ),
            ),
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          margin: const EdgeInsets.symmetric(horizontal: 24),
          padding: const EdgeInsets.symmetric(vertical: 14),
          decoration: BoxDecoration(color: const Color(0xFFF0F2F6), borderRadius: BorderRadius.circular(30)),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: List.generate(
              widget.length,
              (i) => Container(
                margin: const EdgeInsets.symmetric(horizontal: 12),
                width: 16,
                height: 16,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: i < _pin.length ? BrandColors.navy : const Color(0xFFB9C7E3),
                ),
              ),
            ),
          ),
        ),
        if (widget.error != null)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(widget.error!, style: const TextStyle(color: BrandColors.red)),
          ),
        const SizedBox(height: 14),
        Container(
          padding: const EdgeInsets.all(4),
          decoration: BoxDecoration(color: const Color(0xFFD5D8DE), borderRadius: BorderRadius.circular(12)),
          child: Column(children: [
            for (final row in const [
              ['1', '2', '3'],
              ['4', '5', '6'],
              ['7', '8', '9']
            ])
              Row(children: [for (final d in row) _key(d, onTap: () => _tap(d))]),
            Row(children: [
              _key('', child: const SizedBox()),
              _key('0', onTap: () => _tap('0')),
              _key('', onTap: _back, child: const Icon(Icons.backspace_outlined)),
            ]),
          ]),
        ),
      ],
    );
  }
}
