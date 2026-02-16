export default function ADPBadge({ adpDelta, adpPpr }) {
  if (!adpDelta && adpDelta !== 0 || !adpPpr) {
    return <span className="text-sleeper-gray-500">-</span>;
  }

  // Positive delta = Good value (picked later than ADP - got premium player later)
  // Negative delta = Reach (picked earlier than ADP - reached for player)
  const isValue = adpDelta > 0;
  const isReach = adpDelta < 0;

  let colorClass = 'text-sleeper-gray-400';
  let bgClass = 'bg-sleeper-gray-800';

  if (isValue && adpDelta > 10) {
    // Great value (got them much later than expected)
    colorClass = 'text-sleeper-green';
    bgClass = 'bg-sleeper-green/10';
  } else if (isValue) {
    // Good value
    colorClass = 'text-sleeper-blue';
    bgClass = 'bg-sleeper-blue/10';
  } else if (isReach && adpDelta < -10) {
    // Big reach (picked way earlier than they should have)
    colorClass = 'text-sleeper-red';
    bgClass = 'bg-sleeper-red/10';
  } else if (isReach) {
    // Slight reach
    colorClass = 'text-sleeper-purple';
    bgClass = 'bg-sleeper-purple/10';
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <span className={`badge ${bgClass} ${colorClass}`}>
        {adpDelta > 0 ? '+' : ''}{adpDelta.toFixed(1)}
      </span>
      <span className="text-xs text-sleeper-gray-500">
        ADP: {adpPpr.toFixed(1)}
      </span>
    </div>
  );
}
