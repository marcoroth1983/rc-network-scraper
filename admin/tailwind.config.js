import tailwindcssAnimate from 'tailwindcss-animate';

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'sans-serif'] },
      colors: {
        'bg-app': '#0D0D0D',
        'bg-sidebar': '#0A0A0A',
        surface: '#161616',
        'surface-2': '#1C1C1C',
        'surface-active': '#242424',
        border: '#262626',
        'text-primary': '#FAFAFA',
        'text-secondary': '#A1A1AA',
        'text-tertiary': '#6B6B70',
        primary: '#2E6BFF',
        success: '#3FD984',
        danger: '#F75555',
        warning: '#F5B544',
      },
      borderRadius: { shell: '24px', card: '16px', control: '12px', pill: '8px', icon: '10px' },
    },
  },
  plugins: [tailwindcssAnimate],
};
