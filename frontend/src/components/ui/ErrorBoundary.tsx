import { Component, type ReactNode } from 'react'
import { AlertTriangle, RotateCcw } from 'lucide-react'

interface State {
  error: Error | null
}

/** Shows a recoverable message instead of a blank screen when a page crashes. */
export default class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error) {
    console.error('Page crashed:', error)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    // A new deployment renamed the page chunks: a reload fetches the new ones.
    const staleChunk = /dynamically imported module|Loading chunk|Importing a module script/i.test(
      error.message,
    )
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <AlertTriangle className="h-8 w-8 text-amber-400" />
        <p className="text-sm text-gray-300">
          {staleChunk ? "L'application a été mise à jour." : 'Cette page a rencontré une erreur.'}
        </p>
        {!staleChunk && <p className="max-w-md text-xs text-gray-500 break-words">{error.message}</p>}
        <button
          onClick={() => (staleChunk ? window.location.reload() : this.setState({ error: null }))}
          className="flex items-center gap-1.5 rounded-lg bg-purple-600 px-3 py-2 text-xs font-medium text-white hover:bg-purple-500"
        >
          <RotateCcw className="h-3.5 w-3.5" /> {staleChunk ? 'Recharger' : 'Réessayer'}
        </button>
      </div>
    )
  }
}
