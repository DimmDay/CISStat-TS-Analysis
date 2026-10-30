/** Bit-at-a-time PNG CRC-32 oracle, independent of renderer's lookup table.
 * No node:zlib.crc32 requirement; test vectors pin the standard checksum.
 */
export function pngCrc32Oracle(bytes: Uint8Array): number {
  let remainder = 0xffffffff;
  for (const byte of bytes) {
    remainder ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      remainder = (remainder >>> 1) ^ ((remainder & 1) ? 0xedb88320 : 0);
    }
  }
  return (~remainder) >>> 0;
}
