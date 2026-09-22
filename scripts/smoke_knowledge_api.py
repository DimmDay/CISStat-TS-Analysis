# scripts/smoke_knowledge_api.py
"""
Смоук Шага 4 EDU (Task EDU-API-1): живые вызовы новых эндпоинтов
через TestClient — демонстрация контрактов на реальных данных.

Запуск: source /home/z/.venv/bin/activate && python scripts/smoke_knowledge_api.py
"""
from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def show(title, resp, keys=None):
    print(f"\n── {title}")
    print(f"   HTTP {resp.status_code}")
    body = resp.json()
    if isinstance(body, dict) and keys:
        print("   keys:", {k: body[k] for k in keys})
    elif isinstance(body, dict) and "articles" in body:
        print(f"   articles: {len(body['articles'])} шт.")
        for a in body["articles"][:3]:
            print("     ·", a["article_id"], "|", a["title"][:48])
        if len(body["articles"]) > 3:
            print(f"     … ещё {len(body['articles']) - 3}")
    elif isinstance(body, dict) and "terms" in body:
        print(f"   terms: {len(body['terms'])} шт. →", [t["term_id"] for t in body["terms"][:4]], "…")
    elif isinstance(body, dict) and "directions" in body:
        print("   directions:", body["directions"])
        print("   articles:", [a["article_id"] for a in body["articles"]])
        print("   terms:", [t["term_id"] for t in body["terms"]])
        print("   missing_directions:", body["missing_directions"])
    else:
        print("   body:", str(body)[:220])


# 1. Библиотека целиком (порядок пайплайна, draft исключён)
show("GET /v1/knowledge/articles (все published)", client.get("/v1/knowledge/articles"))

# 2. Библиотека этапа
show("GET /v1/knowledge/articles?stage_id=eda", client.get("/v1/knowledge/articles", params={"stage_id": "eda"}))

# 3. Справка узла (окно «Описание», секция «Метрики и алгоритм»)
r = client.get("/v1/knowledge/articles", params={"stage_id": "eda", "node_id": "correlation", "facet": "metrics"})
print("\n── GET ?stage_id=eda&node_id=correlation&facet=metrics")
print("   HTTP", r.status_code, "→", r.json()["article_id"])
print("   body_md[:160]:", r.json()["body_md"][:160].replace("\n", " ⏎ "))

# 4. Честный null «справка готовится»
r = client.get("/v1/knowledge/articles", params={"stage_id": "eda", "node_id": "future_node", "facet": "metrics"})
print("\n── GET ?…unknown node…  → HTTP", r.status_code, "body:", r.json())

# 5. module_help без node_id
r = client.get("/v1/knowledge/articles", params={"stage_id": "forecasting", "facet": "module_help"})
print("\n── GET ?stage_id=forecasting&facet=module_help →", r.json()["article_id"])

# 6. stage_overview стадии графа Моделирования
r = client.get("/v1/knowledge/articles", params={"stage_id": "modeling", "node_id": "tuning", "facet": "stage_overview"})
print("── GET ?stage_id=modeling&node_id=tuning&facet=stage_overview →", r.json()["article_id"])

# 7. Ошибки словаря и неполного ключа
for params in ({"stage_id": "bogus"}, {"stage_id": "eda", "node_id": "correlation"},
               {"facet": "metrics"}, {"stage_id": "eda", "facet": "library"}):
    r = client.get("/v1/knowledge/articles", params=params)
    print(f"── GET {params} → HTTP {r.status_code} ({r.json().get('detail', '')[:60]})")

# 8. Словарь
show("GET /v1/knowledge/glossary", client.get("/v1/knowledge/glossary"))
show("GET /v1/knowledge/glossary?stage_id=modeling", client.get("/v1/knowledge/glossary", params={"stage_id": "modeling"}))

# 9. Обучающие стеки
show("POST /v1/learning/track [seasonality, intervals]",
     client.post("/v1/learning/track", json={"directions": ["seasonality", "intervals"]}))
show("POST /v1/learning/track [volatility] (честная маркировка)",
     client.post("/v1/learning/track", json={"directions": ["volatility"]}))
r = client.post("/v1/learning/track", json={"directions": ["bogus"]})
print("── POST [bogus] → HTTP", r.status_code)

# 10. OpenAPI
schema = app.openapi()
print("\n── OpenAPI:", [p for p in schema["paths"] if "knowledge" in p or "learning" in p])
print("\nСМОУК ЗАВЕРШЁН")
