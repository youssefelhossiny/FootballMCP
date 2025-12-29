import { useState } from 'react'

/**
 * AccessCodeModal - Gate access to the AI chatbot feature
 *
 * Users must enter a secret code (from the portfolio owner's resume)
 * to unlock the chatbot. This prevents API abuse while allowing
 * authorized viewers to test the feature.
 */
function AccessCodeModal({ onSuccess, onClose }) {
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()

    if (!code.trim()) {
      setError('Please enter the access code')
      return
    }

    setLoading(true)
    setError('')

    try {
      const response = await fetch('/api/auth/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: code.trim() })
      })

      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.detail || 'Invalid access code')
      }

      const data = await response.json()

      // Store the token in localStorage
      localStorage.setItem('fpl_access_token', data.access_token)

      // Notify parent component
      onSuccess()
    } catch (err) {
      setError(err.message || 'Invalid access code. Check the resume for the correct code!')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 border border-slate-700 p-6 sm:p-8 rounded-xl max-w-md w-full shadow-2xl">
        {/* Header */}
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 bg-purple-600/20 rounded-lg flex items-center justify-center">
            <svg
              className="w-5 h-5 text-purple-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
              />
            </svg>
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">AI Assistant Access</h2>
            <p className="text-slate-400 text-sm">Protected feature</p>
          </div>
        </div>

        {/* Description */}
        <p className="text-slate-300 mb-6 text-sm leading-relaxed">
          The AI chatbot is a protected feature to prevent API abuse.
          Enter the access code from my{' '}
          <span className="text-purple-400 font-medium">resume</span>{' '}
          to unlock full chatbot functionality.
        </p>

        {/* Form */}
        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label
              htmlFor="access-code"
              className="block text-sm font-medium text-slate-300 mb-2"
            >
              Access Code
            </label>
            <input
              id="access-code"
              type="password"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="Enter the code from my resume"
              autoFocus
              className="w-full px-4 py-3 bg-slate-700/60 border border-slate-600 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
            />
          </div>

          {/* Error message */}
          {error && (
            <div className="mb-4 px-4 py-3 bg-red-500/10 border border-red-500/30 rounded-lg">
              <p className="text-red-400 text-sm flex items-center gap-2">
                <svg className="w-4 h-4 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fillRule="evenodd"
                    d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z"
                    clipRule="evenodd"
                  />
                </svg>
                {error}
              </p>
            </div>
          )}

          {/* Buttons */}
          <div className="flex gap-3">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-3 bg-slate-700 hover:bg-slate-600 rounded-lg text-slate-300 font-medium transition-all"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 py-3 bg-purple-600 hover:bg-purple-500 disabled:bg-purple-600/50 disabled:cursor-not-allowed rounded-lg text-white font-semibold transition-all flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  Verifying...
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M8 11V7a4 4 0 118 0m-4 8v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z"
                    />
                  </svg>
                  Unlock Access
                </>
              )}
            </button>
          </div>
        </form>

        {/* Footer note */}
        <p className="mt-6 text-xs text-slate-500 text-center">
          This protects the AI feature from unauthorized use.
          <br />
          All other features work without authentication.
        </p>
      </div>
    </div>
  )
}

/**
 * Check if user has a valid access token
 */
export function hasValidToken() {
  const token = localStorage.getItem('fpl_access_token')
  if (!token) return false

  try {
    // Decode JWT to check expiration (simple check, server validates fully)
    const payload = JSON.parse(atob(token.split('.')[1]))
    const exp = payload.exp * 1000 // Convert to milliseconds
    return Date.now() < exp
  } catch {
    return false
  }
}

/**
 * Get the stored access token
 */
export function getAccessToken() {
  return localStorage.getItem('fpl_access_token')
}

/**
 * Clear the stored access token (logout)
 */
export function clearAccessToken() {
  localStorage.removeItem('fpl_access_token')
}

export default AccessCodeModal
