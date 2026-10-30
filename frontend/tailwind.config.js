/** Design tokens live here and in src/tokens.ts; both come from the design spec. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ground: "#F5F3EE",
        surface: "#FFFFFF",
        hairline: "#E2DED5",
        ink: "#1C1B19",
        muted: "#6B675F",
        accent: "#1F4E8C",
        verified: "#2E7D4F",
        rejected: "#B4402F",
        warning: "#A86A00",
      },
      fontFamily: {
        sans: ["IBM Plex Sans", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      borderRadius: { card: "12px", chip: "10px" },
      fontSize: {
        label: ["11px", { lineHeight: "16px", letterSpacing: "0.14em" }],
        body: ["13.5px", { lineHeight: "20px" }],
      },
      keyframes: {
        livedot: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.25" } },
        rise: { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: { livedot: "livedot 1.4s ease-in-out infinite", rise: "rise .25s ease-out both" },
    },
  },
  plugins: [],
};
