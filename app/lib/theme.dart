import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// upay-inspired palette. Adjust these constants to match the official
/// upay design system if upay shares it; every screen reads from here.
class BrandColors {
  static const navy = Color(0xFF0B3A75);
  static const navyDark = Color(0xFF072650);
  static const yellow = Color(0xFFFFC72C);
  static const red = Color(0xFFE31E24);
  static const bg = Color(0xFFF4F6FA);
  static const card = Colors.white;
  static const text = Color(0xFF1B2433);
  static const muted = Color(0xFF6B7585);
  static const green = Color(0xFF1E9E5A);
  static const greenBg = Color(0xFFE6F6EE);
  static const amber = Color(0xFFB7791F);
  static const amberBg = Color(0xFFFFF5DB);
  static const redBg = Color(0xFFFDE8E8);
}

ThemeData buildTheme() {
  final base = ThemeData(
    useMaterial3: true,
    fontFamily: GoogleFonts.hindSiliguri().fontFamily,
    colorScheme: ColorScheme.fromSeed(
      seedColor: BrandColors.navy,
      primary: BrandColors.navy,
      secondary: BrandColors.yellow,
      surface: BrandColors.card,
    ),
    scaffoldBackgroundColor: BrandColors.bg,
  );
  return base.copyWith(
    textTheme: base.textTheme.apply(bodyColor: BrandColors.text, displayColor: BrandColors.text),
    appBarTheme: const AppBarTheme(
      backgroundColor: BrandColors.navy,
      foregroundColor: Colors.white,
      elevation: 0,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: BrandColors.navy,
        foregroundColor: Colors.white,
        minimumSize: const Size.fromHeight(52),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        textStyle: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size.fromHeight(52),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
    cardTheme: CardThemeData(
      color: BrandColors.card,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
    ),
  );
}

Color levelColor(String level) => switch (level) {
      'GREEN' => BrandColors.green,
      'YELLOW' => BrandColors.amber,
      'RED' => BrandColors.red,
      _ => BrandColors.muted,
    };

Color levelBg(String level) => switch (level) {
      'GREEN' => BrandColors.greenBg,
      'YELLOW' => BrandColors.amberBg,
      'RED' => BrandColors.redBg,
      _ => BrandColors.bg,
    };
