#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_MATRIX="${PYTHON_MATRIX:-3.10 3.11 3.12 3.13 3.14}"

rm -rf dist
uv build

wheel="$(find dist -name '*.whl' -type f | sort | tail -n 1)"
if [[ -z "${wheel}" ]]; then
  echo "No wheel found in dist/" >&2
  exit 1
fi
wheel_path="$(pwd)/${wheel}"

for python_version in ${PYTHON_MATRIX}; do
  echo "==> Testing ${wheel_path} on Python ${python_version}"
  uv run \
    --no-project \
    --isolated \
    --python "${python_version}" \
    --with "${wheel_path}" \
    --with pytest \
    python -c 'from ibis_unified_lineage.config import default_config_path; import ibis_unified_lineage, pathlib, sys; package_path = pathlib.Path(ibis_unified_lineage.__file__).resolve(); print(sys.version.split()[0], package_path); assert "site-packages" in str(package_path); assert default_config_path().exists()'
  uv run \
    --no-project \
    --isolated \
    --python "${python_version}" \
    --with "${wheel_path}" \
    --with pytest \
    pytest -c pytest-wheel.ini tests
done
