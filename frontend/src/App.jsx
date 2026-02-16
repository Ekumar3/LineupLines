import { BrowserRouter, Routes, Route, useParams } from 'react-router-dom';
import RosterView from './components/roster/RosterView';

function RosterPage() {
  const { draftId, userId } = useParams();
  return <RosterView draftId={draftId} userId={userId} />;
}

function HomePage() {
  return (
    <div className="min-h-screen bg-sleeper-darker py-8">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center py-12">
          <h1 className="text-4xl font-bold text-white mb-4">LineupLines</h1>
          <p className="text-sleeper-gray-400 text-lg mb-8">
            View your fantasy football roster with ADP analysis
          </p>
          <div className="bg-sleeper-dark rounded-lg border border-sleeper-gray-800 p-8 max-w-md mx-auto">
            <h2 className="text-xl font-semibold text-white mb-4">View Your Roster</h2>
            <p className="text-sleeper-gray-300 mb-6">
              Navigate to <code className="bg-sleeper-gray-900 px-2 py-1 rounded text-sleeper-blue">/roster/:draftId/:userId</code> to view a roster
            </p>
            <p className="text-sleeper-gray-400 text-sm">
              Example: <br/>
              <code className="bg-sleeper-gray-900 px-2 py-1 rounded text-sleeper-green text-xs">
                /roster/123abc/456def
              </code>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/roster/:draftId/:userId" element={<RosterPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
