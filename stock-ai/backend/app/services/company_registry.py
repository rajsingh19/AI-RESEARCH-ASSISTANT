"""
company_registry.py — Redesigned company registry with dynamic live lookup and mapping cache.
"""
from __future__ import annotations

import logging
import re
import httpx

logger = logging.getLogger(__name__)

# Base static aliases and special mappings catalog
COMPANY_MAP = {
    "TCS": {
        "ticker": "TCS",
        "name": "Tata Consultancy Services",
        "search_term": "Tata Consultancy Services",
        "yahoo_ticker": "TCS.NS"
    },
    "INFY": {
        "ticker": "INFY",
        "name": "Infosys",
        "search_term": "Infosys",
        "yahoo_ticker": "INFY.NS"
    },
    "RELIANCE": {
        "ticker": "RELIANCE",
        "name": "Reliance Industries",
        "search_term": "Reliance Industries",
        "yahoo_ticker": "RELIANCE.NS"
    },
    "WIPRO": {
        "ticker": "WIPRO",
        "name": "Wipro",
        "search_term": "Wipro",
        "yahoo_ticker": "WIPRO.NS"
    },
    "HCLTECH": {
        "ticker": "HCLTECH",
        "name": "HCL Technologies",
        "search_term": "HCL Technologies",
        "yahoo_ticker": "HCLTECH.NS"
    },
    "AIRTEL": {
        "ticker": "BHARTIARTL",
        "name": "Bharti Airtel",
        "search_term": "Bharti Airtel",
        "yahoo_ticker": "BHARTIARTL.NS"
    },
    "BHARTIARTL": {
        "ticker": "BHARTIARTL",
        "name": "Bharti Airtel",
        "search_term": "Bharti Airtel",
        "yahoo_ticker": "BHARTIARTL.NS"
    },
    "MRF": {
        "ticker": "MRF",
        "name": "MRF Limited",
        "search_term": "MRF Limited",
        "yahoo_ticker": "MRF.NS"
    },
    "PARLE": {
        "ticker": "PARLE",
        "name": "Parle Products",
        "search_term": "Parle Products",
        "yahoo_ticker": "PARLE.BO"
    },
    "TATA MOTORS": {
        "ticker": "TATAMOTORS",
        "name": "Tata Motors Limited",
        "search_term": "Tata Motors",
        "yahoo_ticker": "TATAMOTORS.NS"
    },
    "TATAMOTORS": {
        "ticker": "TATAMOTORS",
        "name": "Tata Motors Limited",
        "search_term": "Tata Motors",
        "yahoo_ticker": "TATAMOTORS.NS"
    },
    "NESTLE": {
        "ticker": "NESTLEIND",
        "name": "Nestle India",
        "search_term": "Nestle India",
        "yahoo_ticker": "NESTLEIND.NS"
    },
    "NESTLEIND": {
        "ticker": "NESTLEIND",
        "name": "Nestle India",
        "search_term": "Nestle India",
        "yahoo_ticker": "NESTLEIND.NS"
    },
    "ADANI": {
        "ticker": "ADANIENT",
        "name": "Adani Enterprises",
        "search_term": "Adani Enterprises",
        "yahoo_ticker": "ADANIENT.NS"
    },
    "ADANIENT": {
        "ticker": "ADANIENT",
        "name": "Adani Enterprises",
        "search_term": "Adani Enterprises",
        "yahoo_ticker": "ADANIENT.NS"
    },
    "SBI": {
        "ticker": "SBIN",
        "name": "State Bank of India",
        "search_term": "State Bank of India",
        "yahoo_ticker": "SBIN.NS"
    },
    "SBIN": {
        "ticker": "SBIN",
        "name": "State Bank of India",
        "search_term": "State Bank of India",
        "yahoo_ticker": "SBIN.NS"
    }
}


class CompanyRegistry:
    """Registry managing list of supported companies and dynamically resolving unlisted ones via Yahoo API."""

    @classmethod
    def lookup(cls, term: str, enable_live: bool = False) -> dict[str, str] | None:
        """Resolve a lookup term (ticker or alias) case-insensitively using cache + live fallback."""
        if not term:
            return None
        cleaned = term.strip().upper()
        
        # 1. Check local config mapping cache
        if cleaned in COMPANY_MAP:
            return COMPANY_MAP[cleaned]
        
        # 2. Check full names and base tickers in cache
        for key, value in list(COMPANY_MAP.items()):
            if cleaned == value["ticker"].upper() or cleaned == value["name"].upper():
                return value
            
        # 3. Check normalized punctuation match
        normalized_cleaned = re.sub(r"[^A-Z0-9]", "", cleaned)
        for key, value in list(COMPANY_MAP.items()):
            norm_key = re.sub(r"[^A-Z0-9]", "", key.upper())
            norm_ticker = re.sub(r"[^A-Z0-9]", "", value["ticker"].upper())
            norm_name = re.sub(r"[^A-Z0-9]", "", value["name"].upper())
            if normalized_cleaned in (norm_key, norm_ticker, norm_name):
                return value

        # 4. If no local match, run live search resolution if enabled
        if enable_live:
            resolved = cls.search_ticker(term)
            if resolved:
                # Dynamically register in memory cache
                cls.register_dynamic(resolved["ticker"], resolved)
                return resolved

        return None

    @classmethod
    def search_ticker(cls, company_name: str) -> dict[str, str] | None:
        """Search Yahoo Finance for the ticker of a company name dynamically."""
        try:
            logger.info("CompanyRegistry: dynamic live API search for name: %r", company_name)
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            url = f"https://query2.finance.yahoo.com/v1/finance/search?q={company_name}&quotesCount=3"
            resp = httpx.get(url, headers=headers, timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                quotes = data.get("quotes", [])
                for q in quotes:
                    symbol = q.get("symbol")
                    if symbol:
                        symbol_upper = symbol.upper()
                        # Extract base ticker (e.g., NESTLEIND from NESTLEIND.NS)
                        base_ticker = symbol_upper.split(".")[0]
                        long_name = q.get("longname") or q.get("shortname") or base_ticker
                        
                        resolved_details = {
                            "ticker": base_ticker,
                            "name": long_name,
                            "search_term": long_name,
                            "yahoo_ticker": symbol_upper
                        }
                        logger.info("CompanyRegistry: dynamic live API resolved %s → %s", company_name, base_ticker)
                        return resolved_details
        except Exception as exc:
            logger.warning("CompanyRegistry: Live search failed for %s: %s", company_name, exc)
        return None

    @classmethod
    def register_dynamic(cls, ticker: str, details: dict[str, str]) -> None:
        """Cache a dynamically detected company in the map."""
        COMPANY_MAP[ticker.upper()] = details
        # Also cache the name key
        name_key = details["name"].upper()
        COMPANY_MAP[name_key] = details
        logger.info("CompanyRegistry: Dynamically cached details for %s (%s)", details["name"], ticker)

    @classmethod
    def get_details(cls, ticker: str) -> dict[str, str] | None:
        """Get canonical details for a verified ticker."""
        for company in list(COMPANY_MAP.values()):
            if company["ticker"].upper() == ticker.strip().upper():
                return company
        return None

    @classmethod
    def list_all(cls) -> list[dict[str, str]]:
        """Return unique listed companies."""
        seen: set[str] = set()
        unique = []
        for value in list(COMPANY_MAP.values()):
            if value["ticker"] not in seen:
                seen.add(value["ticker"])
                unique.append(value)
        return unique
