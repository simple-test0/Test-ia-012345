import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import AppShell from './components/layout/AppShell'
import ErrorBoundary from './components/ui/ErrorBoundary'

// Each page is its own chunk: the first screen loads faster and heavy
// dependencies (charts, markdown) are only fetched when needed.
const ImageGenerationPage = lazy(() => import('./pages/ImageGenerationPage'))
const AgentPage = lazy(() => import('./pages/AgentPage'))
const LabsPage = lazy(() => import('./pages/LabsPage'))

function PageLoader() {
  return (
    <div className="flex h-full items-center justify-center text-gray-500">
      <Loader2 className="h-6 w-6 animate-spin" />
    </div>
  )
}

const page = (el: JSX.Element) => (
  <ErrorBoundary>
    <Suspense fallback={<PageLoader />}>{el}</Suspense>
  </ErrorBoundary>
)

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<Navigate to="/image" replace />} />
          <Route path="image" element={page(<ImageGenerationPage />)} />
          <Route path="agent" element={page(<AgentPage />)} />
          <Route path="labs" element={page(<LabsPage />)} />
          <Route path="*" element={<Navigate to="/image" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
