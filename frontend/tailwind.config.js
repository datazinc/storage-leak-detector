/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        slate: {
          950: "#0f1117",
          900: "#1a1d28",
          850: "#1e2230",
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
