import { readFileSync } from 'node:fs';
import { resolve, win32 } from 'node:path';
import { findPosixShell, findPython, runPythonScript } from './runtimes';
const childProcess = require('node:child_process') as typeof import('node:child_process');

const missing = { status: null, stdout: '', stderr: '', error: new Error('ENOENT') };
const pythonOk = { status: 0, stdout: 'cisstat-python3/1\n', stderr: '' };
const shellOk = { status: 0, stdout: 'cisstat-posix-shell/1', stderr: '' };

describe('test runtime discovery (Windows branches exercised without a Windows host)', () => {
  afterEach(() => jest.restoreAllMocks());

  test('Windows Python alias is rejected; py -3 selects a real interpreter', () => {
    const probe = jest.fn((command: string) => command === 'py' ? pythonOk : { status: 0, stdout: 'Python', stderr: '' });
    expect(findPython({ platform: 'win32', env: {}, probe })).toEqual({ command: 'py', args: ['-3'] });
    expect(probe.mock.calls.map(c => c[0])).toContain('python');
  });

  test('Windows falls back to python3 when python and the launcher are unavailable', () => {
    const probe = jest.fn((command: string) => command === 'python3' ? pythonOk : missing);
    expect(findPython({ platform: 'win32', env: {}, probe })).toEqual({ command: 'python3', args: [] });
  });

  test('explicit Python executable with spaces is one argv item and never silently replaced', () => {
    const command = "C:\\Python tools 'тест'\\python.exe";
    const probe = jest.fn(() => pythonOk);
    expect(findPython({ platform: 'win32', env: { CISSTAT_TEST_PYTHON: command }, probe }).command).toBe(command);
    probe.mockReturnValue(missing);
    expect(() => findPython({ env: { CISSTAT_TEST_PYTHON: command }, probe })).toThrow(/CISSTAT_TEST_PYTHON/);
    expect(probe).toHaveBeenCalledTimes(2);
  });

  test('no real Python is an actionable failure, never a skipped assertion', () => {
    const probe = jest.fn(() => missing);
    expect(() => findPython({ platform: 'win32', env: {}, probe })).toThrow(/Python 3.*CISSTAT_TEST_PYTHON/);
  });

  test('Windows selects Git sh from a nonstandard PATH (not WSL sh)', () => {
    const gitBin = 'D:\\Dev tools\\Git\\bin\\sh.exe';
    const probe = jest.fn((command: string) => command === gitBin ? shellOk : missing);
    const actual = findPosixShell({ platform: 'win32', env: { Path: 'D:\\Dev tools\\Git\\cmd;C:\\Windows\\System32' }, probe });
    expect(actual).toBe(gitBin);
    expect(probe.mock.calls.some(c => c[0] === '/bin/sh' || c[0] === 'sh')).toBe(false);
  });

  test('Windows finds the standard Git for Windows installation', () => {
    const gitBin = win32.join('C:\\Program Files', 'Git', 'bin', 'sh.exe');
    const probe = jest.fn((command: string) => command === gitBin ? shellOk : missing);
    expect(findPosixShell({ platform: 'win32', env: { ProgramFiles: 'C:\\Program Files' }, probe })).toBe(gitBin);
  });

  test('POSIX host retains /bin/sh; shell without mv is rejected by its probe', () => {
    const probe = jest.fn((command: string, _args: string[]) => command === '/bin/sh' ? { ...missing, status: 1 } : shellOk);
    expect(findPosixShell({ platform: 'linux', env: {}, probe })).toBe('/usr/bin/sh');
    expect(probe.mock.calls[0][0]).toBe('/bin/sh');
    expect(probe.mock.calls[0][1]).toContainEqual(expect.stringContaining('/bin/mv'));
  });

  test('explicit missing shell does not fall back or skip real shell checks', () => {
    const probe = jest.fn(() => missing);
    expect(() => findPosixShell({ platform: 'win32', env: { CISSTAT_TEST_SH: 'missing.exe' }, probe })).toThrow(/CISSTAT_TEST_SH/);
    expect(probe).toHaveBeenCalledTimes(1);
  });

  test('Python script is executed without shell interpolation, in UTF-8; guard failure is propagated', () => {
    const executable = "C:\\Python tools\\python.exe";
    const probe = jest.fn(() => pythonOk);
    const exec = jest.spyOn(childProcess, 'execFileSync').mockReturnValue('гвард: 41/41');
    const script = "scripts/с пробелом ' $(never).py";
    expect(runPythonScript(script, '/repo root', { env: { CISSTAT_TEST_PYTHON: executable }, probe })).toBe('гвард: 41/41');
    expect(exec).toHaveBeenCalledWith(executable, ['-X', 'utf8', script], expect.objectContaining({ cwd: '/repo root', encoding: 'utf8', shell: false }));
    exec.mockImplementation(() => { throw new Error('guard failed 1/41'); });
    expect(() => runPythonScript(script, '/repo root', { env: { CISSTAT_TEST_PYTHON: executable }, probe })).toThrow('guard failed 1/41');
    expect(exec).toHaveBeenCalledTimes(2);
  });

  test('root Jest explicitly owns the same Playwright pin as renderer and lock', () => {
    const root = resolve(__dirname, '../..');
    const read = (p: string) => JSON.parse(readFileSync(resolve(root, p), 'utf8'));
    const pin = read('apps/print-renderer/package.json').dependencies['playwright-core'];
    expect(pin).toBe('1.57.0');
    expect(read('package.json').devDependencies['playwright-core']).toBe(pin);
    expect(read('package-lock.json').packages[''].devDependencies['playwright-core']).toBe(pin);
    expect(read('node_modules/playwright-core/package.json').version).toBe(pin);
    expect(require('playwright-core/package.json').version).toBe(pin);
  });
});
