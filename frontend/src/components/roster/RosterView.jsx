import { useMemo } from 'react';
import { useRosterData } from '../../hooks/useRosterData';
import { useAvailableByPosition } from '../../hooks/useAvailableByPosition';
import { useNextPick } from '../../hooks/useNextPick';

import PositionTable from './PositionTable';
import AvailablePlayersTable from '../available/AvailablePlayersTable';
import LoadingSpinner from '../common/LoadingSpinner';
import ErrorMessage from '../common/ErrorMessage';

const POSITION_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'];

const RANKING_KEY_LABELS = {
  ppr: 'PPR',
  half_ppr: 'Half-PPR',
  standard: 'Standard',
  dynasty_ppr: 'Dynasty PPR',
  dynasty_half_ppr: 'Dynasty Half-PPR',
  dynasty_ppr_superflex: 'Dynasty PPR Superflex',
  dynasty_te_premium: 'Dynasty TE Premium',
  dynasty_te_premium_superflex: 'Dynasty TE Premium Superflex',
  keeper_ppr: 'Keeper PPR',
  keeper_superflex: 'Keeper Superflex',
};

// Ranking keys built on a PPR base even though the league might score
// half-PPR/standard — no non-PPR variant is scraped for these, so the backend
// fell back to the closest PPR-based key instead of an exact scoring match.
const PPR_FALLBACK_KEYS = new Set([
  'dynasty_ppr',
  'dynasty_ppr_superflex',
  'dynasty_te_premium',
  'dynasty_te_premium_superflex',
  'keeper_ppr',
  'keeper_superflex',
]);

export default function RosterView({ draftId, userId }) {
  const { data: rosterData, loading, error } = useRosterData(draftId, userId);
  const { data: availableData } = useAvailableByPosition(draftId, 20, 'draftsharks');
  const { draftStatus } = useNextPick(draftId, userId);

  const positionData = useMemo(() =>
    POSITION_ORDER.map(pos => ({
      position: pos,
      drafted: rosterData?.roster_by_position?.[pos] || [],
      summary: rosterData?.position_summary?.[pos],
    })),
    [rosterData]
  );

  // Best Available is ranked by raw ADP (ascending — lowest ADP first) rather
  // than a computed value score, so it mirrors the source's own consensus
  // rankings directly instead of a formula layered on top of them.
  const bestAvailablePlayers = useMemo(() => {
    if (!availableData?.players_by_position) return [];
    return Object.values(availableData.players_by_position)
      .flat()
      .filter((p) => p.adp_ppr != null)
      .sort((a, b) => a.adp_ppr - b.adp_ppr);
  }, [availableData]);

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error} />;
  if (!rosterData) return null;

  return (
    <div className="min-h-screen bg-sleeper-darker py-8">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Pre-draft notice */}
        {draftStatus === 'pre_draft' && (
          <div className="mb-6 flex items-center gap-3 rounded-lg border border-sleeper-purple/30 bg-sleeper-purple/10 px-4 py-3 text-sleeper-purple">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 shrink-0" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
            </svg>
            <span className="text-sm">Draft hasn't started yet — browse available players and plan your picks.</span>
          </div>
        )}

        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-white mb-1">
            {rosterData.league_name || 'My Roster'}
          </h1>
          {availableData?.scoring_format && (
            <p className="text-sleeper-gray-400 mb-2">
              {RANKING_KEY_LABELS[availableData.scoring_format] || availableData.scoring_format} Scoring
            </p>
          )}
          <div className="flex gap-4 text-sleeper-gray-400 flex-wrap items-center">
            <span>Draft Slot: {rosterData.draft_slot}</span>
            <span>Total Picks: {rosterData.total_picks}</span>
            <span>Current Round: {availableData?.current_round}</span>
            {availableData?.current_overall_pick && (
              <span className="text-sleeper-blue">
                Current Pick: #{availableData.current_overall_pick}
              </span>
            )}
          </div>
        </div>

        {/* ADP source warnings */}
        {availableData?.adp_source_available === false && (
          <div className="mb-4 rounded-lg border border-yellow-800 bg-yellow-900/20 px-4 py-2 text-sm text-yellow-200">
            DraftSharks ADP unavailable — showing Sleeper ADP
          </div>
        )}
        {availableData?.adp_source_available &&
          PPR_FALLBACK_KEYS.has(availableData?.ranking_key) &&
          availableData?.scoring_format !== 'ppr' && (
            <div className="mb-4 rounded-lg border border-yellow-800 bg-yellow-900/20 px-4 py-2 text-sm text-yellow-200">
              Showing {RANKING_KEY_LABELS[availableData.ranking_key]} rankings — a {availableData.scoring_format} equivalent
              isn't available for your league type yet.
            </div>
        )}

        {/* Best Available, filterable by position */}
        {bestAvailablePlayers.length > 0 && (
          <AvailablePlayersTable
            draftId={draftId}
            players={bestAvailablePlayers}
            rankingLabel={RANKING_KEY_LABELS[availableData?.ranking_key]}
          />
        )}

        {/* Position Tables - stack on mobile, 2-up on tablet, 3-up on desktop */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {positionData.map(({ position, drafted, summary }) => (
            <div key={position} className="space-y-4">
              {/* Drafted Roster */}
              <PositionTable
                position={position}
                players={drafted}
                positionSummary={summary}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
