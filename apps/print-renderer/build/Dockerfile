# PGV-08-FIX. Build context: repository root. Node 24 required for zlib.crc32.
FROM node:24-bookworm-slim AS compiler
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/embedded/package.json apps/embedded/package.json
COPY apps/standalone/package.json apps/standalone/package.json
COPY apps/print-renderer/package.json apps/print-renderer/package.json
COPY packages/ui/package.json packages/ui/package.json
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY apps/print-renderer/src/ apps/print-renderer/src/
COPY apps/print-renderer/tsconfig.build.json apps/print-renderer/tsconfig.build.json
COPY packages/ui/print/ packages/ui/print/
COPY packages/ui/lib/ packages/ui/lib/
COPY config/ config/
RUN npm run build --workspace=@cisstat/print-renderer

FROM compiler AS production-deps
RUN npm prune --omit=dev --ignore-scripts --workspace=@cisstat/print-renderer --include-workspace-root=false

FROM node:24-bookworm-slim AS runtime
WORKDIR /app
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
    CISSTAT_PRINT_RENDERER_BROWSER_PATH=/opt/pw-browsers/chromium-1200/chrome-linux64/chrome \
    CISSTAT_PRINT_RENDERER_PORT=8907 \
    CISSTAT_PRINT_RENDERER_HARD_TIMEOUT_S=60 \
    CISSTAT_PRINT_RENDERER_TMP_DIR=/tmp \
    HOME=/tmp
# Pinned playwright@1.57.0 installs chromium-1200 + matching shared libraries.
RUN npx --yes playwright@1.57.0 install --with-deps chromium \
    && apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core fontconfig \
    && rm -rf /var/lib/apt/lists/* \
    && test -x "$CISSTAT_PRINT_RENDERER_BROWSER_PATH" \
    && fc-match 'DejaVu Sans' \
    && groupadd --gid 10001 renderer \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp renderer
COPY --from=production-deps /app/node_modules/ /app/node_modules/
COPY --from=compiler /app/apps/print-renderer/dist/ /app/apps/print-renderer/dist/
USER 10001:10001
EXPOSE 8907
HEALTHCHECK --interval=30s --timeout=15s --start-period=20s --retries=3 CMD ["node", "-e", "fetch('http://127.0.0.1:8907/readyz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
# Direct server entrypoint owns the actual worker shutdown handlers.
CMD ["node", "apps/print-renderer/dist/apps/print-renderer/src/server.js"]
