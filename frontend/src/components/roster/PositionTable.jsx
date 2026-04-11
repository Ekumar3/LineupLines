import { memo } from 'react';
import PositionHeader from './PositionHeader';
import PlayerRow from './PlayerRow';

export default memo(function PositionTable({ position, players, positionSummary, showCount = true, vorMap }) {
  const isEmpty = !players || players.length === 0;

  return (
    <div className="card w-fit">
      {/* Position Header */}
      <PositionHeader
        position={position}
        count={positionSummary?.count || 0}
        priority={positionSummary?.priority}
        needsMore={positionSummary?.needs_more}
        showCount={showCount}
      />

      {/* Player Table */}
      <div className="overflow-x-auto">
        <table className="w-full max-w-4xl">
          <thead className="bg-sleeper-gray-900 border-b border-sleeper-gray-800">
            <tr>
              <th className="px-3 py-2 text-center text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider w-24">
                ADP Delta
              </th>
              {vorMap && (
                <th className="px-3 py-2 text-center text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider w-24">
                  VOR
                </th>
              )}
              <th className="px-3 py-2 text-center text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider w-16">
                Pick
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider">
                Player
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-sleeper-gray-800">
            {isEmpty ? (
              <tr>
                <td colSpan={vorMap ? 4 : 3} className="px-3 py-6 text-center text-sleeper-gray-500">
                  No {position}s drafted yet
                </td>
              </tr>
            ) : (
              players.map((player) => (
                <PlayerRow
                  key={player.player_id}
                  player={player}
                  vorData={vorMap?.[player.player_id]}
                />
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
})
