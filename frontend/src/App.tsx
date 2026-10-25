import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/layout/AppShell'
import ErrorBoundary from './components/ErrorBoundary'
import ImageGenerationPage from './pages/ImageGenerationPage'
import AgentPage from './pages/AgentPage'
import LabsPage from './pages/LabsPage'
import ConsolePage from './pages/ConsolePage'

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<AppShell />}>
            <Route index element={<Navigate to="/image" replace />} />
            <Route path="image" element={<ImageGenerationPage />} />
            <Route path="agent" element={<AgentPage />} />
            <Route path="labs" element={<LabsPage />} />
            <Route path="console" element={<ConsolePage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
