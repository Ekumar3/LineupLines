// Display helpers for the in-season lineup page.

// Order starting slots the way a lineup is normally read. Leagues can define
// any slots, so anything not listed sorts after these, alphabetically.
const SLOT_ORDER = [
  'QB', 'RB', 'WR', 'TE', 'FLEX', 'WRRB_FLEX', 'REC_FLEX', 'SUPER_FLEX', 'K', 'DEF',
];

export const SLOT_LABELS = {
  FLEX: 'FLX',
  WRRB_FLEX: 'W/R',
  REC_FLEX: 'W/T',
  SUPER_FLEX: 'SFLX',
};

export const slotLabel = (slot) => SLOT_LABELS[slot] || slot;

export function slotRank(slot) {
  const idx = SLOT_ORDER.indexOf(slot);
  return idx === -1 ? SLOT_ORDER.length : idx;
}

// Same palette as the rest of the app (see RosterPage).
export const POSITION_COLORS = {
  QB: 'text-red-400 bg-red-400/10 border-red-400/20',
  RB: 'text-green-400 bg-green-400/10 border-green-400/20',
  WR: 'text-blue-400 bg-blue-400/10 border-blue-400/20',
  TE: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20',
  K: 'text-purple-400 bg-purple-400/10 border-purple-400/20',
  DEF: 'text-orange-400 bg-orange-400/10 border-orange-400/20',
  FLEX: 'text-pink-400 bg-pink-400/10 border-pink-400/20',
  WRRB_FLEX: 'text-pink-400 bg-pink-400/10 border-pink-400/20',
  SUPER_FLEX: 'text-cyan-400 bg-cyan-400/10 border-cyan-400/20',
  REC_FLEX: 'text-indigo-400 bg-indigo-400/10 border-indigo-400/20',
};

export const DEFAULT_SLOT_COLOR =
  'text-sleeper-gray-400 bg-sleeper-gray-800 border-sleeper-gray-700';

// "just now" / "12m ago" / "3h ago" / "2d ago". `now` is a ms timestamp so the
// caller controls re-rendering (see useNow).
export function formatAgo(iso, now = Date.now()) {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const minutes = Math.max(0, Math.floor((now - then) / 60000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export const formatPoints = (value) =>
  typeof value === 'number' ? value.toFixed(1) : '–';

// "+1.2" / "−0.4" (a real minus sign, which lines up with the plus).
export function formatSigned(value, digits = 1) {
  if (typeof value !== 'number') return '–';
  const rounded = Number(value.toFixed(digits));
  if (rounded === 0) return (0).toFixed(digits);
  return `${rounded > 0 ? '+' : '−'}${Math.abs(rounded).toFixed(digits)}`;
}

export const formatMultiplier = (value) =>
  typeof value === 'number' ? `×${value.toFixed(2)}` : '–';

export const STAT_LABELS = {
  passing_yards: 'Passing yards',
  passing_tds: 'Passing TDs',
  interceptions: 'Interceptions',
  rushing_yards: 'Rushing yards',
  rushing_tds: 'Rushing TDs',
  receptions: 'Receptions',
  receiving_yards: 'Receiving yards',
  receiving_tds: 'Receiving TDs',
  fumbles_lost: 'Fumbles lost',
};

// Yardage and catches read best to one decimal; touchdown-type stats are
// small fractions (0.31 TDs), so show two.
export const formatStatValue = (stat, value) =>
  value.toFixed(stat.endsWith('_yards') || stat === 'receptions' ? 1 : 2);

// The matchup label flips at +/-10 on the OL-minus-DL difference (see
// mart_matchup_grade.sql); the same cut-offs colour the numbers in the popover.
export const MATCHUP_THRESHOLD = 10;

export function matchupTone(diff) {
  if (typeof diff !== 'number') return 'text-sleeper-gray-300';
  if (diff > MATCHUP_THRESHOLD) return 'text-sleeper-green';
  if (diff < -MATCHUP_THRESHOLD) return 'text-sleeper-red';
  return 'text-sleeper-gray-300';
}

// Sleeper injury_status strings: Out/IR/PUP/Doubtful are red, Questionable is
// amber, anything else (Sus, NA, ...) is neutral.
export function injuryStyle(status) {
  const s = (status || '').toLowerCase();
  if (['out', 'ir', 'pup', 'doubtful'].includes(s)) {
    return 'text-sleeper-red bg-sleeper-red/10 border-sleeper-red/30';
  }
  if (s === 'questionable') {
    return 'text-yellow-400 bg-yellow-400/10 border-yellow-400/30';
  }
  return 'text-sleeper-gray-300 bg-sleeper-gray-800 border-sleeper-gray-700';
}

export const injuryLabel = (status) => {
  const s = (status || '').toLowerCase();
  if (s === 'questionable') return 'Q';
  if (s === 'doubtful') return 'D';
  return (status || '').toUpperCase();
};
