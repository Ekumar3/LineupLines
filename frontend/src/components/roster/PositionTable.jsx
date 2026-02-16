import PositionHeader from './PositionHeader';
import PlayerRow from './PlayerRow';

export default function PositionTable({ position, players, positionSummary }) {
  const isEmpty = !players || players.length === 0;

  return (
    <div className="card">
      {/* Position Header */}
      <PositionHeader
        position={position}
        count={positionSummary?.count || 0}
        priority={positionSummary?.priority}
        needsMore={positionSummary?.needs_more}
      />

      {/* Player Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-sleeper-gray-900 border-b border-sleeper-gray-800">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider">
                Pick
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider">
                Player
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider">
                Team
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider">
                Round
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider">
                ADP Delta
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-sleeper-gray-800">
            {isEmpty ? (
              <tr>
                <td colSpan="5" className="px-6 py-8 text-center text-sleeper-gray-500">
                  No {position}s drafted yet
                </td>
              </tr>
            ) : (
              players.map((player, idx) => (
                <PlayerRow
                  key={`${player.player_id}-${idx}`}
                  player={player}
                />
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
