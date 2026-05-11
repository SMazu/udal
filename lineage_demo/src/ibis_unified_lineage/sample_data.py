from __future__ import annotations

import pandas as pd

from ibis_unified_lineage.config import load_default_config


def sample_frames() -> dict[str, pd.DataFrame]:
    """Load the canonical monthly-revenue input fixtures.

    Returns:
        Input frames keyed by the Ibis table names used by
        `build_monthly_revenue_job`.
    """

    return load_default_config().load_frames()


def expected_monthly_revenue() -> pd.DataFrame:
    """Load the expected monthly-revenue output fixture.

    Returns:
        Expected output frame for the configured demo job.
    """

    expected = load_default_config().load_expected_frame()
    if expected is None:
        raise ValueError("The built-in monthly revenue config has no expected_csv")
    return expected
