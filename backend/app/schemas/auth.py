# -*- coding: utf-8 -*-
"""请求/响应模型（Pydantic v2）。"""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=64)


class OperatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: Literal["cs", "ops", "admin"]
    ext_cs_id: Optional[int] = None
    status: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    operator: OperatorOut
