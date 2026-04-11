import React from 'react';
import { useAvailableByPosition } from '../../hooks/useAvailableByPosition';
import PositionTable from '../roster/PositionTable';
import LoadingSpinner from '../common/LoadingSpinner';
import ErrorMessage from '../common/ErrorMessage';

const POSITION_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'];

export default function AvailablePlayersView({ draftId, limit = 20 }) {
  const { data, loading, error } = useAvailableByPosition(draftId, limit);

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error} />;
  if (!data) return null;

  return (
    <div className="min-h-screen bg-sleeper-darker py-8">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-white mb-2">
            Available Players
          </h1>
          <div className="flex gap-4 text-sleeper-gray-400 flex-wrap">
            <span>Current Pick: #{data.current_overall_pick}</span>
            <span>Scoring: {data.scoring_format.toUpperCase()}</span>
            <span>Top {data.limit} per position</span>
          </div>
        </div>

        {/* Position Tables - REUSE existing component */}
        <div className="space-y-6">
          {POSITION_ORDER.map(position => {
            const players = data.players_by_position?.[position] || [];
            return (
              <PositionTable
                key={position}
                position={position}
                players={players}
                positionSummary={null}
                showCount={false}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
