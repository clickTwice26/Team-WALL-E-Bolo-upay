import 'package:flutter/material.dart';

/// The upay agent mascot, used wherever the Bolo agent is opened.
class AgentIcon extends StatelessWidget {
  const AgentIcon({super.key, this.size = 32});
  final double size;

  @override
  Widget build(BuildContext context) =>
      Image.asset('assets/images/upay_agent.png', width: size, height: size, filterQuality: FilterQuality.medium);
}
