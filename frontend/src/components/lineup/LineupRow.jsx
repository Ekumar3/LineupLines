import PlayerHeadshot from '../common/PlayerHeadshot';
import HoverCard from '../common/HoverCard';
import MatchupBadge from './MatchupBadge';
import PlayerBreakdown from './PlayerBreakdown';
import {
  DEFAULT_SLOT_COLOR,
  POSITION_COLORS,
  formatPoints,
  injuryLabel,
  injuryStyle,
  slotLabel,
} from '../../utils/lineupFormat';

// Positions where the OL-vs-DL matchup grade is meaningful.
const SHOW_MATCHUP = new Set(['QB', 'RB', 'WR', 'TE']);

const REASON_BADGES = {
  'SIT (BYE)': { text: 'Bye week', className: 'text-sleeper-gray-300 bg-sleeper-gray-800 border-sleeper-gray-700' },
  'SIT (INJURY)': { text: 'Injured', className: 'text-sleeper-red bg-sleeper-red/10 border-sleeper-red/30' },
};

export default function LineupRow({ rec, scoringLabel }) {
  const isStarter = rec.recommendation === 'START';
  const reason = REASON_BADGES[rec.recommendation];
  const opponent = rec.matchup_grade?.opponent;
  const slotColor = POSITION_COLORS[rec.slot] || DEFAULT_SLOT_COLOR;
  const showMatchup = SHOW_MATCHUP.has(rec.position) && !rec.on_bye && !!rec.matchup_grade;
  // Hovering the matchup chip or the points explains both, so they share a card.
  // K/DEF and bye weeks have neither a matchup nor a projection breakdown.
  const hasExplanation = showMatchup || !!rec.projection_detail;
  const renderBreakdown = () => (
    <PlayerBreakdown rec={rec} showMatchup={showMatchup} scoringLabel={scoringLabel} />
  );
  // Matchup and projection sit side by side when both are shown (see PlayerBreakdown).
  const cardWidth = showMatchup && rec.projection_detail ? 700 : 360;

  const points = (
    <span
      className={`w-12 text-right font-semibold tabular-nums ${
        rec.on_bye ? 'text-sleeper-gray-500' : 'text-white'
      } ${hasExplanation ? 'underline decoration-dotted decoration-sleeper-gray-600 underline-offset-4' : ''}`}
    >
      {formatPoints(rec.projected_points)}
    </span>
  );

  // Second line: position, team, and who they play (or why there's no game).
  let game = null;
  if (rec.on_bye) game = 'Bye';
  else if (opponent) game = `vs ${opponent}`;

  return (
    <div className="flex items-center gap-2 sm:gap-3 px-3 sm:px-5 py-3 hover:bg-sleeper-gray-900/50 transition-colors">
      {isStarter && (
        <span
          className={`w-11 sm:w-12 flex-shrink-0 text-center px-1 sm:px-1.5 py-1 rounded text-xs font-bold border ${slotColor}`}
        >
          {slotLabel(rec.slot)}
        </span>
      )}

      <PlayerHeadshot
        playerId={rec.player_id}
        playerName={rec.player_name}
        position={rec.position}
      />

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-white font-medium truncate">{rec.player_name}</span>
          {rec.injury_status && (
            <span
              title={rec.injury_status}
              className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${injuryStyle(rec.injury_status)}`}
            >
              {injuryLabel(rec.injury_status)}
            </span>
          )}
          {!isStarter && reason && (
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold border ${reason.className}`}>
              {reason.text}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap text-xs text-sleeper-gray-400 mt-0.5">
          <span>
            {rec.position}
            {rec.team && rec.team !== 'FA' ? ` · ${rec.team}` : ''}
            {game ? ` · ${game}` : ''}
          </span>
          {/* On narrow screens the matchup chip sits under the name so the name isn't squeezed. */}
          {showMatchup && (
            <span className="sm:hidden">
              <HoverCard renderContent={renderBreakdown} width={cardWidth}>
                <MatchupBadge grade={rec.matchup_grade} />
              </HoverCard>
            </span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3 flex-shrink-0">
        {hasExplanation ? (
          <HoverCard renderContent={renderBreakdown} width={cardWidth} className="inline-flex items-center gap-3">
            {showMatchup && (
              <span className="hidden sm:inline-flex">
                <MatchupBadge grade={rec.matchup_grade} />
              </span>
            )}
            {points}
          </HoverCard>
        ) : (
          points
        )}
      </div>
    </div>
  );
}
