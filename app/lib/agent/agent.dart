import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../services/voice.dart';
import '../state.dart';
import '../strings.dart';

/// Root navigator: the agent opens pages and sheets from anywhere.
final navigatorKey = GlobalKey<NavigatorState>();

typedef AgentHandler = FutureOr<void> Function(Map<String, dynamic> args);

/// A page the agent can see and act on. [describe] returns
/// {id, step, summary_bn, summary_en, content, actions}; [handlers] run page
/// actions through the same methods as the page's buttons.
class AgentPage {
  AgentPage({required this.describe, this.handlers = const {}, this.mainTab = false});
  final Map<String, dynamic> Function() describe;
  final Map<String, AgentHandler> handlers;
  final bool mainTab; // the tab shell: its centre mic opens the agent
}

class AgentMsg {
  AgentMsg(this.role, this.text, {this.name, this.id});
  final String role; // user | agent | human | system
  final String text;
  final String? name;
  final int? id;
  final List<String> tags = [];
}

/// The Bolo agent: one assistant on every page. Knows the page on screen and
/// the last 3 pages, sends what the user says to /api/agent, speaks the reply
/// and runs the returned actions.
class Agent extends ChangeNotifier {
  Agent._();
  static final Agent instance = Agent._();

  bool enabled = false; // after the PIN unlock
  bool open = false;
  bool busy = false;
  bool listening = false;
  String transcript = '';
  final List<AgentMsg> messages = [];

  final List<AgentPage> _stack = [];
  final List<Map<String, dynamic>> _recent = [];
  final List<Map<String, String>> _history = [];
  final List<String> _utterances = [];
  final Map<String, Map<String, dynamic>> _snapshots = {};
  final Map<String, Future<void> Function()> _refreshers = {};

  // registered by the tab shell
  void Function(int tab)? openTab;
  void Function({String? text, List<String> scamContext})? openAssistant;
  VoidCallback? openSettings;

  AgentPage? get top => _stack.isEmpty ? null : _stack.last;
  bool get onMainTab => top?.mainTab ?? true;

  Map<String, dynamic> get current {
    try {
      return top?.describe() ?? {'id': 'home', 'actions': <String>[]};
    } catch (_) {
      return {'id': 'home', 'actions': <String>[]};
    }
  }

  /// The user's last 3 utterances: the Send Money page adds them to the scam
  /// check, so "upay office called me" counts even if only "send 5000 to 017..."
  /// was passed on as the command.
  List<String> get scamContext => List.of(_utterances);

  // ---------------- page registry ----------------
  void push(AgentPage p) {
    _capture(top);
    _stack.add(p);
    touch();
  }

  void pop(AgentPage p) {
    if (identical(top, p)) _capture(p);
    _stack.remove(p);
    touch();
  }

  /// Before a tab switch: remember the page being left.
  void willChange() => _capture(top);

  /// Page content changed (pages call this from setState).
  void touch() {
    if (_scheduled) return;
    _scheduled = true;
    // pages register while building or disposing: notify after the frame work
    scheduleMicrotask(() {
      _scheduled = false;
      notifyListeners();
    });
  }

  bool _scheduled = false;

  void publish(String id, Map<String, dynamic> snapshot) {
    _snapshots[id] = snapshot;
    touch();
  }

  Map<String, dynamic>? snapshot(String id) => _snapshots[id];

  void registerRefresh(String id, Future<void> Function() fn) => _refreshers[id] = fn;

  Future<void> refreshPage(String id) async => await _refreshers[id]?.call();

  void _capture(AgentPage? p) {
    if (p == null) return;
    try {
      final snap = p.describe();
      _recent.removeWhere((r) => r['id'] == snap['id']);
      _recent.insert(0, snap);
      if (_recent.length > 3) _recent.removeLast();
    } catch (_) {}
  }

  // ---------------- panel ----------------
  void openPanel({bool listen = false}) {
    open = true;
    unread = 0;
    touch();
    if (listen) toggleListen();
  }

  void closePanel() {
    open = false;
    if (listening) toggleListen();
    touch();
  }

  Future<void> toggleListen() async {
    if (listening) {
      await Voice.instance.stop();
      listening = false;
      touch();
      return;
    }
    await Voice.instance.silence();
    if (!await Voice.instance.init()) {
      messages.add(AgentMsg('agent', tr(appState.bangla, 'এই ডিভাইসে ভয়েস চালু নেই। লিখে বলুন।',
          'Voice input is not available here. Please type.')));
      touch();
      return;
    }
    listening = true;
    transcript = '';
    touch();
    await Voice.instance.listen(
      bangla: appState.bangla,
      onText: (text, done) {
        transcript = text;
        if (done) listening = false;
        touch();
        if (done && text.trim().isNotEmpty) send(text);
      },
    );
  }

  // ---------------- conversation ----------------
  Future<void> send(String text) async {
    text = text.trim();
    if (text.isEmpty || busy) return;
    if (listening) {
      listening = false;
      Voice.instance.stop();
    }
    transcript = '';
    if (chat != null) return _sendToHuman(text); // a person is answering now
    messages.add(AgentMsg('user', text));
    _utterances.add(text);
    if (_utterances.length > 3) _utterances.removeAt(0);
    busy = true;
    touch();
    try {
      var observation = false;
      for (var round = 0; round < 3; round++) {
        final page = current;
        final res = await Api.agent({
          'message': observation ? '' : text,
          'page': page,
          'recent_pages': _recent.where((r) => r['id'] != page['id']).take(3).toList(),
          'history': _history.length > 12 ? _history.sublist(_history.length - 12) : List.of(_history),
          'bangla': appState.bangla,
          'settings': {
            'simulate_call': appState.simulateCall,
            'balance_visible': appState.balanceVisible,
            'user_id': appState.userId,
          },
          'observation': observation,
          'use_llm': true,
        });
        if (!observation) _history.add({'role': 'user', 'text': text});
        final actions = ((res['actions'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e)).toList();
        // speak in the language the user will have after these actions
        final lang = actions.where((a) => a['type'] == 'set_language').map((a) => a['lang']).firstOrNull;
        final bn = lang == null ? appState.bangla : lang == 'bn';
        final reply = '${(bn ? res['reply_bn'] : res['reply_en']) ?? ''}';
        final msg = AgentMsg('agent', reply);
        if (reply.isNotEmpty || actions.isNotEmpty) messages.add(msg);
        if (reply.isNotEmpty) {
          _history.add({'role': 'agent', 'text': reply});
          Voice.instance.speak(reply, bangla: bn);
        }
        touch();
        for (final a in actions) {
          final label = await _run(a);
          if (label != null) msg.tags.add(label);
          touch();
        }
        if (res['done'] != false || actions.isEmpty) break;
        observation = true; // look at the page again and tell the user the result
        await _settle();
      }
    } on ApiError catch (e) {
      messages.add(AgentMsg('agent', e.status == 0
          ? tr(appState.bangla, 'সার্ভারে সংযোগ হচ্ছে না।', 'Cannot reach the server.')
          : tr(appState.bangla, 'কিছু একটা সমস্যা হয়েছে।', 'Something went wrong.')));
    } finally {
      busy = false;
      touch();
    }
  }

  // ---------------- human handoff ----------------
  /// The open chat with a person: {id, status, agent_name, queue_position, user_id}.
  Map<String, dynamic>? chat;
  int unread = 0;
  int _lastId = 0;
  final Set<int> _seenIds = {};
  Timer? _poll;

  /// Starts (or resumes) a chat with support staff, with what the bot knows.
  Future<void> connectHuman(String category, String reason) async {
    if (chat != null) return openPanel();
    final page = current;
    final res = await Api.startHandoff({
      'category': category,
      'reason': reason,
      'page': page,
      'recent_pages': _recent.where((r) => r['id'] != page['id']).take(3).toList(),
      'transcript': List.of(_history),
      'bangla': appState.bangla,
    });
    chat = {...res, 'user_id': appState.userId}..remove('messages');
    _ingest(res['messages'] as List?);
    _poll?.cancel();
    _poll = Timer.periodic(const Duration(seconds: 2), (_) => _pollChat());
    touch();
  }

  Future<void> _pollChat() async {
    final c = chat;
    if (c == null) return;
    if (c['user_id'] != appState.userId) return _dropChat(); // demo user switched
    try {
      final res = await Api.pollHandoff('${c['id']}', _lastId);
      if (chat == null) return;
      chat = {...c, ...res}..remove('messages');
      _ingest(res['messages'] as List?);
      if (res['status'] == 'closed') _endChat();
      touch();
    } on ApiError catch (_) {}
  }

  /// System notices are stored as "বাংলা / English": show the user's language.
  String _inLanguage(String t) {
    final i = t.indexOf(' / ');
    if (i < 0) return t;
    return appState.bangla ? t.substring(0, i) : t.substring(i + 3);
  }

  void _ingest(List? msgs) {
    for (final m in msgs ?? const []) {
      final id = (m['id'] as num).toInt();
      if (!_seenIds.add(id)) continue;
      if (id > _lastId) _lastId = id;
      final sender = '${m['sender']}';
      final text = sender == 'system' ? _inLanguage('${m['text']}') : '${m['text']}';
      final role = sender == 'agent' ? 'human' : sender;
      messages.add(AgentMsg(role, text, name: m['name'] as String?, id: id));
      if (sender != 'user') {
        Voice.instance.speak(text, bangla: appState.bangla);
        if (!open) unread++;
      }
    }
  }

  Future<void> _sendToHuman(String text) async {
    final c = chat!;
    busy = true;
    touch();
    try {
      await Api.handoffMessage('${c['id']}', text);
      await _pollChat(); // fetch it back: a PIN in it shows masked
    } on ApiError catch (e) {
      if (e.status == 409) _endChat();
    } finally {
      busy = false;
      touch();
    }
  }

  Future<void> endChat() async {
    final c = chat;
    if (c == null) return;
    try {
      await Api.closeHandoff('${c['id']}');
    } on ApiError catch (_) {}
    await _pollChat();
    _endChat();
  }

  void _endChat() {
    _poll?.cancel();
    _poll = null;
    if (chat == null) return;
    chat = null;
    final s = tr(appState.bangla, 'আপনি আবার বলো upay-এর সাথে আছেন।', "You're back with Bolo upay.");
    messages.add(AgentMsg('agent', s));
    Voice.instance.speak(s, bangla: appState.bangla);
    touch();
  }

  void _dropChat() {
    _poll?.cancel();
    _poll = null;
    chat = null;
    touch();
  }

  /// Wait until the page has finished loading after our actions.
  Future<void> _settle() async {
    await Future.delayed(const Duration(milliseconds: 400));
    for (var i = 0; i < 25; i++) {
      if (!const {'parsing', 'assessing', 'working'}.contains(current['step'])) return;
      await Future.delayed(const Duration(milliseconds: 300));
    }
  }

  static const _tabs = ['home', 'dashboard', 'accuracy'];
  static const _pageNames = {
    'home': ('হোম', 'Home'),
    'dashboard': ('ড্যাশবোর্ড', 'Dashboard'),
    'accuracy': ('অ্যাকুরেসি', 'Accuracy'),
    'assistant': ('সেন্ড মানি', 'Send Money'),
    'settings': ('সেটিংস', 'Settings'),
  };

  static String pageName(String? id, bool bn) {
    final n = _pageNames[id];
    return n == null ? (id ?? '') : (bn ? n.$1 : n.$2);
  }

  static const _labels = {
    'select_amount': ('পরিমাণ বেছে নেওয়া হয়েছে', 'Amount selected'),
    'select_recipient': ('প্রাপক বেছে নেওয়া হয়েছে', 'Recipient selected'),
    'clarify_continue': ('এগিয়ে গেছি', 'Continued'),
    'answer_interview': ('উত্তর পাঠানো হয়েছে', 'Answer sent'),
    'confirm': ('নিশ্চিত করা হয়েছে', 'Confirmed'),
    'accept_suggestion': ('পরামর্শ নেওয়া হয়েছে', 'Suggestion accepted'),
    'keep_amount': ('পরিমাণ ঠিক রাখা হয়েছে', 'Amount kept'),
    'continue_to_pin': ('পিনের ধাপে', 'PIN step'),
    'cancel_transfer': ('বাতিল করা হয়েছে', 'Cancelled'),
    'new_transaction': ('নতুন লেনদেন', 'New transaction'),
    'repeat': ('আবার বলা হয়েছে', 'Repeated'),
  };

  /// Runs one action; returns the ✓ label, or null if nothing happened.
  Future<String?> _run(Map<String, dynamic> a) async {
    final type = '${a['type']}';
    String l(String bn, String en) => tr(appState.bangla, bn, en);
    final nav = navigatorKey.currentState;
    switch (type) {
      case 'navigate':
        final p = '${a['page']}';
        nav?.popUntil((r) => r.isFirst);
        if (p == 'assistant') {
          openAssistant?.call();
        } else if (_tabs.contains(p)) {
          openTab?.call(_tabs.indexOf(p));
        }
        return l('${pageName(p, true)} খোলা হয়েছে', '${pageName(p, false)} opened');
      case 'go_back':
        final popped = await nav?.maybePop() ?? false;
        return popped ? l('ফিরে গেছি', 'Went back') : null;
      case 'open_settings':
        openSettings?.call();
        return l('সেটিংস খোলা হয়েছে', 'Settings opened');
      case 'refresh':
        final h = top?.handlers['refresh'];
        h != null ? await h(a) : await appState.refresh();
        return l('রিফ্রেশ হয়েছে', 'Refreshed');
      case 'set_language':
        appState.setLanguage(a['lang'] == 'bn');
        return l('ভাষা: বাংলা', 'Language: English');
      case 'show_balance':
        appState.setBalanceVisible(a['on'] == true);
        return a['on'] == true ? l('ব্যালেন্স দেখানো হয়েছে', 'Balance shown') : l('ব্যালেন্স লুকানো', 'Balance hidden');
      case 'set_simulate_call':
        appState.setSimulateCall(a['on'] == true);
        return a['on'] == true ? l('কল সিমুলেশন চালু', 'Call simulation on') : l('কল সিমুলেশন বন্ধ', 'Call simulation off');
      case 'switch_user':
        await appState.switchUser('${a['user_id']}');
        return l('ব্যবহারকারী বদলানো হয়েছে', 'User switched');
      case 'reset_demo':
        await Api.reset();
        await appState.refresh();
        return l('ডেমো রিসেট হয়েছে', 'Demo reset');
      case 'connect_human':
        await connectHuman('${a['category']}', '${a['text'] ?? ''}');
        return l('মানুষের সাথে যুক্ত করা হচ্ছে', 'Connecting you to a person');
      case 'start_transfer':
        final text = '${a['text']}';
        final submit = current['id'] == 'assistant' ? top?.handlers['submit_command'] : null;
        if (submit != null) {
          await submit({'text': text, 'scam_context': scamContext});
        } else {
          nav?.popUntil((r) => r.isFirst);
          openAssistant?.call(text: text, scamContext: scamContext);
        }
        return l('সেন্ড মানিতে দেওয়া হয়েছে', 'Sent to Send Money');
      default:
        final h = top?.handlers[type];
        if (h == null) return null;
        await h(a);
        final label = _labels[type];
        return label == null ? null : l(label.$1, label.$2);
    }
  }
}
