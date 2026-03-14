import React from 'react';
import { useRosterData } from '../../hooks/useRosterData';
import { useAvailableByPosition } from '../../hooks/useAvailableByPosition';
import PositionTable from './PositionTable';
import AvailableTable from './AvailableTable';
import LoadingSpinner from '../common/LoadingSpinner';
import ErrorMessage from '../common/ErrorMessage';

const POSITION_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'];

export default function RosterView({ draftId, userId }) {
  const { data: rosterData, loading, error } = useRosterData(draftId, userId);
  const { data: availableData } = useAvailableByPosition(draftId, 10);

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
          <div className="flex gap-4 text-sleeper-gray-400 flex-wrap">
            <span>Draft Slot: {rosterData.draft_slot}</span>
            <span>Total Picks: {rosterData.total_picks}</span>
            <span>Current Round: {availableData.current_round}</span>
            {availableData?.current_overall_pick && (
              <span className="text-sleeper-blue">
                Current Pick: #{availableData.current_overall_pick}
              </span>
            )}
          </div>
        </div>

        {/* Position Tables - 2 per row, 3 rows */}
        <div className="grid grid-cols-3 gap-6">
          {POSITION_ORDER.map(position => {
            const draftedPlayers = rosterData.roster_by_position?.[position] || [];
            const availablePlayers = availableData?.players_by_position?.[position] || [];

            return (
              <div key={position} className="space-y-4">
                {/* Drafted Roster */}
                <PositionTable
                  position={position}
                  players={draftedPlayers}
                  positionSummary={rosterData.position_summary?.[position]}
                />

                {/* Available Players (if any) */}
                {availablePlayers.length > 0 && (
                  <div>
                    <h3 className="text-xl font-medium text-sleeper-gray-400 mb-2">
                      Available {position}s (Top {availableData.limit})
                    </h3>
                    <AvailableTable players={availablePlayers} position={position} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
