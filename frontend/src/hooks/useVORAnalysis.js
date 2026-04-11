import { useState, useEffect } from 'react';

/**
 * Hook to fetch VOR (Value Over Replacement) analysis for a draft.
 * 
 * Usage:
 *   const { data, loading, error } = useVORAnalysis(draftId);
 * 
 * Returns:
 *   - data.recommendations: Array of top VOR picks (top 5 per position)
 *   - data.top_value_pick: Single best recommendation
 *   - data.replacement_level_by_position: Baseline ADP for each position
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

        const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
        const response = await fetch(`${apiUrl}/api/v1/draft/${draftId}/vor`);

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
