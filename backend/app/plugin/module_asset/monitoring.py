"""只读 Watch 适配层：按租户投影指标，失败不进入资产业务事务。"""

import asyncio
import math
from datetime import UTC, datetime
from functools import lru_cache
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit

import httpx
from prometheus_client.parser import text_string_to_metric_families
from pydantic import BaseModel, Field, SecretStr, ValidationError, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.setting import Settings
from app.core.logger import log

CACHE_SECONDS = 15
STALE_SECONDS = 300
FETCH_TIMEOUT_SECONDS = 3
MAX_METRICS_BYTES = 1024 * 1024


class WatchSettings(BaseSettings):
    model_config = SettingsConfigDict(**{**Settings.model_config, "env_prefix": "SANAS_WATCH_"})

    ENABLED: bool = False
    # 仅在管理员明确配置的可信容器网络中使用；公网仍应使用 HTTPS。
    ALLOW_INSECURE_HTTP: bool = False
    BASE_URL: str = "http://127.0.0.1:3001"
    API_KEY: SecretStr = SecretStr("")
    # {租户编号: {Watch 监控编号: 本地展示名称}}；不暴露上游 URL、标签或名称。
    MONITORS: dict[int, dict[int, str]] = Field(default_factory=dict)

    @field_validator("BASE_URL")
    @classmethod
    def validate_base_url(cls, value: str, info: ValidationInfo) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            raise ValueError("Watch 地址必须是无凭据、路径和查询参数的 HTTP(S) 源站")
        if (
            parts.scheme == "http"
            and parts.hostname not in {"127.0.0.1", "::1", "localhost"}
            and not info.data.get("ALLOW_INSECURE_HTTP", False)
        ):
            raise ValueError("非本机 Watch 必须使用 HTTPS")
        _ = parts.port  # 同时验证端口格式与范围。
        return value.rstrip("/")

    @field_validator("MONITORS")
    @classmethod
    def validate_monitors(cls, value: dict[int, dict[int, str]]) -> dict[int, dict[int, str]]:
        if len(value) > 100 or any(
            tenant <= 0
            or len(monitors) > 20
            or any(mid <= 0 or not name.strip() or len(name) > 80 for mid, name in monitors.items())
            for tenant, monitors in value.items()
        ):
            raise ValueError("最多配置 100 个租户，每租户 20 个正整数监控编号及 1–80 字名称")
        return value


@lru_cache(maxsize=1)
def watch_settings() -> WatchSettings:
    return WatchSettings()


class WatchMonitor(BaseModel):
    id: int
    name: str
    status: Literal["up", "down", "pending", "maintenance", "unknown"] = "unknown"
    response_ms: float | None = None
    uptime_24h_percent: float | None = None


class WatchSnapshot(BaseModel):
    state: Literal["disabled", "not_configured", "live", "stale", "unavailable"]
    fetched_at: datetime | None = None
    age_seconds: int | None = None
    monitors: list[WatchMonitor] = Field(default_factory=list)


def parse_metrics(text: str, allowed: set[int]) -> dict[int, dict[str, str | float]]:
    """仅提取上游已实现的三个指标；缺失/非有限值不伪造为健康。"""
    readings: dict[int, dict[str, str | float]] = {}
    statuses = {0: "down", 1: "up", 2: "pending", 3: "maintenance"}
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name not in {
                "monitor_status",
                "monitor_response_time",
                "monitor_uptime_ratio",
            }:
                continue
            raw_id = sample.labels.get("monitor_id", "")
            if not raw_id.isascii() or not raw_id.isdecimal() or int(raw_id) not in allowed:
                continue
            value = float(sample.value)
            if not math.isfinite(value):
                continue
            reading = readings.setdefault(int(raw_id), {})
            if sample.name == "monitor_status" and value in statuses:
                reading["status"] = statuses[value]
            elif sample.name == "monitor_response_time" and value >= 0:
                reading["response_ms"] = value
            elif (
                sample.name == "monitor_uptime_ratio"
                and sample.labels.get("window") == "1d"
                and 0 <= value <= 1
            ):
                reading["uptime_24h_percent"] = value * 100
    return readings


class WatchAdapter:
    """单进程内合并刷新；失败也缓存，避免下游故障时请求风暴。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._retry_at = 0.0
        self._success_at: float | None = None
        self._fetched_at: datetime | None = None
        self._readings: dict[int, dict[str, str | float]] = {}
        self._failed = False

    async def _fetch(self, config: WatchSettings) -> dict[int, dict[str, str | float]]:
        # 禁用重定向与环境代理，避免把服务端密钥转送给其他目标。
        async with asyncio.timeout(FETCH_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(
                timeout=FETCH_TIMEOUT_SECONDS,
                trust_env=False,
                follow_redirects=False,
                auth=httpx.BasicAuth("", config.API_KEY.get_secret_value()),
            ) as client:
                async with client.stream("GET", config.BASE_URL + "/metrics") as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_METRICS_BYTES:
                            raise ValueError("metrics_too_large")
        allowed = {mid for monitors in config.MONITORS.values() for mid in monitors}
        return parse_metrics(body.decode("utf-8"), allowed)

    async def snapshot(self, tenant_id: int) -> WatchSnapshot:
        try:
            config = watch_settings()
        except (ValidationError, ValueError):
            # 错误配置不能阻止应用启动或将环境中的凭据写入响应/日志。
            return WatchSnapshot(state="not_configured")
        if not config.ENABLED:
            return WatchSnapshot(state="disabled")
        monitors = config.MONITORS.get(tenant_id, {})
        if not monitors or not config.API_KEY.get_secret_value():
            return WatchSnapshot(state="not_configured")

        async with self._lock:
            if monotonic() >= self._retry_at:
                try:
                    readings = await self._fetch(config)
                except (httpx.HTTPError, TimeoutError, ValueError, UnicodeError) as exc:
                    self._failed = True
                    log.warning("Watch 指标读取失败 ({})", type(exc).__name__)
                else:
                    self._readings = readings
                    self._success_at = monotonic()
                    self._fetched_at = datetime.now(UTC)
                    self._failed = False
                self._retry_at = monotonic() + CACHE_SECONDS

        age = int(monotonic() - self._success_at) if self._success_at is not None else None
        if age is None or age >= STALE_SECONDS:
            return WatchSnapshot(state="unavailable")
        result = []
        for mid, name in monitors.items():
            reading = self._readings.get(mid, {})
            status = reading.get("status", "unknown")
            result.append(
                WatchMonitor.model_validate({
                    "id": mid,
                    "name": name,
                    "status": status,
                    "response_ms": reading.get("response_ms") if status == "up" else None,
                    "uptime_24h_percent": reading.get("uptime_24h_percent"),
                })
            )
        return WatchSnapshot(
            state="stale" if self._failed else "live",
            fetched_at=self._fetched_at,
            age_seconds=age,
            monitors=result,
        )


watch_adapter = WatchAdapter()
