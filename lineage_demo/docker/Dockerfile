FROM ghcr.io/astral-sh/uv:0.11.13 AS uv

FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    libmariadb-dev \
    mariadb-server \
    openjdk-17-jre-headless \
    pkg-config \
    postgresql \
    postgresql-contrib \
    procps \
  && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

WORKDIR /app

COPY lineage_demo/pyproject.toml /app/pyproject.toml
COPY lineage_demo/uv.lock /app/uv.lock
COPY lineage_demo/.python-version /app/.python-version
COPY lineage_demo/pytest-wheel.ini /app/pytest-wheel.ini
COPY lineage_demo/src /app/src
COPY lineage_demo/tests /app/tests
COPY lineage_demo/fixtures /app/fixtures
COPY lineage_demo/scripts /app/scripts

RUN uv sync --locked --extra mysql --dev --no-editable --python 3.11

COPY lineage_demo/docker/entrypoint.sh /usr/local/bin/lineage-entrypoint
RUN chmod +x /usr/local/bin/lineage-entrypoint

VOLUME ["/artifacts"]

ENTRYPOINT ["lineage-entrypoint"]
CMD ["uv", "run", "--locked", "--extra", "mysql", "--no-editable", "python", "-m", "ibis_unified_lineage.demo_run", "--service-mode", "--artifacts", "/artifacts"]
