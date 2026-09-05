import type { Config } from "tailwindcss";
import tailwindPreset from "@cisstat/ui/tailwind-preset";

const config: Config = {
  presets: [tailwindPreset as Config],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "../../packages/ui/**/*.{ts,tsx}",
  ],
};

export default config;
