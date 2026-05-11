FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

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

WORKDIR /app

COPY lineage_demo/pyproject.toml /app/pyproject.toml
COPY lineage_demo/src /app/src
COPY lineage_demo/tests /app/tests
COPY lineage_demo/fixtures /app/fixtures

RUN python -m pip install --upgrade pip \
  && python -m pip install -e '.[mysql,test]' pyspark==3.5.7 delta-spark==3.3.2

COPY lineage_demo/docker/entrypoint.sh /usr/local/bin/lineage-entrypoint
RUN chmod +x /usr/local/bin/lineage-entrypoint

VOLUME ["/artifacts"]

ENTRYPOINT ["lineage-entrypoint"]
CMD ["python", "-m", "ibis_unified_lineage.demo_run", "--service-mode", "--artifacts", "/artifacts"]
