import { useState, useRef, useEffect } from 'react'
import AccessCodeModal, { hasValidToken, getAccessToken, clearAccessToken } from './AccessCodeModal'

// Simple markdown renderer for chat messages
function renderMarkdown(text) {
  if (!text) return null

  // Split into lines for processing
  const lines = text.split('\n')
  const elements = []
  let currentList = []
  let listType = null // 'ul' or 'ol'

  const flushList = () => {
    if (currentList.length > 0) {
      if (listType === 'ol') {
        elements.push(
          <ol key={`ol-${elements.length}`} className="list-decimal list-inside space-y-1 my-2">
            {currentList}
          </ol>
        )
      } else {
        elements.push(
          <ul key={`ul-${elements.length}`} className="list-disc list-inside space-y-1 my-2">
            {currentList}
          </ul>
        )
      }
      currentList = []
      listType = null
    }
  }

  lines.forEach((line, idx) => {
    // Check for bullet points (*, -, •)
    const bulletMatch = line.match(/^[\s]*[*\-•]\s+(.+)$/)
    // Check for numbered lists
    const numberedMatch = line.match(/^[\s]*(\d+)[.)]\s+(.+)$/)

    if (bulletMatch) {
      if (listType !== 'ul') {
        flushList()
        listType = 'ul'
      }
      currentList.push(
        <li key={`li-${idx}`} className="text-slate-200">
          {formatInlineMarkdown(bulletMatch[1])}
        </li>
      )
    } else if (numberedMatch) {
      if (listType !== 'ol') {
        flushList()
        listType = 'ol'
      }
      currentList.push(
        <li key={`li-${idx}`} className="text-slate-200">
          {formatInlineMarkdown(numberedMatch[2])}
        </li>
      )
    } else {
      flushList()

      // Check for headers
      const h3Match = line.match(/^###\s+(.+)$/)
      const h2Match = line.match(/^##\s+(.+)$/)
      const h1Match = line.match(/^#\s+(.+)$/)

      if (h1Match) {
        elements.push(
          <h3 key={`h1-${idx}`} className="text-lg font-bold text-white mt-3 mb-1">
            {formatInlineMarkdown(h1Match[1])}
          </h3>
        )
      } else if (h2Match) {
        elements.push(
          <h4 key={`h2-${idx}`} className="text-base font-semibold text-white mt-2 mb-1">
            {formatInlineMarkdown(h2Match[1])}
          </h4>
        )
      } else if (h3Match) {
        elements.push(
          <h5 key={`h3-${idx}`} className="text-sm font-semibold text-slate-200 mt-2 mb-1">
            {formatInlineMarkdown(h3Match[1])}
          </h5>
        )
      } else if (line.trim() === '') {
        // Empty line - add spacing
        elements.push(<div key={`br-${idx}`} className="h-2" />)
      } else {
        // Regular paragraph
        elements.push(
          <p key={`p-${idx}`} className="text-slate-200 leading-relaxed">
            {formatInlineMarkdown(line)}
          </p>
        )
      }
    }
  })

  flushList() // Flush any remaining list items

  return <div className="space-y-1">{elements}</div>
}

// Format inline markdown (bold, italic, code)
function formatInlineMarkdown(text) {
  if (!text) return text

  const parts = []
  let remaining = text
  let keyIndex = 0

  // Process the text for **bold**, *italic*, and `code`
  const regex = /(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)/g
  let lastIndex = 0
  let match

  while ((match = regex.exec(remaining)) !== null) {
    // Add text before the match
    if (match.index > lastIndex) {
      parts.push(remaining.slice(lastIndex, match.index))
    }

    if (match[2]) {
      // Bold **text**
      parts.push(
        <strong key={`b-${keyIndex++}`} className="font-semibold text-white">
          {match[2]}
        </strong>
      )
    } else if (match[3]) {
      // Italic *text*
      parts.push(
        <em key={`i-${keyIndex++}`} className="italic text-slate-300">
          {match[3]}
        </em>
      )
    } else if (match[4]) {
      // Code `text`
      parts.push(
        <code key={`c-${keyIndex++}`} className="bg-slate-600 px-1 py-0.5 rounded text-purple-300 text-xs">
          {match[4]}
        </code>
      )
    }

    lastIndex = regex.lastIndex
  }

  // Add remaining text
  if (lastIndex < remaining.length) {
    parts.push(remaining.slice(lastIndex))
  }

  return parts.length > 0 ? parts : text
}

// NOTE: Text-based transfer extraction has been removed
// Transfers are now ONLY applied when Claude explicitly calls the make_transfer tool
// This prevents false positives from parsing suggestion text as actual transfers

function ChatInterface({ teamId, team, onTransferSuggestion, freeTransfers = 1, availableChips = {}, activeChip = null, suggestedTransfers = [] }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: 'Hello! I can help you analyze your FPL team. Ask me about:\n\n• Transfer recommendations\n• Captain picks\n• Player comparisons\n• Fixture analysis\n• xG and advanced stats'
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [isAuthenticated, setIsAuthenticated] = useState(hasValidToken())
  const [showAuthModal, setShowAuthModal] = useState(false)
  const messagesContainerRef = useRef(null)

  // Check auth status on mount
  useEffect(() => {
    setIsAuthenticated(hasValidToken())
  }, [])

  const scrollToBottom = () => {
    // Scroll within the chat container, not the page
    if (messagesContainerRef.current) {
      messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight
    }
  }

  useEffect(() => {
    // Small delay to ensure content is rendered before scrolling
    setTimeout(scrollToBottom, 50)
  }, [messages])

  const sendMessage = async (e) => {
    e.preventDefault()
    if (!input.trim() || loading) return

    // Check if authenticated before sending
    if (!hasValidToken()) {
      setShowAuthModal(true)
      return
    }

    const userMessage = input.trim()
    setInput('')

    // Get current messages before adding the new one (for history)
    const currentMessages = [...messages]

    setMessages(prev => [...prev, { role: 'user', content: userMessage }])
    setLoading(true)

    try {
      const token = getAccessToken()
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': token ? `Bearer ${token}` : ''
        },
        body: JSON.stringify({
          message: userMessage,
          team_id: teamId,
          context: {
            team_name: team?.team_name,
            players: team?.players?.map(p => p.web_name || p.name),
            free_transfers: freeTransfers - suggestedTransfers.length, // Subtract transfers already made
            available_chips: Object.entries(availableChips)
              .filter(([_, available]) => available)
              .map(([chip]) => chip),
            active_chip: activeChip,
            // Include transfers already made in theoretical lineup
            transfers_made: suggestedTransfers.map(t => ({
              out: t.out?.web_name || t.out?.name,
              in: t.in?.web_name || t.in?.name
            }))
          },
          // Send conversation history for context continuity
          history: currentMessages.map(m => ({ role: m.role, content: m.content }))
        })
      })

      // Handle auth errors
      if (response.status === 401) {
        clearAccessToken()
        setIsAuthenticated(false)
        setShowAuthModal(true)
        setLoading(false)
        setMessages(prev => prev.slice(0, -1)) // Remove the user message we just added
        return
      }

      if (!response.ok) throw new Error('Chat request failed')

      const data = await response.json()
      setMessages(prev => [...prev, { role: 'assistant', content: data.response }])

      // Handle transfers from API response ONLY when make_transfer tool is explicitly used
      // This prevents false positives from text parsing - transfers only happen when user confirms
      if (onTransferSuggestion && data.transfers && data.transfers.length > 0) {
        // API returned explicit transfers from Claude's make_transfer tool calls
        const apiTransfers = data.transfers.map(t => ({
          out: { name: t.player_out },
          in: { name: t.player_in },
          reason: t.reason
        }))
        onTransferSuggestion(apiTransfers)
      }
      // NOTE: Removed text-based transfer extraction fallback to prevent false positives
      // Transfers should ONLY be applied when Claude explicitly calls the make_transfer tool
    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
        isError: true
      }])
    } finally {
      setLoading(false)
    }
  }

  const quickQuestions = [
    'Who should I captain?',
    'Best transfer this week?',
    'Suggest transfers for my team',
    'Fixture difficulty?'
  ]

  // Handle successful authentication
  const handleAuthSuccess = () => {
    setIsAuthenticated(true)
    setShowAuthModal(false)
  }

  return (
    <>
      {/* Access Code Modal */}
      {showAuthModal && (
        <AccessCodeModal
          onSuccess={handleAuthSuccess}
          onClose={() => setShowAuthModal(false)}
        />
      )}

      <div className="bg-slate-800/50 rounded-lg flex flex-col h-[690px]">
        {/* Auth Status Indicator */}
        {!isAuthenticated && (
          <div className="px-4 py-2 bg-amber-500/10 border-b border-amber-500/30">
            <div className="flex items-center justify-between">
              <p className="text-amber-400 text-xs flex items-center gap-2">
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd" />
                </svg>
                Access code required for AI chat
              </p>
              <button
                onClick={() => setShowAuthModal(true)}
                className="text-xs px-3 py-1 bg-amber-500/20 hover:bg-amber-500/30 text-amber-400 rounded-full transition-all"
              >
                Enter Code
              </button>
            </div>
          </div>
        )}

        {/* Messages Area - scrollable within container */}
        <div
          ref={messagesContainerRef}
          className="flex-1 overflow-y-auto p-4 space-y-4"
        >
        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] rounded-lg px-4 py-3 ${
                msg.role === 'user'
                  ? 'bg-purple-600 text-white'
                  : msg.isError
                    ? 'bg-red-500/20 text-red-300 border border-red-500'
                    : 'bg-slate-700/80 text-slate-100'
              }`}
            >
              {msg.role === 'user' ? (
                <div className="text-sm">{msg.content}</div>
              ) : (
                <div className="text-sm">{renderMarkdown(msg.content)}</div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-slate-700/80 rounded-lg px-4 py-3">
              <div className="flex gap-1.5 items-center">
                <span className="w-2 h-2 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></span>
                <span className="w-2 h-2 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></span>
                <span className="w-2 h-2 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></span>
                <span className="text-slate-400 text-xs ml-2">Analyzing...</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Quick Questions */}
      <div className="px-4 py-2 border-t border-slate-700/50 bg-slate-800/30">
        <div className="flex flex-wrap gap-2">
          {quickQuestions.map((q, idx) => (
            <button
              key={idx}
              onClick={() => setInput(q)}
              className="text-xs px-3 py-1.5 bg-slate-700/60 hover:bg-purple-600/40 text-slate-300 hover:text-white rounded-full transition-all border border-slate-600/50 hover:border-purple-500/50"
            >
              {q}
            </button>
          ))}
        </div>
      </div>

      {/* Input Area */}
      <form onSubmit={sendMessage} className="p-4 border-t border-slate-700/50 bg-slate-800/30">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about your team..."
            disabled={loading}
            className="flex-1 px-4 py-2.5 bg-slate-700/60 border border-slate-600/50 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500/50 disabled:opacity-50 transition-all"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="px-5 py-2.5 bg-purple-600 hover:bg-purple-500 disabled:bg-slate-600 disabled:cursor-not-allowed rounded-lg text-white font-medium transition-all shadow-lg shadow-purple-900/20"
          >
            Send
          </button>
        </div>
      </form>
      </div>
    </>
  )
}

export default ChatInterface
