/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        sleeper: {
          darker: '#010409',
          dark: '#0d1117',
          gray: {
            50: '#f6f8fa',
            100: '#eaeef2',
            200: '#d0d7de',
            300: '#afb8c1',
            400: '#8c959f',
            500: '#6e7781',
            600: '#57606a',
            700: '#424a53',
            800: '#32383f',
            900: '#24292f',
          },
          blue: '#58a6ff',
          green: '#3fb950',
          red: '#f85149',
          purple: '#bc8cff',
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      }
    },
  },
  plugins: [],
}
