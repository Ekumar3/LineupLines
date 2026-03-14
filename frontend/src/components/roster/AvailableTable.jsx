import ADPBadge from '../common/ADPBadge';
import PlayerHeadshot from '../common/PlayerHeadshot';
import { formatPlayerName } from '../../utils/formatPlayerName';

export default function AvailableTable({ players, position }) {
  if (!players || players.length === 0) return null;

  return (
    <div className="overflow-x-auto">
      <table className="max-w-2xl">
        <thead className="bg-sleeper-gray-900 border-b border-sleeper-gray-800">
          <tr>
            <th className="px-3 py-2 text-center text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider w-24">
              ADP Delta
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-sleeper-gray-400 uppercase tracking-wider">
              Player
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-sleeper-gray-800">
          {players.map((player, idx) => (
            <tr key={`${player.player_id}-${idx}`} className="hover:bg-sleeper-gray-900 transition-colors">
              <td className="px-3 py-3 whitespace-nowrap text-center">
                <ADPBadge
                  adpDelta={player.adp_delta}
                  adpPpr={player.adp_ppr}
                />
              </td>
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
          ))}
        </tbody>
      </table>
    </div>
  );
}
