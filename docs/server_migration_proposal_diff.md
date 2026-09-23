--- server_migration_proposal.md (原始)


+++ server_migration_proposal.md (修改后)
# Предложение по миграции CISStat TS Analysis на корпоративный сервер

**Проект:** CISStat TS Analysis — платформа анализа временных рядов
**Текущий хостинг:** Vercel (фронтенд) + render.com (бэкенд)
**Целевая среда:** Корпоративный сервер
**Дата:** 2026
**Версия документа:** 1.0

---

## Executive Summary

Настоящий документ описывает предложение по миграции платформы CISStat TS Analysis с облачного хостинга (Vercel + render.com) на корпоративный сервер. Миграция обеспечит:

- **Контроль данных:** полное управление инфраструктурой в рамках корпоративного контура
- **Безопасность:** соответствие корпоративным политикам безопасности
- **Производительность:** снижение задержек за счёт размещения в корпоративной сети
- **Масштабируемость:** возможность горизонтального масштабирования под нагрузку
- **Интеграция:** возможность интеграции с корпоративными системами (SSO, мониторинг, логирование)

**Рекомендуемая архитектура:** Единый сервер с Nginx reverse proxy, Next.js фронтендом и FastAPI бэкендом на одном домене.

**Оценка сроков:** 4-5 недель (при наличии готовой инфраструктуры)
**Оценка ресурсов:** 1 DevOps-инженер + 1 Backend-разработчик (частичная занятость)

---

## 1. Текущая архитектура

### 1.1 Компоненты

```
┌─────────────────────────────────────────────────────────────┐
│  Браузер (ts-standalone.vercel.app)                         │
└────────────────┬────────────────────────────────────────────┘
                 │ HTTPS
                 ↓
┌─────────────────────────────────────────────────────────────┐
│  Vercel (Next.js SSR + Static)                              │
│  ├── Frontend: Next.js 14 (React 18)                        │
│  ├── Rewrite: /api/* → render.com                           │
│  └── CDN: статические ассеты                                │
└────────────────┬────────────────────────────────────────────┘
                 │ HTTPS (через Vercel rewrite)
                 ↓
┌─────────────────────────────────────────────────────────────┐
│  render.com (FastAPI)                                       │
│  ├── Backend: FastAPI (Python 3.10)                         │
│  ├── Endpoints: 130+ (session, public, internal)            │
│  ├── Redis: сессии и кэширование                            │
│  └── Storage: временное хранение датасетов                  │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Ключевые характеристики

| Параметр | Значение |
|---|---|
| Фронтенд | Next.js 14 (SSR + SSG) |
| Бэкенд | FastAPI (Python 3.10) |
| API endpoints | 130+ |
| Сессии | Cookie-based (`cisstat_session_id`) |
| Хранилище | Redis (in-memory) |
| Загрузка файлов | До 50 МБ |
| Домен | `ts-standalone.vercel.app` |

### 1.3 Ограничения текущего решения

- **Зависимость от внешних провайдеров:** Vercel и render.com — сторонние сервисы
- **Контроль данных:** данные пользователей хранятся вне корпоративного контура
- **Стоимость:** подписки на Vercel Pro + render.com (при масштабировании)
- **Интеграция:** сложности с интеграцией корпоративных систем (SSO, мониторинг)
- **Compliance:** соответствие требованиям безопасности (GDPR, 152-ФЗ)

---

## 2. Целевая архитектура

### 2.1 Вариант A: Единый сервер (рекомендуемый)

```
┌─────────────────────────────────────────────────────────────┐
│  Корпоративный сервер (ts-analysis.company.ru)              │
│  ├── Nginx (reverse proxy + SSL termination)                │
│  │   ├── / → Next.js (порт 3000)                            │
│  │   └── /api/* → FastAPI (порт 8000)                       │
│  ├── Next.js (PM2, порт 3000)                               │
│  ├── FastAPI (PM2, порт 8000)                               │
│  └── Redis (порт 6379)                                      │
└─────────────────────────────────────────────────────────────┘
```

**Преимущества:**
- ✅ Простота деплоя и обслуживания
- ✅ Нет проблем с CORS (всё на одном домене)
- ✅ Cookie first-party (без ограничений SameSite)
- ✅ Низкая задержка (локальная сеть)
- ✅ Минимальные требования к инфраструктуре

**Недостатки:**
- ❌ Единая точка отказа
- ❌ Сложнее масштабировать горизонтально

### 2.2 Вариант B: Раздельные серверы

```
┌─────────────────────────────────────────────────────────────┐
│  Сервер 1: Фронтенд (ts.company.ru)                         │
│  ├── Nginx                                                  │
│  │   ├── / → Next.js                                        │
│  │   └── /api/* → proxy_pass → Сервер 2                     │
│  └── Next.js                                                │
└────────────────┬────────────────────────────────────────────┘
                 │ Внутренняя сеть
                 ↓
┌─────────────────────────────────────────────────────────────┐
│  Сервер 2: Бэкенд (api.ts.company.ru)                       │
│  ├── Nginx                                                  │
│  └── FastAPI                                                │
└─────────────────────────────────────────────────────────────┘
```

**Преимущества:**
- ✅ Изоляция (фронтенд и бэкенд независимо масштабируются)
- ✅ Безопасность (бэкенд во внутренней сети)

**Недостатки:**
- ❌ Сложнее настройка сети
- ❌ Нужен reverse proxy для обхода CORS
- ❌ Выше стоимость (2 сервера)

### 2.3 Вариант C: Kubernetes

```
┌─────────────────────────────────────────────────────────────┐
│  Kubernetes Cluster                                         │
│  ├── Ingress Controller (Nginx/Traefik)                     │
│  │   ├── ts.company.ru → frontend-service                   │
│  │   └── ts.company.ru/api/* → backend-service              │
│  ├── Deployment: frontend (Next.js)                         │
│  ├── Deployment: backend (FastAPI)                          │
│  └── Services + ConfigMaps + Secrets                        │
└─────────────────────────────────────────────────────────────┘
```

**Преимущества:**
- ✅ Автоматическое масштабирование
- ✅ Self-healing
- ✅ Версионирование деплоя

**Недостатки:**
- ❌ Сложность инфраструктуры
- ❌ Требует экспертизы Kubernetes
- ❌ Выше стоимость (минимум 3 ноды)

### 2.4 Рекомендация

**Вариант A (единый сервер)** рекомендуется для начала миграции по следующим причинам:

1. **Минимальные изменения в коде:** текущий код уже готов к такому сценарию
2. **Простота обслуживания:** один сервер, одна точка мониторинга
3. **Низкая стоимость:** минимальные требования к инфраструктуре
4. **Быстрый старт:** можно мигрировать за 4-5 недель

В будущем, при росте нагрузки, можно перейти к **Варианту B** (раздельные серверы) или **Варианту C** (Kubernetes) без значительных изменений в коде.

---

## 3. Детальное описание рекомендуемого варианта (Вариант A)

### 3.1 Требования к серверу

**Минимальные требования:**
- **ОС:** Linux Ubuntu 22.04 LTS (или CentOS 8/RHEL 8)
- **CPU:** 4 vCPU
- **RAM:** 8 GB
- **Disk:** 100 GB SSD
- **Network:** 1 Gbps

**Рекомендуемые требования (production):**
- **CPU:** 8 vCPU
- **RAM:** 16 GB
- **Disk:** 200 GB SSD
- **Network:** 1 Gbps

### 3.2 Стек технологий

```
Nginx 1.24+ (reverse proxy + SSL termination)
  ↓
Node.js 18+ (Next.js runtime)
  ↓
PM2 (process manager)
  ↓
Python 3.10+ (FastAPI runtime)
  ↓
Redis 7+ (сессии и кэш)
  ↓
PostgreSQL 15+ (опционально, для хранения истории)
```

### 3.3 Конфигурация Nginx

```nginx
# /etc/nginx/sites-available/ts-analysis

# Redirect HTTP → HTTPS
server {
    listen 80;
    server_name ts-analysis.company.ru;
    return 301 https://$server_name$request_uri;
}

# HTTPS server
server {
    listen 443 ssl http2;
    server_name ts-analysis.company.ru;

    # SSL certificates
    ssl_certificate /etc/ssl/certs/ts-analysis.company.ru.crt;
    ssl_certificate_key /etc/ssl/private/ts-analysis.company.ru.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # Frontend (Next.js)
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # API (FastAPI)
    location /api/ {
        rewrite ^/api/(.*)$ /$1 break;
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # File upload size limit (50 MB)
        client_max_body_size 50M;

        # Timeouts (для длительных операций анализа)
        proxy_connect_timeout 120s;
        proxy_send_timeout 120s;
        proxy_read_timeout 120s;
    }

    # Static assets (кэширование)
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
        proxy_pass http://127.0.0.1:3000;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

### 3.4 Конфигурация PM2

```javascript
// ecosystem.config.js
module.exports = {
  apps: [
    {
      name: "frontend",
      cwd: "/opt/cisstat-ts-analysis/apps/standalone",
      script: "npm",
      args: "start",
      instances: 2,  // cluster mode
      exec_mode: "cluster",
      env: {
        NODE_ENV: "production",
        PORT: 3000,
        NEXT_PUBLIC_API_BASE: "/api",
        NEXT_PUBLIC_API_MODE: "public",
      },
      max_memory_restart: "1G",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      error_file: "/var/log/pm2/frontend-error.log",
      out_file: "/var/log/pm2/frontend-out.log",
    },
    {
      name: "backend",
      cwd: "/opt/cisstat-ts-analysis/apps/api",
      script: "uvicorn",
      args: "main:app --host 0.0.0.0 --port 8000 --workers 4",
      interpreter: "python3",
      env: {
        CISSTAT_API_KEYS: "prod-key-1,prod-key-2,prod-key-3",
        REDIS_URL: "redis://localhost:6379",
        DATABASE_URL: "postgresql://user:pass@localhost:5432/cisstat",
      },
      max_memory_restart: "2G",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      error_file: "/var/log/pm2/backend-error.log",
      out_file: "/var/log/pm2/backend-out.log",
    },
  ],
};
```

### 3.5 Конфигурация Redis

```bash
# /etc/redis/redis.conf

bind 127.0.0.1
port 6379
requirepass your-secure-redis-password

# Memory management
maxmemory 2gb
maxmemory-policy allkeys-lru

# Persistence
save 900 1
save 300 10
save 60 10000

# Logging
logfile /var/log/redis/redis-server.log
loglevel notice
```

### 3.6 Переменные окружения

```bash
# .env.production (для Next.js)
NEXT_PUBLIC_API_BASE=/api
NEXT_PUBLIC_API_MODE=public

# .env (для FastAPI)
CISSTAT_API_KEYS=prod-key-1,prod-key-2,prod-key-3
REDIS_URL=redis://localhost:6379
REDIS_PASSWORD=your-secure-redis-password
DATABASE_URL=postgresql://user:pass@localhost:5432/cisstat
SECRET_KEY=your-secret-key-for-jwt
```

---

## 4. Требования к инфраструктуре

### 4.1 Серверы

| Компонент | Количество | CPU | RAM | Disk | Назначение |
|---|---|---|---|---|---|
| Application Server | 1 (минимум) | 4-8 vCPU | 8-16 GB | 100-200 GB SSD | Next.js + FastAPI + Redis |
| Database Server (опционально) | 1 | 2-4 vCPU | 4-8 GB | 100 GB SSD | PostgreSQL |
| Backup Server (опционально) | 1 | 2 vCPU | 4 GB | 500 GB HDD | Бэкапы |

### 4.2 Сеть

- **Домен:** `ts-analysis.company.ru` (или поддомен `ts.company.ru`)
- **SSL-сертификат:** Корпоративный сертификат (или Let's Encrypt)
- **Firewall:** Открыть порты 80 (HTTP), 443 (HTTPS)
- **DNS:** A-запись на IP сервера

### 4.3 Безопасность

- **SSL/TLS:** TLS 1.2+ (обязательно)
- **Firewall:** UFW или iptables (разрешить только 80, 443, 22)
- **SSH:** Только по ключам, отключить password auth
- **Fail2ban:** Защита от brute-force атак
- **Обновления:** Автоматические security updates

### 4.4 Мониторинг

**Минимальный набор:**
- **PM2 logs:** логи приложений
- **Nginx access/error logs:** логи веб-сервера
- **Redis monitoring:** `redis-cli info`
- **System monitoring:** `htop`, `df -h`, `free -m`

**Рекомендуемый набор:**
- **Prometheus + Grafana:** метрики (CPU, RAM, disk, network)
- **Loki:** централизованное логирование
- **Alertmanager:** алерты (email, Slack, Telegram)
- **Uptime monitoring:** Pingdom или UptimeRobot

---

## 5. План миграции

### Фаза 1: Подготовка (1-2 недели)

**Задачи:**
- [ ] Определить требования к инфраструктуре (CPU, RAM, disk)
- [ ] Запросить серверы у IT-отдела
- [ ] Настроить домен и DNS (`ts-analysis.company.ru`)
- [ ] Получить SSL-сертификат
- [ ] Настроить firewall и SSH
- [ ] Установить базовое ПО (Node.js, Python, Redis, Nginx)

**Результат:** Готовый сервер с базовой конфигурацией

### Фаза 2: Деплой бэкенда (1 неделя)

**Задачи:**
- [ ] Клонировать репозиторий `DimmDay/CISStat-TS-Analysis`
- [ ] Установить зависимости Python (`pip install -r requirements.txt`)
- [ ] Настроить переменные окружения (`.env`)
- [ ] Запустить FastAPI через PM2
- [ ] Настроить Redis (конфигурация, пароль)
- [ ] Тестирование API (Postman/curl)

**Результат:** Бэкенд работает на `http://localhost:8000`

### Фаза 3: Деплой фронтенда (1 неделя)

**Задачи:**
- [ ] Установить зависимости Node.js (`npm install`)
- [ ] Собрать Next.js (`npm run build`)
- [ ] Запустить через PM2
- [ ] Настроить Nginx (reverse proxy)
- [ ] Тестирование фронтенда (`https://ts-analysis.company.ru`)

**Результат:** Фронтенд работает на `https://ts-analysis.company.ru`

### Фаза 4: Интеграция и тестирование (1 неделя)

**Задачи:**
- [ ] Тестирование end-to-end (загрузка → анализ → прогноз)
- [ ] Проверка cookie-сессий (F5, разные браузеры)
- [ ] Тестирование загрузки больших файлов (50 МБ)
- [ ] Нагрузочное тестирование (k6, JMeter)
- [ ] Настройка мониторинга (Prometheus, Grafana, Loki)
- [ ] Настройка бэкапов (Redis, PostgreSQL)

**Результат:** Система протестирована, мониторинг настроен

### Фаза 5: Переключение трафика (1 день)

**Задачи:**
- [ ] Обновить DNS (указать на корпоративный сервер)
- [ ] Мониторинг ошибок (Sentry, логи)
- [ ] Rollback-план (вернуться на Vercel при проблемах)
- [ ] Уведомление пользователей о миграции

**Результат:** Трафик переключён на корпоративный сервер

---

## 6. Оценка рисков и митигация

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| CORS-ошибки при раздельных серверах | Средняя | Высокое | Использовать Вариант A (один домен) или настроить CORS |
| Потеря cookie-сессий | Средняя | Высокое | Настроить `SameSite=Lax` или `SameSite=None; Secure` |
| Проблемы с загрузкой больших файлов | Низкая | Среднее | Увеличить `client_max_body_size` в Nginx |
| Производительность Redis | Низкая | Среднее | Мониторинг, настройка `maxmemory-policy` |
| Отказ сервера | Низкая | Критическое | HA-конфигурация (2+ сервера), бэкапы |
| Ошибки в коде после миграции | Средняя | Высокое | Тщательное тестирование, rollback-план |
| Проблемы с SSL-сертификатом | Низкая | Среднее | Использовать проверенный CA, мониторинг истечения |
| DDoS-атаки | Низкая | Высокое | Cloudflare WAF или корпоративный WAF |

---

## 7. Оценка сроков и ресурсов

### 7.1 Сроки

| Фаза | Длительность | Зависимости |
|---|---|---|
| Фаза 1: Подготовка | 1-2 недели | Запрос серверов у IT |
| Фаза 2: Деплой бэкенда | 1 неделя | Готовый сервер |
| Фаза 3: Деплой фронтенда | 1 неделя | Готовый бэкенд |
| Фаза 4: Тестирование | 1 неделя | Готовый фронтенд + бэкенд |
| Фаза 5: Переключение | 1 день | Готовая система |
| **Итого** | **4-5 недель** | |

### 7.2 Ресурсы

| Роль | Загрузка | Задачи |
|---|---|---|
| DevOps-инженер | 100% (4-5 недель) | Настройка сервера, Nginx, PM2, мониторинг |
| Backend-разработчик | 50% (2-3 недели) | Деплой FastAPI, тестирование API |
| Frontend-разработчик | 25% (1-2 недели) | Деплой Next.js, тестирование UI |
| QA-инженер | 50% (1 неделя) | End-to-end тестирование, нагрузочное тестирование |

### 7.3 Стоимость (оценка)

| Статья | Стоимость (USD) | Примечание |
|---|---|---|
| Сервер (4 vCPU, 8 GB RAM) | $100-200/мес | Зависит от провайдера |
| SSL-сертификат | $0-200/год | Let's Encrypt (бесплатно) или корпоративный |
| Домен | $10-50/год | Зависит от зоны |
| Мониторинг (опционально) | $50-100/мес | Prometheus + Grafana (self-hosted) |
| **Итого (инфраструктура)** | **$160-350/мес** | |
| **Итого (работы)** | **80-120 чел-часов** | Зависит от квалификации |

---

## 8. Изменения в коде

### 8.1 Что НЕ нужно менять

- **`apiClient.ts`:** уже использует относительный путь `/api` в продакшене
- **`AppShellContext.tsx`:** уже готов к работе с `/api`
- **Компоненты UI:** не зависят от хостинга

### 8.2 Что нужно настроить

- **Переменные окружения:** создать `.env.production` для Next.js и `.env` для FastAPI
- **Nginx конфигурация:** добавить reverse proxy для `/api/*`
- **PM2 конфигурация:** настроить `ecosystem.config.js`

### 8.3 Опциональные улучшения

- **Логирование:** добавить структурированное логирование (JSON)
- **Метрики:** добавить Prometheus metrics в FastAPI
- **Health checks:** добавить `/health` endpoint для мониторинга
- **Rate limiting:** добавить ограничение запросов в Nginx

---

## 9. Следующие шаги

### 9.1 Немедленные действия

1. **Утвердить архитектуру:** выбрать Вариант A (единый сервер) или другой
2. **Запросить инфраструктуру:** отправить заявку в IT-отдел
3. **Назначить ответственных:** DevOps-инженер + Backend-разработчик

### 9.2 Подготовка к миграции

1. **Создать staging-сервер:** для тестирования перед продакшеном
2. **Подготовить конфигурационные файлы:** Nginx, PM2, Redis
3. **Подготовить документацию:** инструкция по деплою, rollback-план

### 9.3 После миграции

1. **Мониторинг:** настроить алерты (email, Slack)
2. **Бэкапы:** настроить автоматические бэкапы (Redis, PostgreSQL)
3. **Обновления:** настроить автоматические security updates
4. **Документация:** обновить внутреннюю документацию

---

## 10. Приложения

### Приложение A: Чек-лист миграции

- [ ] Сервер запросить и получить
- [ ] Домен настроить
- [ ] SSL-сертификат получить
- [ ] Firewall настроить
- [ ] SSH настроить (только по ключам)
- [ ] Node.js установить
- [ ] Python установить
- [ ] Redis установить и настроить
- [ ] Nginx установить и настроить
- [ ] PM2 установить
- [ ] Бэкенд задеплоить
- [ ] Фронтенд задеплоить
- [ ] Тестирование провести
- [ ] Мониторинг настроить
- [ ] Бэкапы настроить
- [ ] DNS переключить
- [ ] Пользователей уведомить

### Приложение B: Команды для быстрого старта

```bash
# Клонировать репозиторий
git clone https://github.com/DimmDay/CISStat-TS-Analysis.git
cd CISStat-TS-Analysis

# Установить зависимости
npm install
cd apps/api
pip install -r requirements.txt

# Настроить переменные окружения
cp .env.example .env
nano .env

# Запустить бэкенд
uvicorn main:app --host 0.0.0.0 --port 8000

# Запустить фронтенд (в другом терминале)
cd ../standalone
npm run build
npm start

# Проверить
curl http://localhost:3000
curl http://localhost:8000/docs
```

### Приложение C: Полезные ссылки

- **Репозиторий:** https://github.com/DimmDay/CISStat-TS-Analysis
- **Текущий фронтенд:** https://ts-standalone.vercel.app
- **API документация:** https://cisstat-ts-analysis.onrender.com/docs
- **Next.js документация:** https://nextjs.org/docs
- **FastAPI документация:** https://fastapi.tiangolo.com
- **Nginx документация:** https://nginx.org/en/docs

---

## 11. Контакты

**Автор документа:** Senior Developer, CISStat TS Analysis
**Дата создания:** 2026
**Версия:** 1.0

**Для вопросов и уточнений:**
- Технические вопросы: DevOps-инженер
- Архитектурные вопросы: Tech Lead
- Организационные вопросы: Project Manager

---

## 12. История изменений

| Версия | Дата | Изменения | Автор |
|---|---|---|---|
| 1.0 | 2026 |Initial version | Senior Developer |

---

**Конец документа**
