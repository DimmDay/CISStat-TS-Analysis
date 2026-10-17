"""
UPLOAD-DB-9 «Документация» — гвард соответствия документации коду.

Фаза D «выпуск» эпика UPLOAD-DB (spec_database_plan.md). DoD задачи:
«docs соответствуют коду, смоук-чеклист релиза». Этот сюит — механический
гвард этого DoD: документированные факты сверяются с ФАКТАМИ КОДА
(реестр коннекторов, константы guard'а, env-переменные, маршруты API,
пины requirements), а не с текстом самих документов.

Принцип TDD: сюит написан ДО документации и на момент RED честно падает
(файлы/разделы отсутствуют); после GREEN он остаётся постоянным гвардом —
правка реестра/лимитов/пинов без синхронной правки документации роняет
сюит (двойная запись знания: код + документация связаны тестом).

Проверки устойчивые к переформулировкам (RD3): substring на
идентификаторах (имена env, порты, pip-пакеты, пути файлов, кодовые
имена D1/D3/D4/S1/S2/S4/S5), не на полных предложениях.

Только чтение кодовой базы (гвард); без commit/push (AGENTS.md).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.data.db_connectors import (  # noqa: E402
    DB_CONNECTORS,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_QUERY_TIMEOUT,
)
from app.data.db_guard import DEFAULT_CHUNKSIZE, DEFAULT_ROW_LIMIT  # noqa: E402

README = REPO / "README.md"
ARCHITECTURE = REPO / "ARCHITECTURE.md"
HELP_DOC = REPO / "docs" / "upload_db_connections_help.md"
SMOKE_DOC = REPO / "docs" / "upload_db_release_smoke_checklist.md"
ARTICLES = REPO / "packages" / "ui" / "lib" / "knowledge" / "articles.ts"


def _read(path: Path) -> str:
    assert path.exists(), f"Файл документации отсутствует: {path.relative_to(REPO)}"
    return path.read_text(encoding="utf-8")


def _doc_text() -> str:
    """Вся документация задачи одним текстом (перекрёстные ссылки допустимы)."""
    return "\n".join(_read(p) for p in (README, ARCHITECTURE, HELP_DOC, SMOKE_DOC))


# ── 1. Матрица СУБД: документация == реестр ────────────────────────────────


class TestUploadDb9MatrixInDocs:
    """Матрица 6 СУБД отражена в документации ровно как в реестре."""

    def test_all_six_labels_documented(self):
        text = _doc_text()
        for spec in DB_CONNECTORS.values():
            assert spec.label in text, (
                f"В документации нет label реестра «{spec.label}» "
                "(DoD: docs соответствуют коду)"
            )

    def test_readme_matrix_modes_and_ports(self):
        """README: для каждой серверной СУБД указаны режим, диалект и порт."""
        readme = _read(README)
        for spec in DB_CONNECTORS.values():
            if spec.mode == "server":
                if spec.dialect is not None:
                    assert spec.dialect in readme, (
                        f"README не документирует диалект {spec.dialect} ({spec.label})"
                    )
                else:
                    # нативный клиент (ClickHouse): пин пакета вместо диалекта
                    assert spec.pip_package in readme, (
                        f"README не документирует нативный клиент {spec.pip_package} ({spec.label})"
                    )
                assert str(spec.default_port) in readme, (
                    f"README не документирует порт {spec.default_port} ({spec.label})"
                )
            else:
                assert spec.mode in readme, (
                    f"README не документирует режим «{spec.mode}» ({spec.label})"
                )

    def test_embedded_extensions_documented(self):
        """Embedded-дорожка: допустимые расширения файлов документированы."""
        text = _doc_text()
        for cid in ("duckdb", "sqlite"):
            spec = DB_CONNECTORS[cid]
            for ext in spec.path_extensions:
                assert ext in text, (
                    f"В документации нет расширения {ext} ({spec.label}; "
                    "контракт пути ядра Фазы A)"
                )

    def test_duckdb_query_file_extensions(self):
        """DuckDB: прямой SELECT по Parquet/CSV без сервера задокументирован."""
        text = _doc_text()
        spec = DB_CONNECTORS["duckdb"]
        for ext in spec.query_file_extensions:
            assert ext in text, (
                f"В документации нет {ext} — прямой SELECT DuckDB по файлу "
                "(UPLOAD-DB-3) не отражён"
            )


# ── 2. Драйверы: документация == пины requirements + реестр ───────────────


class TestUploadDb9DriversInDocs:
    """Драйверы и pip-пакеты отражены по реестру и requirements."""

    @pytest.mark.parametrize(
        "pkg",
        [
            "psycopg[binary]",
            "clickhouse-connect",
            "pyodbc",
            "pymssql",
            "PyMySQL",
            "cryptography",
            "duckdb",
            "duckdb-engine",
            "sqlalchemy",
        ],
    )
    def test_driver_packages_named(self, pkg: str):
        assert pkg in _doc_text(), (
            f"В документации не назван драйвер/пакет «{pkg}» "
            "(матрица драйверов — DoD UPLOAD-DB-9)"
        )

    def test_mssql_fallback_documented(self):
        """S2/RP2: fallback pymssql и переключатель UPLOAD_DB_MSSQL_DRIVER."""
        text = _doc_text()
        spec = DB_CONNECTORS["mssql"]
        assert spec.fallback_pip_package in text, (
            "Fallback-драйвер MSSQL (S2) не задокументирован"
        )
        assert "UPLOAD_DB_MSSQL_DRIVER" in text, (
            "env-переключатель драйвера MSSQL (UPLOAD-DB-7) не задокументирован"
        )

    def test_mysql_cryptography_reason(self):
        """caching_sha2_password (MySQL 8) → cryptography задокументирован."""
        text = _doc_text().lower()
        assert "caching_sha2_password" in text, (
            "Причина пина cryptography (caching_sha2_password MySQL 8) "
            "не задокументирована"
        )

    def test_odbc_driver_18_named(self):
        """ODBC Driver 18 for SQL Server — системная зависимость MSSQL."""
        assert "ODBC Driver 18" in _doc_text()

    def test_dockerfile_odbc_layer_documented(self):
        """Dockerfile: условный слой INSTALL_MSODBCSQL18 (RP2) отражён."""
        text = _doc_text()
        assert "INSTALL_MSODBCSQL18" in text, (
            "build-arg INSTALL_MSODBCSQL18 (RP2: закрытый контур без apt MS) "
            "не задокументирован"
        )


# ── 3. env-лимиты: документация == код (S4/D5/S5) ─────────────────────────


class TestUploadDb9EnvInDocs:
    """Все env-переменные БД-дорожки документированы с кодовыми дефолтами."""

    ENV_FACTS = {
        "UPLOAD_DB_ROW_LIMIT": DEFAULT_ROW_LIMIT,
        "UPLOAD_DB_CHUNKSIZE": DEFAULT_CHUNKSIZE,
        "UPLOAD_DB_CONNECT_TIMEOUT": DEFAULT_CONNECT_TIMEOUT,
        "UPLOAD_DB_QUERY_TIMEOUT": DEFAULT_QUERY_TIMEOUT,
    }

    def test_all_code_env_names_documented(self):
        """Каждая UPLOAD_DB_* из кода встречается в документации."""
        text = _doc_text()
        for env_name in self.ENV_FACTS:
            assert env_name in text, f"env-переменная {env_name} не документирована"
        assert "UPLOAD_DB_HOST_WHITELIST" in text, (
            "env UPLOAD_DB_HOST_WHITELIST (D5/SSRF, S5) не документирована"
        )
        assert "UPLOAD_DB_MSSQL_DRIVER" in text

    @pytest.mark.parametrize(
        "env_name", ["UPLOAD_DB_ROW_LIMIT", "UPLOAD_DB_CHUNKSIZE",
                     "UPLOAD_DB_CONNECT_TIMEOUT", "UPLOAD_DB_QUERY_TIMEOUT"]
    )
    def test_documented_defaults_match_code(self, env_name: str):
        """Дефолт в документации численно равен константе кода.

        Формат допускает разделители тысяч («1 000 000», «50 000») —
        нормализация выкидывает пробелы/запятые/неразрывные пробелы в окне
        ПОСЛЕ имени переменной, число обязано быть в этом окне (RD3:
        устойчивость к человеческому форматированию без потери смысла).
        """
        text = _doc_text()
        default = self.ENV_FACTS[env_name]
        m = re.search(re.escape(env_name) + r"[\s\S]{0,200}", text)
        assert m, f"env-переменная {env_name} не документирована"
        window = re.sub(r"[\s\u00a0,]", "", m.group(0))
        assert str(default) in window, (
            f"В документации рядом с {env_name} не назван кодовый дефолт {default} "
            "(S4: дефолты — часть контракта)"
        )

    def test_whitelist_off_by_default_documented(self):
        """S5: whitelist выключен по умолчанию (пусто/«*» = off) — задокументирован."""
        text = _doc_text()
        assert "UPLOAD_DB_HOST_WHITELIST" in text
        assert re.search(r"UPLOAD_DB_HOST_WHITELIST[\s\S]{0,300}(off|OFF|выключ|пуст|\*)", text)

    def test_env_names_in_docs_not_superset_of_code(self):
        """Документация не вводит несуществующие UPLOAD_DB_*-переменные."""
        code_names = {
            "UPLOAD_DB_ROW_LIMIT", "UPLOAD_DB_CHUNKSIZE",
            "UPLOAD_DB_CONNECT_TIMEOUT", "UPLOAD_DB_QUERY_TIMEOUT",
            "UPLOAD_DB_HOST_WHITELIST", "UPLOAD_DB_MSSQL_DRIVER",
        }
        docs_text = "\n".join(_read(p) for p in (README, ARCHITECTURE, HELP_DOC, SMOKE_DOC))
        found = set(re.findall(r"UPLOAD_DB_[A-Z_]+", docs_text))
        phantom = found - code_names
        assert not phantom, (
            f"Документация упоминает несуществующие в коде переменные: {sorted(phantom)}"
        )


# ── 4. API-контракт: документация == маршруты приложения ──────────────────


class TestUploadDb9ApiInDocs:
    """Эндпоинты БД-дорожки документированы по фактическим маршрутам."""

    @pytest.mark.parametrize(
        "route",
        [
            "/v1/internal/upload/db/test",
            "/v1/internal/upload/db/load",
            "/v1/public/upload/db/test",
            "/v1/public/upload/db/load",
        ],
    )
    def test_routes_documented(self, route: str):
        assert route in _doc_text(), (
            f"Маршрут {route} не задокументирован (контракт UPLOAD-DB-4)"
        )

    def test_test_probe_semantics_documented(self):
        """Probe-семантика /test (200 {ok:false}, не ошибка) отражена."""
        text = _doc_text()
        assert re.search(r"(ok\s*[:=]\s*false|ok\s*—\s*false|ok:false)", text)

    def test_guard_422_documented(self):
        """DoD плана: read-only guard → 422 задокументирован."""
        text = _doc_text()
        assert "422" in text
        assert re.search(r"(SELECT|WITH)[\s\S]{0,200}422", text) or re.search(
            r"422[\s\S]{0,200}(SELECT|WITH)", text
        )

    def test_masking_documented(self):
        """D4: маскирование секретов в ошибках отражено."""
        assert "D4" in _doc_text()

    def test_union_discriminator_documented(self):
        """Discriminated union по db_type (сервер|embedded) отражён."""
        text = _doc_text()
        assert "db_type" in text
        assert re.search(r"(embedded|встроенн)", text, re.I)


# ── 5. Безопасность: рекомендации ядра отражены (RP4) ─────────────────────


class TestUploadDb9SecurityInDocs:
    """Находки аудита D2-D6 и риски — в документации."""

    def test_readonly_guard_documented(self):
        """D6: read-only guard (SELECT/WITH, запрет DML/DDL/мультистейтмент)."""
        text = _doc_text()
        assert "SELECT" in text and "WITH" in text
        assert re.search(r"(мультистейтмент|multi.?statement)", text, re.I)

    def test_readonly_credentials_recommendation(self):
        """RP4: рекомендация развертывания с read-only пользователем БД."""
        text = _doc_text()
        assert re.search(r"(read.?only|только\s+чтение|read-?only\s+пользовател)", text, re.I), (
            "Рекомендация RP4 (read-only креды — серверная защита поверх "
            "лексического guard'а) не задокументирована"
        )

    def test_row_limit_streaming_documented(self):
        """S4: принудительный потолок + chunksize-стриминг отражены."""
        text = _doc_text().lower()
        assert "chunksize" in text or "чанк" in text

    def test_password_not_in_url_documented(self):
        """D4: пароль не попадает в строку соединения — задокументировано."""
        text = _doc_text()
        assert re.search(r"(не\s+попадает\s+в\s+URL|вне\s+URL|НЕ\s+включается\s+в\s+URL|not\s+in\s+url)", text, re.I)

    def test_licensing_note_not_required_but_timeout_ok(self):
        """Таймауты 10с/60с (S4) отражены (строка дефолтов)."""
        text = _doc_text()
        assert str(DEFAULT_CONNECT_TIMEOUT) in text and str(DEFAULT_QUERY_TIMEOUT) in text


# ── 6. ARCHITECTURE.md: реестр коннекторов + roadmap DATA CONTRACTS ───────


class TestUploadDb9Architecture:
    """ARCHITECTURE.md описывает реестр коннекторов и статус Data Contracts."""

    def test_registry_section_exists(self):
        arch = _read(ARCHITECTURE)
        assert re.search(r"РЕЕСТР\w*\s+КОННЕКТОР\w*", arch, re.I), (
            "В ARCHITECTURE.md нет раздела реестра коннекторов"
        )

    def test_registry_points_to_code(self):
        arch = _read(ARCHITECTURE)
        assert "app/data/db_connectors.py" in arch, (
            "Раздел реестра не ссылается на единственную точку знания о СУБД"
        )
        assert "DbConnectorSpec" in arch, (
            "Контракт записи реестра (DbConnectorSpec) не назван"
        )

    def test_architecture_mentions_decisions(self):
        """Архитектурные решения плана названы кодовыми метками."""
        arch = _read(ARCHITECTURE)
        for marker in ("D1", "D3", "D4"):
            assert marker in arch

    def test_data_contracts_roadmap_note(self):
        """Раздел DATA CONTRACTS несёт пометку roadmap (решение плана)."""
        arch = _read(ARCHITECTURE)
        m = re.search(r"##\s*DATA CONTRACTS[\s\S]{0,4000}", arch)
        assert m, "Раздел DATA CONTRACTS не найден в ARCHITECTURE.md"
        section = m.group(0)
        assert re.search(r"(roadmap|UPLOAD-DB)", section, re.I), (
            "В DATA CONTRACTS нет пометки roadmap про реестр коннекторов"
        )


# ── 7. Справка подключения (перенос UI_HELP app.py:812-918) ───────────────


class TestUploadDb9HelpDoc:
    """Справка подключения покрывает серверные настройки 6 СУБД."""

    def test_help_doc_exists_with_title(self):
        help_text = _read(HELP_DOC)
        assert "Подключение" in help_text or "подключени" in help_text

    def test_postgresql_server_setup(self):
        help_text = _read(HELP_DOC)
        assert "pg_hba.conf" in help_text, "pg_hba.conf (перенос UI_HELP) отсутствует"
        assert "sslmode" in help_text, "sslmode (D3) отсутствует"
        assert "listen_addresses" in help_text

    def test_clickhouse_setup(self):
        help_text = _read(HELP_DOC)
        assert "users.xml" in help_text, "users.xml (перенос UI_HELP) отсутствует"
        assert "8123" in help_text

    def test_mssql_setup(self):
        help_text = _read(HELP_DOC)
        assert "ODBC Driver 18" in help_text
        assert "Encrypt" in help_text
        assert "TrustServerCertificate" in help_text

    def test_mysql_setup(self):
        help_text = _read(HELP_DOC)
        assert re.search(r"(CREATE USER|создани\w+ пользовател)", help_text, re.I), (
            "Настройка MySQL-пользователя отсутствует"
        )
        assert "caching_sha2_password" in help_text

    def test_embedded_readonly_documented(self):
        help_text = _read(HELP_DOC)
        assert re.search(r"mode\s*=\s*ro", help_text), (
            "SQLite read-only URI (mode=ro) не задокументирован"
        )
        assert re.search(r"read_only\s*=\s*True", help_text), (
            "DuckDB read_only=True не задокументирован"
        )

    def test_common_problems_table(self):
        """Перенос раздела «Устранение частых проблем» UI_HELP."""
        help_text = _read(HELP_DOC)
        assert re.search(r"(част\w+\s+проблем|Частые\s+проблемы|Устранение)", help_text, re.I)

    def test_platform_env_reference(self):
        """Справка ссылается на env-лимиты платформы (S4/D5)."""
        help_text = _read(HELP_DOC)
        assert "UPLOAD_DB_ROW_LIMIT" in help_text
        assert "UPLOAD_DB_HOST_WHITELIST" in help_text


# ── 8. Смоук-чеклист релиза (DoD) ──────────────────────────────────────────


class TestUploadDb9SmokeChecklist:
    """Смоук-чеклист релиза покрывает контур UPLOAD-DB."""

    def test_smoke_doc_exists(self):
        smoke = _read(SMOKE_DOC)
        assert re.search(r"(смоук|smoke)", smoke, re.I)

    def test_smoke_covers_api_endpoints(self):
        smoke = _read(SMOKE_DOC)
        assert "upload/db/test" in smoke and "upload/db/load" in smoke

    def test_smoke_covers_embedded_ci_pair(self):
        """CI-класс матрицы: SQLite + DuckDB сквозной Test→Load."""
        smoke = _read(SMOKE_DOC)
        assert "SQLite" in smoke and "DuckDB" in smoke

    def test_smoke_covers_negative_paths(self):
        """Негативные смоук-сценарии: guard/whitelist/маскирование."""
        smoke = _read(SMOKE_DOC)
        assert "422" in smoke
        assert re.search(r"(маскир|mask)", smoke, re.I)

    def test_smoke_covers_env_overrides(self):
        smoke = _read(SMOKE_DOC)
        assert "UPLOAD_DB_ROW_LIMIT" in smoke
        assert "UPLOAD_DB_MSSQL_DRIVER" in smoke

    def test_smoke_covers_docker_build_guards(self):
        smoke = _read(SMOKE_DOC)
        assert "INSTALL_MSODBCSQL18" in smoke

    def test_smoke_states_ui_status_honestly(self):
        """Честный статус UI-дорожки (форма — заглушка, UPLOAD-DB-5 — roadmap)."""
        smoke = _read(SMOKE_DOC)
        assert re.search(r"(заглушк|UPLOAD-DB-5)", smoke, re.I)


# ── 9. Раздел «Обучение»: статья базы знаний ──────────────────────────────


class TestUploadDb9KnowledgeArticle:
    """Статья «Обучение» присутствует в реестре базы знаний."""

    def test_article_registered(self):
        articles = _read(ARTICLES)
        assert 'article_id: "upload-db-connections"' in articles, (
            "Статья справки подключения не зарегистрирована в базе знаний"
        )

    def test_article_stage_and_status(self):
        articles = _read(ARTICLES)
        m = re.search(
            r'article_id:\s*"upload-db-connections"[\s\S]{0,12000}?status:\s*"[a-z]+"',
            articles,
        )
        assert m, "Статья upload-db-connections неполна (нет статуса)"
        assert 'stage_id: "upload"' in m.group(0), (
            "Статья привязана не к стадии «Загрузка»"
        )
        assert 'status: "published"' in m.group(0), "Статья не опубликована"

    def test_article_covers_servers_and_readonly(self):
        articles = _read(ARTICLES)
        m = re.search(
            r'article_id:\s*"upload-db-connections"[\s\S]{0,8000}?(?=\n  \{|\n\];)',
            articles,
        )
        assert m, "Тело статьи не найдено"
        body = m.group(0)
        for token in ("Postgres", "ClickHouse", "read-only", "SELECT"):
            assert token in body, f"В статье нет «{token}»"


# ── 10. README: ссылки на документацию задачи ─────────────────────────────


class TestUploadDb9CrossReferences:
    """README связывает раздел БД с документацией задачи."""

    def test_readme_links_help_doc(self):
        readme = _read(README)
        assert "docs/upload_db_connections_help.md" in readme

    def test_readme_links_smoke_doc(self):
        readme = _read(README)
        assert "docs/upload_db_release_smoke_checklist.md" in readme

    def test_readme_honest_ui_status(self):
        """README честно указывает статус UI-формы (заглушка — roadmap)."""
        readme = _read(README)
        assert re.search(r"(заглушк)", readme, re.I), (
            "README умалчивает, что UI-форма подключения — заглушка"
        )

    def test_readme_states_epic_scope(self):
        """README называет эпик UPLOAD-DB и спеку плана."""
        readme = _read(README)
        assert "UPLOAD-DB" in readme
        assert "spec_database_plan.md" in readme
