import 'package:flutter/material.dart';

import 'agent/agent.dart';
import 'api.dart';
import 'agent/agent_layer.dart';
import 'screens/assistant.dart';
import 'screens/eval_mode.dart';
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
      navigatorKey: navigatorKey,
      builder: (context, child) => _PhoneFrame(
        child: Column(children: [
          // the agent sits above every route, inside the phone frame
          Expanded(child: Stack(children: [child!, const Positioned.fill(child: AgentLayer())])),
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
  void initState() {
    super.initState();
    // the server ended the session (expired): back to the PIN screen
    Session.onExpired = () {
      if (!mounted || !unlocked) return;
      navigatorKey.currentState?.popUntil((r) => r.isFirst);
      Agent.instance.enabled = false;
      appState.signedOut();
      setState(() => unlocked = false);
    };
  }

  @override
  Widget build(BuildContext context) => unlocked
      ? (kEvalMode ? const EvalScreen() : const Shell()) // study phones: straight to evaluation mode
      : LoginScreen(onUnlocked: () {
          Agent.instance.enabled = true; // the agent only works after the PIN unlock
          setState(() => unlocked = true);
        });
}

class Shell extends StatefulWidget {
  const Shell({super.key});
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int tab = 0;
  late final AgentPage _page = AgentPage(
    describe: _describe,
    mainTab: true,
    handlers: {'refresh': (_) => tab == 0 ? appState.refresh() : Agent.instance.refreshPage(_tabIds[tab])},
  );

  static const _tabIds = ['home', 'dashboard', 'accuracy'];

  @override
  void initState() {
    super.initState();
    final agent = Agent.instance;
    agent.openTab = _openTab;
    agent.openAssistant = ({String? text, List<String> scamContext = const []}) => navigatorKey.currentState
        ?.push(MaterialPageRoute(builder: (_) => AssistantScreen(initialText: text, scamContext: scamContext)));
    agent.openSettings = () {
      final ctx = navigatorKey.currentContext;
      if (ctx != null) showSettingsSheet(ctx);
    };
    agent.push(_page);
  }

  @override
  void dispose() {
    Agent.instance.pop(_page);
    super.dispose();
  }

  void _openTab(int i) {
    if (i == tab) return;
    Agent.instance.willChange(); // remember the tab being left
    setState(() => tab = i);
    Agent.instance.touch();
  }

  Map<String, dynamic> _describe() {
    final id = _tabIds[tab];
    if (id == 'home') return describeHome();
    return Agent.instance.snapshot(id) ??
        {'id': id, 'summary_bn': 'পেজটি লোড হচ্ছে।', 'summary_en': 'The page is loading.', 'actions': <String>[]};
  }

  Widget _nav(int i, IconData icon, String label) {
    final on = tab == i;
    final c = on ? BrandColors.navy : BrandColors.muted;
    return Expanded(
      child: InkWell(
        onTap: () => _openTab(i),
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
      listenable: Listenable.merge([appState, Agent.instance]),
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
              tooltip: tr(bn, 'বলো এজেন্ট', 'Bolo agent'),
              // on the main tabs the centre mic is the agent: open it and listen
              onPressed: () => Agent.instance.openPanel(listen: true),
              child: UnreadBadge(count: Agent.instance.unread, child: const Icon(Icons.mic_rounded, size: 34)),
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
