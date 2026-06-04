/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        /* AESTHETIKON Brand Palette */
        brand: {
          navy: {
            50: '#e8edf4',
            100: '#c5d0e3',
            200: '#9fb0d0',
            300: '#7990bd',
            400: '#5c78ae',
            500: '#3f60a0',
            600: '#344f8a',
            700: '#2a3e70',
            800: '#1f2e56',
            900: '#0f1a33',  /* Deep Navy — primary dark */
            950: '#080e1c',
          },
          gold: {
            50: '#fdf8ef',
            100: '#f9edcf',
            200: '#f4dba0',
            300: '#efc871',
            400: '#e8b44e',
            500: '#d4a03a',  /* Signature Gold */
            600: '#b8862e',
            700: '#966b24',
            800: '#75521c',
            900: '#543b14',
          },
          ivory: {
            50: '#fefdfb',
            100: '#fdf9f3',
            200: '#faf3e7',
            300: '#f5ead6',
            400: '#f0e0c4',
            500: '#e8d3ad',
            600: '#d4b88a',
            700: '#b89a6a',
            800: '#8c744e',
            900: '#5e4f34',
          },
          charcoal: {
            50: '#f5f5f5',
            100: '#e5e5e5',
            200: '#cccccc',
            300: '#a3a3a3',
            400: '#737373',
            500: '#525252',
            600: '#3a3a3a',  /* Charcoal — body text */
            700: '#2c2c2c',
            800: '#1f1f1f',
            900: '#141414',
          },
          blush: {
            50: '#fdf5f5',
            100: '#fbe8e8',
            200: '#f7d1d1',
            300: '#f0afaf',
            400: '#e68d8d',
            500: '#d4716a',  /* Blush — warm accent */
            600: '#b85a54',
            700: '#964640',
            800: '#753430',
            900: '#542421',
          },
        },
        /* Keep primary/accent as aliases for Tailwind classes */
        primary: {
          50: '#e8edf4',
          100: '#c5d0e3',
          200: '#9fb0d0',
          300: '#7990bd',
          400: '#5c78ae',
          500: '#3f60a0',
          600: '#344f8a',
          700: '#2a3e70',
          800: '#1f2e56',
          900: '#0f1a33',
          950: '#080e1c',
        },
        accent: {
          50: '#fdf8ef',
          100: '#f9edcf',
          200: '#f4dba0',
          300: '#efc871',
          400: '#e8b44e',
          500: '#d4a03a',
          600: '#b8862e',
          700: '#966b24',
          800: '#75521c',
          900: '#543b14',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        display: ['Playfair Display', 'Georgia', 'serif'],
        accent: ['Cormorant Garamond', 'Georgia', 'serif'],
      },
      fontSize: {
        'display-xl': ['4.5rem', { lineHeight: '1.05', letterSpacing: '-0.02em' }],
        'display-lg': ['3.5rem', { lineHeight: '1.1', letterSpacing: '-0.015em' }],
        'display-md': ['2.5rem', { lineHeight: '1.15', letterSpacing: '-0.01em' }],
      },
      letterSpacing: {
        'luxury': '0.15em',
        'luxury-wide': '0.25em',
      },
      animation: {
        'fade-in': 'fadeIn 0.8s ease-out forwards',
        'fade-in-slow': 'fadeIn 1.4s ease-out forwards',
        'slide-up': 'slideUp 0.6s ease-out forwards',
        'slide-up-slow': 'slideUp 1s ease-out forwards',
        'float': 'float 6s ease-in-out infinite',
        'pulse-slow': 'pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'shimmer': 'shimmer 2.5s ease-in-out infinite',
        'scale-in': 'scaleIn 0.5s ease-out forwards',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(30px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-20px)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        scaleIn: {
          '0%': { opacity: '0', transform: 'scale(0.95)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
      },
      backgroundImage: {
        'gradient-luxury': 'linear-gradient(135deg, #0f1a33 0%, #1f2e56 50%, #2a3e70 100%)',
        'gradient-gold': 'linear-gradient(135deg, #d4a03a 0%, #e8b44e 50%, #d4a03a 100%)',
        'gradient-ivory': 'linear-gradient(180deg, #fefdfb 0%, #faf3e7 100%)',
        'gradient-shimmer': 'linear-gradient(90deg, transparent 0%, rgba(212,160,58,0.15) 50%, transparent 100%)',
      },
      boxShadow: {
        'luxury': '0 20px 60px -15px rgba(15, 26, 51, 0.25)',
        'luxury-lg': '0 30px 80px -20px rgba(15, 26, 51, 0.35)',
        'gold-glow': '0 0 30px rgba(212, 160, 58, 0.2)',
        'gold-glow-lg': '0 0 60px rgba(212, 160, 58, 0.3)',
      },
      borderRadius: {
        '4xl': '2rem',
      },
    },
  },
  plugins: [],
};
