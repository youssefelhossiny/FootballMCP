import { BrowserRouter as Router, Routes, Route, NavLink } from 'react-router-dom'
import BotTeamPage from './pages/BotTeamPage'
import UserTeamPage from './pages/UserTeamPage'
// StatsPage is built but not yet wired into the nav/routes — enable when ready.
// import StatsPage from './pages/StatsPage'

function App() {
  return (
    <Router>
      <div className="min-h-screen" style={{ background: 'var(--bg-base)' }}>
        {/* Top nav */}
        <nav className="sticky top-0 z-40 backdrop-blur-md" style={{ background: 'rgba(10, 15, 26, 0.85)', borderBottom: '1px solid var(--border-subtle)' }}>
          <div className="max-w-[1600px] mx-auto px-6">
            <div className="flex items-center justify-between h-14">
              <div className="flex items-center gap-3">
                <img src="/pl-lion.png" alt="Premier League" className="h-7 w-auto" />
                <div>
                  <div className="text-[15px] font-semibold text-primary leading-tight">FPL Optimizer</div>
                  <div className="text-[10px] text-muted leading-tight uppercase tracking-wider">AI transfer assistant</div>
                </div>
              </div>
              <div className="flex gap-1">
                <NavItem to="/">Bot's Team</NavItem>
                <NavItem to="/my-team">My Team</NavItem>
              </div>
            </div>
          </div>
        </nav>

        <main className="max-w-[1600px] mx-auto px-6 py-6">
          <Routes>
            <Route path="/" element={<BotTeamPage />} />
            <Route path="/my-team" element={<UserTeamPage />} />
            {/* <Route path="/stats" element={<StatsPage />} /> */}
          </Routes>
        </main>
      </div>
    </Router>
  )
}

function NavItem({ to, children }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `px-3.5 py-1.5 rounded-md text-sm font-medium transition-colors ${
          isActive
            ? 'text-white'
            : 'text-secondary hover:text-primary'
        }`
      }
      style={({ isActive }) =>
        isActive ? { background: 'var(--accent-primary-soft)', color: 'var(--accent-primary)' } : {}
      }
    >
      {children}
    </NavLink>
  )
}

export default App
