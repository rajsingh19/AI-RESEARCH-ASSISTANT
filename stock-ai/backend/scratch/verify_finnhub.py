import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_dir))

from app.services.ai_service import get_ai_service
from app.providers.financial.finnhub import FinnhubProvider
from app.config import get_settings


def test_finnhub_key():
    print("Initializing services...")
    ai = get_ai_service()
    settings = get_settings()
    
    key = settings.finnhub_api_key
    print(f"Loaded Finnhub key snippet: {'...' + key[-4:] if key else 'None'}")
    
    if not key or "your_" in key.lower() or key.strip() == "":
        print("ERROR: No valid FINNHUB_API_KEY found in configuration variables.")
        sys.exit(1)
        
    provider = FinnhubProvider(ai, key)
    print("Making live API profile call for AAPL...")
    try:
        # Note: If API key is valid, it retrieves and prints sector/exchange.
        profile = provider.get_company_profile("AAPL")
        
        # Verify it fetched real data rather than falling back to dummy LLM defaults
        if profile.listing_exchange and profile.listing_exchange != "N/A" and profile.listing_exchange != "AAPL":
            print("\n=========================================")
            print("  FINNHUB API KEY STATUS: WORKING   ")
            print("=========================================")
            print(f"Ticker      : {profile.ticker}")
            print(f"Company     : {profile.company_name}")
            print(f"Sector      : {profile.sector}")
            print(f"Exchange    : {profile.listing_exchange}")
            print(f"Country     : {profile.country}")
            print("=========================================\n")
        else:
            print("\n=========================================")
            print("  FINNHUB API KEY STATUS: FAIL / FALLBACK")
            print("=========================================")
            print("Response parsed default dummy values. Please double check that the key matches your Finnhub account.")
            print("=========================================\n")
            sys.exit(1)
    except Exception as e:
        print(f"API Call failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    test_finnhub_key()
