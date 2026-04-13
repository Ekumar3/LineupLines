import { useState, useEffect } from 'react';

/**
 * Hook to fetch VOR (Value Over Replacement) analysis for a draft.
 */
export function useVORAnalysis(draftId) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!draftId) {
      setLoading(false);
      return;
    }

    const fetchVOR = async () => {
      try {
        setLoading(true);
        setError(null);

        const response = await fetch(`/api/v1/draft/${draftId}/vor`);

        if (!response.ok) {
          throw new Error(`VOR API error: ${response.status}`);
        }

        const vorData = await response.json();
        setData(vorData);
      } catch (err) {
        console.error('Error fetching VOR:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchVOR();
  }, [draftId]);

  return { data, loading, error };
}
