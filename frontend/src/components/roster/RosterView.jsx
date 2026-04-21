import { useMemo, useState, useEffect } from 'react';
import { useRosterData } from '../../hooks/useRosterData';
import { useAvailableByPosition } from '../../hooks/useAvailableByPosition';
import { useVORAnalysis } from '../../hooks/useVORAnalysis';

import PositionTable from './PositionTable';
import AvailableTable from './AvailableTable';
import BestAvailableTable from '../available/BestAvailableTable';
import LoadingSpinner from '../common/LoadingSpinner';
import ErrorMessage from '../common/ErrorMessage';

const POSITION_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'];

export default function RosterView({ draftId, userId }) {
  const { data: rosterData, loading, error, lastPolled: rosterPolled } = useRosterData(draftId, userId);
  const { data: availableData, lastPolled: availablePolled } = useAvailableByPosition(draftId, 5);
  const { data: vorData, loading: vorLoading, error: vorError } = useVORAnalysis(draftId);

  // Pick the most recent poll time from any hook
  const lastPolled = rosterPolled && availablePolled
    ? (rosterPolled > availablePolled ? rosterPolled : availablePolled)
    : rosterPolled || availablePolled;

  // Re-render every second to keep the "Xs ago" display ticking
  const [, setTick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  const positionData = useMemo(() =>
    POSITION_ORDER.map(pos => ({
      position: pos,
      drafted: rosterData?.roster_by_position?.[pos] || [],
      available: availableData?.players_by_position?.[pos] || [],
      summary: rosterData?.position_summary?.[pos],
    })),
    [rosterData, availableData]
  );

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error} />;
  if (!rosterData) return null;

  return (
    <div className="min-h-screen bg-sleeper-darker py-8">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
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
            {lastPolled && (
              <span className="text-sleeper-gray-500 text-sm ml-auto">
                {(() => {
                  const ago = Math.round((Date.now() - lastPolled.getTime()) / 1000);
                  return ago < 2 ? 'Live' : `Updated ${ago}s ago`;
                })()}
              </span>
            )}
          </div>
        </div>

        {/* Best Available by VOR */}
        {vorData?.recommendations?.length > 0 && (
          <BestAvailableTable draftId={draftId} recommendations={vorData.recommendations} />
        )}

        {/* Position Tables - 2 per row, 3 rows */}
        <div className="grid grid-cols-3 gap-6">
          {positionData.map(({ position, drafted, available, summary }) => (
            <div key={position} className="space-y-4">
              {/* Drafted Roster */}
              <PositionTable
                position={position}
                players={drafted}
                positionSummary={summary}
              />

              {/* Available Players (if any) */}
              {available.length > 0 && (
                <div>
                  <h3 className="text-xl font-medium text-sleeper-gray-400 mb-2">
                    Available {position}s (Top {availableData?.limit})
                  </h3>
                  <AvailableTable players={available} position={position} />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
