"""健康探针契约测试；替换外部依赖，不启动初始化、调度器或真实数据库。"""

import asyncio
import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# 上游模块在 __init__ 中注册路由；沿用应用先装载 system 再装载 common 的顺序。
importlib.import_module("app.api.v1.module_system")
health = importlib.import_module("app.api.v1.module_common.health.controller")


@pytest.fixture
def health_dependencies(monkeypatch):
    execute = AsyncMock(return_value=None)
    redis = SimpleNamespace(ping=AsyncMock(return_value=True))

    @asynccontextmanager
    async def begin():
        yield

    @asynccontextmanager
    async def session():
        yield SimpleNamespace(begin=begin, execute=execute)

    monkeypatch.setattr(health, "async_db_session", session)
    monkeypatch.setattr(health.settings, "SQL_DB_ENABLE", True)
    monkeypatch.setattr(health.settings, "REDIS_ENABLE", True)
    return SimpleNamespace(execute=execute, redis=redis)


@pytest.fixture
def test_client(health_dependencies):
    app = FastAPI()
    app.include_router(health.HealthRouter, prefix="/common")
    app.state.redis = health_dependencies.redis
    with TestClient(app) as client:
        yield client


def test_check_readiness(test_client, health_dependencies):
    response = test_client.get("/common/health/ready/")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == {"checks": {"database": True, "redis": True}, "errors": None}
    assert str(health_dependencies.execute.await_args.args[0]) == "SELECT 1"
    health_dependencies.redis.ping.assert_awaited_once()


def test_check_health(test_client, health_dependencies):
    response = test_client.get("/common/health/")
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "code": 0,
        "msg": "系统健康",
        "data": True,
        "status_code": 200,
    }
    health_dependencies.execute.assert_not_called()
    health_dependencies.redis.ping.assert_not_called()


@pytest.mark.parametrize("dependency", ["database", "redis"])
def test_readiness_dependency_failure_is_503_without_connection_details(
    test_client,
    health_dependencies,
    dependency,
):
    operation = (
        health_dependencies.execute if dependency == "database" else health_dependencies.redis.ping
    )
    operation.side_effect = RuntimeError("driver://private_user:private_password@internal_host/db")
    response = test_client.get("/common/health/ready/")
    assert response.status_code == 503
    body = response.json()
    assert body["success"] is False
    assert body["data"]["checks"][dependency] is False
    assert body["data"]["errors"] == [f"{dependency}:unavailable"]
    assert "private_password" not in response.text
    assert test_client.get("/common/health/").status_code == 200


def test_readiness_missing_redis(test_client):
    del test_client.app.state.redis
    response = test_client.get("/common/health/ready/")
    assert response.status_code == 503
    assert response.json()["data"]["checks"] == {"database": True, "redis": False}


def test_readiness_disabled_redis_is_optional(test_client, health_dependencies, monkeypatch):
    monkeypatch.setattr(health.settings, "REDIS_ENABLE", False)
    response = test_client.get("/common/health/ready/")
    assert response.status_code == 200
    assert response.json()["data"]["checks"] == {"database": True, "redis": None}
    health_dependencies.redis.ping.assert_not_called()


def test_readiness_disabled_database_is_not_ready(test_client, health_dependencies, monkeypatch):
    monkeypatch.setattr(health.settings, "SQL_DB_ENABLE", False)
    response = test_client.get("/common/health/ready/")
    assert response.status_code == 503
    assert response.json()["data"]["checks"]["database"] is False
    health_dependencies.execute.assert_not_called()


@pytest.mark.parametrize("dependency", ["database", "redis"])
def test_readiness_times_out_a_stalled_dependency(
    test_client,
    health_dependencies,
    monkeypatch,
    dependency,
):
    async def stalled(*args):
        await asyncio.sleep(0.1)

    operation = (
        health_dependencies.execute if dependency == "database" else health_dependencies.redis.ping
    )
    operation.side_effect = stalled
    monkeypatch.setattr(health, "READINESS_TIMEOUT_SECONDS", 0.01, raising=False)
    response = test_client.get("/common/health/ready/")
    assert response.status_code == 503
    assert response.json()["data"]["checks"][dependency] is False


def test_health_openapi_reports_boolean_data(test_client):
    schema = test_client.get("/openapi.json").json()
    response = schema["paths"]["/common/health/"]["get"]["responses"]["200"]
    name = response["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
    data = schema["components"]["schemas"][name]["properties"]["data"]
    assert {option["type"] for option in data["anyOf"]} == {"boolean", "null"}
