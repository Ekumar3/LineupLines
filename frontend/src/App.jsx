import { BrowserRouter, Routes, Route, useParams } from 'react-router-dom';
import RosterView from './components/roster/RosterView';
import RosterPage from './pages/RosterPage';
import Home from './pages/Home';

function DraftAssistPage() {
  const { draftId, userId } = useParams();
  return <RosterView draftId={draftId} userId={userId} />;
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/draftassist/:draftId/:userId" element={<DraftAssistPage />} />
        <Route path="/roster/:leagueId/:userId" element={<RosterPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
