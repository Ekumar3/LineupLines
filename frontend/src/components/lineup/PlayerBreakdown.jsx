import MatchupBadge from './MatchupBadge';
import {
  MATCHUP_THRESHOLD,
  STAT_LABELS,
  formatMultiplier,
  formatPoints,
  formatSigned,
  formatStatValue,
  matchupTone,
} from '../../utils/lineupFormat';

const clampPercent = (value) => Math.max(0, Math.min(100, value));

function GradeBar({ label, value, barClass }) {
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs mb-1">
        <span className="text-sleeper-gray-300">{label}</span>
        <span className="text-white font-semibold tabular-nums">
          {typeof value === 'number' ? value.toFixed(0) : '–'}
          <span className="text-sleeper-gray-500 font-normal"> / 100</span>
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-sleeper-gray-800 overflow-hidden">
        {typeof value === 'number' && (
          <div className={`h-full rounded-full ${barClass}`} style={{ width: `${clampPercent(value)}%` }} />
        )}
      </div>
    </div>
  );
}

function DiffRow({ label, hint, value, strong = false }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-xs">
      <span className={strong ? 'text-white font-medium' : 'text-sleeper-gray-300'}>
        {label}
        {hint && <span className="text-sleeper-gray-500"> · {hint}</span>}
      </span>
      <span className={`tabular-nums font-semibold ${matchupTone(value)}`}>{formatSigned(value)}</span>
    </div>
  );
}

function Step({ title, note, delta, total }) {
  let deltaTone = 'text-sleeper-gray-400';
  if (typeof delta === 'number' && Number(delta.toFixed(1)) > 0) deltaTone = 'text-sleeper-green';
  if (typeof delta === 'number' && Number(delta.toFixed(1)) < 0) deltaTone = 'text-sleeper-red';

  return (
    <li className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="text-sm text-white">{title}</div>
        {note && <div className="text-[11px] text-sleeper-gray-400 mt-0.5 leading-snug">{note}</div>}
      </div>
      <div className="text-right flex-shrink-0">
        <div className="text-sm font-semibold text-white tabular-nums">{formatPoints(total)}</div>
        {typeof delta === 'number' && (
          <div className={`text-xs tabular-nums ${deltaTone}`}>{formatSigned(delta)}</div>
        )}
      </div>
    </li>
  );
}

function MatchupSection({ team, opponent, grade }) {
  return (
    <section>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-white">Matchup</h3>
        <MatchupBadge grade={grade} />
      </div>

      <div className="space-y-2.5">
        <GradeBar label={`${team} offensive line`} value={grade.ol_grade} barClass="bg-sleeper-blue" />
        <GradeBar label={`${opponent} defensive line`} value={grade.dl_grade} barClass="bg-sleeper-purple" />
      </div>
      <p className="text-[11px] text-sleeper-gray-500 mt-1">Grades are 0–100; 50 is a league-average line.</p>

      <div className="mt-2.5 space-y-1 rounded-lg bg-sleeper-dark border border-sleeper-gray-800 px-3 py-2">
        <DiffRow label="Pass game" hint="protection vs pass rush" value={grade.pass_matchup} />
        <DiffRow label="Run game" hint="blocking vs run defense" value={grade.rush_matchup} />
        <DiffRow label="Overall" hint="OL minus DL" value={grade.overall_matchup} strong />
      </div>

      <p className="text-[11px] text-sleeper-gray-500 mt-2 leading-snug">
        Positive favors {team}. Favorable above +{MATCHUP_THRESHOLD}, Tough below −{MATCHUP_THRESHOLD}.
        This label is context only; it doesn&apos;t change the projection.
      </p>
    </section>
  );
}

function VegasNote({ team, detail }) {
  const { implied_team_total: implied, trailing_implied_total: usual, env_multiplier: mult } = detail;

  if (typeof implied !== 'number' || typeof usual !== 'number') {
    return 'No Vegas line is available for this game, so there is no adjustment.';
  }
  return (
    `Vegas has ${team} at ${implied.toFixed(1)} points vs their usual ${usual.toFixed(1)}, ` +
    `so ${formatMultiplier(mult)} (range ×0.75 – ×1.25).`
  );
}

function ProjectionSection({ team, opponent, detail, scoringLabel }) {
  const { baseline_points: baseline, defense_adjusted_points: adjusted, projected_points: projected } = detail;
  const hasSteps = typeof baseline === 'number' && typeof adjusted === 'number';

  return (
    <section>
      <div className="flex items-baseline justify-between mb-2">
        <h3 className="text-sm font-semibold text-white">Projection</h3>
        <span className="text-xs text-sleeper-gray-400">
          <span className="text-white font-semibold text-sm tabular-nums">{formatPoints(projected)}</span> pts
          {scoringLabel ? ` · ${scoringLabel}` : ''}
        </span>
      </div>

      {hasSteps && (
        <ol className="space-y-2.5">
          <Step
            title="Recent form"
            note="Average of his last 3 games; touchdowns pulled toward the position norm."
            total={baseline}
          />
          <Step
            title={`Against ${opponent || 'this'} defense`}
            note={
              `Pass ${formatMultiplier(detail.pass_factor)} · Run ${formatMultiplier(detail.rush_factor)} ` +
              '(above ×1.00 = allows more than average).'
            }
            delta={adjusted - baseline}
            total={adjusted}
          />
          <Step
            title="Vegas game environment"
            note={<VegasNote team={team} detail={detail} />}
            delta={projected - adjusted}
            total={projected}
          />
        </ol>
      )}

      {detail.stats.length > 0 && (
        <div className={hasSteps ? 'mt-3' : ''}>
          <h4 className="text-[11px] font-semibold uppercase tracking-wider text-sleeper-gray-500 mb-1">
            Where the points come from
          </h4>
          <table className="w-full text-xs">
            <tbody>
              {detail.stats.map((s) => (
                <tr key={s.stat} className="border-t border-sleeper-gray-800 first:border-t-0">
                  <td className="py-1 text-sleeper-gray-300">{STAT_LABELS[s.stat] || s.stat}</td>
                  <td className="py-1 text-right text-sleeper-gray-400 tabular-nums">
                    {formatStatValue(s.stat, s.value)}
                  </td>
                  <td
                    className={`py-1 pl-4 text-right font-semibold tabular-nums ${
                      s.points < 0 ? 'text-sleeper-red' : 'text-white'
                    }`}
                  >
                    {formatSigned(s.points)}
                  </td>
                </tr>
              ))}
              <tr className="border-t border-sleeper-gray-700">
                <td className="pt-1.5 text-white font-medium" colSpan={2}>Total</td>
                <td className="pt-1.5 pl-4 text-right text-white font-semibold tabular-nums">
                  {formatPoints(projected)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// The hover card for a lineup row: why the matchup label is what it is, then
// how the projected points were built. Either half is skipped when its data
// isn't there (no grade for the team, or a projection file from before the
// breakdown columns existed).
export default function PlayerBreakdown({ rec, showMatchup, scoringLabel }) {
  const grade = showMatchup ? rec.matchup_grade : null;
  const detail = rec.projection_detail;
  const opponent = detail?.opponent || rec.matchup_grade?.opponent;

  const both = !!grade && !!detail;

  return (
    <div>
      <div className="mb-3 flex items-baseline gap-2">
        <span className="text-white font-semibold">{rec.player_name}</span>
        <span className="text-xs text-sleeper-gray-400">
          {rec.team}
          {opponent ? ` vs ${opponent}` : ''}
        </span>
      </div>

      {/* Side by side on wide screens so the card stays short; stacked on phones. */}
      <div className={both ? 'grid gap-4 sm:grid-cols-2 sm:gap-0' : ''}>
        {grade && (
          <div className={both ? 'sm:pr-4 sm:border-r sm:border-sleeper-gray-800' : ''}>
            <MatchupSection team={rec.team} opponent={opponent} grade={grade} />
          </div>
        )}
        {detail && (
          <div className={both ? 'pt-4 border-t border-sleeper-gray-800 sm:pt-0 sm:border-t-0 sm:pl-4' : ''}>
            <ProjectionSection team={rec.team} opponent={opponent} detail={detail} scoringLabel={scoringLabel} />
          </div>
        )}
      </div>
    </div>
  );
}
