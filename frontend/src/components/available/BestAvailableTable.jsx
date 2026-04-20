import { useState } from 'react';

const POSITION_COLORS = {
  QB: 'bg-red-900 text-red-100',
  RB: 'bg-green-900 text-green-100',
  WR: 'bg-blue-900 text-blue-100',
  TE: 'bg-orange-900 text-orange-100',
  K: 'bg-sleeper-gray-700 text-sleeper-gray-300',
  DEF: 'bg-sleeper-gray-700 text-sleeper-gray-300',
};

function vorColor(score) {
  if (score >= 60) return 'text-green-300';
  if (score >= 30) return 'text-green-400';
  if (score >= 15) return 'text-blue-300';
  if (score >= 5) return 'text-blue-400';
  return 'text-red-400';
}

const DEFAULT_ROWS = 5;

export default function BestAvailableTable({ recommendations }) {
  const [expanded, setExpanded] = useState(false);

  if (!recommendations || recommendations.length === 0) return null;

  const visible = expanded ? recommendations : recommendations.slice(0, DEFAULT_ROWS);
  const hasMore = recommendations.length > DEFAULT_ROWS;

  return (
    <div className="mb-8">
      <div className="mb-2">
        <h2 className="text-lg font-semibold text-white">Best Available (by VOR)</h2>
        <p className="text-sleeper-gray-400 text-sm mt-1">
          VOR measures how much better a player is than the median available player at their position. Higher = more valuable right now.
        </p>
      </div>

      <div className="overflow-x-auto rounded-lg border border-sleeper-gray-700">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-sleeper-gray-800 text-sleeper-gray-300 text-left">
              <th className="px-3 py-2 w-8">#</th>
              <th className="px-3 py-2">Player</th>
              <th className="px-3 py-2">Pos</th>
              <th className="px-3 py-2">VOR</th>
              <th className="px-3 py-2">Proj Pts</th>
              <th className="px-3 py-2">PPG</th>
              <th className="px-3 py-2 hidden sm:table-cell">Tier</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((rec, idx) => {
              const rank = idx + 1;
              const isTop = rank === 1;
              return (
                <tr
                  key={rec.player_name}
                  className={`border-t border-sleeper-gray-700 ${isTop ? 'border-l-2 border-l-green-500' : ''} hover:bg-sleeper-gray-800/50`}
                >
                  <td className="px-3 py-2 text-sleeper-gray-400 font-mono">{rank}</td>
                  <td className="px-3 py-2 text-white font-medium">{rec.player_name}</td>
                  <td className="px-3 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-semibold ${POSITION_COLORS[rec.position] ?? 'bg-sleeper-gray-700 text-sleeper-gray-300'}`}>
                      {rec.position}
                    </span>
                  </td>
                  <td className={`px-3 py-2 font-bold ${vorColor(rec.vor_score)}`}>
                    {rec.vor_score.toFixed(1)}
                  </td>
                  <td className="px-3 py-2 text-sleeper-gray-300">
                    {rec.season_pts != null ? rec.season_pts : '—'}
                  </td>
                  <td className="px-3 py-2 text-sleeper-gray-300">
                    {rec.projected_points != null ? rec.projected_points : '—'}
                  </td>
                  <td className="px-3 py-2 text-sleeper-gray-400 text-xs hidden sm:table-cell">{rec.interpretation}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {hasMore && (
        <button
          onClick={() => setExpanded(e => !e)}
          className="mt-2 text-sleeper-blue text-sm hover:underline"
        >
          {expanded ? 'Show less' : `Show ${recommendations.length - DEFAULT_ROWS} more`}
        </button>
      )}
    </div>
  );
}
