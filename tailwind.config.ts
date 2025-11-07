import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "#0B0F14",
        accent: "#06B6D4",
        "ev-positive": "#16a34a",
        surface: "#111827"
      },
      borderRadius: {
        pill: "999px"
      }
    }
  },
  plugins: []
};

export default config;
