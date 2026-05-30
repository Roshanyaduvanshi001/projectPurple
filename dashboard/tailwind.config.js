/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        darkBg: "#0d1117",
        darkCard: "rgba(22, 27, 34, 0.6)",
        accentGreen: "#10b981",
        accentBlue: "#3b82f6",
        accentAmber: "#f59e0b",
        accentRed: "#ef4444",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
}
