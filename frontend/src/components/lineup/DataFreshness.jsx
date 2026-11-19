import useNow from '../../hooks/useNow';
import { formatAgo } from '../../utils/lineupFormat';

// Shows how current the lineup is: whether it's refreshing right now, when the
// projections were generated, and whether Vegas lines are live or the older
// schedule lines. Labels re-render every 30s so "3m ago" keeps counting.
export default function DataFreshness({ status, refreshing }) {
  const now = useNow();
  if (!status) return null;

  const projectionAgo = formatAgo(status.projection_generated_at, now);
  const oddsAgo = formatAgo(status.odds_fetched_at, now);

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-sleeper-gray-400">
      <span className="inline-flex items-center gap-1.5">
        <span
          className={`w-2 h-2 rounded-full ${
            refreshing ? 'bg-sleeper-blue animate-pulse' : 'bg-sleeper-green'
          }`}
        />
        {refreshing ? 'Updating…' : 'Updates automatically'}
      </span>
      {projectionAgo && <span>Projections updated {projectionAgo}</span>}
      {status.odds_source === 'live' && oddsAgo ? (
        <span>Vegas lines updated {oddsAgo}</span>
      ) : (
        <span title="Fresh Vegas lines aren't available for this week, so nflverse schedule lines are used.">
          Vegas lines: schedule
        </span>
      )}
    </div>
  );
}
