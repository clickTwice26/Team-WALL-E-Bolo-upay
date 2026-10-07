import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import 'console_api.dart';

const _red = Color(0xFFDC2626);
const _amber = Color(0xFFD97706);
const _green = Color(0xFF16A34A);
const _grey = Color(0xFF6B7280);
const _navy = Color(0xFF0B4EA8);

Color _priorityColor(String? p) => switch (p) { 'urgent' => _red, 'high' => _amber, _ => _grey };
Color _levelColor(String? l) => switch (l) { 'RED' => _red, 'YELLOW' => _amber, 'GREEN' => _green, _ => _grey };

String _time(String? iso) {
  final t = iso == null ? null : DateTime.tryParse(iso)?.toLocal();
  return t == null ? '' : '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
}

String _ago(String? iso) {
  final t = iso == null ? null : DateTime.tryParse(iso);
  if (t == null) return '';
  final m = DateTime.now().difference(t).inMinutes;
  return m < 1 ? 'just now' : m < 60 ? '${m}m' : '${m ~/ 60}h ${m % 60}m';
}

String _taka(num? n) {
  final s = (n ?? 0).round().toString();
  final b = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) b.write(',');
    b.write(s[i]);
  }
  return '৳$b';
}

Widget _pill(String text, Color c) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
      decoration: BoxDecoration(color: c.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(10)),
      child: Text(text, style: TextStyle(color: c, fontSize: 11.5, fontWeight: FontWeight.w700)),
    );

/// Queue (left), chat (centre), customer and bot context (right; an end
/// drawer below 1150px). Polls the queue every 3 s and the open chat every 2 s.
class ConsoleHome extends StatefulWidget {
  const ConsoleHome({super.key, required this.api, required this.onSignOut});
  final ConsoleApi api;
  final VoidCallback onSignOut;
  @override
  State<ConsoleHome> createState() => _ConsoleHomeState();
}

class _ConsoleHomeState extends State<ConsoleHome> {
  ConsoleApi get api => widget.api;
  Map<String, dynamic> counts = {};
  List<Map<String, dynamic>> rows = [];
  String filter = 'queue';
  String? selected;
  Map<String, dynamic>? detail;
  final List<Map<String, dynamic>> msgs = [];
  int lastId = 0;
  Timer? _queueTimer, _chatTimer;
  final _composer = TextEditingController();
  final _scroll = ScrollController();
  String? error;

  @override
  void initState() {
    super.initState();
    _loadQueue();
    _queueTimer = Timer.periodic(const Duration(seconds: 3), (_) => _loadQueue());
    _chatTimer = Timer.periodic(const Duration(seconds: 2), (_) => _loadChat());
  }

  @override
  void dispose() {
    _queueTimer?.cancel();
    _chatTimer?.cancel();
    _composer.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<T?> _call<T>(Future<T> Function() f) async {
    try {
      final r = await f();
      if (error != null) setState(() => error = null);
      return r;
    } on ApiError catch (e) {
      if (e.status == 401) {
        widget.onSignOut();
      } else if (mounted) {
        setState(() => error = e.status == 0 ? 'Cannot reach the server.' : '${e.detail}');
      }
      return null;
    }
  }

  Future<void> _loadQueue() async {
    final r = await _call(api.list);
    if (r == null || !mounted) return;
    setState(() {
      counts = Map<String, dynamic>.from(r['counts']);
      rows = [for (final h in r['handoffs'] as List) Map<String, dynamic>.from(h)];
    });
  }

  Future<void> _open(String id) async {
    setState(() {
      selected = id;
      detail = null;
      msgs.clear();
      lastId = 0;
    });
    await _loadChat();
  }

  Future<void> _loadChat() async {
    final id = selected;
    if (id == null) return;
    final r = await _call(() => api.detail(id, after: lastId));
    if (r == null || !mounted || selected != id) return;
    final fresh = [for (final m in r['messages'] as List) Map<String, dynamic>.from(m)];
    setState(() {
      detail = r;
      for (final m in fresh) {
        if (m['id'] > lastId) {
          msgs.add(m);
          lastId = m['id'];
        }
      }
    });
    if (fresh.isNotEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
      });
    }
  }

  bool get _mine => detail?['agent_name'] == api.agent;
  bool get _closed => detail?['status'] == 'closed';
  bool get _otherAgent => detail?['agent_name'] != null && !_mine;
  bool get _bangla => (detail?['context']?['language'] ?? 'bn') == 'bn';

  Future<void> _take() async {
    await _call(() => api.claim(selected!));
    await _loadChat();
    await _loadQueue();
  }

  /// Staff never ask for a PIN or OTP: double-check a message that mentions one
  /// without saying "never share" / "don't share".
  bool _risky(String t) {
    final s = t.toLowerCase();
    final mentions = ['pin', 'otp', 'পিন', 'ওটিপি', 'password'].any(s.contains);
    final safe = ['never', 'don\'t', 'do not', 'কখনো', 'বলবেন না', 'দেবেন না', 'শেয়ার করবেন না'].any(s.contains);
    return mentions && !safe;
  }

  Future<void> _send([String? preset]) async {
    final text = (preset ?? _composer.text).trim();
    if (text.isEmpty || selected == null) return;
    if (_risky(text)) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('This message mentions a PIN or OTP'),
          content: const Text('upay staff never ask for a PIN or OTP. Send it anyway?'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Edit')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Send')),
          ],
        ),
      );
      if (ok != true) return;
    }
    if (preset == null) _composer.clear();
    await _call(() => api.send(selected!, text));
    await _loadChat();
    await _loadQueue();
  }

  Future<void> _close() async {
    final note = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Close chat'),
        content: SizedBox(
          width: 380,
          child: TextField(
            controller: note,
            maxLines: 3,
            decoration: const InputDecoration(labelText: 'Resolution note', border: OutlineInputBorder()),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Back')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Close chat')),
        ],
      ),
    );
    if (ok != true) return;
    await _call(() => api.close(selected!, note.text.trim()));
    await _loadChat();
    await _loadQueue();
  }

  Future<void> _stop(Map<String, dynamic> a) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Stop this transfer?'),
        content: Text('${_taka(a['amount'])} to ${a['recipient']} will be cancelled. '
            'The money stays in the customer\'s account. This cannot be undone.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Back')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: _red),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Stop transfer'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    await _call(() => api.stopTransfer(selected!, a['id']));
    await _loadChat();
  }

  // ================= UI =================
  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 1150;
    return Scaffold(
      appBar: AppBar(
        title: const Row(children: [
          Icon(Icons.support_agent_rounded),
          SizedBox(width: 8),
          Text('Bolo upay · support console', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
        ]),
        actions: [
          for (final (k, label, c) in [
            ('waiting', 'Waiting', Colors.white),
            ('urgent', 'Urgent', const Color(0xFFFCA5A5)),
            ('active', 'Active', const Color(0xFF86EFAC)),
            ('closed', 'Closed', Colors.white54),
          ])
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: Center(child: Text('$label ${counts[k] ?? 0}', style: TextStyle(color: c, fontWeight: FontWeight.w600))),
            ),
          const SizedBox(width: 12),
          Center(child: Text(api.agent, style: const TextStyle(color: Colors.white70))),
          IconButton(tooltip: 'Sign out', onPressed: widget.onSignOut, icon: const Icon(Icons.logout)),
          if (!wide && detail != null)
            Builder(
              builder: (ctx) => IconButton(
                tooltip: 'Customer context',
                onPressed: () => Scaffold.of(ctx).openEndDrawer(),
                icon: const Icon(Icons.person_search_outlined),
              ),
            ),
        ],
      ),
      endDrawer: !wide && detail != null ? Drawer(width: 400, child: SafeArea(child: _context())) : null,
      body: Column(children: [
        if (error != null)
          Container(width: double.infinity, color: const Color(0xFFFEE2E2), padding: const EdgeInsets.all(6),
              child: Text(error!, style: const TextStyle(color: _red))),
        Expanded(
          child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            SizedBox(width: 330, child: _queue()),
            const VerticalDivider(width: 1),
            Expanded(child: _chat()),
            if (wide && detail != null) ...[
              const VerticalDivider(width: 1),
              SizedBox(width: 380, child: _context()),
            ],
          ]),
        ),
      ]),
    );
  }

  // ---------- queue ----------
  Widget _queue() {
    final shown = rows.where((h) => switch (filter) {
          'mine' => h['agent_name'] == api.agent && h['status'] != 'closed',
          'closed' => h['status'] == 'closed',
          _ => h['status'] != 'closed',
        }).toList();
    return Container(
      color: Colors.white,
      child: Column(children: [
        Padding(
          padding: const EdgeInsets.all(8),
          child: SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'queue', label: Text('Queue')),
              ButtonSegment(value: 'mine', label: Text('Mine')),
              ButtonSegment(value: 'closed', label: Text('Closed')),
            ],
            selected: {filter},
            showSelectedIcon: false,
            onSelectionChanged: (s) => setState(() => filter = s.first),
          ),
        ),
        const Divider(height: 1),
        Expanded(
          child: shown.isEmpty
              ? const Center(child: Text('No chats', style: TextStyle(color: _grey)))
              : ListView.separated(
                  itemCount: shown.length,
                  separatorBuilder: (_, _) => const Divider(height: 1),
                  itemBuilder: (_, i) => _queueRow(shown[i]),
                ),
        ),
      ]),
    );
  }

  Widget _queueRow(Map<String, dynamic> h) {
    final last = h['last_message'] as Map?;
    final who = h['status'] == 'waiting' ? 'waiting #${h['queue_position'] ?? '?'}' : (h['agent_name'] ?? '');
    return Material(
      color: h['id'] == selected ? const Color(0xFFEFF4FF) : Colors.white,
      child: InkWell(
        onTap: () => _open(h['id']),
        child: Container(
          decoration: BoxDecoration(border: Border(left: BorderSide(color: _priorityColor(h['priority']), width: 4))),
          padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(
                child: Text('${h['name'] ?? h['user_id']}',
                    overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700)),
              ),
              if (h['unanswered'] == true)
                Container(width: 8, height: 8, margin: const EdgeInsets.only(right: 6),
                    decoration: const BoxDecoration(color: _navy, shape: BoxShape.circle)),
              _pill('${h['priority']}', _priorityColor(h['priority'])),
            ]),
            const SizedBox(height: 2),
            Text('${h['category'] ?? ''} · ${_ago(h['created_at'])} · $who',
                style: const TextStyle(color: _grey, fontSize: 12)),
            if (last != null)
              Text('${last['sender'] == 'agent' ? '${last['name']}: ' : ''}${last['text']}',
                  maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12.5)),
          ]),
        ),
      ),
    );
  }

  // ---------- chat ----------
  Widget _chat() {
    final d = detail;
    if (selected == null) {
      return const Center(child: Text('Pick a chat from the queue.', style: TextStyle(color: _grey)));
    }
    if (d == null) return const Center(child: CircularProgressIndicator());
    final ctx = Map<String, dynamic>.from(d['context'] ?? {});
    final readOnly = _closed || _otherAgent;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Container(
        color: Colors.white,
        padding: const EdgeInsets.fromLTRB(14, 10, 10, 10),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Text('${d['name']} ', style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                Text('${d['name_bn'] ?? ''}  ', style: const TextStyle(color: _grey)),
                _pill('${d['priority']}', _priorityColor(d['priority'])),
                const SizedBox(width: 6),
                _pill('${d['status']}', d['status'] == 'active' ? _green : _grey),
              ]),
              Text('${ctx['category'] ?? ''} · ${ctx['reason'] ?? ''}',
                  maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: _grey, fontSize: 12.5)),
            ]),
          ),
          if (!_closed && d['agent_name'] == null)
            FilledButton.icon(onPressed: _take, icon: const Icon(Icons.pan_tool_alt_outlined, size: 18), label: const Text('Take chat')),
          const SizedBox(width: 8),
          if (!_closed && !_otherAgent)
            OutlinedButton(onPressed: _close, child: const Text('Close chat')),
        ]),
      ),
      const Divider(height: 1),
      Expanded(
        child: ListView.builder(
          controller: _scroll,
          padding: const EdgeInsets.all(14),
          itemCount: msgs.length,
          itemBuilder: (_, i) => _message(msgs[i]),
        ),
      ),
      if (readOnly)
        Container(
          color: const Color(0xFFF9FAFB),
          padding: const EdgeInsets.all(12),
          child: Text(_closed ? 'This chat is closed${d['resolution'] != null ? ': ${d['resolution']}' : '.'}'
              : '${d['agent_name']} is handling this chat (read-only).', style: const TextStyle(color: _grey)),
        )
      else ...[
        _quickReplies(),
        Container(
          color: Colors.white,
          padding: const EdgeInsets.fromLTRB(10, 6, 10, 10),
          child: Row(children: [
            Expanded(
              child: TextField(
                controller: _composer,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => _send(),
                decoration: InputDecoration(
                  isDense: true,
                  hintText: _bangla ? 'বাংলায় লিখুন...' : 'Write a reply...',
                  border: const OutlineInputBorder(),
                ),
              ),
            ),
            const SizedBox(width: 8),
            FilledButton(onPressed: _send, child: const Text('Send')),
          ]),
        ),
      ],
    ]);
  }

  Widget _message(Map<String, dynamic> m) {
    final sender = m['sender'];
    if (sender == 'system') {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Text('${m['text']}  ${_time(m['ts'])}', textAlign: TextAlign.center,
            style: const TextStyle(color: _grey, fontStyle: FontStyle.italic, fontSize: 12)),
      );
    }
    final staff = sender == 'agent';
    return Align(
      alignment: staff ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 520),
        margin: const EdgeInsets.symmetric(vertical: 3),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: staff ? const Color(0xFFE0ECFF) : Colors.white,
          border: Border.all(color: const Color(0xFFE2E5EA)),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${staff ? m['name'] : 'Customer'} · ${_time(m['ts'])}',
              style: const TextStyle(color: _grey, fontSize: 11)),
          SelectableText('${m['text']}'),
        ]),
      ),
    );
  }

  Widget _quickReplies() {
    final bn = _bangla;
    final replies = bn
        ? [
            'আসসালামু আলাইকুম, আমি ${api.agent}, উপায় সাপোর্ট থেকে। কীভাবে সাহায্য করতে পারি?',
            'চিন্তা করবেন না, আপনার টাকা নিরাপদ আছে।',
            'পিন বা ওটিপি কখনো কাউকে বলবেন না, আমাদেরও না।',
            'আপনার অপেক্ষমাণ লেনদেনটি আমি বাতিল করেছি। টাকা আপনার অ্যাকাউন্টেই আছে।',
            'আর কিছু সাহায্য লাগবে?',
          ]
        : [
            'Hello, I am ${api.agent} from upay support. How can I help?',
            'Don\'t worry, your money is safe.',
            'Never share your PIN or OTP with anyone, not even us.',
            'I have cancelled your pending transfer. The money is still in your account.',
            'Is there anything else I can help with?',
          ];
    return Container(
      color: Colors.white,
      height: 40,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        children: [
          for (final r in replies)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: ActionChip(
                label: Text(r.length > 42 ? '${r.substring(0, 40)}…' : r, style: const TextStyle(fontSize: 12)),
                tooltip: r,
                onPressed: () => _send(r),
              ),
            ),
        ],
      ),
    );
  }

  // ---------- context ----------
  Widget _section(String title, List<Widget> children) => Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: const TextStyle(fontWeight: FontWeight.w700, color: _navy)),
              const SizedBox(height: 6),
              ...children,
            ]),
          ),
        ),
      );

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.only(bottom: 3),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 92, child: Text(k, style: const TextStyle(color: _grey, fontSize: 12.5))),
          Expanded(child: Text(v, style: const TextStyle(fontSize: 12.5))),
        ]),
      );

  Widget _context() {
    final d = detail;
    if (d == null) return const SizedBox.shrink();
    final ctx = Map<String, dynamic>.from(d['context'] ?? {});
    final cust = Map<String, dynamic>.from(d['customer'] ?? {});
    final prof = Map<String, dynamic>.from(cust['profile'] ?? {});
    final page = Map<String, dynamic>.from(ctx['page'] ?? {});
    final transcript = [for (final t in (ctx['transcript'] as List? ?? [])) Map<String, dynamic>.from(t)];
    final said = transcript.where((t) => t['role'] == 'user').map((t) => '"${t['text']}"').toList();
    final bn = _bangla;
    String summary(Map p) => '${(bn ? p['summary_bn'] : p['summary_en']) ?? p['summary_en'] ?? ''}';
    return ListView(padding: const EdgeInsets.all(12), children: [
      _section('Customer', [
        Text('${prof['name']} · ${prof['name_bn'] ?? ''}', style: const TextStyle(fontWeight: FontWeight.w700)),
        Text('${prof['persona'] ?? ''}', style: const TextStyle(color: _grey, fontSize: 12.5)),
        const SizedBox(height: 4),
        _kv('Phone', '${prof['phone']}'),
        _kv('Balance', _taka(prof['balance'])),
        _kv('Contacts', [for (final c in (prof['contacts'] as List? ?? [])) '${c['name']}'].join(', ')),
      ]),
      _section('Handed over by the bot', [
        _kv('Why', '${ctx['category'] ?? ''}${(ctx['reason'] ?? '').toString().isNotEmpty ? ' · ${ctx['reason']}' : ''}'),
        _kv('They said', said.isEmpty ? '-' : said.join('  ')),
        _kv('Page', '${page['id'] ?? '-'}${page['step'] != null ? ' · ${page['step']}' : ''}'),
        if (summary(page).isNotEmpty) _kv('On screen', summary(page)),
        _kv('Before', [for (final p in (ctx['recent_pages'] as List? ?? [])) '${p['id']}'].join(' ← ')),
        if (transcript.isNotEmpty) ...[
          const SizedBox(height: 4),
          const Text('Bot conversation', style: TextStyle(color: _grey, fontSize: 12)),
          for (final t in transcript)
            Text('${t['role'] == 'user' ? 'Customer' : 'Bot'}: ${t['text']}', style: const TextStyle(fontSize: 12)),
        ],
      ]),
      _section('Transfers checked by the scam shield', [
        if ((cust['assessments'] as List? ?? []).isEmpty) const Text('None', style: TextStyle(color: _grey)),
        for (final a in (cust['assessments'] as List? ?? [])) _check(Map<String, dynamic>.from(a)),
      ]),
      _section('Recent transactions', [
        for (final t in (cust['transactions'] as List? ?? []))
          Text('${_time(t['ts'])}  ${t['type']} · ${_taka(t['amount'])} · ${t['with']}', style: const TextStyle(fontSize: 12)),
      ]),
    ]);
  }

  Widget _check(Map<String, dynamic> a) {
    final bn = _bangla;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(border: Border.all(color: const Color(0xFFE2E5EA)), borderRadius: BorderRadius.circular(6)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          _pill('${a['level']}', _levelColor(a['level'])),
          const SizedBox(width: 6),
          Expanded(
            child: Text('${_taka(a['amount'])} to ${a['recipient']}${a['new_recipient'] == true ? ' (new)' : ''}',
                style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
          ),
          Text('${a['status']}', style: const TextStyle(color: _grey, fontSize: 12)),
        ]),
        if (a['on_call'] == true)
          const Text('On a phone call', style: TextStyle(color: _red, fontSize: 12, fontWeight: FontWeight.w600)),
        for (final r in (a['reasons'] as List? ?? []))
          Text('• ${bn ? r['bn'] : r['en']}', style: const TextStyle(fontSize: 12)),
        for (final ans in (a['answers'] as List? ?? []))
          Text('Answer: "$ans"', style: const TextStyle(fontSize: 12, fontStyle: FontStyle.italic)),
        if (a['can_cancel'] == true && !_closed && !_otherAgent) ...[
          const SizedBox(height: 6),
          FilledButton.icon(
            style: FilledButton.styleFrom(backgroundColor: _red, visualDensity: VisualDensity.compact),
            onPressed: () => _stop(a),
            icon: const Icon(Icons.block, size: 16),
            label: const Text('Stop this transfer'),
          ),
        ],
      ]),
    );
  }
}
