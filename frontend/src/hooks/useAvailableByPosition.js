import { useState, useEffect } from 'react';
import { draftAPI } from '../utils/api';

export const useAvailableByPosition = (draftId, limit = 20) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchAvailable = async () => {
      try {
        setLoading(true);
        const availableData = await draftAPI.getAvailableByPosition(draftId, limit);
        setData(availableData);
        setError(null);
      } catch (err) {
        setError(err.message || 'Failed to fetch available players');
        setData(null);
      } finally {
        setLoading(false);
      }
    };

    if (draftId) {
      fetchAvailable();
    }
  }, [draftId, limit]);

  return { data, loading, error };
};
