FROM ghcr.io/astral-sh/uv:python3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_COMPILE_BYTECODE=1
WORKDIR /app

# 先只拷贝依赖清单，利用 Docker 层缓存（依赖不变时不重装）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# 启动前执行迁移（幂等），data/ 由卷挂载持久化
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"]

EXPOSE 8000
