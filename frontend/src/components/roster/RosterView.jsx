import { useMemo, useState } from 'react';
import { useRosterData } from '../../hooks/useRosterData';
import { useAvailableByPosition } from '../../hooks/useAvailableByPosition';
import { useNextPick } from '../../hooks/useNextPick';

import PositionTable from './PositionTable';
import AvailablePlayersTable from '../available/AvailablePlayersTable';
import LoadingSpinner from '../common/LoadingSpinner';
import ErrorMessage from '../common/ErrorMessage';

const POSITION_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'];

const ADP_SOURCE_LABELS = {
  sleeper: 'Sleeper',
  draftsharks: 'DraftSharks',
};

export default function RosterView({ draftId, userId }) {
  const [adpSource, setAdpSource] = useState('draftsharks');
  const { data: rosterData, loading, error } = useRosterData(draftId, userId);
  const { data: availableData } = useAvailableByPosition(draftId, 20, adpSource);
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
          <h1 className="text-3xl font-bold text-white mb-2">
            My Roster
          </h1>
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

        {/* ADP source toggle */}
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <span className="text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider">
            ADP Source
          </span>
          <div className="flex rounded-lg overflow-hidden border border-sleeper-gray-600 text-xs font-medium w-fit">
            {Object.entries(ADP_SOURCE_LABELS).map(([source, label]) => (
              <button
                key={source}
                onClick={() => setAdpSource(source)}
                className={`px-3 py-1.5 transition-colors ${
                  adpSource === source
                    ? 'bg-sleeper-blue text-white'
                    : 'bg-sleeper-gray-800 text-sleeper-gray-300 hover:bg-sleeper-gray-700'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* ADP source warnings */}
        {adpSource !== 'sleeper' && availableData?.adp_source_available === false && (
          <div className="mb-4 rounded-lg border border-yellow-800 bg-yellow-900/20 px-4 py-2 text-sm text-yellow-200">
            {ADP_SOURCE_LABELS[adpSource]} ADP unavailable — showing Sleeper ADP
          </div>
        )}
        {adpSource === 'draftsharks' && availableData?.adp_source_available && availableData?.scoring_format !== 'ppr' && (
          <div className="mb-4 rounded-lg border border-yellow-800 bg-yellow-900/20 px-4 py-2 text-sm text-yellow-200">
            DraftSharks ADP shown is PPR — your league scoring is {availableData.scoring_format}.
          </div>
        )}

        {/* Best Available, filterable by position */}
        {bestAvailablePlayers.length > 0 && (
          <AvailablePlayersTable
            draftId={draftId}
            players={bestAvailablePlayers}
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
