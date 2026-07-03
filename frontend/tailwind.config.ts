import type { Config } from 'tailwindcss'

// Every palette below resolves to CSS variables defined in src/index.css, so
// the whole app re-skins itself when [data-theme] flips between the dark
// "instrument" theme and the light "atelier" theme.
const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`

const steps = (family: string, list: number[]) =>
  Object.fromEntries(list.map((s) => [s, v(`${family}-${s}`)]))

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    fontFamily: {
      sans: ['"Space Grotesk"', 'system-ui', 'Segoe UI', 'sans-serif'],
      mono: ['"IBM Plex Mono"', 'Consolas', 'monospace'],
    },
    borderRadius: {
      none: '0',
      sm: '2px',
      DEFAULT: '3px',
      md: '4px',
      lg: '5px',
      xl: '6px',
      '2xl': '8px',
      full: '9999px',
    },
    extend: {
      colors: {
        // "white" is the on-accent text color: ink on amber (dark theme),
        // paper on vermillon (light theme).
        white: v('tw-white'),
        gray: steps('gray', [100, 200, 300, 400, 500, 600, 700, 800, 900, 950]),
        purple: steps('purple', [200, 300, 400, 500, 600, 900]),
        green: steps('green', [200, 300, 400, 500]),
        red: steps('red', [200, 300, 400, 500, 600, 900]),
        yellow: steps('yellow', [300, 400, 500]),
        blue: steps('blue', [300, 400, 500]),
        amber: steps('amber', [300, 400, 500]),
        emerald: { 400: v('emerald-400') },
      },
    },
  },
  plugins: [],
} satisfies Config
