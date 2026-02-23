import axios from 'axios';

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  }
});

export const draftAPI = {
  // Get user roster grouped by position
  getUserRoster: async (draftId, userId) => {
    const response = await api.get(`/drafts/${draftId}/users/${userId}/roster`);
    return response.data;
  },

  // Get draft details for next pick calculation
  getDraftDetails: async (draftId) => {
    const response = await api.get(`/drafts/${draftId}`);
    return response.data;
  },

  // Get all picks for ADP analysis
  getDraftPicks: async (draftId) => {
    const response = await api.get(`/drafts/${draftId}/picks`);
    return response.data;
  },

  // Get league settings for scoring format
  getLeagueSettings: async (leagueId) => {
    const response = await api.get(`/leagues/${leagueId}/settings`);
    return response.data;
  },

  // Get available players by position with ADP delta
  getAvailableByPosition: async (draftId, limit = 20) => {
    const response = await api.get(
      `/drafts/${draftId}/available-by-position?limit=${limit}`
    );
    return response.data;
  }
};

export default api;
