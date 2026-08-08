/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class', // Enables dark mode toggling via the 'dark' class on the <html> tag
  content: [
    "./app/templates/**/*.html",
    "./app/main.py",
  ],
  theme: {
    extend: {
      colors: {
        // Official GitHub Palette
        gh: {
          dark: {
            bg: '#0d1117',
            surface: '#161b22',
            border: '#30363d',
            text: '#c9d1d9',
            muted: '#8b949e',
            blue: '#58a6ff',
            green: '#238636',
            greenHover: '#2ea043',
            red: '#da3633',
          },
          light: {
            bg: '#ffffff',
            surface: '#f6f8fa',
            border: '#d0d7de',
            text: '#24292f',
            muted: '#57606a',
            blue: '#0969da',
            green: '#2da44e',
            greenHover: '#2c974b',
            red: '#cf222e',
          }
        }
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          '"Segoe UI"',
          'Helvetica',
          'Arial',
          'sans-serif',
          '"Apple Color Emoji"',
          '"Segoe UI Emoji"',
        ],
      },
    },
  },
  plugins: [],
}
