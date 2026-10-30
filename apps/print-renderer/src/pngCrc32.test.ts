import { pngCrc32 } from './pngCrc32';
import { pngCrc32Oracle } from '../../../scripts/testing/pngCrc32Oracle';

describe('PNG CRC-32: runtime-independent checksum and independent oracle', () => {
  it.each([
    ['empty', Buffer.alloc(0), 0x00000000],
    ['IEEE check vector', Buffer.from('123456789'), 0xcbf43926],
    ['PNG IEND chunk type', Buffer.from('IEND'), 0xae426082],
    ['binary bytes', Buffer.from([0, 128, 255, 42]), 0x88eef038],
  ] as const)('%s', (_label, bytes, expected) => {
    expect(pngCrc32(bytes)).toBe(expected);
    expect(pngCrc32Oracle(bytes)).toBe(expected);
  });

  it('checks only visible bytes in a Uint8Array view', () => {
    const bytes = new Uint8Array([255, ...Buffer.from('123456789'), 0]);
    const view = bytes.subarray(1, -1);
    expect(pngCrc32(view)).toBe(0xcbf43926);
    expect(pngCrc32Oracle(view)).toBe(0xcbf43926);
  });

  it('agrees with a bit-at-a-time oracle on deterministic binary inputs', () => {
    const bytes = Uint8Array.from({ length: 1024 }, (_, i) => (i * 73 + 19) & 255);
    for (const length of [0, 1, 7, 13, 255, 1024]) {
      expect(pngCrc32(bytes.subarray(0, length))).toBe(pngCrc32Oracle(bytes.subarray(0, length)));
    }
  });
});
