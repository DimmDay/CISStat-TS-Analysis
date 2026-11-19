#!/bin/sh
set -eu
module=apps/print-renderer/dist/apps/print-renderer/src
if [ -n "${CISSTAT_PRINT_RENDERER_SOCKET:-}" ]; then
  node "$module/socketTransport.js"
  exec flock --no-fork --exclusive --nonblock "${CISSTAT_PRINT_RENDERER_SOCKET%/*}/renderer.lock" node "$module/server.js"
fi
exec node "$module/server.js"
