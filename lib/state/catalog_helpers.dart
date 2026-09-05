/// Plain-language readings of the engine's catalog rows, mirroring tools/devui/web/src/api.ts `describe` and Easy.tsx.
const targetText = <String, String>{
  'Single|Enemies': 'one enemy', 'Group|Enemies': 'all enemies', 'Random|Enemies': 'random enemies', 'Spread|Enemies': 'enemies in a line',
  'SingleAndGroup|Enemies': 'one enemy, then all', 'Single|Friendlies': 'one ally', 'Group|Friendlies': 'all allies', 'Self|Friendlies': 'self', 'Self|Enemies': 'self',
};

String describe(Map<String, dynamic>? row, [Map<String, dynamic> o = const {}]) {
  if (row == null) return '';
  final dmg = o['DamageType'] ?? row['dmgType'];
  final target = o['TargetType'] ?? row['target'];
  final rel = row['relation'];
  final element = o['element'] ?? row['element'];
  final hits = (o['hitCount'] ?? row['hits'] ?? 1) as num;
  final mag = (o['magnification'] ?? row['mag'] ?? 0) as num;
  final brk = (o['breakDamageValue'] ?? row['breakDmg'] ?? 0) as num;
  final who = targetText['$target|$rel'] ?? '$target $rel'.toLowerCase();
  final el = (element == null || element == 'None') ? '' : '$element ';
  String s;
  if ((dmg == 'Physic' || dmg == 'Magic') && mag > 0) {
    s = 'Deal $el${dmg == 'Physic' ? 'physical' : 'magic'} damage to $who';
    if (hits > 1) s += ' ($hits hits)';
  } else if (row['effectType'] == 'DamageAndRecovery' && rel == 'Friendlies') {
    s = 'Restore HP to $who';
  } else if (brk > 0 && mag == 0) {
    s = 'Break attack on $who (no damage)';
  } else {
    s = '${row['name'] ?? 'Effect'} on $who';
  }
  if (brk >= 9999) s += ', staggers instantly';
  else if (brk >= 40) s += ', high break power';
  return '$s.';
}

/// What a skill-effect row does, for the handful of types the shipped Resonances use.
String? effectLabel(Map<String, dynamic>? e) {
  if (e == null) return null;
  final p = ((e['params'] as List?) ?? const []).cast<num>();
  num at(int i) => i < p.length ? p[i] : 0;
  switch (e['type']) {
    case 'Deffence':
      return at(0) == 1 ? 'Protect: physical defence +${at(1)}%' : at(0) == 2 ? 'Shell: magic defence +${at(1)}%' : 'Cuts the next hit by ${at(1)}%';
    case 'CureStatusCondition':
      return at(1) == 1 ? 'Dispels buffs on the target' : 'Cures status ailments';
    case 'OverHeal':
      return 'Healing can exceed max HP';
    case 'ParameterVariation':
      final st = e['status'];
      return (st != null && st != 'None') ? 'Inflicts $st (${at(0)}% per turn, ${at(2)} turns)' : 'Changes a stat';
    case 'AccuracyVariation':
      return '${e['status'] ?? 'Accuracy'}: accuracy ${at(0)}%';
    case 'InstantDeath':
      return '${e['prob']}% chance of instant death';
    case 'Steal':
      return 'Steals an item';
    case 'CritMul':
      return 'Critical damage +${at(0)}%';
    case 'MulBaseSkillByLevel':
    case 'AppendDamage':
    case 'DmgMulSpecificSkill':
      return null;
    default:
      return e['type']?.toString();
  }
}

String iconTagFor(Map<String, dynamic> cat, String element, bool physical, bool supportive) {
  final icons = (cat['icons'] as List).cast<Map<String, dynamic>>();
  bool has(String t) => icons.any((i) => i['tag'] == t);
  if (supportive) return has('UI.Skill.Action.Icon.Support') ? 'UI.Skill.Action.Icon.Support' : 'UI.Skill.Action.Icon.Heal';
  if (element != 'None' && has('UI.Skill.Action.Icon.$element')) return 'UI.Skill.Action.Icon.$element';
  return 'UI.Skill.Action.Icon.Attack';
}

/// PNG file name of an icon tag, or null.
String? iconPng(Map<String, dynamic>? cat, String? tag) {
  if (cat == null || tag == null) return null;
  for (final i in (cat['icons'] as List).cast<Map<String, dynamic>>()) {
    if (i['tag'] == tag) return i['png'] as String?;
  }
  return null;
}

String? ownerOf(Map<String, dynamic> cat, num finishBlow) {
  for (final v in (cat['visions'] as List).cast<Map<String, dynamic>>()) {
    if (v['finishBlow'] == finishBlow) return v['name'] as String?;
  }
  return null;
}

const statParams = <(int, String, int)>[(1, 'HP', 50), (2, 'MP', 10), (5, 'Attack', 5), (6, 'Defence', 5), (7, 'Intelligence', 5), (8, 'Mind', 5), (9, 'Agility', 3)];
const statFields = <(String, String, int, int)>[('MaxHitPoint', 'HP', 200, 3000), ('MaxMagicPoint', 'MP', 30, 400), ('Attack', 'Attack', 5, 120), ('Defence', 'Defence', 5, 120), ('Intelligence', 'Intelligence', 5, 120), ('Mind', 'Mind', 5, 120), ('Agility', 'Agility', 5, 120)];
const elements = ['None', 'Fire', 'Ice', 'Wind', 'Earth', 'Thunder', 'Water', 'Light', 'Dark'];
const roles = <(String, String)>[('eUnitRole::Attacker', 'Attacker'), ('eUnitRole::Breaker', 'Breaker'), ('eUnitRole::Defender', 'Defender'), ('eUnitRole::Healer', 'Healer'), ('eUnitRole::Enhancer', 'Enhancer'), ('eUnitRole::Jammer', 'Jammer')];
const tierCap = 8;

/// Brave Exvius rarity: 1..7 are stars, then NV and NV+ (and EX) as written.
String rarityLabel(dynamic r) {
  if (r == null) return '-';
  final s = r.toString();
  return int.tryParse(s) != null ? '$s★' : s;
}

String rarityRange(dynamic lo, dynamic hi) => lo == null && hi == null ? '' : (lo == hi || hi == null ? rarityLabel(lo) : '${rarityLabel(lo)} → ${rarityLabel(hi)}');

const _animOrder = ['idle', 'standby', 'move', 'jump', 'atk', 'magicatk', 'magic_atk', 'limitatk', 'limit_atk', 'limitmove', 'limit_move', 'magic_standby', 'win', 'winbefore', 'win_before', 'dying', 'dead'];
List<String> orderAnims(List<String> a) => [..._animOrder.where(a.contains), ...(a.where((x) => !_animOrder.contains(x)).toList()..sort())];
