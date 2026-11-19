import { useMemo } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import useLineup from '../hooks/useLineup';
import LoadingSpinner from '../components/common/LoadingSpinner';
import ErrorMessage from '../components/common/ErrorMessage';
import LineupRow from '../components/lineup/LineupRow';
import DataFreshness from '../components/lineup/DataFreshness';
import { formatPoints, slotRank } from '../utils/lineupFormat';

const FORMAT_LABELS = { ppr: 'PPR', half_ppr: 'Half PPR', standard: 'Standard' };

const byProjectedDesc = (a, b) => (b.projected_points ?? -1) - (a.projected_points ?? -1);

export default function LineupPage() {
  const { leagueId, userId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const leagueName = location.state?.leagueName;

  const { data, status, loading, refreshing, error } = useLineup(leagueId, userId);

  const { starters, bench, startersTotal, someUnprojected } = useMemo(() => {
    const recs = data?.recommendations ?? [];
    const starting = recs
      .filter((r) => r.recommendation === 'START')
      .sort((a, b) => slotRank(a.slot) - slotRank(b.slot) || byProjectedDesc(a, b));
    return {
      starters: starting,
      bench: recs.filter((r) => r.recommendation !== 'START').sort(byProjectedDesc),
      startersTotal: starting.reduce((sum, r) => sum + (r.projected_points ?? 0), 0),
      // K and DEF aren't projected by the model, so the total leaves them out.
      someUnprojected: starting.some((r) => r.projected_points == null),
    };
  }, [data]);

  const backButton = (
    <button
      onClick={() => navigate('/')}
      className="text-sleeper-gray-400 hover:text-white text-sm mb-4 flex items-center gap-1 transition-colors"
    >
      &larr; Back to Leagues
    </button>
  );

  if (loading && !data) return <LoadingSpinner />;

  if (error && !data) {
    // Projections not generated yet: not a failure, and the page keeps polling.
    if (error.pending) {
      return (
        <div className="min-h-screen bg-sleeper-darker py-8">
          <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
            {backButton}
            <div className="bg-sleeper-dark rounded-xl border border-sleeper-gray-800 border-dashed py-16 px-6 text-center">
              <div className="w-12 h-12 mx-auto mb-4 rounded-full border-2 border-sleeper-blue border-t-transparent animate-spin" />
              <h2 className="text-white font-semibold text-lg mb-2">Preparing this week&apos;s projections</h2>
              <p className="text-sleeper-gray-400 max-w-md mx-auto">{error.message}</p>
            </div>
          </div>
        </div>
      );
    }
    return <ErrorMessage message={error.message} />;
  }

  if (!data) return null;

  const formatLabel = FORMAT_LABELS[data.scoring_format] || data.scoring_format?.toUpperCase();

  return (
    <div className="min-h-screen bg-sleeper-darker py-8">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="mb-6">
          {backButton}
          <h1 className="text-3xl font-bold text-white mb-2">{leagueName || 'Your Lineup'}</h1>
          <div className="flex gap-x-4 gap-y-1 text-sleeper-gray-400 flex-wrap text-sm mb-3">
            <span>Week {data.week}</span>
            <span>{data.season}</span>
            <span>{formatLabel}</span>
          </div>
          <DataFreshness status={status} refreshing={refreshing} />
        </div>

        {!data.optimal_lineup_set && (
          <div className="mb-4 bg-yellow-400/10 border border-yellow-400/30 rounded-lg px-4 py-3 text-sm text-yellow-300">
            Not every starting slot could be filled with an eligible, healthy player.
          </div>
        )}

        {data.recommendations.length === 0 ? (
          <div className="bg-sleeper-dark rounded-xl border border-sleeper-gray-800 border-dashed py-16 text-center text-sleeper-gray-400">
            No players found on this roster.
          </div>
        ) : (
          <>
            <section className="bg-sleeper-dark rounded-xl border border-sleeper-gray-800 overflow-hidden">
              <div className="flex items-center justify-between px-4 sm:px-5 py-4 border-b border-sleeper-gray-800">
                <h2 className="text-white font-semibold text-lg">Start</h2>
                <span className="text-sm text-sleeper-gray-400">
                  Projected{' '}
                  <span className="text-white font-semibold tabular-nums">
                    {formatPoints(startersTotal)}
                  </span>{' '}
                  pts
                  {someUnprojected && (
                    <span className="text-sleeper-gray-500"> (excl. K/DEF)</span>
                  )}
                </span>
              </div>
              <div className="divide-y divide-sleeper-gray-800">
                {starters.map((rec) => (
                  <LineupRow key={rec.player_id} rec={rec} scoringLabel={formatLabel} />
                ))}
              </div>
            </section>

            {bench.length > 0 && (
              <section className="mt-6 bg-sleeper-dark rounded-xl border border-sleeper-gray-800 overflow-hidden">
                <div className="px-4 sm:px-5 py-4 border-b border-sleeper-gray-800">
                  <h2 className="text-white font-semibold text-lg">Sit</h2>
                </div>
                <div className="divide-y divide-sleeper-gray-800">
                  {bench.map((rec) => (
                    <LineupRow key={rec.player_id} rec={rec} scoringLabel={formatLabel} />
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
