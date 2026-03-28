import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { draftAPI } from '../utils/api';
import LoadingSpinner from '../components/common/LoadingSpinner';

export default function Home() {
  const [username, setUsername] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [draftsData, setDraftsData] = useState(null);
  const [userData, setUserData] = useState(null);
  
  const navigate = useNavigate();

  // Load from local storage on mount
  useEffect(() => {
    const savedUsername = localStorage.getItem('sleeper_username');
    if (savedUsername) {
      setUsername(savedUsername);
      fetchDrafts(savedUsername);
    }
  }, []);

  const fetchDrafts = async (uname) => {
    if (!uname) return;
    setLoading(true);
    setError(null);
    try {
      const [userRes, draftsRes] = await Promise.all([
        draftAPI.lookupUser(uname).catch(() => null), // Ignore lookup failure if drafts succeed
        draftAPI.getUserDrafts(uname)
      ]);
      setUserData(userRes);
      setDraftsData(draftsRes);
      // Only save to local storage if the fetch is successful
      localStorage.setItem('sleeper_username', uname);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to find user or drafts.');
      setDraftsData(null);
      setUserData(null);
      // Don't clear local storage on network errors, just in case
      if (err.response?.status === 404) {
        localStorage.removeItem('sleeper_username');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (username.trim()) {
      fetchDrafts(username.trim());
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('sleeper_username');
    setUsername('');
    setDraftsData(null);
    setUserData(null);
    setError(null);
  };

  const handleDraftClick = (draftId, userId) => {
    navigate(`/roster/${draftId}/${userId}`);
  };

  const avatarUrl = userData?.avatar 
    ? `https://sleepercdn.com/avatars/${userData.avatar}` 
    : null;

  return (
    <div className="min-h-screen bg-sleeper-darker py-8 px-4 sm:px-6 lg:px-8 font-sans">
      <div className="max-w-4xl mx-auto">
        <div className="text-center mb-12">
          <h1 className="text-4xl font-extrabold text-white tracking-tight mb-4">LineupLines</h1>
          <p className="text-sleeper-gray-400 text-lg max-w-xl mx-auto">
            Live fantasy football draft assistant with real-time ADP value tracking.
          </p>
        </div>

        {!draftsData && !loading && (
          <div className="bg-sleeper-dark rounded-xl border border-sleeper-gray-800 p-8 max-w-md mx-auto shadow-xl">
            <h2 className="text-xl font-semibold text-white mb-6 text-center">Enter your Sleeper Username</h2>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="e.g. ekumar3"
                  className="w-full bg-sleeper-gray-900 border border-sleeper-gray-700 rounded-lg px-4 py-3 text-white placeholder-sleeper-gray-500 focus:outline-none focus:border-sleeper-blue focus:ring-1 focus:ring-sleeper-blue transition-colors"
                  required
                />
              </div>
              <button
                type="submit"
                className="w-full bg-sleeper-blue hover:bg-[#00a3e0] text-white font-medium py-3 px-4 rounded-lg transition-colors shadow-[0_0_15px_rgba(0,186,255,0.2)] hover:shadow-[0_0_20px_rgba(0,186,255,0.4)]"
              >
                Find My Drafts
              </button>
            </form>
            {error && (
              <div className="mt-6 bg-sleeper-red/10 border border-sleeper-red/20 rounded-lg p-3">
                <p className="text-sleeper-red text-center text-sm">{error}</p>
              </div>
            )}
          </div>
        )}

        {loading && (
          <div className="flex flex-col items-center justify-center py-20 bg-sleeper-dark rounded-xl border border-sleeper-gray-800">
            <LoadingSpinner size="lg" />
            <p className="text-sleeper-gray-400 mt-6 font-medium tracking-wide">Fetching drafts from Sleeper...</p>
          </div>
        )}

        {draftsData && !loading && (
          <div className="space-y-6">
            <div className="flex flex-col sm:flex-row justify-between items-center bg-sleeper-dark p-4 sm:p-6 rounded-xl border border-sleeper-gray-800 shadow-sm gap-4">
              <div className="flex items-center gap-4">
                {avatarUrl ? (
                  <img 
                    src={avatarUrl} 
                    alt={username} 
                    className="w-12 h-12 rounded-full border border-sleeper-gray-700 shadow-lg object-cover bg-sleeper-gray-800"
                    onError={(e) => {
                      // Fallback to initials if image fails to load
                      e.target.onerror = null;
                      e.target.style.display = 'none';
                      e.target.nextSibling.style.display = 'flex';
                    }}
                  />
                ) : null}
                <div 
                  className={`w-12 h-12 bg-gradient-to-br from-sleeper-blue to-sleeper-purple rounded-full flex items-center justify-center text-white font-bold text-xl shadow-lg ${avatarUrl ? 'hidden' : ''}`}
                >
                  {username.charAt(0).toUpperCase()}
                </div>
                <div>
                  <h3 className="text-white font-semibold text-lg leading-tight">
                    {userData?.display_name || username}
                  </h3>
                  <p className="text-sleeper-gray-400 text-sm mt-0.5">{draftsData.total_drafts} Total Drafts</p>
                </div>
              </div>
              <button
                onClick={handleLogout}
                className="text-sm font-medium text-sleeper-gray-400 hover:text-white transition-colors px-4 py-2 rounded-lg border border-sleeper-gray-700 hover:bg-sleeper-gray-800 hover:border-sleeper-gray-600"
              >
                Change User
              </button>
            </div>

            <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
              {draftsData.drafts?.map((draft) => (
                <div
                  key={draft.draft_id}
                  onClick={() => handleDraftClick(draft.draft_id, draftsData.user_id)}
                  className="bg-sleeper-dark rounded-xl border border-sleeper-gray-800 p-5 cursor-pointer hover:border-sleeper-blue transition-all group relative overflow-hidden flex flex-col h-full"
                >
                  <div className="absolute top-0 left-0 w-1 h-full bg-sleeper-gray-800 group-hover:bg-sleeper-blue transition-colors" />
                  
                  <div className="flex justify-between items-start mb-4 pl-2">
                    <h4 className="text-white font-semibold text-lg group-hover:text-sleeper-blue transition-colors truncate pr-3 flex-1 flex items-center gap-2">
                      {draft.metadata?.league_type === "2" ? (
                        <span title="Dynasty" className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded bg-sleeper-blue/20 text-sleeper-blue text-xs font-bold border border-sleeper-blue/30">D</span>
                      ) : draft.metadata?.league_type === "1" ? (
                        <span title="Keeper" className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded bg-sleeper-purple/20 text-sleeper-purple text-xs font-bold border border-sleeper-purple/30">K</span>
                      ) : (
                        <span title="Redraft" className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded bg-sleeper-gray-800 text-sleeper-gray-400 text-xs font-bold border border-sleeper-gray-700">R</span>
                      )}
                      <span className="truncate">{draft.metadata?.name || 'Unnamed League'}</span>
                    </h4>
                  </div>
                  
                  <div className="space-y-3 pl-2 flex-grow">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-sleeper-gray-500">Status</span>
                      <span className={`px-2.5 py-1 rounded-md text-xs font-medium tracking-wide ${
                        ['drafting', 'in_progress'].includes(draft.status)
                          ? 'bg-sleeper-green/10 text-sleeper-green border border-sleeper-green/20'
                          : draft.status === 'pre_draft'
                          ? 'bg-sleeper-purple/10 text-sleeper-purple border border-sleeper-purple/20'
                          : 'bg-sleeper-gray-800 text-sleeper-gray-400 border border-sleeper-gray-700'
                      }`}>
                        {['drafting', 'in_progress'].includes(draft.status) ? 'LIVE DRAFT' : 
                         draft.status === 'pre_draft' ? 'PRE-DRAFT' : 'COMPLETED'}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-sm">
                      <span className="text-sleeper-gray-500">Teams</span>
                      <span className="text-sleeper-gray-300 font-medium">
                        {draft.settings?.teams} Team
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-sm">
                      <span className="text-sleeper-gray-500">Format</span>
                      <span className="text-sleeper-gray-300 font-medium">
                        {draft.metadata?.scoring_type?.toUpperCase() || 'PPR'} 
                        {draft.metadata?.te_premium ? ` TEP +${draft.metadata.te_premium}` : ''}
                        {draft.settings?.slots_super_flex > 0 ? ' SFX' : ''}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-sm">
                      <span className="text-sleeper-gray-500">Season</span>
                      <span className="text-sleeper-gray-300 font-medium">
                        {draft.season} {draft.sport.toUpperCase()}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
              
              {(!draftsData.drafts || draftsData.drafts.length === 0) && (
                <div className="col-span-full flex flex-col items-center justify-center py-16 bg-sleeper-dark rounded-xl border border-sleeper-gray-800 border-dashed">
                  <div className="w-16 h-16 bg-sleeper-gray-900 rounded-full flex items-center justify-center mb-4">
                    <span className="text-2xl">🏈</span>
                  </div>
                  <h3 className="text-white font-medium text-lg mb-2">No Drafts Found</h3>
                  <p className="text-sleeper-gray-400 text-center max-w-sm">
                    We couldn't find any drafts for this season. Make sure you've joined a league on Sleeper!
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
