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

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: appState,
      builder: (context, _) {
        final bn = appState.bangla;
        return Scaffold(
          body: IndexedStack(index: tab, children: const [HomeScreen(), DashboardScreen(), AccuracyScreen()]),
          floatingActionButton: tab == 0
              ? FloatingActionButton.large(
                  backgroundColor: BrandColors.navy,
                  foregroundColor: Colors.white,
                  shape: const CircleBorder(),
                  onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const AssistantScreen())),
                  child: const Icon(Icons.mic_rounded, size: 40),
                )
              : null,
          floatingActionButtonLocation: FloatingActionButtonLocation.centerDocked,
          bottomNavigationBar: NavigationBar(
            selectedIndex: tab,
            onDestinationSelected: (i) => setState(() => tab = i),
            destinations: [
              NavigationDestination(icon: const Icon(Icons.home_outlined), selectedIcon: const Icon(Icons.home), label: tr(bn, 'হোম', 'Home')),
              NavigationDestination(icon: const Icon(Icons.shield_outlined), selectedIcon: const Icon(Icons.shield), label: tr(bn, 'ড্যাশবোর্ড', 'Dashboard')),
              NavigationDestination(icon: const Icon(Icons.analytics_outlined), selectedIcon: const Icon(Icons.analytics), label: tr(bn, 'অ্যাকুরেসি', 'Accuracy')),
            ],
          ),
        );
      },
    );
  }
}
