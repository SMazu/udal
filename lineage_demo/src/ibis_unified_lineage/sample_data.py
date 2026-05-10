from __future__ import annotations

import pandas as pd


def sample_frames() -> dict[str, pd.DataFrame]:
    return {
        "orders": pd.DataFrame(
            [
                {
                    "order_id": 1,
                    "customer_id": 101,
                    "order_month": "2026-01",
                    "quantity": 2,
                    "unit_price": 100.0,
                    "discount_pct": 0.10,
                    "currency": "EUR",
                    "status": "paid",
                    "promo_id": 9001,
                },
                {
                    "order_id": 2,
                    "customer_id": 102,
                    "order_month": "2026-01",
                    "quantity": 1,
                    "unit_price": 200.0,
                    "discount_pct": 0.00,
                    "currency": "USD",
                    "status": "paid",
                    "promo_id": 9002,
                },
                {
                    "order_id": 3,
                    "customer_id": 101,
                    "order_month": "2026-02",
                    "quantity": 3,
                    "unit_price": 50.0,
                    "discount_pct": 0.05,
                    "currency": "EUR",
                    "status": "cancelled",
                    "promo_id": 9001,
                },
                {
                    "order_id": 4,
                    "customer_id": 103,
                    "order_month": "2026-01",
                    "quantity": 5,
                    "unit_price": 20.0,
                    "discount_pct": 0.00,
                    "currency": "GBP",
                    "status": "paid",
                    "promo_id": 9003,
                },
                {
                    "order_id": 5,
                    "customer_id": 104,
                    "order_month": "2026-02",
                    "quantity": 4,
                    "unit_price": 80.0,
                    "discount_pct": 0.15,
                    "currency": "USD",
                    "status": "paid",
                    "promo_id": 9002,
                },
            ]
        ),
        "customers": pd.DataFrame(
            [
                {"customer_id": 101, "region": "EMEA", "segment": "enterprise"},
                {"customer_id": 102, "region": "NA", "segment": "midmarket"},
                {"customer_id": 103, "region": "EMEA", "segment": "consumer"},
                {"customer_id": 104, "region": "NA", "segment": "enterprise"},
            ]
        ),
        "fx_rates": pd.DataFrame(
            [
                {"currency": "EUR", "rate_month": "2026-01", "rate_to_usd": 1.10},
                {"currency": "EUR", "rate_month": "2026-02", "rate_to_usd": 1.12},
                {"currency": "GBP", "rate_month": "2026-01", "rate_to_usd": 1.25},
                {"currency": "USD", "rate_month": "2026-01", "rate_to_usd": 1.00},
                {"currency": "USD", "rate_month": "2026-02", "rate_to_usd": 1.00},
            ]
        ),
        "promotions": pd.DataFrame(
            [
                {"promo_id": 9001, "channel": "email", "promo_discount_pct": 0.05},
                {"promo_id": 9002, "channel": "search", "promo_discount_pct": 0.10},
                {"promo_id": 9003, "channel": "retail", "promo_discount_pct": 0.00},
            ]
        ),
        "returns": pd.DataFrame(
            [
                {"order_id": 1, "is_returned": False, "return_fee": 0.0},
                {"order_id": 2, "is_returned": True, "return_fee": 12.0},
                {"order_id": 4, "is_returned": False, "return_fee": 0.0},
                {"order_id": 5, "is_returned": False, "return_fee": 0.0},
            ]
        ),
    }


def expected_monthly_revenue() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "region": "EMEA",
                "segment": "consumer",
                "channel": "retail",
                "order_month": "2026-01",
                "total_net_usd": 125.0,
                "gross_local": 100.0,
                "active_customers": 1,
                "returned_orders": 0,
            },
            {
                "region": "EMEA",
                "segment": "enterprise",
                "channel": "email",
                "order_month": "2026-01",
                "total_net_usd": 188.1,
                "gross_local": 200.0,
                "active_customers": 1,
                "returned_orders": 0,
            },
            {
                "region": "NA",
                "segment": "enterprise",
                "channel": "search",
                "order_month": "2026-02",
                "total_net_usd": 244.8,
                "gross_local": 320.0,
                "active_customers": 1,
                "returned_orders": 0,
            },
            {
                "region": "NA",
                "segment": "midmarket",
                "channel": "search",
                "order_month": "2026-01",
                "total_net_usd": 168.0,
                "gross_local": 200.0,
                "active_customers": 1,
                "returned_orders": 1,
            },
        ]
    )
