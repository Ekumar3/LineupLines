import React, { useMemo } from 'react';
import { useAvailableByPosition } from '../../hooks/useAvailableByPosition';
import { useVORAnalysis } from '../../hooks/useVORAnalysis';
import BestAvailableTable from './BestAvailableTable';
import PositionTable from '../roster/PositionTable';
import LoadingSpinner from '../common/LoadingSpinner';
import ErrorMessage from '../common/ErrorMessage';

const POSITION_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'];

export default function AvailablePlayersView({ draftId, limit = 20 }) {
  const { data, loading, error } = useAvailableByPosition(draftId, limit);
  const { data: vorData, loading: vorLoading, error: vorError } = useVORAnalysis(draftId);

  // Build a map of player_name -> VOR data (matching key)
  const vorMap = useMemo(() => {
    if (!vorData?.recommendations) return {};
    
    return vorData.recommendations.reduce((acc, rec) => {
      // Key by player_name since it's the common identifier across endpoints
      acc[rec.player_name] = rec;
      return acc;
    }, {});
  }, [vorData]);

  if (loading || vorLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error} />;
  if (vorError) {
    console.warn('VOR data unavailable:', vorError);
    // Continue without VOR data
  }
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

        {/* Best Available Table */}
        {vorData?.recommendations?.length > 0 && (
          <BestAvailableTable recommendations={vorData.recommendations} />
        )}

        {/* Top Value Pick Recommendation */}
        {vorData?.top_value_pick && (
          <div className="mb-8 p-4 bg-sleeper-gray-900 border border-green-800 rounded-lg">
            <h2 className="text-lg font-semibold text-green-100 mb-3">
              ⭐ Best Value Available
            </h2>
            <div className="flex items-center gap-4">
              <div className="flex-1">
                <p className="text-white font-semibold">
                  {vorData.top_value_pick.player_name}
                </p>
                <p className="text-sleeper-gray-400 text-sm">
                  {vorData.top_value_pick.position} • ADP: {vorData.top_value_pick.adp_overall.toFixed(1)}
                </p>
              </div>
              <div className="text-right">
                <p className="text-green-100 font-bold text-lg">
                  VOR: {vorData.top_value_pick.vor_score.toFixed(1)}
                </p>
                <p className="text-green-300 text-sm">
                  {vorData.top_value_pick.interpretation}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Replacement Level Reference */}
        {vorData?.replacement_level_by_position && (
          <div className="mb-8 p-3 bg-sleeper-gray-800 rounded text-xs text-sleeper-gray-300">
            <p className="font-semibold text-sleeper-gray-200 mb-2">
              Replacement Level (Median ADP by Position)
            </p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {Object.entries(vorData.replacement_level_by_position).map(([pos, adp]) => (
                <div key={pos}>
                  <span className="font-medium">{pos}:</span> {adp.toFixed(1)}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Position Tables */}
        <div className="space-y-6">
          {POSITION_ORDER.map(position => {
            const players = data.players_by_position?.[position] || [];
            return (
              <PositionTable
                key={position}
                position={position}
                players={players}
                vorMap={vorMap}
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
