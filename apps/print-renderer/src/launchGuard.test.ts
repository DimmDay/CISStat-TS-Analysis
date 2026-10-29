/** Real noexec-compatible shell gate; no Chromium or unsafe PID probing. */
import { mkdtempSync, writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { createLaunchGuard } from './launchGuard';

describe('PGV-08 launch ownership before handshake', () => {
  let root: string;
  beforeEach(() => { root = mkdtempSync(join(process.cwd(), 'pgv08-test-')); });
  afterEach(() => { jest.restoreAllMocks(); rmSync(root, {recursive:true,force:true}); });
  test('cancellation before spawn prevents exec, even when the wrapper starts later', () => {
    const guard = createLaunchGuard(root);
    const unexpected = join(root, 'must-not-exist');
    guard.cancel();
    const child = spawnSync('/bin/sh', [guard.wrapper, '/bin/sh', '-c', `printf running > '${unexpected}'`]);
    expect(child.status).toBe(125);
    expect(existsSync(unexpected)).toBe(false);
    guard.cleanup();
    expect(existsSync(guard.directory)).toBe(false);
  });
  test('failure to record ownership cannot fall through to browser exec', () => {
    const guard = createLaunchGuard(root);
    const unexpected = join(root, 'must-not-exist');
    // Simulate a temp directory disappearing after the shell read its script.
    const body = readFileSync(guard.wrapper, 'utf8').replace("printf '%s'", `/bin/rm -rf '${guard.directory}'\nprintf '%s'`);
    const child = spawnSync('/bin/sh', ['-c', body, 'gate', '/bin/sh', '-c', `printf running > '${unexpected}'`]);
    expect(child.status).not.toBe(0);
    expect(existsSync(unexpected)).toBe(false);
    guard.cleanup();
  });
  test('known job PID is killed as an entire process group', () => {
    const kill = jest.spyOn(process, 'kill').mockReturnValue(true);
    const guard = createLaunchGuard(root);
    writeFileSync(join(guard.directory, 'browser.pid'), '43210');
    guard.cancel();
    expect(kill).toHaveBeenCalledWith(-43210, 'SIGKILL');
    guard.cleanup();
  });
  test.each(['0', '-1', 'not-a-pid'])('unsafe PID %s cannot signal another group', pid => {
    const kill = jest.spyOn(process, 'kill').mockReturnValue(true);
    const guard = createLaunchGuard(root);
    writeFileSync(join(guard.directory, 'browser.pid'), pid);
    guard.cancel();
    expect(kill).not.toHaveBeenCalled();
    guard.cleanup();
  });
});
