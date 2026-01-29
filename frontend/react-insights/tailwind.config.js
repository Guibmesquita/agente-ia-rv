/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#772B21',
          dark: '#381811',
          light: '#CFE3DA',
        },
        background: '#FFF8F3',
        card: '#ffffff',
        foreground: '#221B19',
        muted: '#5a4f4c',
        border: '#e5dcd7',
        success: '#10b981',
        warning: '#f59e0b',
        danger: '#AC3631',
        'svn-brown': '#8b4513',
        'svn-orange': '#dc7f37',
        'svn-green': '#6b8e23',
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
      },
      borderRadius: {
        'card': '0.75rem',
        'btn': '0.5rem',
        'input': '0.375rem',
      },
      boxShadow: {
        'card': '0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)',
      },
    },
  },
  plugins: [],
}
