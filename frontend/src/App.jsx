import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, useParams, useLocation } from 'react-router-dom';
import RosterView from './components/roster/RosterView';
import RosterPage from './pages/RosterPage';
import Home from './pages/Home';
import FeedbackWidget from './components/common/FeedbackWidget';
import { trackEvent } from './utils/analytics';

function DraftAssistPage() {
  const { draftId, userId } = useParams();
  return <RosterView draftId={draftId} userId={userId} />;
}

function PageViewTracker() {
  const location = useLocation();
  useEffect(() => {
    trackEvent('page_view');
  }, [location.pathname]);
  return null;
}

function App() {
  return (
    <BrowserRouter>
      <PageViewTracker />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/draftassist/:draftId/:userId" element={<DraftAssistPage />} />
        <Route path="/roster/:leagueId/:userId" element={<RosterPage />} />
      </Routes>
      {/* Feedback widget floats over every page */}
      <FeedbackWidget />
    </BrowserRouter>
  );
}

export default App;
