import type { Config } from "tailwindcss";
import { tailwindPreset } from "@cisstat/ui";

const config: Config = {
  presets: [tailwindPreset as Config],
  content: [
    "./app/**/*.{ts,tsx}",
    "../../packages/ui/**/*.{ts,tsx}",
  ],
};

export default config;
