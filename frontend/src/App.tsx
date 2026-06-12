import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Landing from './pages/Landing'
import BrandPipeline from './pages/BrandPipeline'
import ContentCreator from './pages/ContentCreator'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/build" element={<BrandPipeline />} />
        <Route path="/content" element={<ContentCreator />} />
      </Routes>
    </BrowserRouter>
  )
}