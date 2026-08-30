import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // ApexLedger dark void palette (Cursor/Linear inspired)
        background: "#0c0d0e",
        foreground: "#e4e4e7",
        card: "#141516",
        "card-foreground": "#e4e4e7",
        border: "#27272a",
        input: "#27272a",
        ring: "#3b82f6",
        primary: {
          DEFAULT: "#3b82f6",
          foreground: "#ffffff",
        },
        secondary: {
          DEFAULT: "#1c1d1f",
          foreground: "#a1a1aa",
        },
        muted: {
          DEFAULT: "#1c1d1f",
          foreground: "#71717a",
        },
        accent: {
          DEFAULT: "#1c1d1f",
          foreground: "#e4e4e7",
        },
        destructive: {
          DEFAULT: "#ef4444",
          foreground: "#ffffff",
        },
        success: {
          DEFAULT: "#22c55e",
          foreground: "#ffffff",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "sans-serif",
        ],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
      borderRadius: {
        lg: "0.5rem",
        md: "0.375rem",
        sm: "0.25rem",
      },
    },
  },
  plugins: [],
};

export default config;
