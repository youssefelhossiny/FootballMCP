/**
 * FPL Optimizer API Client
 * Handles all communication with the backend API
 */

const API_BASE = '/api'

/**
 * Fetch wrapper with error handling
 */
async function fetchAPI(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`

  try {
    const response = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers
      },
      ...options
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Request failed' }))
      throw new Error(error.detail || `HTTP ${response.status}`)
    }

    return await response.json()
  } catch (error) {
    console.error(`API Error (${endpoint}):`, error)
    throw error
  }
}

/**
 * Player endpoints
 */
export const playersAPI = {
  /**
   * Get all players with optional filters
   */
  getAll: (filters = {}) => {
    const params = new URLSearchParams()
    if (filters.position) params.append('position', filters.position)
    if (filters.minPrice) params.append('min_price', filters.minPrice)
    if (filters.maxPrice) params.append('max_price', filters.maxPrice)
    if (filters.team) params.append('team', filters.team)
    if (filters.limit) params.append('limit', filters.limit)

    const query = params.toString()
    return fetchAPI(`/players${query ? `?${query}` : ''}`)
  },

  /**
   * Get player by ID
   */
  getById: (id) => fetchAPI(`/players/${id}`)
}

/**
 * Team endpoints
 */
export const teamAPI = {
  /**
   * Get user's team by FPL team ID
   */
  getUserTeam: (teamId) => fetchAPI(`/team/${teamId}`),

  /**
   * Get bot's autonomous team
   */
  getBotTeam: () => fetchAPI('/bot/team')
}

/**
 * Optimal team endpoints
 */
export const optimalAPI = {
  /**
   * Get optimal wildcard team
   */
  getWildcard: () => fetchAPI('/optimal/wildcard'),

  /**
   * Get optimal free hit team
   */
  getFreehit: () => fetchAPI('/optimal/freehit')
}

/**
 * Chat endpoint
 */
export const chatAPI = {
  /**
   * Send message to chat assistant
   */
  sendMessage: (message, teamId = null, context = {}) => {
    return fetchAPI('/chat', {
      method: 'POST',
      body: JSON.stringify({
        message,
        team_id: teamId,
        context
      })
    })
  }
}

/**
 * Player detail (name-based) — powers the player profile slide-over.
 */
export const playerDetailAPI = {
  getByName: (name) => fetchAPI(`/player/${encodeURIComponent(name)}`)
}

/**
 * Bot endpoints (Stats page)
 */
export const botAPI = {
  getTeam: () => fetchAPI('/bot/team'),
  getDecision: () => fetchAPI('/bot/decision'),
  getPriceChanges: () => fetchAPI('/bot/price-changes')
}

/**
 * Season history — per-GW series for the Stats page.
 * Returns { gw, user, bot, avg, rankUser, rankBot, bench } aligned by gameweek.
 * `teamId` may be null (returns bot + field average only).
 */
export const historyAPI = {
  getSeries: (teamId) =>
    fetchAPI(`/history${teamId ? `/${teamId}` : ''}`)
}

/**
 * Health check
 */
export const healthAPI = {
  check: () => fetchAPI('/health')
}

export default {
  players: playersAPI,
  playerDetail: playerDetailAPI,
  team: teamAPI,
  bot: botAPI,
  history: historyAPI,
  optimal: optimalAPI,
  chat: chatAPI,
  health: healthAPI
}
