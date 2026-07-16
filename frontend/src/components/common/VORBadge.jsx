/**
 * VOR (Value Over Replacement) Badge
 *
 * Shows VOR score with color coding:
 * - Green (Elite): VOR >= 30
 * - Yellow (Strong): VOR >= 15
 * - Blue (Moderate): VOR >= 5
 * - Gray (Below): VOR < 5
 */

import { useState } from 'react';
import PlayerHeadshot from './PlayerHeadshot';

export default function VORBadge({ vorScore, interpretation, replacementPlayerId, replacementPlayerName, replacementPlayerTeam, replacementPlayerPosition, replacementPlayerPoints }) {
  const [isHovering, setIsHovering] = useState(false);

  if (vorScore === undefined || vorScore === null) {
    return null;
  }

  // Determine color based on VOR score
  let bgColor = 'bg-sleeper-gray-700';
  let textColor = 'text-sleeper-gray-300';
  let label = 'N/A';

  if (vorScore >= 60) {
    bgColor = 'bg-green-900';
    textColor = 'text-green-100';
    label = `Elite`;
  } else if (vorScore >= 30) {
    bgColor = 'bg-green-800';
    textColor = 'text-green-100';
    label = `Strong`;
  } else if (vorScore >= 15) {
    bgColor = 'bg-blue-900';
    textColor = 'text-blue-100';
    label = `Moderate`;
  } else if (vorScore >= 5) {
    bgColor = 'bg-blue-800';
    textColor = 'text-blue-100';
    label = `Neutral`;
  } else {
    bgColor = 'bg-red-900';
    textColor = 'text-red-100';
    label = `Below`;
  }

  return (
    <div className="relative inline-block" onMouseEnter={() => setIsHovering(true)} onMouseLeave={() => setIsHovering(false)}>
      <div
        className={`${bgColor} ${textColor} px-2 py-1 rounded text-xs font-medium whitespace-nowrap`}
        title={`${interpretation || 'Value Over Replacement'}${replacementPlayerName ? ` - Replacement Player: ${replacementPlayerName}` : ''} ${replacementPlayerTeam ? ` (${replacementPlayerTeam})` : ''}`}
      >
        VOR: {vorScore.toFixed(1)}
      </div>
      {isHovering && replacementPlayerId && (
        <div className="absolute z-10 top-full mt-1 left-0 bg-sleeper-gray-800 border border-sleeper-gray-700 rounded shadow-lg p-2 flex items-center gap-2 min-w-max">
          <PlayerHeadshot
            playerId={replacementPlayerId}
            playerName={replacementPlayerName}
            position={replacementPlayerPosition}
          />
          <div className="text-xs">
            <div className="text-sleeper-gray-200 font-medium">{replacementPlayerName}</div>
            <div className="text-sleeper-gray-400">
              {replacementPlayerTeam}{replacementPlayerTeam && replacementPlayerPosition ? ' · ' : ''}{replacementPlayerPosition}
            </div>
            {replacementPlayerPoints != null && (
              <div className="text-sleeper-gray-400">{replacementPlayerPoints.toFixed(1)} pts</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
