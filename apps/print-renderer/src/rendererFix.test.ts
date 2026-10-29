import { buildRequestPolicy, sanitizeFrozenSvg, validateRenderPayload, injectPngPhys } from './rendererCore';
import { PrintRenderWorker, readConfig, RenderTimeoutError } from './renderWorker';
import * as launchGuard from './launchGuard';
import { cyrillicScenario, ihScenario } from './smokeScenarios';

describe('PGV-08-FIX independent boundaries', () => {
  test.each(['javascript:alert(1)', 'chrome://settings', 'vbscript:x', 'custom:payload', '//host/x', 'relative.svg'])('URL %s is denied by default', url => {
    expect(buildRequestPolicy().shouldBlock(url)).toBe(true);
  });
  test.each(['javascript:x', 'vbscript:x', 'custom:x', 'relative.png', 'file:///etc/passwd'])('SVG reference %s is removed', ref => {
    const result = sanitizeFrozenSvg(`<svg><image href="${ref}"/></svg>`);
    expect(result.xml).not.toContain(`href="${ref}"`);
    expect(result.warnings.length).toBeGreaterThan(0);
  });
  test('local SVG fragments survive', () => {
    expect(sanitizeFrozenSvg('<svg><use href="#axis"/></svg>').xml).toContain('href="#axis"');
  });
  test.each([0, -1, NaN, Infinity, 1.1, 2, 3])('invalid production scale %s is rejected', scale => {
    const payload = cyrillicScenario(); payload.options = { scale };
    expect(validateRenderPayload(payload).payload).toBeNull();
  });
  test('mini probes and full-size scale are valid', () => {
    for (const scale of [.05, 1]) { const p = cyrillicScenario(); p.options = { scale }; expect(validateRenderPayload(p).violations).toEqual([]); }
  });
  test('IH fixture denominator equals its population', () => {
    const section = ihScenario().sections[0];
    if (section.kind !== 'ih_conditional') throw new Error('IH missing');
    expect(section.ih_input.row_totals!.reduce((a,b) => a!+b!,0)).toBe(section.ih_input.n_observations);
  });
  test('direct worker call rejects oversized payload before dependency/browser work', async () => {
    const worker = new PrintRenderWorker(readConfig({}));
    const dependency = jest.spyOn(worker, 'dependencyManifest');
    const payload = cyrillicScenario(); payload.options = { scale: 9 };
    await expect(worker.renderPayload(payload, 1, 1)).rejects.toThrow(/invalid_payload/);
    expect(dependency).not.toHaveBeenCalled();
  });
});

describe('PGV-08-FIX cold launch cancellation', () => {
  afterEach(() => { jest.useRealTimers(); jest.restoreAllMocks(); });
  test('late launch is killed and never starts a page after timeout', async () => {
    jest.useFakeTimers();
    jest.spyOn(launchGuard, 'createLaunchGuard').mockReturnValue({directory:'/fake/job',wrapper:'/fake/job/launch.sh',cancel:jest.fn(),cleanup:jest.fn()});
    let finishLaunch!: (value: any) => void;
    const pending = new Promise<any>(r => { finishLaunch = r; });
    const context = { close: jest.fn(async()=>{}), newPage: jest.fn(async()=>{ throw new Error('must never render'); }) };
    const kill = jest.fn();
    const browser: any = { newContext: jest.fn(async()=>context), close: jest.fn(async()=>{}), process: ()=>({pid:54321, kill}) };
    const server: any = { process: ()=>({pid:54321, kill}), kill: jest.fn(async()=>{kill('SIGKILL');}), close: jest.fn(async()=>{}), wsEndpoint: ()=> 'ws://127.0.0.1/fake' };
    const launch = jest.fn((_options: any)=>pending);
    const module = { chromium: { launch, launchServer: launch, executablePath: () => '/fake/chrome', connect: jest.fn(async()=>browser) } };
    const worker: any = new PrintRenderWorker({...readConfig({}),hardTimeoutS:1});
    worker.playwrightModule = module;
    jest.spyOn(worker,'dependencyManifest').mockReturnValue({dependency_status:'available',checks:{browser:true,fonts:true,bundle:true}} as any);
    const payload=cyrillicScenario(); payload.options={timeout_s:1};
    const result=worker.renderPayload(payload,1,1).catch((e:any)=>e);
    await jest.advanceTimersByTimeAsync(1000);
    expect(await result).toBeInstanceOf(RenderTimeoutError);
    // Real launchServer enforces its own deadline; this fake deliberately resolves later.
    finishLaunch(module.chromium.launchServer.mock.calls.length ? server : browser);
    await jest.advanceTimersByTimeAsync(0);
    expect(browser.newContext).not.toHaveBeenCalled();
    expect(server.kill.mock.calls.length + kill.mock.calls.length).toBeGreaterThan(0);
    const opts=launch.mock.calls[0][0] as any;
    expect(opts.timeout).toBeLessThanOrEqual(1000);
    expect(opts.chromiumSandbox).toBe(true);
  });
});
