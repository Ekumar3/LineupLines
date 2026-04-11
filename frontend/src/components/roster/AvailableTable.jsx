import { memo } from 'react';
import ADPBadge from '../common/ADPBadge';
import VORBadge from '../common/VORBadge';
import PlayerHeadshot from '../common/PlayerHeadshot';
import { formatPlayerName } from '../../utils/formatPlayerName';

/**
 * AvailableTable with VOR display
 * 
 * Props:
 *   - players: Array of player objects from available endpoint
 *   - position: Position being displayed
 *   - vorMap: Map of player_name -> VOR data (keyed by name, not ID)
 */
export default memo(function AvailableTable({ players, position, vorMap }) {
  if (!players || players.length === 0) return null;

  return (
    <div className="overflow-x-auto">
      <table className="max-w-4xl">
        <thead className="bg-sleeper-gray-900 border-b border-sleeper-gray-800">
          <tr>
            <th className="px-3 py-2 text-center text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider w-20">
              ADP Delta
            </th>
            {vorMap && Object.keys(vorMap).length > 0 && (
              <th className="px-3 py-2 text-center text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider w-24">
                VOR
              </th>
            )}
            <th className="px-3 py-2 text-left text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider">
              Player
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-sleeper-gray-800">
          {players.map((player) => {
            // Look up VOR by player_name
            const vorData = vorMap?.[player.player_name];

            return (
              <tr key={player.player_id} className="hover:bg-sleeper-gray-900 transition-colors">
                <td className="px-3 py-3 whitespace-nowrap text-center">
                  <ADPBadge
                    adpDelta={player.adp_delta}
                    adpPpr={player.adp_ppr}
                  />
                </td>
                {vorMap && Object.keys(vorMap).length > 0 && (
                  <td className="px-3 py-3 whitespace-nowrap text-center">
                    {vorData ? (
                      <VORBadge
                        vorScore={vorData.vor_score}
                        interpretation={vorData.interpretation}
                      />
                    ) : (
                      <span className="text-xs text-sleeper-gray-500">--</span>
                    )}
                  </td>
                )}
                <td className="px-3 py-3 whitespace-nowrap">
                  <div className="flex items-center gap-2">
                    <PlayerHeadshot
                      playerId={player.player_id}
                      playerName={player.player_name}
                      position={position}
                    />
                    <span className="text-sm font-medium text-white">
                      {formatPlayerName(player.player_name)}
                    </span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
})
