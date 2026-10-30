import os
os.environ["JOBMVP_API_KEY"] = "k"
import pytest
from fastapi.testclient import TestClient
from console import app as capp
from tests.test_pipeline import Fake, J

H = {"X-API-Key": "k"}

@pytest.fixture()
def client(conn):
    return TestClient(capp.app)

def test_auth_required(client):
    assert client.get("/api/sources").status_code == 401
    assert client.get("/api/sources", headers={"X-API-Key": "bad"}).status_code == 401

def test_enable_rules_and_audit(client, conn):
    conn.execute("INSERT INTO source_config(source_id,name,tier,field_whitelist) VALUES ('b1','b','B','{}')"); conn.commit()
    assert client.post("/api/sources/b1/enable", json={"enabled": True}, headers=H).status_code == 422
    assert client.post("/api/sources/b1/enable", json={"enabled": True, "approval_note": "LEGAL-001"}, headers=H).status_code == 200
    assert client.get("/api/audit", headers=H).json()[0]["action"] == "source_enable"
    assert client.post("/api/sources/nope/enable", json={"enabled": True}, headers=H).status_code == 404

def test_trigger_run_and_views(client, conn):
    capp.REGISTRY["fx"] = lambda: Fake([[J(1), J(2)]])
    capp.run_source.__defaults__  # 仅确认可导入
    r = client.post("/api/sources/fx/run", headers=H)        # TestClient 会同步执行 BackgroundTasks（真实 raw_root 为相对路径 data/raw）
    assert r.status_code == 202
    runs = client.get("/api/sources/fx/runs", headers=H).json()
    assert runs[0]["status"] == "success" and runs[0]["parsed"] == 2
    assert client.get("/api/quality", headers=H).json()[0]["total"] == 2
    assert client.get("/api/metrics/new_jobs_daily", headers=H).json()["version"] == "v1"
    assert client.get("/api/metrics/pg_user;drop", headers=H).status_code == 404
    conn.execute("UPDATE source_config SET enabled=false"); conn.commit()
    assert client.post("/api/sources/fx/run", headers=H).status_code == 409
