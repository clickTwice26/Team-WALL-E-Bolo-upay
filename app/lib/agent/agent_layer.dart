import 'package:flutter/material.dart';

import '../widgets/agent_icon.dart';

import '../state.dart';
import '../strings.dart';
import '../theme.dart';
import 'agent.dart';

/// The agent on top of every route: a floating orb (on pushed pages and
/// sheets) and a non-blocking bottom panel. Taps outside them reach the page.
class AgentLayer extends StatelessWidget {
  const AgentLayer({super.key});

  @override
  Widget build(BuildContext context) {
    // its own Overlay, so the panel's text field works above the Navigator
    return Overlay(initialEntries: [OverlayEntry(builder: (_) => const _LayerBody())]);
  }
}

class _LayerBody extends StatelessWidget {
  const _LayerBody();

  @override
  Widget build(BuildContext context) {
    final agent = Agent.instance;
    return ListenableBuilder(
      listenable: Listenable.merge([agent, appState]),
      builder: (context, _) {
        if (!agent.enabled) return const SizedBox.shrink();
        return Stack(children: [
          if (!agent.open && !agent.onMainTab)
            Positioned(
                right: 14,
                bottom: 18,
                child: UnreadBadge(count: agent.unread, child: AgentOrb(onTap: () => agent.openPanel()))),
          if (agent.open) const Positioned(left: 0, right: 0, bottom: 0, child: _Panel()),
        ]);
      },
    );
  }
}

class AgentOrb extends StatelessWidget {
  const AgentOrb({super.key, required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white,
      shape: const CircleBorder(side: BorderSide(color: BrandColors.yellow, width: 3)),
      elevation: 6,
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: onTap,
        child: const SizedBox(
          width: 58,
          height: 58,
          child: Center(child: AgentIcon(size: 46)),
        ),
      ),
    );
  }
}

/// Red count of unread messages from a person, on the orb and the centre mic.
class UnreadBadge extends StatelessWidget {
  const UnreadBadge({super.key, required this.count, required this.child});
  final int count;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    if (count == 0) return child;
    return Stack(clipBehavior: Clip.none, children: [
      child,
      Positioned(
        right: -2,
        top: -2,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
          decoration: BoxDecoration(color: BrandColors.red, borderRadius: BorderRadius.circular(10),
              border: Border.all(color: Colors.white, width: 2)),
          child: Text('$count', style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700)),
        ),
      ),
    ]);
  }
}

class _Panel extends StatefulWidget {
  const _Panel();
  @override
  State<_Panel> createState() => _PanelState();
}

class _PanelState extends State<_Panel> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  int _seen = 0;

  Agent get agent => Agent.instance;
  bool get bn => appState.bangla;

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _send([String? text]) {
    final t = (text ?? _input.text).trim();
    if (t.isEmpty) return;
    _input.clear();
    agent.send(t);
  }

  void _autoScroll() {
    if (agent.messages.length == _seen) return;
    _seen = agent.messages.length;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
      }
    });
  }

  /// Ideas for what to say on this page and step. Never "confirm" on a RED
  /// review, and nothing during the scam interview: answers must be the
  /// user's own words.
  List<String> _suggestions(Map<String, dynamic> page) {
    if (agent.chat != null) return const []; // a person is answering
    final human = tr(bn, 'মানুষের সাথে কথা বলতে চাই', 'Talk to a person');
    final ideas = _ideas(page);
    return page['step'] == 'interview' ? ideas : [...ideas, human];
  }

  List<String> _ideas(Map<String, dynamic> page) {
    final step = page['step'];
    final c = Map<String, dynamic>.from(page['content'] ?? {});
    List<String> s(List<String> b, List<String> e) => bn ? b : e;
    switch (page['id']) {
      case 'assistant':
        switch (step) {
          case 'interview':
            return const [];
          case 'clarify':
            return s(['প্রথমটা', '৫০০ টাকা', 'বাতিল করো'], ['The first one', '500 taka', 'Cancel']);
          case 'review':
            if (c['mistake'] != null) {
              return s(['হ্যাঁ, ঠিক করে দাও', 'না, আগেরটাই থাক'], ['Yes, fix it', 'No, keep it']);
            }
            if (c['level'] == 'RED') return s(['বাতিল করো', 'কেন ঝুঁকি?'], ['Cancel', 'Why is it risky?']);
            return s(['হ্যাঁ, পাঠাও', 'বাতিল করো'], ['Yes, send it', 'Cancel']);
          case 'hold':
          case 'auth':
            return s(['বাতিল করো'], ['Cancel']);
          case 'done':
            return s(['নতুন লেনদেন', 'আবার পাঠাও', 'হোমে যাও'], ['New transaction', 'Send it again', 'Go home']);
          default:
            return s(['আম্মুকে ৫০০ টাকা পাঠাও', 'ব্যালেন্স দেখাও'], ['Send 500 taka to Ammu', 'Show my balance']);
        }
      case 'settings':
        return s(['ইংরেজিতে বলো', 'ফোন কল সিমুলেশন চালু করো', 'করিম মিয়া হিসেবে লগইন করো'],
            ['Speak Bangla', 'Turn on call simulation', 'Switch to Karim Mia']);
      case 'dashboard':
      case 'accuracy':
        return s(['এই পেজে কী আছে?', 'রিফ্রেশ করো', 'হোমে যাও'], ["What's on this page?", 'Refresh', 'Go home']);
      default:
        return s(['ব্যালেন্স দেখাও', 'আম্মুকে ৫০০ টাকা পাঠাও', 'ড্যাশবোর্ড খোলো', 'এই পেজে কী আছে?'],
            ['Show my balance', 'Send 500 taka to Ammu', 'Open the dashboard', "What's on this page?"]);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      // listen to the agent itself: a const parent is never rebuilt
      listenable: Listenable.merge([agent, appState]),
      builder: (context, _) {
        _autoScroll();
        final page = agent.current;
        final h = MediaQuery.sizeOf(context).height;
        return Padding(
          padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
          child: Material(
            color: Colors.white,
            elevation: 16,
            shadowColor: Colors.black45,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
            child: ConstrainedBox(
              constraints: BoxConstraints(maxHeight: h * 0.55),
              child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                agent.chat != null ? _chatHeader() : _header(page),
                if (agent.chat != null) _pinBanner(),
                if (agent.busy) const LinearProgressIndicator(minHeight: 2),
                Flexible(child: _messages()),
                if (agent.listening || agent.transcript.isNotEmpty) _transcript(),
                _chips(_suggestions(page)),
                _composer(),
              ]),
            ),
          ),
        );
      },
    );
  }

  Widget _header(Map<String, dynamic> page) => Container(
        padding: const EdgeInsets.fromLTRB(14, 10, 4, 8),
        decoration: const BoxDecoration(
          color: BrandColors.navy,
          borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        ),
        child: Row(children: [
          Container(
            padding: const EdgeInsets.all(2),
            decoration: const BoxDecoration(color: Colors.white, shape: BoxShape.circle),
            child: const AgentIcon(size: 28),
          ),
          const SizedBox(width: 8),
          Text(tr(bn, 'বলো এজেন্ট', 'Bolo agent'),
              style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 16)),
          const SizedBox(width: 8),
          Flexible(
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(color: Colors.white24, borderRadius: BorderRadius.circular(12)),
              child: Text('${tr(bn, 'এখন', 'On')}: ${Agent.pageName(page['id'], bn)}',
                  overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontSize: 12)),
            ),
          ),
          const Spacer(),
          IconButton(
            tooltip: tr(bn, 'বন্ধ করুন', 'Close'),
            onPressed: agent.closePanel,
            icon: const Icon(Icons.keyboard_arrow_down_rounded, color: Colors.white),
          ),
        ]),
      );

  Widget _chatHeader() {
    final c = agent.chat!;
    final name = c['agent_name'];
    final status = name == null
        ? tr(bn, 'অপেক্ষা করছেন · লাইনে #${bnDigits('${c['queue_position'] ?? 1}')}', 'Waiting · #${c['queue_position'] ?? 1} in line')
        : '$name · ${tr(bn, 'অনলাইন', 'online')}';
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 8, 4, 8),
      decoration: const BoxDecoration(
        color: BrandColors.green,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      child: Row(children: [
        const Icon(Icons.support_agent_rounded, color: Colors.white),
        const SizedBox(width: 8),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(tr(bn, 'উপায় সাপোর্ট', 'upay support'),
                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 15)),
            Text(status, style: const TextStyle(color: Colors.white, fontSize: 12)),
          ]),
        ),
        TextButton(
          onPressed: agent.endChat,
          child: Text(tr(bn, 'চ্যাট শেষ', 'End chat'), style: const TextStyle(color: Colors.white)),
        ),
        IconButton(
          onPressed: agent.closePanel,
          icon: const Icon(Icons.keyboard_arrow_down_rounded, color: Colors.white),
        ),
      ]),
    );
  }

  Widget _pinBanner() => Container(
        color: BrandColors.redBg,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        child: Row(children: [
          const Icon(Icons.lock_outline, size: 16, color: BrandColors.red),
          const SizedBox(width: 6),
          Expanded(
            child: Text(tr(bn, 'উপায় কখনো আপনার পিন, ওটিপি বা টাকা চাইবে না।', 'upay will never ask for your PIN, OTP or money.'),
                style: const TextStyle(color: BrandColors.red, fontSize: 12.5, fontWeight: FontWeight.w600)),
          ),
        ]),
      );

  Widget _messages() {
    final msgs = agent.messages;
    if (msgs.isEmpty) {
      return Padding(
        padding: const EdgeInsets.all(14),
        child: Text(
            tr(bn, 'যেকোনো পেজে বলুন বা লিখুন: আমি পেজ খুলতে, টাকা পাঠানো শুরু করতে আর এই পেজে কী আছে বলতে পারি।',
                'Say or type anything on any page: I can open pages, start a transfer and tell you what is on this page.'),
            style: const TextStyle(color: BrandColors.muted)),
      );
    }
    return ListView.builder(
      controller: _scroll,
      shrinkWrap: true,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
      itemCount: msgs.length,
      itemBuilder: (_, i) => _bubble(msgs[i]),
    );
  }

  Widget _bubble(AgentMsg m) {
    if (m.role == 'system') {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 16),
        child: Text(m.text, textAlign: TextAlign.center,
            style: const TextStyle(color: BrandColors.muted, fontStyle: FontStyle.italic, fontSize: 12.5)),
      );
    }
    if (m.role == 'human') {
      return Align(
        alignment: Alignment.centerLeft,
        child: Container(
          constraints: const BoxConstraints(maxWidth: 320),
          margin: const EdgeInsets.only(bottom: 6),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: BrandColors.greenBg,
            border: Border.all(color: BrandColors.green, width: 1.5),
            borderRadius: BorderRadius.circular(14),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Text(m.name ?? tr(bn, 'এজেন্ট', 'Agent'),
                style: const TextStyle(color: BrandColors.green, fontWeight: FontWeight.w700, fontSize: 12)),
            Text(m.text, style: const TextStyle(fontSize: 14.5)),
          ]),
        ),
      );
    }
    final mine = m.role == 'user';
    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 320),
        margin: const EdgeInsets.only(bottom: 6),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: mine ? BrandColors.navy : const Color(0xFFF1F4FA),
          borderRadius: BorderRadius.circular(14),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          if (m.text.isNotEmpty)
            Text(m.text, style: TextStyle(color: mine ? Colors.white : BrandColors.text, fontSize: 14.5)),
          if (m.tags.isNotEmpty)
            Padding(
              padding: EdgeInsets.only(top: m.text.isEmpty ? 0 : 6),
              child: Wrap(spacing: 6, runSpacing: 4, children: [
                for (final t in m.tags)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(color: BrandColors.greenBg, borderRadius: BorderRadius.circular(10)),
                    // an icon, not "✓": the bundled Bangla font has no check mark glyph
                    child: Row(mainAxisSize: MainAxisSize.min, children: [
                      const Icon(Icons.check_rounded, size: 13, color: BrandColors.green),
                      const SizedBox(width: 3),
                      Text(t, style: const TextStyle(color: BrandColors.green, fontSize: 12, fontWeight: FontWeight.w600)),
                    ]),
                  ),
              ]),
            ),
        ]),
      ),
    );
  }

  Widget _transcript() => Padding(
        padding: const EdgeInsets.fromLTRB(14, 0, 14, 6),
        child: Row(children: [
          Icon(Icons.mic, size: 16, color: agent.listening ? BrandColors.red : BrandColors.muted),
          const SizedBox(width: 6),
          Expanded(
            child: Text(agent.transcript.isEmpty ? tr(bn, 'শুনছি...', 'Listening...') : agent.transcript,
                style: const TextStyle(fontStyle: FontStyle.italic, color: BrandColors.muted)),
          ),
        ]),
      );

  Widget _chips(List<String> items) {
    if (items.isEmpty) return const SizedBox(height: 4);
    return SizedBox(
      height: 40,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 10),
        children: [
          for (final s in items)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: ActionChip(
                label: Text(s, style: const TextStyle(fontSize: 13)),
                backgroundColor: const Color(0xFFFFF6CC),
                side: BorderSide.none,
                onPressed: agent.busy ? null : () => _send(s),
              ),
            ),
        ],
      ),
    );
  }

  Widget _composer() => SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(10, 4, 10, 10),
          child: Row(children: [
            Expanded(
              child: TextField(
                controller: _input,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => _send(),
                decoration: InputDecoration(
                  isDense: true,
                  filled: true,
                  fillColor: BrandColors.bg,
                  hintText: tr(bn, 'বলুন বা লিখুন...', 'Say or type...'),
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(24), borderSide: BorderSide.none),
                  suffixIcon: IconButton(icon: const Icon(Icons.send_rounded), onPressed: _send),
                ),
              ),
            ),
            const SizedBox(width: 8),
            Material(
              color: agent.listening ? BrandColors.red : BrandColors.navy,
              shape: const CircleBorder(),
              child: InkWell(
                customBorder: const CircleBorder(),
                onTap: agent.toggleListen,
                child: SizedBox(
                  width: 46,
                  height: 46,
                  child: Icon(agent.listening ? Icons.stop_rounded : Icons.mic_rounded, color: Colors.white),
                ),
              ),
            ),
          ]),
        ),
      );
}
