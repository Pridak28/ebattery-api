from __future__ import annotations


SOURCE_KIND_PUBLIC_ESTIMATED = "public_estimated"
SOURCE_KIND_PUBLIC_OBSERVED_SYSTEM = "public_observed_system"
SOURCE_KIND_PUBLIC_AGGREGATE = "public_aggregate"
SOURCE_KIND_DERIVED_PUBLIC = "derived_public"
SOURCE_KIND_PARTICIPANT_EXPORT = "participant_export"
SOURCE_KIND_SETTLEMENT_EXPORT = "settlement_export"
SOURCE_KIND_UNVERIFIED_SNAPSHOT = "unverified_snapshot"
SOURCE_KIND_SCENARIO = "scenario"

SOURCE_KINDS = {
    SOURCE_KIND_PUBLIC_ESTIMATED,
    SOURCE_KIND_PUBLIC_OBSERVED_SYSTEM,
    SOURCE_KIND_PUBLIC_AGGREGATE,
    SOURCE_KIND_DERIVED_PUBLIC,
    SOURCE_KIND_PARTICIPANT_EXPORT,
    SOURCE_KIND_SETTLEMENT_EXPORT,
    SOURCE_KIND_UNVERIFIED_SNAPSHOT,
    SOURCE_KIND_SCENARIO,
}

BANKABLE_SOURCE_KINDS = {
    SOURCE_KIND_PARTICIPANT_EXPORT,
    SOURCE_KIND_SETTLEMENT_EXPORT,
}

PUBLIC_OR_UNVERIFIED_SOURCE_KINDS = SOURCE_KINDS - BANKABLE_SOURCE_KINDS

REQUIRED_DAMAS_COLUMNS = (
    "date",
    "slot",
    "price_eur_mwh",
    "afrr_up_activated_mwh",
    "afrr_down_activated_mwh",
    "afrr_up_price_eur",
    "afrr_down_price_eur",
)


def is_damas_shaped(columns) -> bool:
    cols = set(columns)
    return all(col in cols for col in REQUIRED_DAMAS_COLUMNS)


def bankability_level_for_source(source_kind: str | None) -> str:
    if source_kind in BANKABLE_SOURCE_KINDS:
        return "bankable_settlement"
    if source_kind == SOURCE_KIND_UNVERIFIED_SNAPSHOT:
        return "historical_backtest_only"
    if source_kind in PUBLIC_OR_UNVERIFIED_SOURCE_KINDS:
        return "scenario_public_market_only"
    return "needs_source_classification"
