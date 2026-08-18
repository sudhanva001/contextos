/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#11141B",
          card: "#181C26",
          raised: "#1F2430",
          line: "#2A3040",
        },
        parchment: "#F4F1E8",
        gold: {
          DEFAULT: "#E7A94C",
          soft: "#F0C787",
          dim: "#9C7B44",
        },
        teal: {
          DEFAULT: "#5FB3AE",
          soft: "#8FCAC6",
        },
        text: {
          primary: "#E9E7E0",
          secondary: "#A7ADBD",
          muted: "#6B7180",
        },
      },
      fontFamily: {
        display: ["'Space Grotesk'", "sans-serif"],
        body: ["'Inter'", "sans-serif"],
        mono: ["'JetBrains Mono'", "monospace"],
      },
      borderRadius: {
        sm: "4px",
        md: "6px",
        lg: "10px",
      },
    },
  },
  plugins: [],
};
