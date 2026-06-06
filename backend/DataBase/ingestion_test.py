"""
Unit tests for stocks, commodities, and crypto ingestion modules.

Mocks:
  - yfinance.Ticker  → controls .info and .history()
  - dal.DAL          → in-memory fake so no MongoDB needed
"""

import unittest
from datetime import datetime, timezone, date
from unittest.mock import MagicMock, patch, call
import pandas as pd

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------

def make_history_df(dates_and_rows):
    """Build a minimal DataFrame that mimics yfinance history output."""
    index = pd.DatetimeIndex([r[0] for r in dates_and_rows], tz="UTC")
    data = {
        "Open":   [r[1] for r in dates_and_rows],
        "High":   [r[2] for r in dates_and_rows],
        "Low":    [r[3] for r in dates_and_rows],
        "Close":  [r[4] for r in dates_and_rows],
        "Volume": [r[5] for r in dates_and_rows],
    }
    return pd.DataFrame(data, index=index)


SAMPLE_HISTORY = make_history_df([
    ("2024-01-02", 185.0, 186.5, 184.0, 185.9, 1_000_000),
    ("2024-01-03", 186.0, 188.0, 185.5, 187.2, 1_200_000),
])

SAMPLE_STOCK_INFO = {
    "shortName": "Apple Inc.",
    "longName": "Apple Inc.",
    "country": "United States",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "currency": "USD",
    "exchange": "NMS",
    "quoteType": "EQUITY",
    "market": "us_market",
    "website": "https://www.apple.com",
    "longBusinessSummary": "Apple designs consumer electronics.",
}

SAMPLE_CRYPTO_INFO = {
    "shortName": "Bitcoin USD",
    "currency": "USD",
    "exchange": "CCC",
    "quoteType": "CRYPTOCURRENCY",
    "market": "ccc_market",
}

SAMPLE_COMMODITY_INFO = {
    "shortName": "Gold Dec 24",
    "currency": "USD",
    "exchange": "CMX",
    "quoteType": "FUTURE",
    "market": "us_market",
}


# ---------------------------------------------------------------------------
# Fake DAL
# ---------------------------------------------------------------------------

class FakeVersionedCollection:
    """Minimal stand-in for a versioned MongoDB collection wrapper."""

    def __init__(self):
        self.docs = []
        self.collection = MagicMock()
        self.collection.count_documents.return_value = 0

    def save_version(self, doc):
        self.docs.append(doc)
        return doc

    def find_latest(self, query):
        for doc in reversed(self.docs):
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None


class FakeDAL:
    def __init__(self):
        self.data_sources = FakeVersionedCollection()
        self.assets = FakeVersionedCollection()
        self.time_series = FakeVersionedCollection()

    def create_indexes(self):
        pass


# ---------------------------------------------------------------------------
# Helper: build a patched module under test
# ---------------------------------------------------------------------------

def _import_module_with_mocks(module_name):
    """
    Import one of the ingestion modules with DAL and yfinance replaced by fakes.
    Returns (module, fake_dal).
    """
    import importlib, sys

    fake_dal = FakeDAL()

    dal_mock = MagicMock()
    dal_mock.DAL.return_value = fake_dal

    yf_mock = MagicMock()

    with patch.dict("sys.modules", {"dal": dal_mock, "yfinance": yf_mock,
                                    "pymongo": MagicMock(),
                                    "pymongo.errors": MagicMock()}):
        if module_name in sys.modules:
            del sys.modules[module_name]
        mod = importlib.import_module(module_name)
        mod.dal = fake_dal          # replace the module-level singleton
        mod.yf = yf_mock

    return mod, fake_dal, yf_mock


# ===========================================================================
# Tests: shared helper functions (safe_float / safe_int)
# ===========================================================================

class TestSafeConversions(unittest.TestCase):
    """safe_float and safe_int are duplicated across all ingestion modules;
       we test through stocks_ingestion as a representative."""

    @classmethod
    def setUpClass(cls):
        cls.mod, cls.dal, cls.yf = _import_module_with_mocks("stocks_ingestion")

    def test_safe_float_normal(self):
        self.assertAlmostEqual(self.mod.safe_float(3.14), 3.14)

    def test_safe_float_none(self):
        self.assertIsNone(self.mod.safe_float(None))

    def test_safe_float_nan(self):
        import math
        self.assertIsNone(self.mod.safe_float(float("nan")))

    def test_safe_float_string_number(self):
        self.assertAlmostEqual(self.mod.safe_float("2.5"), 2.5)

    def test_safe_float_invalid_string(self):
        self.assertIsNone(self.mod.safe_float("abc"))

    def test_safe_int_normal(self):
        self.assertEqual(self.mod.safe_int(42), 42)

    def test_safe_int_none(self):
        self.assertIsNone(self.mod.safe_int(None))

    def test_safe_int_nan(self):
        self.assertIsNone(self.mod.safe_int(float("nan")))

    def test_safe_int_float(self):
        self.assertEqual(self.mod.safe_int(3.9), 3)


# ===========================================================================
# Tests: stocks_ingestion
# ===========================================================================

class TestStocksIngestion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mod, cls.dal, cls.yf = _import_module_with_mocks("stocks_ingestion")

    def _make_ticker(self, info=None, history=None):
        ticker = MagicMock()
        ticker.info = info if info is not None else SAMPLE_STOCK_INFO
        ticker.history.return_value = history if history is not None else SAMPLE_HISTORY
        self.yf.Ticker.return_value = ticker
        return ticker

    # --- build_asset_doc ---

    def test_build_asset_doc_uses_short_name(self):
        doc = self.mod.build_asset_doc("AAPL", SAMPLE_STOCK_INFO)
        self.assertEqual(doc["name"], "Apple Inc.")

    def test_build_asset_doc_fallback_to_symbol(self):
        doc = self.mod.build_asset_doc("XYZ", {})
        self.assertEqual(doc["name"], "XYZ")

    def test_build_asset_doc_asset_class(self):
        doc = self.mod.build_asset_doc("AAPL", SAMPLE_STOCK_INFO)
        self.assertEqual(doc["asset_class"], "stock")

    def test_build_asset_doc_not_deleted(self):
        doc = self.mod.build_asset_doc("AAPL", SAMPLE_STOCK_INFO)
        self.assertFalse(doc["deleted"])

    def test_build_asset_doc_attributes(self):
        doc = self.mod.build_asset_doc("AAPL", SAMPLE_STOCK_INFO)
        self.assertEqual(doc["attributes"]["currency"], "USD")
        self.assertEqual(doc["attributes"]["exchange"], "NMS")
        self.assertEqual(doc["attributes"]["industry"], "Consumer Electronics")

    # --- build_timeseries_doc ---

    def test_build_timeseries_doc_structure(self):
        row_date = pd.Timestamp("2024-01-02", tz="UTC")
        row = {"Open": 185.0, "High": 186.5, "Low": 184.0, "Close": 185.9, "Volume": 1_000_000}
        doc = self.mod.build_timeseries_doc("AAPL", row_date, row, "1y")
        self.assertEqual(doc["asset_id"], "AAPL")
        self.assertEqual(doc["source_id"], self.mod.SOURCE_ID)
        self.assertEqual(doc["business_date"], "2024-01-02")
        self.assertEqual(doc["business_year"], 2024)
        self.assertAlmostEqual(doc["values"]["close"], 185.9)
        self.assertEqual(doc["values"]["volume"], 1_000_000)
        self.assertFalse(doc["deleted"])

    def test_build_timeseries_doc_provenance(self):
        row_date = pd.Timestamp("2024-01-02", tz="UTC")
        row = {"Open": 185.0, "High": 186.5, "Low": 184.0, "Close": 185.9, "Volume": 1_000_000}
        doc = self.mod.build_timeseries_doc("AAPL", row_date, row, "1y")
        self.assertEqual(doc["provenance"]["symbol"], "AAPL")
        self.assertEqual(doc["provenance"]["period"], "1y")

    # --- ingest_stock ---

    def test_ingest_stock_inserts_timeseries(self):
        self._make_ticker()
        # Simulate count_documents returning 0 before, 1 after
        self.dal.time_series.collection.count_documents.side_effect = [0, 1, 0, 1]
        self.mod.ingest_stock("AAPL", period="1y")
        self.assertGreater(len(self.dal.time_series.docs), 0)

    def test_ingest_stock_saves_asset(self):
        self._make_ticker()
        self.dal.time_series.collection.count_documents.side_effect = [0, 1] * 10
        self.mod.ingest_stock("AAPL", period="1y")
        self.assertTrue(any(d["asset_id"] == "AAPL" for d in self.dal.assets.docs))

    def test_ingest_stock_skips_on_empty_info(self):
        self._make_ticker(info={})
        before = len(self.dal.time_series.docs)
        self.mod.ingest_stock("AAPL", period="1y")
        # Empty info → should skip entirely
        self.assertEqual(len(self.dal.time_series.docs), before)

    def test_ingest_stock_skips_on_empty_history(self):
        self._make_ticker(history=pd.DataFrame())
        before = len(self.dal.time_series.docs)
        self.mod.ingest_stock("AAPL", period="1y")
        self.assertEqual(len(self.dal.time_series.docs), before)

    def test_ingest_stock_handles_history_exception(self):
        ticker = MagicMock()
        ticker.info = SAMPLE_STOCK_INFO
        ticker.history.side_effect = Exception("network error")
        self.yf.Ticker.return_value = ticker
        # Should not raise
        self.mod.ingest_stock("AAPL", period="1y")

    # --- run ---

    def test_run_calls_save_source_metadata(self):
        self._make_ticker()
        self.dal.time_series.collection.count_documents.return_value = 0
        self.dal.time_series.collection.count_documents.side_effect = None
        before = len(self.dal.data_sources.docs)
        self.mod.run(period="1y")
        self.assertGreater(len(self.dal.data_sources.docs), before)


# ===========================================================================
# Tests: crypto_ingestion
# ===========================================================================

class TestCryptoIngestion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mod, cls.dal, cls.yf = _import_module_with_mocks("crypto_ingestion")

    def _make_ticker(self, info=None, history=None):
        ticker = MagicMock()
        ticker.info = info if info is not None else SAMPLE_CRYPTO_INFO
        ticker.history.return_value = history if history is not None else SAMPLE_HISTORY
        self.yf.Ticker.return_value = ticker
        return ticker

    def test_build_asset_doc_asset_class(self):
        doc = self.mod.build_asset_doc("BTC-USD", SAMPLE_CRYPTO_INFO)
        self.assertEqual(doc["asset_class"], "crypto")

    def test_build_asset_doc_underlying_symbol(self):
        doc = self.mod.build_asset_doc("BTC-USD", SAMPLE_CRYPTO_INFO)
        self.assertEqual(doc["attributes"]["underlying_symbol"], "BTC")

    def test_build_asset_doc_no_dash_symbol(self):
        doc = self.mod.build_asset_doc("BTCUSD", {})
        self.assertEqual(doc["attributes"]["underlying_symbol"], "BTCUSD")

    def test_build_asset_doc_region_defaults_to_global(self):
        doc = self.mod.build_asset_doc("BTC-USD", {})
        self.assertEqual(doc["region"], "global")

    def test_ingest_crypto_inserts_timeseries(self):
        self._make_ticker()
        self.dal.time_series.collection.count_documents.side_effect = [0, 1, 0, 1]
        self.mod.ingest_crypto("BTC-USD", period="1y")
        self.assertGreater(len(self.dal.time_series.docs), 0)

    def test_ingest_crypto_skips_on_empty_history(self):
        self._make_ticker(history=pd.DataFrame())
        before = len(self.dal.time_series.docs)
        self.mod.ingest_crypto("BTC-USD", period="1y")
        self.assertEqual(len(self.dal.time_series.docs), before)

    def test_ingest_crypto_handles_history_exception(self):
        ticker = MagicMock()
        ticker.info = SAMPLE_CRYPTO_INFO
        ticker.history.side_effect = Exception("timeout")
        self.yf.Ticker.return_value = ticker
        self.mod.ingest_crypto("BTC-USD", period="1y")  # must not raise

    def test_timeseries_doc_source_id(self):
        row_date = pd.Timestamp("2024-01-02", tz="UTC")
        row = {"Open": 42000.0, "High": 43000.0, "Low": 41000.0, "Close": 42500.0, "Volume": 50000}
        doc = self.mod.build_timeseries_doc("BTC-USD", row_date, row, "1y")
        self.assertEqual(doc["source_id"], self.mod.SOURCE_ID)


# ===========================================================================
# Tests: comodities_ingestion
# ===========================================================================

class TestCommoditiesIngestion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mod, cls.dal, cls.yf = _import_module_with_mocks("comodities_ingestion")

    def _make_ticker(self, info=None, history=None):
        ticker = MagicMock()
        ticker.info = info if info is not None else SAMPLE_COMMODITY_INFO
        ticker.history.return_value = history if history is not None else SAMPLE_HISTORY
        self.yf.Ticker.return_value = ticker
        return ticker

    def test_normalize_commodity_name_uses_short_name(self):
        name = self.mod.normalize_commodity_name("GC=F", {"shortName": "Gold Dec 24"})
        self.assertEqual(name, "Gold Dec 24")

    def test_normalize_commodity_name_uses_long_name_when_no_short(self):
        name = self.mod.normalize_commodity_name("GC=F", {"longName": "Gold Futures Dec 2024"})
        self.assertEqual(name, "Gold Futures Dec 2024")

    def test_normalize_commodity_name_fallback(self):
        name = self.mod.normalize_commodity_name("GC=F", {})
        self.assertEqual(name, "Gold Futures")

    def test_normalize_commodity_name_unknown_symbol(self):
        name = self.mod.normalize_commodity_name("XX=F", {})
        self.assertEqual(name, "XX=F")

    def test_build_asset_doc_asset_class(self):
        doc = self.mod.build_asset_doc("GC=F", SAMPLE_COMMODITY_INFO)
        self.assertEqual(doc["asset_class"], "commodity")

    def test_build_asset_doc_instrument_type(self):
        doc = self.mod.build_asset_doc("GC=F", SAMPLE_COMMODITY_INFO)
        self.assertEqual(doc["attributes"]["instrument_type"], "futures")

    def test_build_asset_doc_region_defaults_to_global(self):
        doc = self.mod.build_asset_doc("GC=F", {})
        self.assertEqual(doc["region"], "global")

    def test_ingest_commodity_inserts_timeseries(self):
        self._make_ticker()
        self.dal.time_series.collection.count_documents.side_effect = [0, 1, 0, 1]
        self.mod.ingest_commodity("GC=F", period="1y")
        self.assertGreater(len(self.dal.time_series.docs), 0)

    def test_ingest_commodity_skips_on_empty_history(self):
        self._make_ticker(history=pd.DataFrame())
        before = len(self.dal.time_series.docs)
        self.mod.ingest_commodity("GC=F", period="1y")
        self.assertEqual(len(self.dal.time_series.docs), before)

    def test_ingest_commodity_handles_history_exception(self):
        ticker = MagicMock()
        ticker.info = SAMPLE_COMMODITY_INFO
        ticker.history.side_effect = Exception("api error")
        self.yf.Ticker.return_value = ticker
        self.mod.ingest_commodity("GC=F", period="1y")  # must not raise

    def test_all_known_fallback_symbols_covered(self):
        for sym in ["GC=F", "SI=F", "HG=F", "CL=F", "NG=F", "ZC=F"]:
            name = self.mod.normalize_commodity_name(sym, {})
            self.assertNotEqual(name, sym, f"Missing fallback for {sym}")


# ===========================================================================
# Tests: provider.py  (ingest_ticker)
# ===========================================================================

class TestProvider(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mod, cls.dal, cls.yf = _import_module_with_mocks("provider")

    def _make_ticker(self, info=None, history=None):
        ticker = MagicMock()
        ticker.info = info if info is not None else SAMPLE_STOCK_INFO
        ticker.history.return_value = history if history is not None else SAMPLE_HISTORY
        self.yf.Ticker.return_value = ticker
        return ticker

    def test_build_source_doc_structure(self):
        doc = self.mod.build_source_doc()
        self.assertEqual(doc["source_id"], self.mod.SOURCE_ID)
        self.assertIn("stock", doc["asset_classes_supported"])
        self.assertFalse(doc["deleted"])

    def test_build_asset_doc_stock_class(self):
        doc = self.mod.build_asset_doc("AAPL", SAMPLE_STOCK_INFO)
        self.assertEqual(doc["asset_class"], "stock")
        self.assertEqual(doc["symbol"], "AAPL")

    def test_ingest_ticker_saves_source(self):
        self._make_ticker()
        before = len(self.dal.data_sources.docs)
        self.mod.ingest_ticker("AAPL", period="3mo")
        self.assertGreater(len(self.dal.data_sources.docs), before)

    def test_ingest_ticker_saves_asset(self):
        self._make_ticker()
        self.mod.ingest_ticker("AAPL", period="3mo")
        self.assertTrue(any(d["asset_id"] == "AAPL" for d in self.dal.assets.docs))

    def test_ingest_ticker_saves_timeseries(self):
        self._make_ticker()
        before = len(self.dal.time_series.docs)
        self.mod.ingest_ticker("AAPL", period="3mo")
        self.assertEqual(len(self.dal.time_series.docs) - before, len(SAMPLE_HISTORY))

    def test_ingest_ticker_empty_history(self):
        self._make_ticker(history=pd.DataFrame())
        before = len(self.dal.time_series.docs)
        self.mod.ingest_ticker("AAPL", period="3mo")
        self.assertEqual(len(self.dal.time_series.docs), before)

    def test_build_timeseries_doc_nan_values(self):
        row_date = pd.Timestamp("2024-01-02", tz="UTC")
        row = {"Open": float("nan"), "High": None, "Low": 184.0, "Close": 185.9, "Volume": None}
        doc = self.mod.build_timeseries_doc("AAPL", row_date, row, "3mo")
        self.assertIsNone(doc["values"]["open"])
        self.assertIsNone(doc["values"]["high"])
        self.assertIsNone(doc["values"]["volume"])
        self.assertAlmostEqual(doc["values"]["low"], 184.0)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)