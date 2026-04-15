import { useState, useEffect, useRef } from 'react';
import { draftAPI } from '../utils/api';

export const useRosterData = (draftId, userId) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastPolled, setLastPolled] = useState(null);
  const initialLoadDone = useRef(false);
  const prevDataJson = useRef(null);
  const inFlight = useRef(false);

  useEffect(() => {
    let cancelled = false;

    const fetchRoster = async () => {
      if (inFlight.current) return; // skip if previous request still pending
      inFlight.current = true;
      try {
        if (!initialLoadDone.current) setLoading(true);

        // Fetch both roster and picks data
        const [rosterData, picksData] = await Promise.all([
          draftAPI.getUserRoster(draftId, userId),
          draftAPI.getDraftPicks(draftId)
        ]);

        if (cancelled) return;

        // Create a map of picks by player_id for quick lookup
        const picksByPlayerId = {};
        if (picksData.picks) {
          picksData.picks.forEach(pick => {
            picksByPlayerId[pick.player_id] = {
              adp_ppr: pick.adp_ppr,
              adp_delta: pick.adp_delta
            };
          });
        }

        // Enrich roster data with ADP information
        const enrichedRoster = { ...rosterData };
        if (enrichedRoster.roster_by_position) {
          Object.keys(enrichedRoster.roster_by_position).forEach(position => {
            enrichedRoster.roster_by_position[position] = enrichedRoster.roster_by_position[position].map(player => ({
              ...player,
              adp_ppr: picksByPlayerId[player.player_id]?.adp_ppr || player.adp_ppr,
              adp_delta: picksByPlayerId[player.player_id]?.adp_delta || player.adp_delta
            }));
          });
        }

        const json = JSON.stringify(enrichedRoster);
        if (json !== prevDataJson.current) {
          prevDataJson.current = json;
          setData(enrichedRoster);
          console.log(`[useRosterData] Updated at ${new Date().toLocaleTimeString()} — total picks: ${enrichedRoster.total_picks}`);
        }
        setLastPolled(new Date());
        initialLoadDone.current = true;
        setError(null);
      } catch (err) {
        if (cancelled) return;
        // Treat 404 as "no picks yet" — return empty roster so the page still renders
        if (err.response?.status === 404) {
          const emptyRoster = {
            draft_id: draftId,
            user_id: userId,
            draft_slot: 0,
            total_picks: 0,
            roster_by_position: { QB: [], RB: [], WR: [], TE: [], K: [], DEF: [] },
            position_summary: {},
          };
          setData(emptyRoster);
          setError(null);
          initialLoadDone.current = true;
        } else if (initialLoadDone.current) {
          console.warn('[useRosterData] Poll failed, keeping stale data:', err.message);
        } else {
          setError(err.message || 'Failed to fetch roster');
          setData(null);
        }
      } finally {
        inFlight.current = false;
        if (!cancelled) setLoading(false);
      }
    };

    if (draftId && userId) {
      fetchRoster();

      const interval = setInterval(fetchRoster, 5000);

      return () => {
        cancelled = true;
        clearInterval(interval);
      };
    }
  }, [draftId, userId]);

  return { data, loading, error, lastPolled };
};
