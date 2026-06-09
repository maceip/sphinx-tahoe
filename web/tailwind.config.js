/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0a0b0f",
        fg: "#e7eaf2",
        panel: "#12141c",
        panel2: "#171a24",
        line: "#252a38",
        mute: "#8b93a7",
        accent: "#5eead4",
        accent2: "#7c9cff",
        warn: "#fbbf24",
        danger: "#fb7185",
        good: "#34d399",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      keyframes: {
        pulseline: {
          "0%,100%": { opacity: "0.4" },
          "50%": { opacity: "1" },
        },
      },
      animation: { pulseline: "pulseline 1.4s ease-in-out infinite" },
    },
  },
  plugins: [],
};
