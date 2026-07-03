from __future__ import annotations

import logging
import re
from typing import Sequence

from sqlalchemy.orm import Session

from app.models.chat import CompanySnapshot
from app.models.chat import ExtractedQuery
from app.models.chat import IntentType
from app.models.chat import MetricName
from app.models.chat import RetrievalContext
from app.models.company import Company, CompanyFinancialHistory, CompanyDividend
from app.utils.exceptions import DataAccessError


logger = logging.getLogger(__name__)


class DBService:
    """Encapsulates all database access for stock company data."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_companies(self) -> list[Company]:
        try:
            return self.db.query(Company).order_by(Company.ticker.asc()).all()
        except Exception as exc:
            logger.exception("Failed to list companies from the database.")
            raise DataAccessError("Unable to fetch company data from SQLite.") from exc

    def get_company_catalog(self) -> list[dict[str, str]]:
        companies = self.list_companies()
        return [
            {"ticker": company.ticker, "company_name": company.company_name}
            for company in companies
        ]

    def build_context(self, extracted_query: ExtractedQuery) -> RetrievalContext:
        all_companies = self.list_companies()
        company_lookup = self._build_lookup(all_companies)

        requested_metrics = list(extracted_query.metrics)
        if not requested_metrics and extracted_query.intent in {
            IntentType.COMPANY_OVERVIEW,
            IntentType.COMPARE_COMPANIES,
        }:
            requested_metrics = [
                MetricName.REVENUE,
                MetricName.PROFIT,
                MetricName.EPS,
                MetricName.PE_RATIO,
            ]

        if extracted_query.requires_all_companies and not extracted_query.company_identifiers:
            selected_companies = all_companies
            unavailable_identifiers: list[str] = []
        else:
            selected_companies = []
            unavailable_identifiers = []
            seen: set[str] = set()

            for identifier in extracted_query.company_identifiers:
                resolved = company_lookup.get(self._normalize(identifier))
                if resolved is None:
                    unavailable_identifiers.append(identifier)
                    continue

                if resolved.ticker not in seen:
                    selected_companies.append(resolved)
                    seen.add(resolved.ticker)

        company_metadata = {}
        company_history = {}
        company_dividends = {}

        for company in selected_companies:
            ticker_upper = company.ticker.upper()
            
            # 1. Fetch metadata
            company_metadata[ticker_upper] = {
                "sector": company.sector,
                "industry": company.industry,
                "market_cap": company.market_cap,
                "headquarters": company.headquarters,
                "ceo": company.ceo,
                "competitors": company.competitors.split(",") if company.competitors else [],
                "website": company.website,
                "listing_exchange": company.listing_exchange,
                "country": company.country
            }

            # 2. Fetch history
            hist_rows = self.db.query(CompanyFinancialHistory).filter(
                CompanyFinancialHistory.ticker == ticker_upper
            ).order_by(CompanyFinancialHistory.year.asc()).all()
            company_history[ticker_upper] = [
                {
                    "year": h.year, "revenue": h.revenue, "profit": h.profit, "eps": h.eps,
                    "operating_margin": h.operating_margin, "net_margin": h.net_margin,
                    "roe": h.roe, "roce": h.roce, "dividend": h.dividend
                }
                for h in hist_rows
            ]

            # 3. Fetch dividends
            div_rows = self.db.query(CompanyDividend).filter(
                CompanyDividend.ticker == ticker_upper
            ).order_by(CompanyDividend.date.desc()).all()
            company_dividends[ticker_upper] = [
                {"date": d.date, "dividend": d.dividend, "yield": d.dividend_yield}
                for d in div_rows
            ]

        context = RetrievalContext(
            companies=[self._to_snapshot(company) for company in selected_companies],
            requested_metrics=requested_metrics,
            unavailable_identifiers=unavailable_identifiers,
            analysis_notes=[],
            company_metadata=company_metadata,
            company_history=company_history,
            company_dividends=company_dividends
        )
        context.analysis_notes.extend(self._build_analysis_notes(extracted_query, context))
        return context

    def _build_lookup(self, companies: Sequence[Company]) -> dict[str, Company]:
        lookup: dict[str, Company] = {}
        for company in companies:
            aliases = {
                company.ticker,
                company.company_name,
                company.company_name.replace("Limited", ""),
                company.company_name.replace("Ltd", ""),
                company.company_name.split()[0],
            }
            for alias in aliases:
                normalized = self._normalize(alias)
                if normalized:
                    lookup[normalized] = company
        return lookup

    def _build_analysis_notes(
        self,
        extracted_query: ExtractedQuery,
        context: RetrievalContext,
    ) -> list[str]:
        notes: list[str] = []
        companies = context.companies

        if not companies:
            notes.append("No companies were resolved from the SQLite database.")
            return notes

        if extracted_query.intent == IntentType.RANKING and context.requested_metrics:
            metric = context.requested_metrics[0]
            ranked = sorted(
                companies,
                key=lambda company: getattr(company, metric.value),
                reverse=True,
            )
            winner = ranked[0]
            notes.append(
                f"Highest {metric.value} belongs to {winner.ticker} at "
                f"{getattr(winner, metric.value)}."
            )

        if extracted_query.intent == IntentType.COMPARE_COMPANIES and len(companies) >= 2:
            first = companies[0]
            second = companies[1]
            metrics = context.requested_metrics or [
                MetricName.REVENUE,
                MetricName.PROFIT,
                MetricName.EPS,
                MetricName.PE_RATIO,
            ]

            for metric in metrics:
                first_value = getattr(first, metric.value)
                second_value = getattr(second, metric.value)
                if first_value == second_value:
                    notes.append(
                        f"{first.ticker} and {second.ticker} have the same "
                        f"{metric.value}: {first_value}."
                    )
                else:
                    winner = first.ticker if first_value > second_value else second.ticker
                    notes.append(
                        f"For {metric.value}, {winner} is higher "
                        f"({first.ticker}: {first_value}, {second.ticker}: {second_value})."
                    )

        return notes

    def _to_snapshot(self, company: Company) -> CompanySnapshot:
        return CompanySnapshot(
            ticker=company.ticker,
            company_name=company.company_name,
            revenue=company.revenue,
            profit=company.profit,
            eps=company.eps,
            pe_ratio=company.pe_ratio,
        )

    def _normalize(self, value: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", value.upper())
