/** Real subprocesses for cross-platform Jest. Missing prerequisites fail, never skip. */
import { execFileSync, spawnSync } from 'node:child_process';
import { win32 } from 'node:path';

interface ProbeResult {
  status: number | null;
  stdout?: string | null;
  stderr?: string | null;
  error?: Error;
}
interface Command { command: string; args: string[] }
export interface RuntimeOptions {
  platform?: NodeJS.Platform;
  // A test may intentionally provide only PATH. Next augments ProcessEnv
  // with a required NODE_ENV; tool discovery has no such requirement.
  env?: Record<string, string | undefined>;
  probe?: (command: string, args: string[]) => ProbeResult;
}

function envValue(env: Record<string, string | undefined>, key: string): string | undefined {
  return env[Object.keys(env).find(k => k.toLowerCase() === key.toLowerCase()) ?? key];
}

function selectCommand(candidates: Command[], probeArgs: string[], marker: string, help: string, options: RuntimeOptions): Command {
  const probe = options.probe ?? ((command, args) => spawnSync(command, args, {
    encoding: 'utf8', timeout: 5000, maxBuffer: 65536, windowsHide: true, shell: false,
    env: options.env ?? process.env,
  }));
  const tried: string[] = [];
  for (const candidate of candidates) {
    const result = probe(candidate.command, [...candidate.args, ...probeArgs]);
    if (!result.error && result.status === 0 && result.stdout?.trim() === marker) return candidate;
    tried.push(`${candidate.command}: ${result.error?.message ?? `exit ${result.status}, unexpected probe output`}`);
  }
  throw new Error(`${help}\n${tried.join('\n')}`);
}

export function findPython(options: RuntimeOptions = {}): Command {
  const env = options.env ?? process.env;
  const explicit = envValue(env, 'CISSTAT_TEST_PYTHON');
  const windows = (options.platform ?? process.platform) === 'win32';
  const candidates = explicit ? [{ command: explicit, args: [] }] : windows
    ? [{ command: 'python', args: [] }, { command: 'py', args: ['-3'] }, { command: 'python3', args: [] }]
    : [{ command: 'python3', args: [] }, { command: 'python', args: [] }];
  return selectCommand(candidates, ['-X', 'utf8', '-c',
    'import sys; print("cisstat-python3/1" if sys.version_info >= (3, 9) else "unsupported-python")'],
  'cisstat-python3/1', 'Python 3 (>=3.9) is required. Install Python 3.12 or set CISSTAT_TEST_PYTHON to its executable (no arguments).', options);
}

export function runPythonScript(script: string, cwd: string, options: RuntimeOptions = {}): string {
  const python = findPython(options);
  // Resolve only the interpreter. A nonzero guard must propagate, never try
  // another interpreter after the actual assertion script has failed.
  return execFileSync(python.command, [...python.args, '-X', 'utf8', script], {
    cwd, encoding: 'utf8', shell: false, windowsHide: true, timeout: 30000,
    env: { ...process.env, ...options.env, PYTHONUTF8: '1' },
  });
}

export function findPosixShell(options: RuntimeOptions = {}): string {
  const env = options.env ?? process.env;
  const explicit = envValue(env, 'CISSTAT_TEST_SH');
  const windows = (options.platform ?? process.platform) === 'win32';
  const candidates: string[] = [];
  if (explicit) candidates.push(explicit);
  else if (windows) {
    // Native Node cannot spawn /bin/sh on Windows. Use Git's MSYS shell,
    // not System32/sh.exe (the WSL launcher uses a different filesystem).
    for (const dir of (envValue(env, 'PATH') ?? '').split(';').filter(Boolean)) {
      const unquoted = dir.replace(/^"|"$/g, '');
      candidates.push(win32.join(unquoted, '..', 'bin', 'sh.exe'));
      candidates.push(win32.join(unquoted, '..', 'usr', 'bin', 'sh.exe'));
    }
    for (const base of [envValue(env, 'ProgramFiles'), envValue(env, 'ProgramW6432'), envValue(env, 'ProgramFiles(x86)')].filter(Boolean)) {
      candidates.push(win32.join(base!, 'Git', 'bin', 'sh.exe'));
    }
    const local = envValue(env, 'LOCALAPPDATA');
    if (local) candidates.push(win32.join(local, 'Programs', 'Git', 'bin', 'sh.exe'));
  } else candidates.push('/bin/sh', '/usr/bin/sh', 'sh');
  return selectCommand([...new Set(candidates)].map(command => ({ command, args: [] })),
    ['-c', 'test -x /bin/mv && printf cisstat-posix-shell/1'], 'cisstat-posix-shell/1',
    'POSIX shell with /bin/mv is required for launchGuard tests. On Windows install Git for Windows or set CISSTAT_TEST_SH to Git/bin/sh.exe. No tests were skipped.', options).command;
}
