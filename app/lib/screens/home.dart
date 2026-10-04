import 'package:flutter/material.dart';

import '../api.dart';
import '../state.dart';
import '../strings.dart';
import '../theme.dart';
import 'assistant.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  bool get bn => appState.bangla;

  void _openAssistant(BuildContext context, [String? text]) {
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => AssistantScreen(initialText: text)));
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: appState,
      builder: (context, _) {
        final p = appState.profile;
        if (appState.error != null && p == null) return _offline(context);
        if (p == null) return const Center(child: CircularProgressIndicator());
        return RefreshIndicator(
          onRefresh: appState.refresh,
          child: ListView(padding: EdgeInsets.zero, children: [
            _header(context, p),
            Container(
              color: BrandColors.yellow,
              child: Container(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 0),
                decoration: const BoxDecoration(
                  gradient: LinearGradient(
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                      colors: [BrandColors.yellow, BrandColors.yellow, BrandColors.bg, BrandColors.bg],
                      stops: [0, .5, .5, 1]),
                ),
                child: _boloCard(context),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(16),
              child: _services(context),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: _recent(p),
            ),
            const SizedBox(height: 100),
          ]),
        );
      },
    );
  }

  Widget _offline(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.cloud_off, size: 56, color: BrandColors.muted),
            const SizedBox(height: 12),
            Text(tr(bn, 'সার্ভারে সংযোগ হচ্ছে না', 'Cannot reach the server'),
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(height: 12),
            FilledButton(onPressed: appState.load, child: Text(tr(bn, 'আবার চেষ্টা করুন', 'Retry'))),
          ]),
        ),
      );

  Widget _header(BuildContext context, Map<String, dynamic> p) {
    final name = bn ? p['name_bn'] : p['name'];
    return Container(
      color: BrandColors.yellow,
      padding: EdgeInsets.fromLTRB(16, MediaQuery.of(context).padding.top + 14, 16, 18),
      child: Row(children: [
        CircleAvatar(
          radius: 26,
          backgroundColor: Colors.white,
          child: Text(name.toString().characters.first,
              style: const TextStyle(color: BrandColors.navy, fontWeight: FontWeight.w800, fontSize: 22)),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(name, style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w700, color: BrandColors.text)),
            Text(bn ? bnDigits(p['phone']) : p['phone'], style: const TextStyle(color: BrandColors.muted, fontSize: 13)),
          ]),
        ),
        GestureDetector(
          onTap: appState.toggleBalance,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            decoration: BoxDecoration(color: BrandColors.navy, borderRadius: BorderRadius.circular(22)),
            child: Text(
              appState.balanceVisible ? taka(appState.balance, bn) : tr(bn, 'ব্যালেন্স', 'Balance'),
              style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 15),
            ),
          ),
        ),
        IconButton(
          tooltip: 'Settings',
          onPressed: () => _settings(context),
          icon: const Icon(Icons.tune_rounded, color: BrandColors.navy),
        ),
      ]),
    );
  }

  Widget _boloCard(BuildContext context) => Material(
        color: Colors.white,
        elevation: 2,
        shadowColor: Colors.black12,
        borderRadius: BorderRadius.circular(16),
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: () => _openAssistant(context),
          child: Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(16),
              gradient: const LinearGradient(colors: [Color(0xFFE8F0FC), Colors.white]),
            ),
            child: Row(children: [
              Container(
                width: 52,
                height: 52,
                decoration: const BoxDecoration(color: BrandColors.navy, shape: BoxShape.circle),
                child: const Icon(Icons.mic_rounded, color: Colors.white, size: 28),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Text('বলো upay', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: BrandColors.text)),
                  Text(tr(bn, 'মুখে বলুন, নিরাপদে টাকা পাঠান', 'Just say it. Send money safely.'),
                      style: const TextStyle(color: BrandColors.muted, fontSize: 13)),
                ]),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
                decoration: BoxDecoration(color: BrandColors.yellow, borderRadius: BorderRadius.circular(20)),
                child: Text(tr(bn, 'বলুন', 'Speak'),
                    style: const TextStyle(fontWeight: FontWeight.w700, color: BrandColors.text, fontSize: 13)),
              ),
            ]),
          ),
        ),
      );

  Widget _service(BuildContext context, IconData icon, Color bg, Color fg, String label, VoidCallback? onTap,
      {bool big = true}) {
    return InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: onTap ??
          () => ScaffoldMessenger.of(context).showSnackBar(SnackBar(
              content: Text(tr(bn, 'এই প্রোটোটাইপে শুধু সেন্ড মানি, রিচার্জ ও ব্যালেন্স',
                  'Prototype supports Send Money, Recharge and Balance')))),
      child: Opacity(
        opacity: onTap == null ? 0.55 : 1,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Container(
            width: big ? 62 : 48,
            height: big ? 62 : 48,
            decoration: BoxDecoration(color: bg, shape: big ? BoxShape.circle : BoxShape.rectangle,
                borderRadius: big ? null : BorderRadius.circular(12)),
            child: Icon(icon, color: fg, size: big ? 30 : 26),
          ),
          const SizedBox(height: 6),
          Text(label, textAlign: TextAlign.center, maxLines: 2,
              style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: BrandColors.text)),
        ]),
      ),
    );
  }

  Widget _services(BuildContext context) {
    void say(String t) => _openAssistant(context, t);
    final main = [
      _service(context, Icons.send_rounded, const Color(0xFFBDEBFA), const Color(0xFF0B79B8),
          tr(bn, 'সেন্ড মানি', 'Send Money'), () => _openAssistant(context)),
      _service(context, Icons.payments_rounded, const Color(0xFFFFD9CC), const Color(0xFFE0603A),
          tr(bn, 'ক্যাশ আউট', 'Cash Out'), null),
      _service(context, Icons.phone_iphone_rounded, const Color(0xFFD3E6FB), const Color(0xFF2F7BD8),
          tr(bn, 'মোবাইল টপআপ', 'Mobile TopUp'), () => say(tr(bn, 'আমার নম্বরে ৫০ টাকা রিচার্জ', 'amar number e 50 taka recharge'))),
      _service(context, Icons.receipt_long_rounded, const Color(0xFFC9D3EE), const Color(0xFF3B4F9A),
          tr(bn, 'পে বিল', 'Pay Bill'), null),
    ];
    final second = [
      _service(context, Icons.account_balance_wallet_outlined, BrandColors.bg, const Color(0xFF6A5ACD),
          tr(bn, 'ব্যালেন্স', 'Balance'), () => say(tr(bn, 'ব্যালেন্স কত', 'balance koto')), big: false),
      _service(context, Icons.request_page_outlined, BrandColors.bg, const Color(0xFF2BA3A0),
          tr(bn, 'রিকোয়েস্ট মানি', 'Request Money'), null, big: false),
      _service(context, Icons.account_balance_outlined, BrandColors.bg, const Color(0xFF2F7BD8),
          tr(bn, 'ফান্ড ট্রান্সফার', 'Fund Transfer'), null, big: false),
      _service(context, Icons.qr_code_2_rounded, BrandColors.bg, BrandColors.text,
          tr(bn, 'মেক পেমেন্ট', 'Make Payment'), null, big: false),
    ];
    Widget row(List<Widget> items) => Row(children: [for (final i in items) Expanded(child: i)]);
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 6),
        child: Column(children: [
          row(main),
          const Padding(padding: EdgeInsets.symmetric(vertical: 12, horizontal: 12), child: Divider(height: 1)),
          row(second),
        ]),
      ),
    );
  }

  Widget _recent(Map<String, dynamic> p) {
    final rec = ((p['recent'] as List?) ?? []).take(6).map((e) => Map<String, dynamic>.from(e)).toList();
    String label(String t) => switch (t) {
          'send_money' => tr(bn, 'সেন্ড মানি', 'Send Money'),
          'mobile_recharge' => tr(bn, 'রিচার্জ', 'Recharge'),
          'receive' => tr(bn, 'টাকা এসেছে', 'Received'),
          _ => t,
        };
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(tr(bn, 'সাম্প্রতিক লেনদেন', 'Recent transactions'),
          style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16, color: BrandColors.navy)),
      const SizedBox(height: 8),
      Card(
        child: Column(children: [
          for (final t in rec)
            ListTile(
              dense: true,
              leading: Icon(t['type'] == 'receive' ? Icons.call_received_rounded : Icons.call_made_rounded,
                  color: t['type'] == 'receive' ? BrandColors.green : BrandColors.navy),
              title: Text('${label(t['type'])}${t['name'] != null ? ' · ${t['name']}' : ''}'),
              subtitle: Text(bn ? bnDigits(t['counterparty'] ?? '') : (t['counterparty'] ?? '')),
              trailing: Text('${t['type'] == 'receive' ? '+' : '-'}${taka(t['amount'], bn)}',
                  style: TextStyle(fontWeight: FontWeight.w700, color: t['type'] == 'receive' ? BrandColors.green : BrandColors.text)),
            ),
        ]),
      ),
    ]);
  }

  void _settings(BuildContext context) {
    showModalBottomSheet(
      context: context,
      showDragHandle: true,
      builder: (ctx) => ListenableBuilder(
        listenable: appState,
        builder: (ctx, _) => SafeArea(
          child: ListView(shrinkWrap: true, padding: const EdgeInsets.fromLTRB(16, 0, 16, 16), children: [
            Text(tr(bn, 'ডেমো সেটিংস', 'Demo settings'), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            Text(tr(bn, 'ডেমো ব্যবহারকারী', 'Demo user'), style: const TextStyle(color: BrandColors.muted)),
            for (final u in appState.users)
              RadioListTile<String>(
                value: u['id'],
                groupValue: appState.userId,
                onChanged: (v) => appState.switchUser(v!),
                title: Text(bn ? u['name_bn'] : u['name']),
                subtitle: Text(u['persona']),
              ),
            SwitchListTile(
              value: appState.bangla,
              onChanged: (_) => appState.toggleLanguage(),
              title: const Text('বাংলা / English'),
            ),
            SwitchListTile(
              value: appState.simulateCall,
              onChanged: appState.setSimulateCall,
              title: Text(tr(bn, 'ফোন কল চলছে (সিমুলেশন)', 'Simulate active phone call')),
              subtitle: Text(tr(bn, 'আসল অ্যাপে ফোনের কল-স্ট্যাটাস থেকে আসবে', 'In the native app this comes from the phone call state')),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: () async {
                await Api.reset();
                await appState.refresh();
                if (ctx.mounted) Navigator.pop(ctx);
              },
              icon: const Icon(Icons.restart_alt),
              label: Text(tr(bn, 'ডেমো ডেটা রিসেট', 'Reset demo data')),
            ),
          ]),
        ),
      ),
    );
  }
}
