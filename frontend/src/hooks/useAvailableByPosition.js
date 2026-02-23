import { useState, useEffect, useRef } from 'react';
import { draftAPI } from '../utils/api';

export const useAvailableByPosition = (draftId, limit = 20) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const initialLoadDone = useRef(false);

  useEffect(() => {
    const fetchAvailable = async () => {
      try {
        if (!initialLoadDone.current) setLoading(true);
        const availableData = await draftAPI.getAvailableByPosition(draftId, limit);
        setData(availableData);
        initialLoadDone.current = true;
        setError(null);
        console.log(`[useAvailableByPosition] Refreshed at ${new Date().toLocaleTimeString()} — current pick: #${availableData?.current_overall_pick}`);
      } catch (err) {
        setError(err.message || 'Failed to fetch available players');
        setData(null);
      } finally {
        setLoading(false);
      }
    };

    if (draftId) {
      fetchAvailable();

      // Poll for updates every 5 seconds
      const interval = setInterval(fetchAvailable, 5000);

      // Cleanup interval on unmount or when dependencies change
      return () => clearInterval(interval);
    }
  }, [draftId, limit]);

  return { data, loading, error };
};
