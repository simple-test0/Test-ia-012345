import { Component, ErrorInfo, ReactNode } from 'react'
import { AlertTriangle, RotateCw } from 'lucide-react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/**
 * Catches render-time crashes so an error in one view degrades to a recovery
 * panel instead of unmounting the whole app to a blank/black screen.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('Unhandled UI error:', error, info)
  }

  handleReset = () => this.setState({ error: null })

  render() {
    if (!this.state.error) return this.props.children

    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-gray-950 p-6 text-center">
        <AlertTriangle className="h-10 w-10 text-amber-400" />
        <div>
          <h1 className="text-sm font-semibold text-gray-200">Une erreur est survenue</h1>
          <p className="mt-1 max-w-md text-xs text-gray-500">
            L'interface a rencontré un problème. Vous pouvez réessayer sans perdre l'application.
          </p>
        </div>
        <pre className="max-w-md overflow-auto rounded-lg border border-gray-800 bg-gray-900 p-3 text-left text-[11px] text-red-400">
          {this.state.error.message}
        </pre>
        <button
          onClick={this.handleReset}
          className="flex items-center gap-1.5 rounded-lg bg-purple-600 px-3 py-2 text-xs font-medium text-white hover:bg-purple-500"
        >
          <RotateCw className="h-3.5 w-3.5" /> Réessayer
        </button>
      </div>
    )
  }
}
