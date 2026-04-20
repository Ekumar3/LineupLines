import { memo } from 'react';
import ADPBadge from '../common/ADPBadge';
import PlayerHeadshot from '../common/PlayerHeadshot';
import { formatPlayerName } from '../../utils/formatPlayerName';

export default memo(function PlayerRow({ player, showProjections = false }) {
  if (showProjections) {
    return (
      <tr className="hover:bg-sleeper-gray-900 transition-colors">
        <td className="px-3 py-3 whitespace-nowrap">
          <div className="flex items-center gap-2">
            <PlayerHeadshot
              playerId={player.player_id}
              playerName={player.player_name}
              position={player.position}
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
    );
  }

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
