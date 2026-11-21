# -*- coding: utf-8 -*-
"""全局配置：从环境变量 / .env 读取，禁止硬编码密钥。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",  # 忽略 .env 中的 ZHLSZ_* 等 spider 用变量
    )

    app_name: str = "Green-OS API"
    app_version: str = "0.1.0"

    # 数据库：SQLite(WAL) 起步，切 PG 时仅改 DATABASE_URL（ADR-2）
    database_url: str = "sqlite:///./data/app.db"

    # JWT
    jwt_secret: str = "dev-secret-change-me"  # 生产必须通过 .env 覆盖
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720  # 12h

    # 业务常量（PRD 决议 D4：逾期保留期默认 3 天，可配置）
    task_expire_days: int = 3

    # CORS（逗号分隔）
    cors_origins: str = "http://localhost:5173,http://localhost"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
