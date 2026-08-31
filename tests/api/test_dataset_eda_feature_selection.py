from __future__ import annotations
import io
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from apps.api.main import app
from apps.api.session_store import reset_session_store_for_testing

client=TestClient(app)
@pytest.fixture(autouse=True)
def reset(): reset_session_store_for_testing(); client.cookies.clear(); yield; reset_session_store_for_testing(); client.cookies.clear()
def upload(frame):
    data=io.BytesIO(); frame.to_csv(data,index=False); data.seek(0)
    assert client.post("/v1/internal/upload",files={"file":("features.csv",data,"text/csv")}).status_code==200
def test_endpoint_returns_feature_selection_profile():
    n=100; rng=np.random.default_rng(2); x=rng.normal(size=n); y=np.r_[0,x[:-1]]+rng.normal(scale=.2,size=n)
    upload(pd.DataFrame({"Date":pd.date_range("2024-01-01",periods=n,freq="D"),"Y":y,"X":x,"Noise":rng.normal(size=n)}))
    response=client.get("/v1/session/dataset/eda-feature-selection",params={"column":"Y","difference_order":1})
    assert response.status_code==200, response.text
    body=response.json(); assert body["features"] and body["difference_order"]==1 and body["correlation_matrix"]

def test_endpoint_validates_session_and_column():
    assert client.get("/v1/session/dataset/eda-feature-selection",params={"column":"Y"}).status_code==404
