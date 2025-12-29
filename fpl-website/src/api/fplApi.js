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
 * Health check
 */
export const healthAPI = {
  check: () => fetchAPI('/health')
}

export default {
  players: playersAPI,
  team: teamAPI,
  optimal: optimalAPI,
  chat: chatAPI,
  health: healthAPI
}
