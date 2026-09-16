/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        void: "#12142B",
        panel: "#1B1E3D",
        panel2: "#20244A",
        ink: "#EDEAE0",
        "ink-muted": "#8B8FA8",
        marigold: "#F2A93B",
        "marigold-dim": "#B87F28",
        sindoor: "#C1443A",
        line: "rgba(237,234,224,0.12)",
      },
      fontFamily: {
        display: ["var(--font-fraunces)", "serif"],
        body: ["var(--font-plex)", "sans-serif"],
      },
    },
  },
  plugins: [],
};
