import 'package:flutter/material.dart';

import 'screens/assistant.dart';
import 'screens/home.dart';
import 'screens/insights.dart';
import 'state.dart';
import 'strings.dart';
import 'theme.dart';

void main() {
  runApp(const BoloUpayApp());
  appState.load();
}

class BoloUpayApp extends StatelessWidget {
  const BoloUpayApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Bolo upay (prototype)',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      builder: (context, child) => Column(children: [
        Expanded(child: child!),
        const _PrototypeRibbon(),
      ]),
      home: const Shell(),
    );
  }
}

/// Always visible: this is a hackathon prototype, not the official upay app.
class _PrototypeRibbon extends StatelessWidget {
  const _PrototypeRibbon();

  @override
  Widget build(BuildContext context) {
    return Material(
      color: BrandColors.navyDark,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 8),
          child: Text(
            'Prototype for AI Dev Fest 2026 · not the official upay app · synthetic demo data',
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.white.withValues(alpha: 0.85), fontSize: 11),
          ),
        ),
      ),
    );
  }
}

class Shell extends StatefulWidget {
  const Shell({super.key});
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int tab = 0;

  Widget _nav(int i, IconData icon, String label) {
    final on = tab == i;
    final c = on ? BrandColors.navy : BrandColors.muted;
    return Expanded(
      child: InkWell(
        onTap: () => setState(() => tab = i),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          Icon(icon, color: c),
          Text(label, style: TextStyle(fontSize: 12, color: c, fontWeight: on ? FontWeight.w700 : FontWeight.w500)),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: appState,
      builder: (context, _) {
        final bn = appState.bangla;
        return Scaffold(
          body: IndexedStack(index: tab, children: const [HomeScreen(), DashboardScreen(), AccuracyScreen()]),
          floatingActionButton: SizedBox(
            width: 70,
            height: 70,
            child: FloatingActionButton(
              backgroundColor: BrandColors.navy,
              foregroundColor: Colors.white,
              elevation: 4,
              shape: const CircleBorder(side: BorderSide(color: Colors.white, width: 4)),
              tooltip: 'বলো upay',
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const AssistantScreen())),
              child: const Icon(Icons.mic_rounded, size: 34),
            ),
          ),
          floatingActionButtonLocation: FloatingActionButtonLocation.centerDocked,
          bottomNavigationBar: BottomAppBar(
            color: const Color(0xFFFFFBEA),
            height: 68,
            padding: EdgeInsets.zero,
            notchMargin: 6,
            shape: const CircularNotchedRectangle(),
            child: Row(children: [
              _nav(0, Icons.home_rounded, tr(bn, 'হোম', 'Home')),
              _nav(1, Icons.shield_outlined, tr(bn, 'ড্যাশবোর্ড', 'Dashboard')),
              const Expanded(child: SizedBox()),
              _nav(2, Icons.analytics_outlined, tr(bn, 'অ্যাকুরেসি', 'Accuracy')),
              Expanded(
                child: InkWell(
                  onTap: appState.toggleLanguage,
                  child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                    const Icon(Icons.translate_rounded, color: BrandColors.muted),
                    Text(bn ? 'English' : 'বাংলা', style: const TextStyle(fontSize: 12, color: BrandColors.muted)),
                  ]),
                ),
              ),
            ]),
          ),
        );
      },
    );
  }
}
