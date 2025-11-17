import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Bet365-inspired palette with dark purple/magenta gradient
        background: "#0A0E1A", // Very dark navy blue
        background2: "#1A0F2E", // Deep dark purple
        background3: "#2D1B3D", // Rich dark magenta/plum
        background4: "#3D1F4D", // Brighter dark magenta/fuchsia
        accent: "#00D084", // Bet365 green
        accentHover: "#00B875",
        accentDark: "#009966",
        surface: "#1A0F2E", // Deep dark purple
        surface2: "#2D1B3D", // Rich dark magenta
        border: "rgba(255, 255, 255, 0.1)",
        borderHover: "rgba(0, 208, 132, 0.3)",
        text: "#FFFFFF",
        textSecondary: "rgba(255, 255, 255, 0.7)",
        textMuted: "rgba(255, 255, 255, 0.5)",
        positive: "#00D084",
        negative: "#FF4444",
        warning: "#FFB800"
      }
    }
  },
  plugins: []
};

export default config;
