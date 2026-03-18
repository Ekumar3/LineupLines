import { useState, memo } from 'react';

export default memo(function PlayerHeadshot({ playerId, playerName, position }) {
  const [imgError, setImgError] = useState(false);

  const showFallback = imgError || position === 'DEF';
  const initials = playerName
    ?.split(' ')
    .map(n => n[0])
    .join('')
    .slice(0, 2)
    .toUpperCase() || '?';

  if (showFallback) {
    return (
      <div className="w-8 h-8 rounded-full bg-sleeper-gray-800 flex items-center justify-center flex-shrink-0">
        <span className="text-xs font-medium text-sleeper-gray-400">{initials}</span>
      </div>
    );
  }

  return (
    <img
      src={`https://sleepercdn.com/content/nfl/players/thumb/${playerId}.jpg`}
      alt={playerName}
      loading="lazy"
      onError={() => setImgError(true)}
      className="w-8 h-8 rounded-full object-cover flex-shrink-0 bg-sleeper-gray-800"
    />
  );
})
