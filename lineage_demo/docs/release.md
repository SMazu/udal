# Release Checklist

This package is prepared for a future PyPI release, but the project owner must
confirm the package name, license, repository URL, and maintainers before the
first public upload.

Current official guidance to follow:

- PyPA project metadata guide:
  <https://packaging.python.org/guides/writing-pyproject-toml/>
- PyPI Trusted Publishing overview:
  <https://docs.pypi.org/trusted-publishers/>
- PyPI GitHub Actions publisher setup:
  <https://docs.pypi.org/trusted-publishers/using-a-publisher/>
- PyPI attestations:
  <https://docs.pypi.org/attestations/producing-attestations/>

## Preflight

Run from this directory:

```bash
uv sync --dev
uv run pytest tests
scripts/uv_test_matrix.sh
rm -rf dist
uv build
```

Inspect the wheel:

```bash
uv run python - <<'PY'
from pathlib import Path
from zipfile import ZipFile

wheel = sorted(Path("dist").glob("ibis_unified_lineage-*.whl"))[-1]
with ZipFile(wheel) as zf:
    names = zf.namelist()
print(wheel)
assert any(name.startswith("ibis_unified_lineage/") for name in names)
assert "ibis_unified_lineage/py.typed" in names
assert not any(name.startswith("examples/") for name in names)
assert not any("/fixtures/" in name for name in names)
PY
```

Run service verification from the parent repository root:

```bash
docker build -f lineage_demo/docker/Dockerfile -t ibis-unified-lineage-demo:latest .
docker run --rm -v "$PWD/lineage_demo/artifacts/docker-e2e:/artifacts" ibis-unified-lineage-demo:latest
docker run --rm --entrypoint /app/scripts/uv_test_matrix.sh ibis-unified-lineage-demo:latest
```

## PyPI Trusted Publishing

Preferred release flow:

1. Move this directory into its standalone repository or adapt the workflow
   working directory if it stays in a monorepo.
2. Confirm the final project name on PyPI and TestPyPI.
3. Configure a PyPI Trusted Publisher for the repository and workflow file.
4. Use a GitHub environment named `pypi` and require reviewer approval.
5. Publish from a GitHub Release using `.github/workflows/release.yml`.

Trusted Publishing uses GitHub OIDC and avoids long-lived API tokens. The PyPI
docs also note that the official PyPA publish action generates and uploads
attestations by default when publishing through Trusted Publishing.

## Versioning

The version currently appears in two places:

- `pyproject.toml`
- `src/ibis_unified_lineage/__init__.py`

Before release, update both together. A future agent may replace this with a
single-source version plugin, but avoid adding that complexity until the release
repository is finalized.

## Owner Decisions Before First Upload

- Choose and add a real license file.
- Confirm whether `ibis-unified-lineage` is the final PyPI name.
- Fill in `project.urls` once the repository URL exists.
- Decide whether the package should remain `Development Status :: 3 - Alpha`.
- Decide whether examples should be published in the sdist. They are excluded
  from the wheel but currently included in the sdist for handoff usefulness.
