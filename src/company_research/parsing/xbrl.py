from __future__ import annotations

from typing import Any

from company_research.models.evidence import MetricObservation

# XBRL concept → normalized metric name + unit
_CONCEPT_MAP: dict[str, tuple[str, str]] = {
    "Revenues": ("revenue", "USD"),
    "RevenueFromContractWithCustomerExcludingAssessedTax": ("revenue", "USD"),
    "SalesRevenueNet": ("revenue", "USD"),
    "GrossProfit": ("gross_profit", "USD"),
    "OperatingIncomeLoss": ("operating_income", "USD"),
    "NetIncomeLoss": ("net_income", "USD"),
    "EarningsPerShareBasic": ("eps_basic", "USD_per_share"),
    "EarningsPerShareDiluted": ("eps_diluted", "USD_per_share"),
    "CashAndCashEquivalentsAtCarryingValue": ("cash", "USD"),
    "LongTermDebt": ("long_term_debt", "USD"),
    "ResearchAndDevelopmentExpense": ("rd_expense", "USD"),
    "SellingGeneralAndAdministrativeExpense": ("sga_expense", "USD"),
    "CommonStockSharesOutstanding": ("shares_outstanding", "count"),
    "WeightedAverageNumberOfSharesOutstandingBasic": ("shares_basic", "count"),
    "WeightedAverageNumberOfDilutedSharesOutstanding": ("shares_diluted", "count"),
    "ShareBasedCompensation": ("stock_based_compensation", "USD"),
    "CapitalExpendituresContinuingOperations": ("capex", "USD"),
    "PaymentsToAcquirePropertyPlantAndEquipment": ("capex", "USD"),
    "NetCashProvidedByUsedInOperatingActivities": ("operating_cash_flow", "USD"),
    "NetCashProvidedByUsedInInvestingActivities": ("investing_cash_flow", "USD"),
    "NetCashProvidedByUsedInFinancingActivities": ("financing_cash_flow", "USD"),
    "Assets": ("total_assets", "USD"),
    "Liabilities": ("total_liabilities", "USD"),
    "StockholdersEquity": ("shareholders_equity", "USD"),
    "RetainedEarningsAccumulatedDeficit": ("retained_earnings", "USD"),
}


def _period_label(data: dict[str, Any]) -> tuple[str, str]:
    """Return (period_label, period_type) from an XBRL fact entry."""
    end = data.get("end", "")
    start = data.get("start", "")
    if start:
        # Annual or quarterly period
        from datetime import date
        try:
            s = date.fromisoformat(start)
            e = date.fromisoformat(end)
            days = (e - s).days
            if days > 350:
                return f"FY_{end[:4]}", "fiscal"
            elif days > 80:
                return f"Q_{end}", "fiscal"
        except ValueError:
            pass
    return f"as_of_{end}", "fiscal"


def extract_metrics(
    company_facts: dict[str, Any],
    run_id: str,
    source_id: str,
    cutoff_year: int,
    lookback_years: int,
) -> list[MetricObservation]:
    """Extract MetricObservations from EDGAR XBRL companyfacts JSON."""
    observations: list[MetricObservation] = []
    min_year = cutoff_year - lookback_years

    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})

    for concept, (metric_name, unit_hint) in _CONCEPT_MAP.items():
        concept_data = us_gaap.get(concept, {})
        units = concept_data.get("units", {})

        for unit_key, entries in units.items():
            # Use USD or shares depending on concept
            if unit_key not in ("USD", "shares", "USD/shares"):
                continue
            for entry in entries:
                form = entry.get("form", "")
                end = entry.get("end", "")
                val = entry.get("val")
                accn = entry.get("accn", "")

                if not end or val is None:
                    continue

                try:
                    year = int(end[:4])
                except ValueError:
                    continue

                if year < min_year or year > cutoff_year:
                    continue

                # Prefer 10-K and 10-Q entries; skip amended duplicates for now
                if form not in ("10-K", "10-Q", "10-K/A", "10-Q/A", "20-F"):
                    continue

                period_label, period_type = _period_label(entry)
                unit_str = unit_key if unit_hint == "count" else unit_hint

                observations.append(
                    MetricObservation(
                        run_id=run_id,
                        name=metric_name,
                        value=float(val),
                        unit=unit_str,
                        period=period_label,
                        period_type=period_type,
                        value_type="reported",
                        currency="USD" if unit_key == "USD" else None,
                        source_id=source_id,
                        notes=f"XBRL concept: {concept}, accession: {accn}",
                    )
                )

    return observations
