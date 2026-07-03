from __future__ import annotations

import logging
from dataclasses import dataclass

from app.models.chat import ExtractedQuery
from app.models.chat import MetricName
from app.models.chat import RetrievalContext


logger = logging.getLogger(__name__)

DISCLAIMER = (
    "This information is based on the available database records and is not "
    "investment advice."
)


@dataclass(frozen=True, slots=True)
class BuiltFinancialContext:
    """Container for grounded financial context sent to the answer-generation LLM."""

    context_text: str
    company_count: int
    metric_count: int


class ContextBuilder:
    """Builds deterministic financial context from retrieved SQLite data."""

    def build(
        self,
        extracted_query: ExtractedQuery,
        retrieval_context: RetrievalContext,
    ) -> BuiltFinancialContext:
        requested_metrics = self._normalize_metrics(
            extracted_query.metrics or retrieval_context.requested_metrics
        )
        company_sections = [
            self._build_company_section(company, requested_metrics)
            for company in retrieval_context.companies
        ]

        sections: list[str] = [
            "Financial Context:",
        ]

        if company_sections:
            sections.extend(company_sections)
        else:
            sections.append("No matching company data was found in the database.")

        if retrieval_context.analysis_notes:
            sections.append("")
            sections.append("Analysis Notes:")
            sections.extend(
                f"- {note}" for note in retrieval_context.analysis_notes if note.strip()
            )

        if retrieval_context.unavailable_identifiers:
            sections.append("")
            sections.append("Unavailable Companies:")
            sections.extend(
                f"- {identifier}"
                for identifier in retrieval_context.unavailable_identifiers
            )

        sections.append("")
        sections.append("Rules:")
        sections.append("- Use only the financial values in this context.")
        sections.append("- If a value is missing, say Not Available.")
        sections.append("- Do not provide investment advice.")
        sections.append(f"- {DISCLAIMER}")

        context_text = "\n".join(sections)
        logger.info(
            "Built grounded financial context. intent=%s companies=%s metrics=%s",
            extracted_query.intent,
            len(retrieval_context.companies),
            len(requested_metrics),
        )

        return BuiltFinancialContext(
            context_text=context_text,
            company_count=len(retrieval_context.companies),
            metric_count=len(requested_metrics),
        )

    def _build_company_section(
        self,
        company,
        requested_metrics: list[MetricName],
    ) -> str:
        lines = [
            "",
            f"Company: {company.company_name}",
            f"Ticker: {company.ticker}",
        ]

        metrics_to_render = requested_metrics or [
            MetricName.REVENUE,
            MetricName.PROFIT,
            MetricName.EPS,
            MetricName.PE_RATIO,
        ]

        for metric in metrics_to_render:
            label = self._metric_label(metric)
            value = getattr(company, metric.value, None)
            lines.append(f"{label}: {self._render_value(metric, value)}")

        return "\n".join(lines)

    def _render_value(self, metric: MetricName, value: float | None) -> str:
        if value is None:
            return "Not Available"

        if metric in {MetricName.REVENUE, MetricName.PROFIT}:
            return f"Rs. {value:,.0f} crore"

        if metric in {MetricName.EPS, MetricName.PE_RATIO}:
            return f"{value:,.2f}".rstrip("0").rstrip(".")

        return str(value)

    def _metric_label(self, metric: MetricName) -> str:
        labels = {
            MetricName.REVENUE: "Revenue",
            MetricName.PROFIT: "Profit",
            MetricName.EPS: "EPS",
            MetricName.PE_RATIO: "PE Ratio",
        }
        return labels[metric]

    def _normalize_metrics(self, metrics: list[MetricName | str]) -> list[MetricName]:
        normalized_metrics: list[MetricName] = []

        for metric in metrics:
            if isinstance(metric, MetricName):
                normalized_metrics.append(metric)
                continue

            try:
                normalized_metrics.append(MetricName(metric))
            except ValueError:
                logger.warning("Skipping unsupported metric in context builder: %s", metric)

        return normalized_metrics
