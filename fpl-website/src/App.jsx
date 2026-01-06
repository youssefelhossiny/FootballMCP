import { BrowserRouter as Router, Routes, Route, NavLink } from 'react-router-dom'
import BotTeamPage from './pages/BotTeamPage'
import UserTeamPage from './pages/UserTeamPage'

/* ORIGINAL COLORS (to revert):
   - Main bg: bg-gradient-to-br from-purple-900 via-indigo-900 to-slate-900
   - Nav bg: bg-slate-800/50 border-b border-slate-700
   - Active nav: bg-purple-600 text-white
   - Inactive nav: text-slate-300 hover:bg-slate-700
*/

function App() {
  return (
    <Router>
      {/* Main container */}
      <div className="min-h-screen bg-gradient-to-br from-purple-900 via-indigo-900 to-slate-900">
        {/* Navigation */}
        <nav className="bg-slate-800/50 border-b border-slate-700">
          <div className="max-w-7xl mx-auto px-4">
            <div className="flex items-center justify-between h-16">
              <div className="flex items-center gap-2">
                <span className="text-2xl">⚽</span>
                <span className="text-xl font-bold text-white">FPL Optimizer</span>
              </div>
              <div className="flex gap-1">
                <NavLink
                  to="/"
                  className={({ isActive }) =>
                    `px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                      isActive
                        ? 'bg-purple-600 text-white'
                        : 'text-slate-300 hover:bg-slate-700'
                    }`
                  }
                >
                  Bot's Team
                </NavLink>
                <NavLink
                  to="/my-team"
                  className={({ isActive }) =>
                    `px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                      isActive
                        ? 'bg-purple-600 text-white'
                        : 'text-slate-300 hover:bg-slate-700'
                    }`
                  }
                >
                  My Team
                </NavLink>
              </div>
            </div>
          </div>
        </nav>

        {/* Main Content */}
        <main className="max-w-7xl mx-auto px-4 py-8">
          <Routes>
            <Route path="/" element={<BotTeamPage />} />
            <Route path="/my-team" element={<UserTeamPage />} />
          </Routes>
        </main>
      </div>
    </Router>
  )
}

export default App
