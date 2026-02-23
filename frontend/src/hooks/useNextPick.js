import { useState, useEffect, useRef } from 'react';
import { draftAPI } from '../utils/api';

export const useNextPick = (draftId, userId) => {
  const [nextPickNumber, setNextPickNumber] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const initialLoadDone = useRef(false);

  useEffect(() => {
    const calculateNextPick = async () => {
      try {
        if (!initialLoadDone.current) setLoading(true);

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
        initialLoadDone.current = true;
        setError(null);
        console.log(`[useNextPick] Refreshed at ${new Date().toLocaleTimeString()} — next pick: #${nextPick}`);
      } catch (err) {
        console.error('Failed to calculate next pick:', err);
        setError(err.message || 'Failed to calculate next pick');
      } finally {
        setLoading(false);
      }
    };

    if (draftId && userId) {
      calculateNextPick();

      // Poll for updates every 5 seconds
      const interval = setInterval(calculateNextPick, 5000);

      // Cleanup interval on unmount or when dependencies change
      return () => clearInterval(interval);
    }
  }, [draftId, userId]);

  return { nextPickNumber, loading, error };
};
