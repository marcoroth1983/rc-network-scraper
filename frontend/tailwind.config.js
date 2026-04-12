/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'sans-serif'] },
      colors: {
        brand: { DEFAULT: '#2563EB', light: '#EFF6FF', dark: '#1D4ED8' },
        surface: '#F5F5F7',
        aurora: {
          deep: '#0f0f23',
          card: 'rgba(15, 15, 35, 0.6)',
          elevated: 'rgba(255, 255, 255, 0.05)',
          border: 'rgba(255, 255, 255, 0.08)',
          'border-hover': 'rgba(255, 255, 255, 0.15)',
          'text-primary': '#F8FAFC',
          'text-secondary': 'rgba(248, 250, 252, 0.65)',
          'text-muted': 'rgba(248, 250, 252, 0.35)',
          indigo: '#6366F1',
          violet: '#A78BFA',
          pink: '#EC4899',
          teal: '#2DD4BF',
          price: '#FDE68A',
          'badge-new': '#34D399',
          'glow-indigo': 'rgba(99, 102, 241, 0.15)',
        },
      },
      borderRadius: { card: '16px' },
      boxShadow: {
        card: '0 1px 3px rgba(0,0,0,.06), 0 4px 12px rgba(0,0,0,.05)',
        'card-hover': '0 4px 16px rgba(0,0,0,.10), 0 1px 4px rgba(0,0,0,.06)',
        'aurora-card': '0 0 60px rgba(99,102,241,0.06), 0 4px 16px rgba(0,0,0,0.2)',
        'aurora-hover': '0 0 30px rgba(99,102,241,0.12), 0 8px 24px rgba(0,0,0,0.25)',
      },
      animation: {
        'aurora-drift': 'aurora-drift 10s ease-in-out infinite alternate',
      },
      keyframes: {
        'aurora-drift': {
          '0%':   { transform: 'translateY(0) scale(1)',         opacity: '0.2' },
          '100%': { transform: 'translateY(-30px) scale(1.05)',  opacity: '0.12' },
        },
      },
    },
  },
  plugins: [],
};
