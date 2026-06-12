import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'

export default function Navbar() {
  const [scrolled, setScrolled] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const isLanding = location.pathname === '/'

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20)
    window.addEventListener('scroll', onScroll)
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <nav
      className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
        scrolled
          ? 'bg-cream/90 backdrop-blur-md border-b border-border'
          : 'bg-transparent'
      }`}
    >
      <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
        <img
          src="/logo.png"
          alt="BeyondX"
          onClick={() => navigate('/')}
          className="h-10 cursor-pointer object-contain"
        />

        {isLanding && (
          <div className="hidden md:flex items-center gap-8">
            <a href="#flows" className="text-sm text-muted hover:text-charcoal transition-colors">
              Services
            </a>
            <a href="#outputs" className="text-sm text-muted hover:text-charcoal transition-colors">
              What you get
            </a>
            <a href="#how-it-works" className="text-sm text-muted hover:text-charcoal transition-colors">
              How it works
            </a>
          </div>
        )}

        <button
          onClick={() => navigate('/build')}
          className="bg-coral hover:bg-coral-dark text-white text-sm font-medium px-5 py-2.5 rounded-full transition-colors duration-200"
        >
          Get started
        </button>
      </div>
    </nav>
  )
}