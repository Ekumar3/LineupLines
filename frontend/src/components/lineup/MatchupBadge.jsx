const STYLES = {
  favorable: {
    label: 'Favorable',
    className: 'text-sleeper-green bg-sleeper-green/10 border-sleeper-green/30',
  },
  unfavorable: {
    label: 'Tough',
    className: 'text-sleeper-red bg-sleeper-red/10 border-sleeper-red/30',
  },
  neutral: {
    label: 'Neutral',
    className: 'text-sleeper-gray-300 bg-sleeper-gray-800 border-sleeper-gray-700',
  },
};

// OL-vs-DL matchup label for the player's offense; the hover card (see
// PlayerBreakdown) explains it. Not shown for K/DEF: the grade is the team's
// offensive line against the opponent's defensive line, which says nothing
// about a kicker or a team defense.
export default function MatchupBadge({ grade }) {
  if (!grade) return null;

  const style = STYLES[grade.overall_signal] || STYLES.neutral;
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${style.className}`}
    >
      {style.label}
    </span>
  );
}
