import { useState, useEffect } from 'react';
import { draftAPI } from '../utils/api';

export const useRosterData = (draftId, userId) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchRoster = async () => {
      try {
        setLoading(true);

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
        setError(null);
      } catch (err) {
        setError(err.message || 'Failed to fetch roster');
        setData(null);
      } finally {
        setLoading(false);
      }
    };

    if (draftId && userId) {
      fetchRoster();
    }
  }, [draftId, userId]);

  return { data, loading, error };
};
