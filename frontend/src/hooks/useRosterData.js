import { useState, useEffect, useRef } from 'react';
import { draftAPI } from '../utils/api';

export const useRosterData = (draftId, userId) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const initialLoadDone = useRef(false);

  useEffect(() => {
    const fetchRoster = async () => {
      try {
        if (!initialLoadDone.current) setLoading(true);

        // Fetch both roster and picks data
        const [rosterData, picksData] = await Promise.all([
          draftAPI.getUserRoster(draftId, userId),
          draftAPI.getDraftPicks(draftId)
        ]);

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

        setData(enrichedRoster);
        initialLoadDone.current = true;
        setError(null);
        console.log(`[useRosterData] Refreshed at ${new Date().toLocaleTimeString()} — total picks: ${enrichedRoster.total_picks}`);
      } catch (err) {
        setError(err.message || 'Failed to fetch roster');
        setData(null);
      } finally {
        setLoading(false);
      }
    };

    if (draftId && userId) {
      fetchRoster();

      // Poll for updates every 5 seconds
      const interval = setInterval(fetchRoster, 5000);

      // Cleanup interval on unmount or when dependencies change
      return () => clearInterval(interval);
    }
  }, [draftId, userId]);

  return { data, loading, error };
};
