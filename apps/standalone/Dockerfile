# apps/standalone/Dockerfile
#
# AUTH-06-OPS-PHASE1 (2026-11-04): прод-образ Next.js standalone shell
# (полный переезд платформы с Vercel на собственный сервер, домен
# datasetup.ru). На Vercel этот workspace собирался верселевским билдером
# (vercel.json: npm install + npm run build --workspace); здесь то же
# самое внутри docker multi-stage.
#
# ВАЖНО: контекст сборки -- КОРЕНЬ репозитория, НЕ apps/standalone:
# монорепо npm-workspaces; сборке нужны packages/ui (transpilePackages в
# next.config.mjs) и package-lock.json корня.
#   docker build -f apps/standalone/Dockerfile <корень-репо>
#
# СОЗНАТЕЛЬНО БЕЗ output:'standalone' в next.config.mjs: файл входит в
# AUTH-00 inventory (reviewed UI source), задача не меняет reviewed-код
# вообще. Классический `next start` с полным node_modules монорепо даёт
# идентичное поведение, включая runtime-чтение API_URL /
# CISSTAT_AUTH_PUBLIC_ORIGIN в first-party proxy
# (packages/ui/server/firstPartyProxy.ts::firstPartyProxy).

# ---------------------------------------------------------------- build ---
FROM node:22-bookworm-slim AS build

WORKDIR /repo

# Слой манифестов workspace'ов: npm ci кэшируется, пока зависимости не
# менялись (правки исходников пересборку зависимостей не триггерят).
# workspaces корня: apps/embedded, apps/print-renderer, apps/standalone,
# packages/* -- npm ci требует манифесты ВСЕХ workspace'ов.
COPY package.json package-lock.json ./
COPY apps/embedded/package.json apps/embedded/package.json
COPY apps/print-renderer/package.json apps/print-renderer/package.json
COPY apps/standalone/package.json apps/standalone/package.json
COPY packages/ui/package.json packages/ui/package.json
RUN npm ci

# Исходники: ui -- TS-исходники без отдельной сборки (main=./index.ts),
# потребляются через transpilePackages; standalone shell целиком
# (включая app/api/v1/[...path]/route.ts -- first-party proxy AUTH-06).
COPY packages/ui ./packages/ui

# shared/pipeline_nodes/*.json -- импортируются packages/ui относительно
# КОРНЯ монорепо (eda_checks.json, upload_stops.json); без этого next build
# падает: Module not found: Can't resolve '../../../shared/pipeline_nodes/...'
# (инцидент первого docker compose build на VM cisstat-api).
COPY shared ./shared

COPY apps/standalone ./apps/standalone

RUN npm run build --workspace=@cisstat/ts-analysis-standalone

# --------------------------------------------------------------- runtime ---
FROM node:22-bookworm-slim

WORKDIR /repo
ENV NODE_ENV=production

# node_modules монорепо: npm создаёт СИМВОЛЬНУЮ ССЫЛКУ
# node_modules/@cisstat/ui -> packages/ui -- COPY сохраняет её; целевой
# каталог копируется рядом, поэтому ссылка разрешается (гвард ниже
# fail-closed: пересорвавшаяся ссылка валит СБОРКУ, а не прод).
COPY --from=build /repo/node_modules ./node_modules

# AUTH-06-OPS hotfix (2026-11-04, инцидент первого docker compose build
# на VM cisstat-api; в репо -- AUTH-06-OPS-PHASE1-V2, 2026-11-05):
# CMD делает `npm run start --workspace=...` -- npm читает КОРНЕВОЙ
# package.json (поле workspaces) и манифесты объявленных workspace'ов.
# Без этих слоёв контейнер уходил в Restarting (exit 254) при собранном
# .next: Next.js стартовал сборку манифестов раньше падения npm-резолва.
COPY --from=build /repo/package.json ./package.json
COPY --from=build /repo/apps/embedded/package.json ./apps/embedded/package.json
COPY --from=build /repo/apps/print-renderer/package.json ./apps/print-renderer/package.json
COPY --from=build /repo/packages/ui ./packages/ui
COPY --from=build /repo/apps/standalone/package.json ./apps/standalone/package.json
COPY --from=build /repo/apps/standalone/next.config.mjs ./apps/standalone/next.config.mjs
COPY --from=build /repo/apps/standalone/public ./apps/standalone/public
COPY --from=build /repo/apps/standalone/.next ./apps/standalone/.next

# Fail-closed гварды времени сборки (философия DEPLOY-1: сломанный образ
# не собирается, а не умирает молча в runtime).
RUN node -e "console.log('next', require('./node_modules/next/package.json').version)" \
    && node -e "console.log('@cisstat/ui ->', require('fs').realpathSync('/repo/node_modules/@cisstat/ui'))" \
    && node -e "require('fs').accessSync('/repo/apps/standalone/.next/BUILD_ID'); \
                console.log('BUILD_ID OK (next build completed)')" \
    && node -e "const fs=require('fs'); \
                const p='/repo/packages/ui/server/firstPartyProxy.ts'; \
                fs.accessSync(p); \
                console.log('first-party proxy source OK (AUTH-06)')"

# AUTH-06-OPS hotfix (2026-11-04): npm run --workspace читает КОРНЕВОЙ package.json
RUN node -e 'const m=require("/repo/package.json"); if(!Array.isArray(m.workspaces)||!m.workspaces.includes("apps/standalone")) throw new Error("workspace apps/standalone not declared"); console.log("root manifest OK (npm --workspace runnable)")'

EXPOSE 3000

# next start: слушает 3000 (PORT из compose продублирован флагом);
# cwd -- workspace-каталог (npm --workspace выполняет скрипт из него).
CMD ["npm", "run", "start", "--workspace=@cisstat/ts-analysis-standalone", "--", "-p", "3000"]
