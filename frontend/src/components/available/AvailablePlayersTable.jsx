import { useState, useMemo, Fragment } from 'react';
import ADPBadge from '../common/ADPBadge';
import PlayerHeadshot from '../common/PlayerHeadshot';
import { formatPlayerName } from '../../utils/formatPlayerName';

const POSITION_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'];

const POSITION_COLORS = {
  QB: 'bg-red-900 text-red-100',
  RB: 'bg-green-900 text-green-100',
  WR: 'bg-blue-900 text-blue-100',
  TE: 'bg-orange-900 text-orange-100',
  K: 'bg-sleeper-gray-700 text-sleeper-gray-300',
  DEF: 'bg-sleeper-gray-700 text-sleeper-gray-300',
};

const TIER_COLORS = [
  'bg-yellow-900 text-yellow-100',
  'bg-purple-900 text-purple-100',
  'bg-teal-900 text-teal-100',
  'bg-pink-900 text-pink-100',
  'bg-indigo-900 text-indigo-100',
];

const DEFAULT_ROWS = 5;

export default function AvailablePlayersTable({ draftId, recommendations, availableData }) {
  const [expanded, setExpanded] = useState(false);
  const [positionFilter, setPositionFilter] = useState('ALL');

  const activeRecs = recommendations;

  const adpByPlayerId = useMemo(() => {
    if (!availableData?.players_by_position) return {};
    return Object.values(availableData.players_by_position)
      .flat()
      .reduce((acc, p) => {
        acc[p.player_id] = { adp_delta: p.adp_delta, adp_ppr: p.adp_ppr, tier: p.tier, positional_tier: p.positional_tier };
        return acc;
      }, {});
  }, [availableData]);

  const rows = useMemo(() => {
    return (activeRecs || []).map((rec) => ({
      ...rec,
      adp_delta: adpByPlayerId[rec.player_id]?.adp_delta ?? null,
      adp_ppr: adpByPlayerId[rec.player_id]?.adp_ppr ?? null,
      tier: adpByPlayerId[rec.player_id]?.tier ?? null,
      positional_tier: adpByPlayerId[rec.player_id]?.positional_tier ?? null,
    }));
  }, [activeRecs, adpByPlayerId]);

  const filtered =
    positionFilter === 'ALL' ? rows : rows.filter((r) => r.position === positionFilter);

  if (!recommendations || recommendations.length === 0) return null;

  const visible = expanded ? filtered : filtered.slice(0, DEFAULT_ROWS);
  const hasMore = filtered.length > DEFAULT_ROWS;

  return (
    <div className="mb-8">
      {/* Header row */}
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-white">Best Available</h2>
        </div>
      </div>

      {/* Position filter */}
      <div className="mb-3 flex flex-wrap rounded-lg overflow-hidden border border-sleeper-gray-600 text-xs font-medium w-fit">
        {['ALL', ...POSITION_ORDER].map((pos) => (
          <button
            key={pos}
            onClick={() => {
              setPositionFilter(pos);
              setExpanded(false);
            }}
            className={`px-3 py-1.5 transition-colors ${
              positionFilter === pos
                ? 'bg-sleeper-blue text-white'
                : 'bg-sleeper-gray-800 text-sleeper-gray-300 hover:bg-sleeper-gray-700'
            }`}
          >
            {pos === 'ALL' ? 'All' : pos}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto rounded-lg border border-sleeper-gray-700">
        {filtered.length === 0 ? (
          <div className="p-4 text-sleeper-gray-400 text-sm text-center">
            No available players at this position.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-sleeper-gray-800 text-sleeper-gray-300 text-left">
                <th className="px-2 py-1.5 w-8">#</th>
                <th className="px-2 py-1.5">Player</th>
                <th className="px-2 py-1.5 w-16">Pos</th>
                <th className="px-2 py-1.5 w-28 text-center">ADP Delta</th>
                <th className="px-2 py-1.5 w-20">Proj Pts</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((rec, idx) => {
                const rank = idx + 1;
                const isTop = rank === 1;
                const tierValue = positionFilter === 'ALL' ? rec.tier : rec.positional_tier;
                const prevTierValue =
                  idx > 0 ? (positionFilter === 'ALL' ? visible[idx - 1].tier : visible[idx - 1].positional_tier) : undefined;
                const showTierDivider = tierValue != null && tierValue !== prevTierValue;
                const tierColorClass = tierValue != null ? TIER_COLORS[(tierValue - 1) % TIER_COLORS.length] : '';
                return (
                  <Fragment key={rec.player_id}>
                    {showTierDivider && (
                      <tr>
                        <td colSpan={5} className={`px-2 py-0.5 text-xs font-semibold ${tierColorClass}`}>
                          Tier {tierValue}
                        </td>
                      </tr>
                    )}
                    <tr
                      className={`border-t border-sleeper-gray-700 ${isTop ? 'border-l-2 border-l-green-500' : ''} hover:bg-sleeper-gray-800/50`}
                    >
                      <td className="px-2 py-1.5 text-sleeper-gray-400 font-mono">{rank}</td>
                      <td className="px-2 py-1.5 text-white font-medium">
                        <div className="flex items-center gap-2">
                          <PlayerHeadshot
                            playerId={rec.player_id}
                            playerName={rec.player_name}
                            position={rec.position}
                          />
                          <span>{formatPlayerName(rec.player_name)}</span>
                        </div>
                      </td>
                      <td className="px-2 py-1.5">
                        <span className={`px-2 py-0.5 rounded text-xs font-semibold ${POSITION_COLORS[rec.position] ?? 'bg-sleeper-gray-700 text-sleeper-gray-300'}`}>
                          {rec.position}
                        </span>
                      </td>
                      <td className="px-2 py-1.5 text-center">
                        <ADPBadge adpDelta={rec.adp_delta} adpPpr={rec.adp_ppr} />
                      </td>
                      <td className="px-2 py-1.5 text-sleeper-gray-300">
                        {rec.projected_points != null ? rec.projected_points.toFixed(1) : '—'}
                      </td>
                    </tr>
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {hasMore && (
        <button
          onClick={() => setExpanded(e => !e)}
          className="mt-2 text-sleeper-blue text-sm hover:underline"
        >
          {expanded ? 'Show less' : `Show ${filtered.length - DEFAULT_ROWS} more`}
        </button>
      )}
    </div>
  );
}
