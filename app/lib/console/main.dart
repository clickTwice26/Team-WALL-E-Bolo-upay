import 'package:flutter/material.dart';

import '../api.dart';
import 'console_api.dart';
import 'console_home.dart';

/// Support console: a desktop web tool for upay staff, served at /console.
void main() => runApp(const ConsoleApp());

const navy = Color(0xFF0B4EA8);

ThemeData consoleTheme() {
  final base = ThemeData(
    useMaterial3: true,
    fontFamily: 'HindSiliguri', // Bangla messages render
    visualDensity: VisualDensity.compact,
    colorScheme: ColorScheme.fromSeed(seedColor: navy, primary: navy, surface: Colors.white),
    scaffoldBackgroundColor: const Color(0xFFF3F4F6),
    dividerColor: const Color(0xFFE2E5EA),
  );
  return base.copyWith(
    textTheme: base.textTheme.apply(fontSizeFactor: 0.95, bodyColor: const Color(0xFF1F2937)),
    appBarTheme: const AppBarTheme(
      backgroundColor: Color(0xFF111827),
      foregroundColor: Colors.white,
      elevation: 0,
      toolbarHeight: 52,
    ),
    cardTheme: const CardThemeData(
      color: Colors.white,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
          side: BorderSide(color: Color(0xFFE2E5EA)), borderRadius: BorderRadius.all(Radius.circular(8))),
    ),
  );
}

class ConsoleApp extends StatefulWidget {
  const ConsoleApp({super.key});
  @override
  State<ConsoleApp> createState() => _ConsoleAppState();
}

class _ConsoleAppState extends State<ConsoleApp> {
  ConsoleApi? api;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Bolo upay · support console',
      debugShowCheckedModeBanner: false,
      theme: consoleTheme(),
      home: api == null
          ? _Login(onLogin: (a) => setState(() => api = a))
          : ConsoleHome(api: api!, onSignOut: () => setState(() => api = null)),
    );
  }
}

class _Login extends StatefulWidget {
  const _Login({required this.onLogin});
  final ValueChanged<ConsoleApi> onLogin;
  @override
  State<_Login> createState() => _LoginState();
}

class _LoginState extends State<_Login> {
  final _name = TextEditingController();
  final _code = TextEditingController();
  String? error;
  bool busy = false;

  Future<void> _go() async {
    if (_name.text.trim().isEmpty || _code.text.isEmpty) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final name = await ConsoleApi.login(_name.text.trim(), _code.text);
      widget.onLogin(ConsoleApi(_code.text, name));
    } on ApiError catch (e) {
      setState(() => error = e.status == 401 ? 'Wrong access code.' : 'Cannot reach the server.');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: SizedBox(
          width: 360,
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                const Row(children: [
                  Icon(Icons.support_agent_rounded, color: navy, size: 28),
                  SizedBox(width: 8),
                  Text('Support console', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
                ]),
                const SizedBox(height: 4),
                const Text('Bolo upay · prototype, synthetic customers',
                    style: TextStyle(color: Colors.black54, fontSize: 13)),
                const SizedBox(height: 20),
                TextField(
                  controller: _name,
                  decoration: const InputDecoration(labelText: 'Your name (shown to the customer)', border: OutlineInputBorder()),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _code,
                  obscureText: true,
                  onSubmitted: (_) => _go(),
                  decoration: const InputDecoration(labelText: 'Access code', border: OutlineInputBorder()),
                ),
                if (error != null) ...[
                  const SizedBox(height: 10),
                  Text(error!, style: const TextStyle(color: Colors.red)),
                ],
                const SizedBox(height: 16),
                FilledButton(onPressed: busy ? null : _go, child: const Text('Sign in')),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}
