"""
freshness_validator.py — Service for validating cache freshness and orchestrating database updates.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.company import Company
from app.services.ai_service import GeminiAIService
from app.services.company_fetcher import CompanyFetcher

logger = logging.getLogger(__name__)

class FreshnessValidator:
    @staticmethod
    def validate_and_refresh_financials(
        db: Session,
        ticker: str,
        ai_service: GeminiAIService,
        settings: Settings,
        query: str
    ) -> Tuple[Optional[str], Optional[str], bool, Optional[str]]:
        """
        Validates SQLite financial record freshness. If missing or expired, triggers a live fetch,
        updating SQLite before proceeding. Falls back to cached data with warnings on API/network errors.
        
        Returns:
            Tuple[last_updated, data_source, is_live, warning_message]
        """
        ticker_upper = ticker.upper()
        normalized = query.lower()

        # Force refresh indicators (Requirement 7)
        force_indicators = {"latest", "current", "recent", "today", "this quarter", "this year"}
        has_force_indicator = any(word in normalized for word in force_indicators)

        # Financial metric keywords (Requirement 6)
        financial_keywords = {
            "revenue", "profit", "eps", "pe ratio", "market cap", "shareholding",
            "balance sheet", "cash flow", "quarterly", "annual", "financial performance"
        }
        is_financial_query = any(kw in normalized for kw in financial_keywords)

        # Retrieve company from DB
        company = db.query(Company).filter(Company.ticker == ticker_upper).first()

        # Check if financial cache is expired
        is_financial_expired = False
        if company and company.last_updated:
            try:
                last_updated_dt = datetime.fromisoformat(company.last_updated)
                if last_updated_dt.tzinfo is None:
                    last_updated_dt = last_updated_dt.replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - last_updated_dt
                ttl_hours = getattr(settings, "financial_cache_ttl_hours", 24)
                if age > timedelta(hours=ttl_hours):
                    is_financial_expired = True
                    logger.info("[METRICS] Cache Expired for %s. (Age: %s, TTL: %sh)", ticker_upper, age, ttl_hours)
            except Exception as exc:
                logger.warning("FreshnessValidator: Failed to parse last_updated timestamp: %s", exc)
                is_financial_expired = True
        else:
            if company:
                is_financial_expired = True

        # Check if refresh is needed
        should_refresh = False
        reason = ""
        if not company:
            should_refresh = True
            reason = "Cache Miss"
        elif has_force_indicator:
            should_refresh = True
            reason = "Force Refresh Indicator"
        elif is_financial_query and is_financial_expired:
            should_refresh = True
            reason = "Cache Expired"

        if not should_refresh:
            # Cache Hit: reuse fresh data
            if company:
                logger.info("[METRICS] Cache Hit for %s. Reusing cached metrics (Last Updated: %s).", ticker_upper, company.last_updated)
                company._is_live = False
                return company.last_updated, company.data_source, False, None
            return None, None, False, None

        # Fetching latest data
        logger.info("[METRICS] Live Fetch Started for %s. Reason: %s", ticker_upper, reason)
        try:
            fetcher = CompanyFetcher(ai_service, settings)
            provider_name = fetcher._provider.provider_name
            
            # Fetch metadata profile, core financials and history entries
            fetcher.fetch_profile_and_metadata(db, ticker_upper)
            fetcher.fetch_financials(db, ticker_upper)
            fetcher.fetch_historical_financials(db, ticker_upper)

            # Reload to capture any updates
            company = db.query(Company).filter(Company.ticker == ticker_upper).first()
            if company:
                company.last_updated = datetime.now(timezone.utc).isoformat()
                company.data_source = provider_name
                company._is_live = True
                
                # Auto-sync company current metrics with latest historical year record (Requirement 5)
                if company.reporting_period and company.reporting_period.strip().startswith("Q"):
                    logger.info("[METRICS] Keeping newer quarterly metrics for %s: %s", ticker_upper, company.reporting_period)
                else:
                    from app.models.company import CompanyFinancialHistory
                    latest_hist = db.query(CompanyFinancialHistory).filter(
                        CompanyFinancialHistory.ticker == ticker_upper
                    ).order_by(CompanyFinancialHistory.year.desc()).first()
                    if latest_hist:
                        company.revenue = latest_hist.revenue
                        company.profit = latest_hist.profit
                        company.eps = latest_hist.eps
                        company.reporting_period = f"FY{latest_hist.year}"
                        logger.info("[METRICS] SQLite Synchronized with latest historical year %d for %s.", latest_hist.year, ticker_upper)

                db.commit()
                db.refresh(company)
                logger.info("[METRICS] SQLite Updated successfully for %s.", ticker_upper)
                return company.last_updated, company.data_source, True, None
            
            return None, provider_name, True, None

        except Exception as exc:
            logger.exception("[METRICS] Live Fetch Failed for %s. Falling back to cached records.", ticker_upper)
            
            # Fallback to cached records if company exists in DB
            company = db.query(Company).filter(Company.ticker == ticker_upper).first()
            if company:
                company._is_live = False
                warn_msg = (
                    f"Financial metrics are based on cached records last updated at "
                    f"{company.last_updated or 'unknown date'} due to live API/network issues."
                )
                return company.last_updated, company.data_source, False, warn_msg
            
            return None, None, False, "Live API fetch failed and no cached records are available."
