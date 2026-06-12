/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        cream: '#FAF9F6',
        'cream-dark': '#F0EDE6',
        charcoal: '#1A1A18',
        'charcoal-soft': '#2C2C29',
        muted: '#6B6B67',
        border: '#E2DED8',
        coral: '#FF4D2E',
        'coral-dark': '#E63D1F',
      },
      fontFamily: {
        display: ['Syne', 'sans-serif'],
        body: ['Inter', 'sans-serif'],
      },
      letterSpacing: {
        tighter: '-0.04em',
        tight: '-0.025em',
      },
    },
  },
  plugins: [],
}