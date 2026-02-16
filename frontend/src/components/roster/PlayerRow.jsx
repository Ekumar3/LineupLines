import ADPBadge from '../common/ADPBadge';

export default function PlayerRow({ player }) {
  return (
    <tr className="hover:bg-sleeper-gray-900 transition-colors">
      <td className="px-6 py-4 whitespace-nowrap text-sm text-sleeper-gray-400">
        #{player.pick_no}
      </td>
      <td className="px-6 py-4 whitespace-nowrap">
        <div className="flex items-center">
          <div className="text-sm font-medium text-white">
            {player.player_name}
          </div>
        </div>
      </td>
      <td className="px-6 py-4 whitespace-nowrap text-sm text-sleeper-gray-400">
        {player.team || '-'}
      </td>
      <td className="px-6 py-4 whitespace-nowrap text-sm text-sleeper-gray-400">
        Round {player.round}
      </td>
      <td className="px-6 py-4 whitespace-nowrap text-right">
        <ADPBadge
          adpDelta={player.adp_delta}
          adpPpr={player.adp_ppr}
        />
      </td>
    </tr>
  );
}
