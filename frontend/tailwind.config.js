/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#080D18",
        sidebar: "#0B1220",
        surface: "#111B2B",
        raised: "#162235",
        line: "#263449",
        primary: { DEFAULT: "#3B82F6", hover: "#2563EB", soft: "rgba(59,130,246,0.14)" },
        accent: "#22D3EE",
        violet: "#8B5CF6",
        good: "#22C55E",
        warn: "#F59E0B",
        bad: "#EF4444",
        ink: "#F1F5F9",
        muted: "#94A3B8",
        faint: "#64748B",
      },
      fontFamily: {
        sans: ['"Inter Variable"', "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "Cascadia Code", "Consolas", "monospace"],
      },
      fontSize: { "2xs": ["0.6875rem", "1rem"] },
      boxShadow: { card: "0 1px 2px rgba(0,0,0,0.3)", pop: "0 12px 32px rgba(0,0,0,0.5)" },
      keyframes: {
        shimmer: { "0%": { opacity: 0.45 }, "50%": { opacity: 0.8 }, "100%": { opacity: 0.45 } },
        rise: { from: { opacity: 0, transform: "translateY(4px)" }, to: { opacity: 1, transform: "none" } },
      },
      animation: { shimmer: "shimmer 1.6s ease-in-out infinite", rise: "rise 160ms ease-out" },
    },
  },
  plugins: [],
};
