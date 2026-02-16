export default function PositionHeader({ position, count, priority, needsMore }) {
  const priorityColors = {
    high: 'bg-sleeper-red/10 text-sleeper-red',
    medium: 'bg-sleeper-purple/10 text-sleeper-purple',
    low: 'bg-sleeper-gray-800 text-sleeper-gray-400',
  };

  const priorityBg = priorityColors[priority] || priorityColors.low;

  return (
    <div className="px-6 py-4 bg-sleeper-gray-900 flex items-center justify-between">
      <div className="flex items-center gap-4">
        <h2 className="text-xl font-bold text-white">{position}</h2>
        <span className="text-sleeper-gray-400">
          {count} player{count !== 1 ? 's' : ''}
        </span>
      </div>
      {needsMore && (
        <span className={`px-3 py-1 rounded-full text-xs font-medium ${priorityBg}`}>
          {priority?.toUpperCase()} PRIORITY
        </span>
      )}
    </div>
  );
}
