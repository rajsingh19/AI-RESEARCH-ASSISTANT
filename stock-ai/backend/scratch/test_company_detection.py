import unittest
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_dir))

from app.services.ai_service import get_ai_service
from app.services.company_detector import CompanyDetector
from app.services.company_registry import CompanyRegistry


class TestCompanyDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ai = get_ai_service()
        cls.detector = CompanyDetector(cls.ai)

    def test_haldiram_unlisted_detection(self):
        """Verify that 'Haldiram' does not default to Reliance, and resolves to HALDIRAM."""
        ticker, name, confidence = self.detector.detect("Revenue of Haldiram?")
        self.assertIsNotNone(ticker)
        self.assertEqual(ticker.upper(), "HALDIRAM")
        self.assertTrue("haldiram" in name.lower())
        self.assertGreaterEqual(confidence, 0.7)

    def test_airtel_alias_detection(self):
        """Verify that 'Airtel' maps to BHARTIARTL."""
        ticker, name, confidence = self.detector.detect("Latest news on Airtel")
        self.assertEqual(ticker, "BHARTIARTL")
        self.assertGreaterEqual(confidence, 0.7)

    def test_mrf_lookup(self):
        """Verify that 'MRF' resolves to MRF."""
        ticker, name, confidence = self.detector.detect("PE ratio of MRF")
        self.assertEqual(ticker, "MRF")
        self.assertGreaterEqual(confidence, 0.7)

    def test_nestle_india_dynamic(self):
        """Verify Nestle India resolves dynamically to NESTLEIND."""
        ticker, name, confidence = self.detector.detect("Revenue of Nestle India")
        self.assertEqual(ticker, "NESTLEIND")
        self.assertGreaterEqual(confidence, 0.7)

    def test_ambiguous_query_clarification(self):
        """Verify that ambiguous queries trigger low confidence (< 0.7)."""
        ticker, name, confidence = self.detector.detect("Is this stock cheap?")
        self.assertLess(confidence, 0.7)


if __name__ == "__main__":
    unittest.main()
