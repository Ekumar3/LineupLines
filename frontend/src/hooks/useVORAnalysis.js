import { useState, useEffect, useRef } from 'react';

const POLL_INTERVAL = 5000;

/**
 * Hook to fetch VOR (Value Over Replacement) analysis for a draft.
 * Polls every 5 seconds to keep recommendations current as picks are made.
 */
export function useVORAnalysis(draftId) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const prevJson = useRef(null);

  useEffect(() => {
    if (!draftId) {
      setLoading(false);
      return;
    }

    const fetchVOR = async () => {
      try {
        const response = await fetch(`/api/v1/draft/${draftId}/vor`);

        if (!response.ok) {
          throw new Error(`VOR API error: ${response.status}`);
        }

        const vorData = await response.json();
        const json = JSON.stringify(vorData);

        // Only update state if data actually changed
        if (json !== prevJson.current) {
          prevJson.current = json;
          setData(vorData);
          console.log(`[VOR] Updated — ${vorData.recommendations?.length ?? 0} recommendations`);
        }

        setError(null);
      } catch (err) {
        console.error('Error fetching VOR:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchVOR();
    const interval = setInterval(fetchVOR, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [draftId]);

  return { data, loading, error };
}
