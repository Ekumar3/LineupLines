import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { draftAPI } from '../utils/api';
import LoadingSpinner from '../components/common/LoadingSpinner';
import ErrorMessage from '../components/common/ErrorMessage';

const POSITION_LABELS = {
  QB: 'Quarterback',
  RB: 'Running Back',
  WR: 'Wide Receiver',
  TE: 'Tight End',
  K: 'Kicker',
  DEF: 'Defense',
  FLEX: 'Flex (RB/WR/TE)',
  SUPER_FLEX: 'Super Flex (QB/RB/WR/TE)',
  REC_FLEX: 'Rec Flex (WR/TE)',
  IDP_FLEX: 'IDP Flex',
  BN: 'Bench',
  DL: 'Defensive Line',
  LB: 'Linebacker',
  DB: 'Defensive Back',
};

const POSITION_COLORS = {
  QB: 'text-red-400 bg-red-400/10 border-red-400/20',
  RB: 'text-green-400 bg-green-400/10 border-green-400/20',
  WR: 'text-blue-400 bg-blue-400/10 border-blue-400/20',
  TE: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20',
  K: 'text-purple-400 bg-purple-400/10 border-purple-400/20',
  DEF: 'text-orange-400 bg-orange-400/10 border-orange-400/20',
  FLEX: 'text-pink-400 bg-pink-400/10 border-pink-400/20',
  SUPER_FLEX: 'text-cyan-400 bg-cyan-400/10 border-cyan-400/20',
  REC_FLEX: 'text-indigo-400 bg-indigo-400/10 border-indigo-400/20',
  BN: 'text-sleeper-gray-400 bg-sleeper-gray-800 border-sleeper-gray-700',
};

export default function RosterPage() {
  const { leagueId, userId } = useParams();
  const navigate = useNavigate();
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchSettings = async () => {
      try {
        const data = await draftAPI.getLeagueSettings(leagueId);
        setSettings(data);
      } catch (err) {
        setError(err.response?.data?.detail || err.message || 'Failed to load league settings');
      } finally {
        setLoading(false);
      }
    };
    fetchSettings();
  }, [leagueId]);

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error} />;
  if (!settings) return null;

  const starters = settings.roster_positions?.filter(pos => pos !== 'BN') || [];
  const benchCount = settings.roster_positions?.filter(pos => pos === 'BN').length || 0;

  // Group starters by position for summary
  const starterCounts = {};
  starters.forEach(pos => {
    starterCounts[pos] = (starterCounts[pos] || 0) + 1;
  });

  return (
    <div className="min-h-screen bg-sleeper-darker py-8">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="mb-8">
          <button
            onClick={() => navigate('/')}
            className="text-sleeper-gray-400 hover:text-white text-sm mb-4 flex items-center gap-1 transition-colors"
          >
            &larr; Back to Leagues
          </button>
          <h1 className="text-3xl font-bold text-white mb-2">Starting Lineup</h1>
          <div className="flex gap-4 text-sleeper-gray-400 flex-wrap text-sm">
            <span>{settings.total_rosters} Teams</span>
            <span>{settings.scoring_format?.toUpperCase()}</span>
            <span>{starters.length} Starters + {benchCount} Bench</span>
          </div>
        </div>

        {/* Starting Lineup Slots */}
        <div className="bg-sleeper-dark rounded-xl border border-sleeper-gray-800 overflow-hidden">
          <div className="px-5 py-4 border-b border-sleeper-gray-800">
            <h2 className="text-white font-semibold text-lg">Roster Slots</h2>
          </div>
          <div className="divide-y divide-sleeper-gray-800">
            {starters.map((pos, idx) => {
              const colorClass = POSITION_COLORS[pos] || POSITION_COLORS.BN;
              return (
                <div key={idx} className="flex items-center px-5 py-3 hover:bg-sleeper-gray-900/50 transition-colors">
                  <span className={`inline-flex items-center justify-center w-16 px-2 py-1 rounded text-xs font-bold border ${colorClass}`}>
                    {pos}
                  </span>
                  <span className="ml-4 text-sleeper-gray-400 text-sm">
                    {POSITION_LABELS[pos] || pos}
                  </span>
                  <span className="ml-auto text-sleeper-gray-600 text-sm italic">
                    Empty
                  </span>
                </div>
              );
            })}
          </div>

          {/* Bench section */}
          {benchCount > 0 && (
            <>
              <div className="px-5 py-3 border-t border-sleeper-gray-700 bg-sleeper-gray-900/30">
                <span className="text-sleeper-gray-500 text-xs font-semibold uppercase tracking-wider">
                  Bench ({benchCount} slots)
                </span>
              </div>
              <div className="divide-y divide-sleeper-gray-800">
                {Array.from({ length: benchCount }).map((_, idx) => (
                  <div key={`bn-${idx}`} className="flex items-center px-5 py-3 hover:bg-sleeper-gray-900/50 transition-colors">
                    <span className={`inline-flex items-center justify-center w-16 px-2 py-1 rounded text-xs font-bold border ${POSITION_COLORS.BN}`}>
                      BN
                    </span>
                    <span className="ml-4 text-sleeper-gray-500 text-sm">Bench</span>
                    <span className="ml-auto text-sleeper-gray-600 text-sm italic">Empty</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Position Summary */}
        <div className="mt-6 bg-sleeper-dark rounded-xl border border-sleeper-gray-800 p-5">
          <h3 className="text-white font-semibold mb-4">Position Summary</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {Object.entries(starterCounts).map(([pos, count]) => {
              const colorClass = POSITION_COLORS[pos] || POSITION_COLORS.BN;
              return (
                <div key={pos} className={`rounded-lg border px-3 py-2 ${colorClass}`}>
                  <span className="font-bold text-sm">{pos}</span>
                  <span className="ml-2 text-xs opacity-75">x{count}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
