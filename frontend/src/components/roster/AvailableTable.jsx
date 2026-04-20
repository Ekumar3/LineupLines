import { memo } from 'react';
import PlayerHeadshot from '../common/PlayerHeadshot';
import { formatPlayerName } from '../../utils/formatPlayerName';

/**
 * AvailableTable showing top available players at a position.
 *
 * Props:
 *   - players: Array of player objects from available endpoint
 *   - position: Position being displayed
 */
export default memo(function AvailableTable({ players, position }) {
  if (!players || players.length === 0) return null;

  return (
    <div className="overflow-x-auto">
      <table className="max-w-4xl">
        <thead className="bg-sleeper-gray-900 border-b border-sleeper-gray-800">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider">
              Player
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider w-20">
              Proj Pts
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider w-16">
              PPG
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-sleeper-gray-800">
          {players.map((player) => (
            <tr key={player.player_id} className="hover:bg-sleeper-gray-900 transition-colors">
              <td className="px-3 py-3 whitespace-nowrap">
                <div className="flex items-center gap-2">
                  <PlayerHeadshot
                    playerId={player.player_id}
                    playerName={player.player_name}
                    position={position}
                  />
                  <div>
                    <span className="text-sm font-medium text-white">
                      {formatPlayerName(player.player_name)}
                    </span>
                    <span className="text-xs text-sleeper-gray-400 ml-1">
                      {player.team}
                    </span>
                  </div>
                </div>
              </td>
              <td className="px-3 py-3 whitespace-nowrap text-center text-sm text-white font-medium">
                {player.projected_pts != null ? player.projected_pts : '—'}
              </td>
              <td className="px-3 py-3 whitespace-nowrap text-center text-sm text-sleeper-gray-300">
                {player.avg_ppg != null ? player.avg_ppg : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
})
