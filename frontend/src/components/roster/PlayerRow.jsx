import { memo } from 'react';
import ADPBadge from '../common/ADPBadge';
import PlayerHeadshot from '../common/PlayerHeadshot';
import { formatPlayerName } from '../../utils/formatPlayerName';

export default memo(function PlayerRow({ player }) {
  return (
    <tr className="hover:bg-sleeper-gray-900 transition-colors">
      <td className="px-3 py-3 whitespace-nowrap text-center">
        <ADPBadge
          adpDelta={player.adp_delta}
          adpPpr={player.adp_ppr}
        />
      </td>
      <td className="px-3 py-3 whitespace-nowrap text-center text-sm text-sleeper-gray-400">
        #{player.pick_no}
      </td>
      <td className="px-3 py-3 whitespace-nowrap">
        <div className="flex items-center gap-2">
          <PlayerHeadshot
            playerId={player.player_id}
            playerName={player.player_name}
            position={player.position}
          />
          <span className="text-sm font-medium text-white">
            {formatPlayerName(player.player_name)}
          </span>
        </div>
      </td>
    </tr>
  );
})
