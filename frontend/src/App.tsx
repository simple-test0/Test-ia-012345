import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/layout/AppShell'
import ImageGenerationPage from './pages/ImageGenerationPage'
import AgentPage from './pages/AgentPage'
import LabsPage from './pages/LabsPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<Navigate to="/image" replace />} />
          <Route path="image" element={<ImageGenerationPage />} />
          <Route path="agent" element={<AgentPage />} />
          <Route path="labs" element={<LabsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
