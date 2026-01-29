tailwind.config = {
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#772B21',
          dark: '#381811',
          light: '#CFE3DA',
          hover: '#381811'
        },
        background: '#FFF8F3',
        card: '#ffffff',
        foreground: '#221B19',
        muted: '#5a4f4c',
        border: '#e5dcd7',
        success: '#10b981',
        warning: '#f59e0b',
        danger: '#AC3631',
        svn: {
          brown: '#8b4513',
          orange: '#dc7f37',
          green: '#6b8e23'
        }
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif']
      },
      spacing: {
        'sidebar': '220px',
        'sidebar-collapsed': '70px',
        'topbar': '60px'
      },
      borderRadius: {
        'card': '16px',
        'btn': '8px',
        'input': '8px'
      },
      boxShadow: {
        'card': '0 2px 8px rgba(0, 0, 0, 0.08)',
        'card-hover': '0 4px 16px rgba(0, 0, 0, 0.12)',
        'modal': '0 20px 60px rgba(0, 0, 0, 0.3)'
      }
    }
  }
}
