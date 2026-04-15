import { useState, useEffect, useRef } from 'react';
import { draftAPI } from '../utils/api';

export const useAvailableByPosition = (draftId, limit = 20) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const initialLoadDone = useRef(false);
  const prevDataJson = useRef(null);

  useEffect(() => {
    let cancelled = false;

    const fetchAvailable = async () => {
      try {
        if (!initialLoadDone.current) setLoading(true);
        const availableData = await draftAPI.getAvailableByPosition(draftId, limit);
        if (cancelled) return;
        const json = JSON.stringify(availableData);
        if (json !== prevDataJson.current) {
          prevDataJson.current = json;
          setData(availableData);
          console.log(`[useAvailableByPosition] Updated at ${new Date().toLocaleTimeString()} — current pick: #${availableData?.current_overall_pick}`);
        }
        initialLoadDone.current = true;
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err.message || 'Failed to fetch available players');
        setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    if (draftId) {
      fetchAvailable();

      // Poll for updates every 3 seconds
      const interval = setInterval(fetchAvailable, 3000);

      // Cleanup interval on unmount or when dependencies change
      return () => {
        cancelled = true;
        clearInterval(interval);
      };
    }
  }, [draftId, limit]);

  return { data, loading, error };
};
