import 'package:flutter/material.dart';

import 'screens/assistant.dart';
import 'screens/home.dart';
import 'screens/insights.dart';
import 'screens/login.dart';
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
      builder: (context, child) => _PhoneFrame(
        child: Column(children: [
          Expanded(child: child!),
          const _PrototypeRibbon(),
        ]),
      ),
      home: const _Gate(),
    );
  }
}

/// Always the mobile layout: on a wide screen the app sits in a 430px column.
class _PhoneFrame extends StatelessWidget {
  const _PhoneFrame({required this.child});
  final Widget child;

  static const double _width = 430;

  @override
  Widget build(BuildContext context) {
    final mq = MediaQuery.of(context);
    if (mq.size.width <= _width) return child;
    return ColoredBox(
      color: BrandColors.navyDark,
      child: Center(
        child: SizedBox(
          width: _width,
          child: ClipRect(
            child: MediaQuery(data: mq.copyWith(size: Size(_width, mq.size.height)), child: child),
          ),
        ),
      ),
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

/// PIN unlock first (demo PIN 1234), then the app.
class _Gate extends StatefulWidget {
  const _Gate();
  @override
  State<_Gate> createState() => _GateState();
}

class _GateState extends State<_Gate> {
  bool unlocked = false;
  @override
  Widget build(BuildContext context) =>
      unlocked ? const Shell() : LoginScreen(onUnlocked: () => setState(() => unlocked = true));
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
              _nav(1, Icons.history_rounded, tr(bn, 'ড্যাশবোর্ড', 'Dashboard')),
              const Expanded(child: SizedBox()),
              _nav(2, Icons.account_balance_wallet_outlined, tr(bn, 'অ্যাকুরেসি', 'Accuracy')),
              Expanded(
                child: InkWell(
                  onTap: appState.toggleLanguage,
                  child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                    const Icon(Icons.more_horiz_rounded, color: BrandColors.muted),
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
