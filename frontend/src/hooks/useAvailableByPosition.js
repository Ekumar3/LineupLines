import { useState, useEffect, useRef } from 'react';
import { draftAPI } from '../utils/api';

export const useAvailableByPosition = (draftId, limit = 20) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastPolled, setLastPolled] = useState(null);
  const initialLoadDone = useRef(false);
  const prevDataJson = useRef(null);
  const inFlight = useRef(false);

  useEffect(() => {
    let cancelled = false;

    const fetchAvailable = async () => {
      if (inFlight.current) return; // skip if previous request still pending
      inFlight.current = true;
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
        setLastPolled(new Date());
        initialLoadDone.current = true;
        setError(null);
      } catch (err) {
        if (cancelled) return;
        // Don't overwrite data on transient errors — just update lastPolled
        if (initialLoadDone.current) {
          console.warn('[useAvailableByPosition] Poll failed, keeping stale data:', err.message);
        } else {
          setError(err.message || 'Failed to fetch available players');
          setData(null);
        }
      } finally {
        inFlight.current = false;
        if (!cancelled) setLoading(false);
      }
    };

    if (draftId) {
      fetchAvailable();

      // Poll every 10 seconds as a fallback in case SSE events are missed
      const pollInterval = setInterval(() => fetchAvailable(), 10000);

      const es = new EventSource(`/api/v1/drafts/${draftId}/stream`);
      es.addEventListener('pick', () => fetchAvailable());
      es.addEventListener('status', (e) => {
        try {
          const { status } = JSON.parse(e.data);
          if (status === 'complete') {
            es.close();
            clearInterval(pollInterval);
          }
        } catch (_) {}
        fetchAvailable();
      });
      es.onerror = () => {
        console.warn('[useAvailableByPosition] SSE connection error, will reconnect');
      };

      return () => {
        cancelled = true;
        es.close();
        clearInterval(pollInterval);
      };
    }
  }, [draftId, limit]);

  return { data, loading, error, lastPolled };
};
