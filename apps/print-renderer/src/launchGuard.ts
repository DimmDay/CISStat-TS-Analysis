/** Own the browser process group BEFORE the Playwright handshake completes.
 * Playwright launch timeout can spend another 30s gracefully closing a cold
 * launch. The shell gate gives our deadline a PID even in that interval.
 * /tmp may be noexec: /bin/sh reads this script; it is never exec'd from tmpfs.
 */
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";
export interface LaunchGuard {
  directory: string;
  wrapper: string;
  cancel(): void;
  cleanup(): void;
}
export function createLaunchGuard(tmpDir: string): LaunchGuard {
  const directory = mkdtempSync(join(tmpDir, "cisstat-render-"));
  const pidPath = join(directory, "browser.pid");
  const pidPart = join(directory, "browser.pid.part");
  const cancelled = join(directory, "cancelled");
  const wrapper = join(directory, "launch.sh");
  const quote = (s: string) => "'" + s.replace(/'/g, "'\\''") + "'";
  writeFileSync(wrapper, `#!/bin/sh\nset -eu\nprintf '%s' "$$" > ${quote(pidPart)}\n/bin/mv -f ${quote(pidPart)} ${quote(pidPath)}\nif [ -f ${quote(cancelled)} ]; then exit 125; fi\nexec "$@"\n`, { mode: 0o600 });
  return {
    directory, wrapper,
    cancel() {
      // Gate first: a not-yet-spawned wrapper must never exec the browser.
      try { writeFileSync(cancelled, "cancelled", { mode: 0o600 }); } catch { /* already cleaned */ }
      try {
        const raw = readFileSync(pidPath, "utf8");
        if (/^[1-9][0-9]*$/.test(raw)) {
          // Playwright starts this shell as the browser group leader on Linux.
          process.kill(-Number(raw), "SIGKILL");
        }
      } catch { /* no child yet / group already reaped */ }
    },
    cleanup() { rmSync(directory, { recursive: true, force: true }); },
  };
}
