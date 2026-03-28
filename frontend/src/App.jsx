import { BrowserRouter, Routes, Route, useParams } from 'react-router-dom';
import RosterView from './components/roster/RosterView';
import Home from './pages/Home';

function RosterPage() {
  const { draftId, userId } = useParams();
  return <RosterView draftId={draftId} userId={userId} />;
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/roster/:draftId/:userId" element={<RosterPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
