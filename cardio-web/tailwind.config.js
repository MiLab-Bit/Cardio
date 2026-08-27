/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        parchment: '#f4ecd8',
        'parchment-deep': '#e8dcc0',
        ink: '#2b2118',
        'ink-soft': '#5a4a38',
        brass: '#b08d57',
        'brass-deep': '#8a6d3f',
        jade: '#3f7d6e',
        cinnabar: '#b5462f',
      },
      fontFamily: {
        serif: ['"Noto Serif SC"', 'Georgia', 'serif'],
        sans: ['"Noto Sans SC"', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        card: '0 8px 30px rgba(43, 33, 24, 0.10)',
      },
    },
  },
  plugins: [],
}
