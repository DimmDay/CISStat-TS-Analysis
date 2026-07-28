import path from "path";
import type { Config } from "tailwindcss";
import tailwindPreset from "@cisstat/ui/tailwind-preset";

const config: Config = {
  presets: [tailwindPreset as Config],
  content: [
    path.resolve(__dirname, "app/**/*.{ts,tsx}"),
    path.resolve(__dirname, "../../packages/ui/**/*.{ts,tsx}"),
  ],
};

export default config;