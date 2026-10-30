// Optional fault-injection setup: model a Node runtime without zlib.crc32.
// Only the explicitly launched verification process is affected.
Object.defineProperty(require('node:zlib'), 'crc32', {
  value: undefined,
  writable: true,
  configurable: true,
});
