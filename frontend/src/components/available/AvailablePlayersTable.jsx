import { useState, useMemo } from 'react';
import { useVORAnalysis } from '../../hooks/useVORAnalysis';
import ADPBadge from '../common/ADPBadge';
import VORBadge from '../common/VORBadge';
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

const DEFAULT_ROWS = 5;

const MODE_LABELS = {
  replacement_rank: 'Replacement Level',
  next_available: 'Next Available',
};

const MODE_DESCRIPTIONS = {
  replacement_rank:
    'VOR vs. the last projected starter at each position (e.g. WR24 in a 12-team league).',
  next_available:
    'VOR gap to the next-best player directly below at each position.',
};

export default function AvailablePlayersTable({ draftId, recommendations, availableData }) {
  const [expanded, setExpanded] = useState(false);
  const [vorMode, setVorMode] = useState('replacement_rank');
  const [positionFilter, setPositionFilter] = useState('ALL');

  // Fetch alternate-mode data lazily when the user switches away from default
  const { data: altData, loading: altLoading } = useVORAnalysis(
    vorMode !== 'replacement_rank' ? draftId : null,
    vorMode
  );

  const activeRecs =
    vorMode === 'replacement_rank'
      ? recommendations
      : altData?.recommendations ?? [];

  const adpByPlayerId = useMemo(() => {
    if (!availableData?.players_by_position) return {};
    return Object.values(availableData.players_by_position)
      .flat()
      .reduce((acc, p) => {
        acc[p.player_id] = { adp_delta: p.adp_delta, adp_ppr: p.adp_ppr };
        return acc;
      }, {});
  }, [availableData]);

  const rows = useMemo(() => {
    return (activeRecs || []).map((rec) => ({
      ...rec,
      adp_delta: adpByPlayerId[rec.player_id]?.adp_delta ?? null,
      adp_ppr: adpByPlayerId[rec.player_id]?.adp_ppr ?? null,
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
          <h2 className="text-lg font-semibold text-white">Best Available (by VOR)</h2>
          <p className="text-sleeper-gray-400 text-sm mt-1">
            {MODE_DESCRIPTIONS[vorMode]}
          </p>
        </div>

        {/* Mode toggle */}
        <div className="flex rounded-lg overflow-hidden border border-sleeper-gray-600 text-xs font-medium shrink-0">
          {Object.entries(MODE_LABELS).map(([mode, label]) => (
            <button
              key={mode}
              onClick={() => {
                setVorMode(mode);
                setExpanded(false);
              }}
              className={`px-3 py-1.5 transition-colors ${
                vorMode === mode
                  ? 'bg-sleeper-blue text-white'
                  : 'bg-sleeper-gray-800 text-sleeper-gray-300 hover:bg-sleeper-gray-700'
              }`}
            >
              {label}
            </button>
          ))}
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
        {altLoading && vorMode !== 'replacement_rank' ? (
          <div className="p-4 text-sleeper-gray-400 text-sm text-center">Loading…</div>
        ) : filtered.length === 0 ? (
          <div className="p-4 text-sleeper-gray-400 text-sm text-center">
            No available players at this position.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-sleeper-gray-800 text-sleeper-gray-300 text-left">
                <th className="px-3 py-2 w-8">#</th>
                <th className="px-3 py-2">Player</th>
                <th className="px-3 py-2">Pos</th>
                <th className="px-3 py-2">ADP Delta</th>
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
                    key={rec.player_id}
                    className={`border-t border-sleeper-gray-700 ${isTop ? 'border-l-2 border-l-green-500' : ''} hover:bg-sleeper-gray-800/50`}
                  >
                    <td className="px-3 py-2 text-sleeper-gray-400 font-mono">{rank}</td>
                    <td className="px-3 py-2 text-white font-medium">
                      <div className="flex items-center gap-2">
                        <PlayerHeadshot
                          playerId={rec.player_id}
                          playerName={rec.player_name}
                          position={rec.position}
                        />
                        <span>{formatPlayerName(rec.player_name)}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <span className={`px-2 py-0.5 rounded text-xs font-semibold ${POSITION_COLORS[rec.position] ?? 'bg-sleeper-gray-700 text-sleeper-gray-300'}`}>
                        {rec.position}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <ADPBadge adpDelta={rec.adp_delta} adpPpr={rec.adp_ppr} />
                    </td>
                    <td className="px-3 py-2">
                      <VORBadge vorScore={rec.vor_score} interpretation={rec.interpretation} />
                    </td>
                    <td className="px-3 py-2 text-sleeper-gray-300">
                      {rec.projected_points != null ? rec.projected_points.toFixed(1) : '—'}
                    </td>
                    <td className="px-3 py-2 text-sleeper-gray-300">
                      {rec.avg_ppg != null ? rec.avg_ppg.toFixed(1) : '—'}
                    </td>
                    <td className="px-3 py-2 text-sleeper-gray-400 text-xs hidden sm:table-cell">{rec.interpretation}</td>
                  </tr>
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
