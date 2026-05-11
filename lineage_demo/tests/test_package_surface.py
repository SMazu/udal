from __future__ import annotations

import ibis_unified_lineage


def test_public_package_surface_excludes_demo_helpers() -> None:
    """Verify the importable library surface stays independent of examples."""

    public_names = set(ibis_unified_lineage.__all__)

    assert "extract_lineage" in public_names
    assert "LineageGraph" in public_names
    assert "build_monthly_revenue_job" not in public_names
    assert "load_default_config" not in public_names
    assert "JobConfig" not in public_names
