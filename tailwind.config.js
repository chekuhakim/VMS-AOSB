/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./accounts/**/*.py",
    "./core/**/*.py",
    "./documents/**/*.py",
    "./envelope1/**/*.py",
    "./staff/**/*.py",
    "./tenders/**/*.py",
    "./vendors/**/*.py",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#FF6F00",
          50: "#FFF4EB",
          100: "#FFE8D6",
          600: "#FF6F00",
          700: "#E65100",
        },
        cream: { DEFAULT: "#FAF7F2" },
        peach: { DEFAULT: "#FFE8D6" },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
