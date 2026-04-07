/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'sans-serif'] },
      colors: {
        brand: { DEFAULT: '#2563EB', light: '#EFF6FF', dark: '#1D4ED8' },
        surface: '#F5F5F7',
      },
      borderRadius: { card: '16px' },
      boxShadow: {
        card: '0 1px 3px rgba(0,0,0,.06), 0 4px 12px rgba(0,0,0,.05)',
        'card-hover': '0 4px 16px rgba(0,0,0,.10), 0 1px 4px rgba(0,0,0,.06)',
      },
    },
  },
  plugins: [],
};
