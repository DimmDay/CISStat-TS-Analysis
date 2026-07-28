import path from "path";
import type { Config } from "tailwindcss";
import tailwindPreset from "@cisstat/ui/tailwind-preset";

const config: Config = {
  presets: [tailwindPreset as Config],
  content: [
    path.resolve(process.cwd(), "app/**/*.{ts,tsx}"),
    path.resolve(process.cwd(), "../../packages/ui/**/*.{ts,tsx}"),
  ],
};

export default config;