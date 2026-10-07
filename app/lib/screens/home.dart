import 'package:flutter/material.dart';

import '../widgets/agent_icon.dart';

import '../agent/agent.dart';
import '../api.dart';
import '../state.dart';
import '../strings.dart';
import '../theme.dart';
import 'assistant.dart';
import 'eval_mode.dart';

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
            // demo site only (DEMO_MODE lists the personas): one tap per judged scenario
            if (appState.users.isNotEmpty)
              Padding(padding: const EdgeInsets.fromLTRB(16, 16, 16, 0), child: _demoScenarios(context)),
            Padding(
              padding: const EdgeInsets.all(16),
              child: _services(context),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: _moreServices(context),
            ),
            const SizedBox(height: 16),
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
          onPressed: () => showSettingsSheet(context),
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
                decoration: const BoxDecoration(color: Colors.white, shape: BoxShape.circle),
                child: const AgentIcon(size: 48),
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

  /// The three scenarios in docs/SCENARIOS.md: reset the demo data, set the
  /// call signal, and open the assistant with the scenario's command.
  Widget _demoScenarios(BuildContext context) {
    Future<void> run(String command, {bool onCall = false}) async {
      try {
        await Api.reset();
        await appState.refresh();
      } on ApiError catch (_) {
        // reset is best effort: the scenario still runs on the current data
      }
      appState.setSimulateCall(onCall);
      if (context.mounted) _openAssistant(context, command);
    }

    Widget item(IconData icon, Color c, String title, String sub, VoidCallback onTap) => ListTile(
          dense: true,
          leading: Icon(icon, color: c),
          title: Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
          subtitle: Text(sub),
          trailing: const Icon(Icons.play_circle_outline_rounded, color: BrandColors.navy),
          onTap: onTap,
        );
    return Card(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: Text(tr(bn, 'ডেমো দৃশ্য (এক ট্যাপে)', 'Demo scenarios (one tap)'),
              style: const TextStyle(color: BrandColors.navy, fontSize: 16, fontWeight: FontWeight.w600)),
        ),
        item(Icons.support_agent_rounded, BrandColors.red, tr(bn, '১. ভুয়া উপায় কর্মী', '1. Fake upay employee'),
            tr(bn, 'ফোন কলে "উপায় অফিস" ৳৫,০০০ চাইছে', 'On a call, "upay office" asks for ৳5,000'),
            () => run('upay office theke phone kore bollo 01799998888 e 5000 taka pathate', onCall: true)),
        item(Icons.people_alt_outlined, BrandColors.navy, tr(bn, '২. ভুল প্রাপক', '2. Wrong recipient'),
            tr(bn, 'দুইজন রহিম: কাকে ৳৫০০?', 'Two contacts named Rahim: which one gets ৳500?'),
            () => run('rahim ke 500 taka pathao')),
        item(Icons.exposure_plus_1_rounded, BrandColors.amber, tr(bn, '৩. অস্বাভাবিক বড় অঙ্ক', '3. Unusually large amount'),
            tr(bn, 'সাধারণত ৳৩৬০, এবার ৳৩,৫০০: বাড়তি শূন্য?', 'Usually ৳360, now ৳3,500: an extra zero?'),
            () => run('rahim store ke 3500 taka')),
        const SizedBox(height: 4),
      ]),
    );
  }

  Widget _service(BuildContext context, IconData icon, Color bg, Color fg, String label, VoidCallback? onTap,
      {bool big = true}) {
    return InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: onTap ??
          () => ScaffoldMessenger.of(context).showSnackBar(SnackBar(
              content: Text(tr(bn, 'এই প্রোটোটাইপে সেন্ড মানি, ক্যাশ আউট, রিচার্জ, পে বিল, মেক পেমেন্ট ও ব্যালেন্স',
                  'Prototype supports Send Money, Cash Out, Recharge, Pay Bill, Make Payment and Balance')))),
      child: Opacity(
        opacity: onTap == null ? 0.9 : 1,
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
          tr(bn, 'ক্যাশ আউট', 'Cash Out'), () => say(tr(bn, 'ক্যাশ আউট করব', 'cash out korbo'))),
      _service(context, Icons.phone_iphone_rounded, const Color(0xFFD3E6FB), const Color(0xFF2F7BD8),
          tr(bn, 'মোবাইল টপআপ', 'Mobile TopUp'), () => say(tr(bn, 'আমার নম্বরে ৫০ টাকা রিচার্জ', 'amar number e 50 taka recharge'))),
      _service(context, Icons.receipt_long_rounded, const Color(0xFFC9D3EE), const Color(0xFF3B4F9A),
          tr(bn, 'পে বিল', 'Pay Bill'), () => say(tr(bn, 'বিল দেব', 'bill dibo'))),
    ];
    final second = [
      _service(context, Icons.account_balance_wallet_outlined, BrandColors.bg, const Color(0xFF6A5ACD),
          tr(bn, 'ব্যালেন্স', 'Balance'), () => say(tr(bn, 'ব্যালেন্স কত', 'balance koto')), big: false),
      _service(context, Icons.request_page_outlined, BrandColors.bg, const Color(0xFF2BA3A0),
          tr(bn, 'রিকোয়েস্ট মানি', 'Request Money'), null, big: false),
      _service(context, Icons.account_balance_outlined, BrandColors.bg, const Color(0xFF2F7BD8),
          tr(bn, 'ফান্ড ট্রান্সফার', 'Fund Transfer'), null, big: false),
      _service(context, Icons.qr_code_2_rounded, BrandColors.bg, BrandColors.text,
          tr(bn, 'মেক পেমেন্ট', 'Make Payment'), () => say(tr(bn, 'মেক পেমেন্ট করব', 'make payment korbo')),
          big: false),
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

  Widget _moreServices(BuildContext context) {
    Widget section(String title, List<(IconData, Color, String)> items) => Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 4, 12, 10),
              child: Text(title, style: const TextStyle(color: BrandColors.navy, fontSize: 16, fontWeight: FontWeight.w600)),
            ),
            GridView.count(
              crossAxisCount: 4,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              childAspectRatio: 0.95,
              children: [
                for (final it in items)
                  _service(context, it.$1, Colors.transparent, it.$2, it.$3, null, big: false),
              ],
            ),
          ],
        );
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 12),
        child: Column(children: [
          section(tr(bn, 'উপায় পেমেন্টস', 'upay Payments'), [
            (Icons.traffic_rounded, const Color(0xFF3C9A5F), tr(bn, 'ট্রাফিক ফাইন', 'Traffic Fine')),
            (Icons.flight_takeoff_rounded, const Color(0xFF6C63FF), tr(bn, 'ভিসা ফি', 'Indian Visa')),
            (Icons.confirmation_number_outlined, const Color(0xFF7B6FB0), tr(bn, 'টিকেট', 'Ticket')),
            (Icons.apartment_rounded, const Color(0xFF2BA3A0), tr(bn, 'হোটেল', 'Hotel')),
            (Icons.volunteer_activism_outlined, const Color(0xFF3C9A5F), tr(bn, 'যাকাত', 'Zakat Payment')),
            (Icons.inventory_2_outlined, const Color(0xFF2F7BD8), tr(bn, 'ডোনেশন', 'Donation')),
            (Icons.landscape_outlined, const Color(0xFFD32F2F), tr(bn, 'ভূমি মন্ত্রণালয়', 'Ministry of Land')),
            (Icons.health_and_safety_outlined, const Color(0xFF0B8F7A), tr(bn, 'ইন্স্যুরেন্স', 'Insurance')),
          ]),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(children: [
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 5),
                decoration: BoxDecoration(color: BrandColors.yellow, borderRadius: BorderRadius.circular(20)),
                child: Text(tr(bn, 'আরও দেখুন ›', 'See More ›'), style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
              ),
              Expanded(
                child: Align(
                  alignment: Alignment.centerRight,
                  child: Container(
                    margin: const EdgeInsets.only(right: 10),
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    decoration: BoxDecoration(color: const Color(0xFFFFF6CC), borderRadius: BorderRadius.circular(20)),
                    child: Row(mainAxisSize: MainAxisSize.min, children: [
                      const Icon(Icons.card_giftcard_rounded, size: 18, color: BrandColors.navy),
                      const SizedBox(width: 4),
                      Text(tr(bn, 'উপায় অফার', 'upay Offers'), style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                    ]),
                  ),
                ),
              ),
            ]),
          ),
          section(tr(bn, 'অন্যান্য সেবা', 'Other Services'), [
            (Icons.mosque_outlined, const Color(0xFF3C9A5F), tr(bn, 'ইসলামিক ফাইন্যান্স', 'Islamic Finance')),
            (Icons.sports_esports_outlined, const Color(0xFF6C63FF), tr(bn, 'গেমস', 'Games')),
            (Icons.favorite_border_rounded, const Color(0xFFD32F2F), tr(bn, 'হেলথ', 'Health')),
            (Icons.location_on_outlined, const Color(0xFFE0603A), tr(bn, 'সার্ভিস লোকেটর', 'Service Locator')),
          ]),
        ]),
      ),
    );
  }

  Widget _recent(Map<String, dynamic> p) {
    final rec = ((p['recent'] as List?) ?? []).take(6).map((e) => Map<String, dynamic>.from(e)).toList();
    String label(String t) => switch (t) {
          'send_money' => tr(bn, 'সেন্ড মানি', 'Send Money'),
          'mobile_recharge' => tr(bn, 'রিচার্জ', 'Recharge'),
          'cash_out' => tr(bn, 'ক্যাশ আউট', 'Cash Out'),
          'bill_payment' => tr(bn, 'পে বিল', 'Pay Bill'),
          'merchant_payment' => tr(bn, 'মেক পেমেন্ট', 'Make Payment'),
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
}

/// What the agent sees on Home, computed live from the app state.
Map<String, dynamic> describeHome() {
  final p = appState.profile ?? {};
  final shown = appState.balanceVisible;
  final recent = ((p['recent'] as List?) ?? []).take(3).map((e) => Map<String, dynamic>.from(e)).toList();
  String tx(Map t, bool bn) {
    final who = t['name'] ?? t['counterparty'];
    return switch (t['type']) {
      'receive' => bn ? '$who থেকে ${taka(t['amount'], true)} এসেছে' : 'received ${taka(t['amount'], false)} from $who',
      'mobile_recharge' => bn ? '$who নম্বরে ${taka(t['amount'], true)} রিচার্জ' : 'recharged ${taka(t['amount'], false)} to $who',
      'bill_payment' => bn ? '$who বিল ${taka(t['amount'], true)} দেওয়া' : 'paid a ${taka(t['amount'], false)} $who bill',
      'cash_out' => bn ? '$who এজেন্টে ${taka(t['amount'], true)} ক্যাশ আউট' : 'cashed out ${taka(t['amount'], false)} at agent $who',
      'merchant_payment' => bn ? '$who কে ${taka(t['amount'], true)} পেমেন্ট' : 'paid ${taka(t['amount'], false)} to $who',
      _ => bn ? '$who কে ${taka(t['amount'], true)} পাঠানো' : 'sent ${taka(t['amount'], false)} to $who',
    };
  }

  return {
    'id': 'home',
    'summary_bn': 'হোম পেজ। ব্যবহারকারী ${p['name_bn'] ?? ''}, ব্যালেন্স ${shown ? taka(appState.balance, true) : 'লুকানো'}। '
        'সাম্প্রতিক লেনদেন: ${recent.map((t) => tx(t, true)).join('; ')}। '
        'সেবা: সেন্ড মানি, ক্যাশ আউট, মোবাইল টপআপ, পে বিল (${appState.billers.map((b) => b['name_bn']).join(', ')}), '
        'মেক পেমেন্ট, ব্যালেন্স। সব লেনদেনে একই নিরাপত্তা যাচাই হয়।',
    'summary_en': 'Home page. User ${p['name'] ?? ''}, balance ${shown ? taka(appState.balance, false) : 'hidden'}. '
        'Recent transactions: ${recent.map((t) => tx(t, false)).join('; ')}. '
        'Services: Send Money, Cash Out, Mobile TopUp, Pay Bill (${appState.billers.map((b) => b['name']).join(', ')}), '
        'Make Payment, Balance. Every payment gets the same safety check.',
    'content': {
      'user': p['name'],
      'balance_visible': shown,
      if (shown) 'balance': appState.balance,
      'recent': [for (final t in recent) {'type': t['type'], 'amount': t['amount'], 'with': t['name'] ?? t['counterparty']}],
      'services': ['send_money', 'cash_out', 'mobile_recharge', 'bill_payment', 'merchant_payment', 'check_balance'],
    },
    'actions': <String>[],
  };
}

/// Demo settings. While open, the sheet is the agent's page "settings".
Future<void> showSettingsSheet(BuildContext context) =>
    showModalBottomSheet(context: context, showDragHandle: true, builder: (_) => const _SettingsSheet());

class _SettingsSheet extends StatefulWidget {
  const _SettingsSheet();
  @override
  State<_SettingsSheet> createState() => _SettingsSheetState();
}

class _SettingsSheetState extends State<_SettingsSheet> {
  late final AgentPage _page = AgentPage(describe: _describe);

  @override
  void initState() {
    super.initState();
    Agent.instance.push(_page);
  }

  @override
  void dispose() {
    Agent.instance.pop(_page);
    super.dispose();
  }

  Map<String, dynamic> _describe() {
    final users = appState.users;
    final me = users.firstWhere((u) => u['id'] == appState.userId, orElse: () => {});
    final others = users.where((u) => u['id'] != appState.userId);
    return {
      'id': 'settings',
      'summary_bn': 'ডেমো সেটিংস। ব্যবহারকারী: ${me['name_bn'] ?? ''}। ভাষা: ${appState.bangla ? 'বাংলা' : 'ইংরেজি'}। '
          'ফোন কল সিমুলেশন: ${appState.simulateCall ? 'চালু' : 'বন্ধ'}। অন্য ব্যবহারকারী: '
          '${others.map((u) => u['name_bn']).join(', ')}। এখান থেকে ডেমো ডেটা রিসেট করা যায়।',
      'summary_en': 'Demo settings. User: ${me['name'] ?? ''}. Language: ${appState.bangla ? 'Bangla' : 'English'}. '
          'Phone call simulation: ${appState.simulateCall ? 'on' : 'off'}. Other users: '
          '${others.map((u) => u['name']).join(', ')}. The demo data can be reset here.',
      'content': {
        'user_id': appState.userId,
        'bangla': appState.bangla,
        'simulate_call': appState.simulateCall,
        'users': [for (final u in users) {'id': u['id'], 'name': u['name']}],
      },
      'actions': <String>[],
    };
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: appState,
      builder: (ctx, _) {
        final bn = appState.bangla;
        return SafeArea(
          child: ListView(shrinkWrap: true, padding: const EdgeInsets.fromLTRB(16, 0, 16, 16), children: [
            Text(tr(bn, 'ডেমো সেটিংস', 'Demo settings'), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            Text(tr(bn, 'ডেমো ব্যবহারকারী', 'Demo user'), style: const TextStyle(color: BrandColors.muted)),
            RadioGroup<String>(
              groupValue: appState.userId,
              onChanged: (v) => appState.switchUser(v!),
              child: Column(children: [
                for (final u in appState.users)
                  RadioListTile<String>(
                    value: u['id'],
                    title: Text(bn ? u['name_bn'] : u['name']),
                    subtitle: Text(u['persona']),
                  ),
              ]),
            ),
            SwitchListTile(
              value: appState.bangla,
              onChanged: (_) => appState.toggleLanguage(),
              title: const Text('বাংলা / English'),
            ),
            if (appState.nativeCall != null)
              ListTile(
                leading: Icon(appState.nativeCall! ? Icons.phone_in_talk : Icons.phone_disabled_outlined),
                title: Text(tr(bn, 'ফোন কল শনাক্তকরণ চালু', 'Phone call detection is on')),
                subtitle: Text(appState.nativeCall!
                    ? tr(bn, 'এখন একটি কল চলছে', 'A call is active now')
                    : tr(bn, 'এখন কোনো কল নেই (শুধু হ্যাঁ/না দেখা হয়)', 'No call right now (only yes/no is read)')),
              ),
            if (appState.callToggle)
              SwitchListTile(
                value: appState.simulateCall,
                onChanged: appState.setSimulateCall,
                title: Text(tr(bn, 'ফোন কল চলছে (সিমুলেশন)', 'Simulate active phone call')),
                subtitle: Text(appState.nativeCall != null
                    ? tr(bn, 'ডেমোর জন্য: ফোনে কল না থাকলেও কল ধরা হবে', 'For demos: counts a call even when the phone has none')
                    : tr(bn, 'অ্যান্ড্রয়েড অ্যাপে ফোনের কল-স্ট্যাটাস থেকে আসে', 'In the Android app this comes from the phone call state')),
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
            // study tools (docs/AUDIO_EVAL.md), only on a demo site
            if (appState.users.isNotEmpty)
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.graphic_eq_rounded),
                title: Text(tr(bn, 'মূল্যায়ন মোড (আসল কণ্ঠ)', 'Evaluation mode (real speech)')),
                onTap: () {
                  Navigator.pop(ctx);
                  navigatorKey.currentState?.push(MaterialPageRoute(builder: (_) => const EvalScreen()));
                },
              ),
          ]),
        );
      },
    );
  }
}
