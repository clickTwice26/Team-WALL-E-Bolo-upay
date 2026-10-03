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
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
              child: _boloCard(context),
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
      padding: EdgeInsets.fromLTRB(16, MediaQuery.of(context).padding.top + 12, 16, 22),
      decoration: const BoxDecoration(
        gradient: LinearGradient(colors: [BrandColors.navy, BrandColors.navyDark], begin: Alignment.topLeft, end: Alignment.bottomRight),
        borderRadius: BorderRadius.vertical(bottom: Radius.circular(24)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          CircleAvatar(
            radius: 24,
            backgroundColor: BrandColors.yellow,
            child: Text(name.toString().characters.first,
                style: const TextStyle(color: BrandColors.navy, fontWeight: FontWeight.w800, fontSize: 20)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(name, style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w700)),
              const SizedBox(height: 4),
              GestureDetector(
                onTap: appState.toggleBalance,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
                  decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20)),
                  child: Text(
                    appState.balanceVisible ? taka(appState.balance, bn) : tr(bn, 'ব্যালেন্স দেখতে ট্যাপ করুন', 'Tap for balance'),
                    style: const TextStyle(color: BrandColors.navy, fontWeight: FontWeight.w700),
                  ),
                ),
              ),
            ]),
          ),
          IconButton(
            tooltip: 'Settings',
            onPressed: () => _settings(context),
            icon: const Icon(Icons.tune_rounded, color: Colors.white),
          ),
        ]),
      ]),
    );
  }

  Widget _boloCard(BuildContext context) => Material(
        color: BrandColors.yellow,
        borderRadius: BorderRadius.circular(18),
        child: InkWell(
          borderRadius: BorderRadius.circular(18),
          onTap: () => _openAssistant(context),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(children: [
              Container(
                width: 56,
                height: 56,
                decoration: const BoxDecoration(color: BrandColors.navy, shape: BoxShape.circle),
                child: const Icon(Icons.mic_rounded, color: Colors.white, size: 30),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Text('বলো upay', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: BrandColors.navy)),
                  Text(tr(bn, 'মুখে বলুন, টাকা পাঠান। প্রতারণা থেকে সুরক্ষাসহ।', 'Just say it. Send money safely, with scam protection.'),
                      style: const TextStyle(color: BrandColors.navy)),
                ]),
              ),
              const Icon(Icons.arrow_forward_ios_rounded, color: BrandColors.navy, size: 18),
            ]),
          ),
        ),
      );

  Widget _services(BuildContext context) {
    final items = [
      (Icons.send_rounded, tr(bn, 'সেন্ড মানি', 'Send Money'), tr(bn, 'টাকা পাঠাও', 'send money'), true),
      (Icons.phone_iphone_rounded, tr(bn, 'মোবাইল রিচার্জ', 'Recharge'), tr(bn, 'আমার নম্বরে ৫০ টাকা রিচার্জ', 'amar number e 50 taka recharge'), true),
      (Icons.account_balance_wallet_outlined, tr(bn, 'ব্যালেন্স', 'Balance'), tr(bn, 'ব্যালেন্স কত', 'balance koto'), true),
      (Icons.payments_outlined, tr(bn, 'ক্যাশ আউট', 'Cash Out'), null, false),
      (Icons.receipt_long_outlined, tr(bn, 'পে বিল', 'Pay Bill'), null, false),
      (Icons.storefront_outlined, tr(bn, 'পেমেন্ট', 'Payment'), null, false),
    ];
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 12),
        child: GridView.count(
          crossAxisCount: 3,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          childAspectRatio: 1.15,
          children: [
            for (final it in items)
              InkWell(
                borderRadius: BorderRadius.circular(12),
                onTap: it.$4
                    ? () => it.$3 == tr(bn, 'টাকা পাঠাও', 'send money') ? _openAssistant(context) : _openAssistant(context, it.$3)
                    : () => ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                        content: Text(tr(bn, 'এই প্রোটোটাইপে শুধু সেন্ড মানি, রিচার্জ ও ব্যালেন্স', 'Prototype supports Send Money, Recharge and Balance')))),
                child: Opacity(
                  opacity: it.$4 ? 1 : 0.45,
                  child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(color: BrandColors.bg, borderRadius: BorderRadius.circular(14)),
                      child: Icon(it.$1, color: BrandColors.navy),
                    ),
                    const SizedBox(height: 6),
                    Text(it.$2, textAlign: TextAlign.center, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                  ]),
                ),
              ),
          ],
        ),
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
      Text(tr(bn, 'সাম্প্রতিক লেনদেন', 'Recent transactions'), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
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
