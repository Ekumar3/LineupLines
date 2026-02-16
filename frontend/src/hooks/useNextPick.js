import { useState, useEffect } from 'react';
import { draftAPI } from '../utils/api';

export const useNextPick = (draftId, userId) => {
  const [nextPickNumber, setNextPickNumber] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const calculateNextPick = async () => {
      try {
        setLoading(true);

        // Get draft details and all picks
        const [draftDetails, picksData] = await Promise.all([
          draftAPI.getDraftDetails(draftId),
          draftAPI.getDraftPicks(draftId)
        ]);

        // Find user's draft slot
        const draftOrder = draftDetails.draft_order;
        const userSlot = draftOrder.findIndex(uid => uid === userId) + 1;

        // Calculate next pick based on snake draft logic
        const totalPicks = picksData.picks.length;
        const teams = draftDetails.settings.teams;
        const reversalRound = draftDetails.settings.reversal_round || 1;

        // Snake draft calculation
        let currentRound = Math.floor(totalPicks / teams) + 1;
        let isReversed = currentRound > reversalRound && currentRound % 2 === 0;

        let nextPick;
        if (isReversed) {
          nextPick = (currentRound - 1) * teams + (teams - userSlot + 1);
        } else {
          nextPick = (currentRound - 1) * teams + userSlot;
        }

        setNextPickNumber(nextPick);
        setError(null);
      } catch (err) {
        console.error('Failed to calculate next pick:', err);
        setError(err.message || 'Failed to calculate next pick');
      } finally {
        setLoading(false);
      }
    };

    if (draftId && userId) {
      calculateNextPick();
    }
  }, [draftId, userId]);

  return { nextPickNumber, loading, error };
};
