FROM ghcr.io/astral-sh/uv:0.8.17 AS uv
FROM python:3.12-slim AS base
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
COPY core ./core
COPY adapters ./adapters
COPY server ./server
COPY sim ./sim
COPY evals ./evals
RUN uv sync --frozen --no-dev

FROM base AS server
EXPOSE 8765
CMD ["donewise-server"]

FROM base AS sim
EXPOSE 8080
CMD ["uvicorn", "donewise_sim.app:build_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
