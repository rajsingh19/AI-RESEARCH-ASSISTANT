"""
company_registry.py — Single source of truth for resolving tickers, full names, and search terms.
"""
from __future__ import annotations

import re


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
    "HALDIRAM": {
        "ticker": "HALDIRAM",
        "name": "Haldiram Foods",
        "search_term": "Haldiram Foods",
        "yahoo_ticker": "HALDIRAM.NS"
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
    """Registry managing list of supported companies and parsing query aliases."""

    @staticmethod
    def lookup(term: str) -> dict[str, str] | None:
        """Resolve a lookup term (ticker or alias) case-insensitively."""
        if not term:
            return None
        cleaned = term.strip().upper()
        # Direct lookup
        if cleaned in COMPANY_MAP:
            return COMPANY_MAP[cleaned]
        
        # Substring lookup in name or keys
        for key, value in COMPANY_MAP.items():
            if cleaned == value["ticker"].upper() or cleaned == value["name"].upper():
                return value
            
        # Try normalizing punctuation
        normalized_cleaned = re.sub(r"[^A-Z0-9]", "", cleaned)
        for key, value in COMPANY_MAP.items():
            norm_key = re.sub(r"[^A-Z0-9]", "", key.upper())
            norm_ticker = re.sub(r"[^A-Z0-9]", "", value["ticker"].upper())
            norm_name = re.sub(r"[^A-Z0-9]", "", value["name"].upper())
            if normalized_cleaned in (norm_key, norm_ticker, norm_name):
                return value

        return None

    @staticmethod
    def get_details(ticker: str) -> dict[str, str] | None:
        """Get canonical details for a verified ticker."""
        for company in COMPANY_MAP.values():
            if company["ticker"].upper() == ticker.strip().upper():
                return company
        return None

    @staticmethod
    def list_all() -> list[dict[str, str]]:
        """Return unique listed companies."""
        seen: set[str] = set()
        unique = []
        for value in COMPANY_MAP.values():
            if value["ticker"] not in seen:
                seen.add(value["ticker"])
                unique.append(value)
        return unique
