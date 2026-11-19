import axios from 'axios';

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  }
});

export const draftAPI = {
  // Look up user details (like avatar)
  lookupUser: async (username) => {
    const response = await api.get(`/users/lookup/${username}`);
    return response.data;
  },

  // Get user drafts
  getUserDrafts: async (username) => {
    const response = await api.get(`/users/${username}/drafts`);
    return response.data;
  },

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

  // Get league settings for scoring format (via draft)
  getDraftLeagueSettings: async (draftId) => {
    const response = await api.get(`/drafts/${draftId}/league-settings`);
    return response.data;
  },

  // Get league settings directly by league ID
  getLeagueSettings: async (leagueId) => {
    const response = await api.get(`/leagues/${leagueId}/settings`);
    return response.data;
  },

  // Get available players by position with ADP delta
  getAvailableByPosition: async (draftId, limit = 20, adpSource = 'sleeper') => {
    const response = await api.get(
      `/drafts/${draftId}/available-by-position?limit=${limit}&adp_source=${adpSource}`
    );
    return response.data;
  }
};

export const inSeasonAPI = {
  // Cheap freshness check: current week + when projections/odds last updated.
  getStatus: async (leagueId) => {
    const response = await api.get(`/in-season/${leagueId}/status`);
    return response.data;
  },

  // Start/sit recommendations for the user's roster. Computes the optimal
  // lineup server-side, so allow more time than the default 10s.
  getRecommendations: async (leagueId, userId) => {
    const response = await api.get(
      `/in-season/${leagueId}/${userId}/recommendations`,
      { timeout: 30000 }
    );
    return response.data;
  }
};

export default api;
