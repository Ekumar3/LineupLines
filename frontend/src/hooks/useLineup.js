import { useState, useEffect, useCallback, useRef } from 'react';
import { inSeasonAPI } from '../utils/api';

const POLL_MS = 60_000;

// What the displayed lineup was built from. When any part changes (a new week,
// regenerated projections, refreshed Vegas lines) the lineup is stale.
const statusKey = (s) =>
  s
    ? [s.season, s.week, s.scoring_format, s.projection_generated_at, s.odds_fetched_at].join('|')
    : null;

function describeError(err) {
  const detail = err.response?.data?.detail;
  const pending = err.response?.status === 503;
  return {
    pending,
    message: pending
      ? 'Projections for this week are still being prepared. This page will update on its own when they are ready.'
      : detail || err.message || 'Failed to load lineup recommendations.',
  };
}

/**
 * Loads start/sit recommendations for a roster and keeps them current.
 *
 * Polls the lightweight /status endpoint every minute (and whenever the tab
 * becomes visible again). When the projection or odds timestamps change, the
 * lineup is reloaded in the background without blanking the screen. If the
 * first load fails because projections aren't ready (503), the same polling
 * retries until they are.
 */
export default function useLineup(leagueId, userId) {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const loadedKey = useRef(null); // status key the visible lineup was built from
  const requestId = useRef(0); // lets a newer request supersede an older one
  const hasData = useRef(false);

  const load = useCallback(
    async ({ silent = false } = {}) => {
      const id = ++requestId.current;
      if (silent) setRefreshing(true);
      else setLoading(true);

      try {
        // Status first, so the key we record matches (or predates) the data.
        const latestStatus = await inSeasonAPI.getStatus(leagueId).catch(() => null);
        const recommendations = await inSeasonAPI.getRecommendations(leagueId, userId);
        if (id !== requestId.current) return;

        setData(recommendations);
        hasData.current = true;
        setError(null);
        if (latestStatus) setStatus(latestStatus);
        loadedKey.current = statusKey(latestStatus);
      } catch (err) {
        if (id !== requestId.current) return;
        // A failed background refresh keeps the lineup already on screen.
        if (!hasData.current) setError(describeError(err));
      } finally {
        if (id === requestId.current) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [leagueId, userId]
  );

  // Initial load (and reload when switching leagues).
  useEffect(() => {
    hasData.current = false;
    loadedKey.current = null;
    load();
  }, [load]);

  // Watch for new data.
  useEffect(() => {
    const poll = async () => {
      try {
        const latest = await inSeasonAPI.getStatus(leagueId);
        setStatus(latest);
        if (statusKey(latest) !== loadedKey.current) load({ silent: true });
      } catch {
        // Transient (server restarting, offline). Try again next tick.
      }
    };

    const interval = setInterval(poll, POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === 'visible') poll();
    };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [leagueId, load]);

  return { data, status, loading, refreshing, error };
}
