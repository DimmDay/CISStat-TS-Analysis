import type { Config } from "tailwindcss";
import tailwindPreset from "@cisstat/ui/tailwind-preset";
import path from "path";

const configDir = (() => {
  try { return path.dirname(decodeURIComponent(new URL(import.meta.url).pathname)); }
  catch { return typeof __dirname !== "undefined" ? __dirname : process.cwd(); }
})();

console.error("TW_CONFIG_DIR:", configDir);

const config: Config = {
  presets: [tailwindPreset as Config],
  content: [
    path.resolve(configDir, "app/**/*.{ts,tsx}"),
    path.resolve(configDir, "../../packages/ui/**/*.{ts,tsx}"),
  ],
};

export default config;
