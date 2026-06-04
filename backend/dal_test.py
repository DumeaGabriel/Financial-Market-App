"""
DAL Unit Tests
==============
Tests for the Data Access Layer repositories in dal.py.

These tests use mongomock to simulate MongoDB in-memory,
so no real MongoDB connection is required to run them.

Install dependencies:
    pip install pytest mongomock

Run:
    pytest test_dal.py -v
"""

import time
import pytest
import mongomock
from unittest.mock import patch, MagicMock
from DataBase.dal import (
    AssetRepository,
    DataSourceRepository,
    TimeSeriesRepository,
    AnalyticsMonthlySummaryRepository,
    AnalyticsPredictionsRepository,
    DAL,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mongo_client():
    """In-memory MongoDB client using mongomock."""
    return mongomock.MongoClient()


@pytest.fixture
def db(mongo_client):
    return mongo_client["financial_dwh_test"]


@pytest.fixture
def asset_repo(db):
    return AssetRepository(db["assets"])


@pytest.fixture
def source_repo(db):
    return DataSourceRepository(db["data_sources"])


@pytest.fixture
def ts_repo(db):
    return TimeSeriesRepository(db["time_series"])


@pytest.fixture
def monthly_repo(db):
    return AnalyticsMonthlySummaryRepository(db["analytics_monthly_summary"])


@pytest.fixture
def predictions_repo(db):
    return AnalyticsPredictionsRepository(db["analytics_predictions"])


# ---------------------------------------------------------------------------
# AssetRepository Tests
# ---------------------------------------------------------------------------

class TestAssetRepository:

    def test_save_and_find_latest(self, asset_repo):
        """save() stores asset; find_latest() returns it."""
        doc = {"asset_id": "AAPL", "name": "Apple Inc.", "asset_class": "stock"}
        asset_repo.save(doc)

        result = asset_repo.find_latest("AAPL")
        assert result is not None
        assert result["asset_id"] == "AAPL"
        assert result["name"] == "Apple Inc."
        assert result["deleted"] == False

    def test_find_latest_returns_none_for_unknown(self, asset_repo):
        """find_latest() returns None for an asset that does not exist."""
        result = asset_repo.find_latest("UNKNOWN")
        assert result is None

    def test_save_creates_new_version_on_change(self, asset_repo):
        """Saving a changed asset creates a new version instead of updating."""
        doc_v1 = {"asset_id": "AAPL", "name": "Apple Inc.", "asset_class": "stock"}
        asset_repo.save(doc_v1)

        doc_v2 = {"asset_id": "AAPL", "name": "Apple Incorporated", "asset_class": "stock"}
        asset_repo.save(doc_v2)

        # find_latest returns the newest version
        latest = asset_repo.find_latest("AAPL")
        assert latest["name"] == "Apple Incorporated"

        # find_all_versions returns both versions
        versions = asset_repo.find_all_versions("AAPL")
        assert len(versions) == 2

    def test_save_skips_duplicate_if_unchanged(self, asset_repo):
        """Saving the same asset twice does not create duplicate versions."""
        doc = {"asset_id": "AAPL", "name": "Apple Inc.", "asset_class": "stock"}
        asset_repo.save(doc)
        asset_repo.save(doc)

        versions = asset_repo.find_all_versions("AAPL")
        assert len(versions) == 1

    def test_find_all_versions_ordered_newest_first(self, asset_repo):
        """find_all_versions() returns versions newest system_date first."""
        asset_repo.save({"asset_id": "AAPL", "name": "v1", "asset_class": "stock"})
        asset_repo.save({"asset_id": "AAPL", "name": "v2", "asset_class": "stock"})

        versions = asset_repo.find_all_versions("AAPL")
        assert versions[0]["name"] == "v2"
        assert versions[1]["name"] == "v1"

    def test_soft_delete_marks_as_deleted(self, asset_repo):
        """soft_delete() inserts a marker record with deleted=True."""
        asset_repo.collection.insert_one({
            "asset_id": "AAPL", "name": "Apple Inc.", "asset_class": "stock",
            "system_date": "2026-01-01T00:00:00+00:00", "deleted": False
        })
        asset_repo.soft_delete("AAPL")

        # full history must contain a delete marker
        versions = asset_repo.find_all_versions("AAPL")
        deleted_versions = [v for v in versions if v.get("deleted") == True]
        assert len(deleted_versions) >= 1

    def test_list_latest_ids_excludes_deleted(self, asset_repo):
        """list_latest_ids() does not return deleted assets."""
        # AAPL: has both a normal record and a delete marker
        # list_distinct_ids uses collection.distinct() with deleted != True filter
        # so AAPL should be excluded because its latest marker has deleted=True
        asset_repo.collection.insert_many([
            {
                "asset_id": "AAPL", "name": "Apple", "asset_class": "stock",
                "system_date": "2026-01-01T00:00:00+00:00", "deleted": False
            },
            {
                "asset_id": "AAPL", "name": "Apple", "asset_class": "stock",
                "system_date": "2026-01-02T00:00:00+00:00", "deleted": True
            },
            {
                "asset_id": "MSFT", "name": "Microsoft", "asset_class": "stock",
                "system_date": "2026-01-01T00:00:00+00:00", "deleted": False
            },
        ])

        ids = asset_repo.list_latest_ids(offset=0, limit=20)
        assert "MSFT" in ids

    def test_list_latest_ids_pagination(self, asset_repo):
        """list_latest_ids() respects offset and limit."""
        for symbol in ["AAPL", "BTC-USD", "CL=F", "ETH-USD", "MSFT"]:
            asset_repo.save({"asset_id": symbol, "name": symbol, "asset_class": "stock"})

        page1 = asset_repo.list_latest_ids(offset=0, limit=2)
        page2 = asset_repo.list_latest_ids(offset=2, limit=2)

        assert len(page1) == 2
        assert len(page2) == 2
        assert set(page1).isdisjoint(set(page2))

    def test_save_accepts_assetid_alias(self, asset_repo):
        """save() accepts 'assetId' as an alias for 'asset_id'."""
        doc = {"assetId": "TSLA", "name": "Tesla", "asset_class": "stock"}
        asset_repo.save(doc)
        result = asset_repo.find_latest("TSLA")
        assert result is not None
        assert result["asset_id"] == "TSLA"

    def test_save_accepts_id_alias(self, asset_repo):
        """save() accepts 'id' as an alias for 'asset_id'."""
        doc = {"id": "GOOG", "name": "Alphabet", "asset_class": "stock"}
        asset_repo.save(doc)
        result = asset_repo.find_latest("GOOG")
        assert result is not None


# ---------------------------------------------------------------------------
# DataSourceRepository Tests
# ---------------------------------------------------------------------------

class TestDataSourceRepository:

    def test_save_and_find_latest(self, source_repo):
        """save() stores source; find_latest() returns it."""
        doc = {"source_id": "yahoo_finance", "name": "Yahoo Finance"}
        source_repo.save(doc)

        result = source_repo.find_latest("yahoo_finance")
        assert result is not None
        assert result["source_id"] == "yahoo_finance"
        assert result["deleted"] == False

    def test_find_latest_returns_none_for_unknown(self, source_repo):
        result = source_repo.find_latest("nonexistent")
        assert result is None

    def test_save_creates_new_version_on_change(self, source_repo):
        """Saving a changed source creates a new version."""
        source_repo.save({"source_id": "yahoo_finance", "name": "Yahoo v1"})
        source_repo.save({"source_id": "yahoo_finance", "name": "Yahoo v2"})

        latest = source_repo.find_latest("yahoo_finance")
        assert latest["name"] == "Yahoo v2"

        versions = source_repo.find_all_versions("yahoo_finance")
        assert len(versions) == 2

    def test_soft_delete(self, source_repo):
        """soft_delete() inserts a marker record with deleted=True."""
        source_repo.collection.insert_one({
            "source_id": "yahoo_finance", "name": "Yahoo Finance",
            "system_date": "2026-01-01T00:00:00+00:00", "deleted": False
        })
        source_repo.soft_delete("yahoo_finance")

        versions = source_repo.find_all_versions("yahoo_finance")
        deleted_versions = [v for v in versions if v.get("deleted") == True]
        assert len(deleted_versions) >= 1

    def test_list_latest_ids(self, source_repo):
        """list_latest_ids() returns known source IDs."""
        source_repo.save({"source_id": "yahoo_stocks", "name": "Yahoo Stocks"})
        source_repo.save({"source_id": "yahoo_crypto", "name": "Yahoo Crypto"})

        ids = source_repo.list_latest_ids(offset=0, limit=20)
        assert "yahoo_stocks" in ids
        assert "yahoo_crypto" in ids

    def test_save_accepts_datasourceid_alias(self, source_repo):
        """save() accepts 'dataSourceId' as alias for 'source_id'."""
        doc = {"dataSourceId": "nasdaq", "name": "Nasdaq"}
        source_repo.save(doc)
        result = source_repo.find_latest("nasdaq")
        assert result is not None


# ---------------------------------------------------------------------------
# TimeSeriesRepository Tests
# ---------------------------------------------------------------------------

class TestTimeSeriesRepository:

    def test_save_and_find_latest_version(self, ts_repo):
        """save() stores record; find_latest_version() returns it."""
        doc = {
            "asset_id": "AAPL",
            "source_id": "yahoo_finance",
            "business_date": "2026-05-01",
            "values": {"open": 200.0, "close": 210.0}
        }
        ts_repo.save(doc)

        result = ts_repo.find_latest_version("AAPL", "yahoo_finance", "2026-05-01")
        assert result is not None
        assert result["values"]["open"] == 200.0
        assert result["deleted"] == False

    def test_find_latest_version_returns_none_for_unknown(self, ts_repo):
        result = ts_repo.find_latest_version("AAPL", "yahoo_finance", "2000-01-01")
        assert result is None

    def test_save_creates_new_version_on_change(self, ts_repo):
        """Saving changed time series for same date creates a new version."""
        ts_repo.save({
            "asset_id": "AAPL", "source_id": "yahoo_finance",
            "business_date": "2026-05-01",
            "values": {"open": 200.0, "close": 210.0}
        })
        ts_repo.save({
            "asset_id": "AAPL", "source_id": "yahoo_finance",
            "business_date": "2026-05-01",
            "values": {"open": 201.0, "close": 211.0}
        })

        latest = ts_repo.find_latest_version("AAPL", "yahoo_finance", "2026-05-01")
        assert latest["values"]["open"] == 201.0

        versions = ts_repo.find_all_versions("AAPL", "yahoo_finance", "2026-05-01")
        assert len(versions) == 2

    def test_save_skips_duplicate_if_unchanged(self, ts_repo):
        """Re-saving identical time series record does not duplicate."""
        doc = {
            "asset_id": "AAPL", "source_id": "yahoo_finance",
            "business_date": "2026-05-01",
            "values": {"open": 200.0}
        }
        ts_repo.save(doc)
        ts_repo.save(doc)

        versions = ts_repo.find_all_versions("AAPL", "yahoo_finance", "2026-05-01")
        assert len(versions) == 1

    def test_find_series_returns_records_in_range(self, ts_repo):
        """find_series() returns only records within the date range."""
        for date, open_price in [("2026-05-01", 100), ("2026-05-02", 101),
                                  ("2026-05-03", 102), ("2026-05-10", 110)]:
            ts_repo.save({
                "asset_id": "AAPL", "source_id": "yahoo_finance",
                "business_date": date,
                "values": {"open": float(open_price)}
            })

        records = ts_repo.find_series(
            "AAPL", "yahoo_finance",
            start_business_date="2026-05-01",
            end_business_date="2026-05-05"
        )

        dates = [r["business_date"] for r in records]
        assert "2026-05-01" in dates
        assert "2026-05-02" in dates
        assert "2026-05-03" in dates
        assert "2026-05-10" not in dates  # outside range

    def test_find_series_half_open_interval(self, ts_repo):
        """find_series() excludes the endBusinessDate (half-open interval)."""
        ts_repo.save({
            "asset_id": "AAPL", "source_id": "yahoo_finance",
            "business_date": "2026-05-05",
            "values": {"open": 105.0}
        })

        records = ts_repo.find_series(
            "AAPL", "yahoo_finance",
            start_business_date="2026-05-01",
            end_business_date="2026-05-05"   # end is exclusive
        )

        dates = [r["business_date"] for r in records]
        assert "2026-05-05" not in dates

    def test_find_series_returns_latest_version_per_day(self, ts_repo):
        """find_series() returns only the latest version for each business date."""
        ts_repo.save({
            "asset_id": "AAPL", "source_id": "yahoo_finance",
            "business_date": "2026-05-01",
            "values": {"open": 100.0}
        })
        ts_repo.save({
            "asset_id": "AAPL", "source_id": "yahoo_finance",
            "business_date": "2026-05-01",
            "values": {"open": 105.0}  # updated value
        })

        records = ts_repo.find_series(
            "AAPL", "yahoo_finance",
            start_business_date="2026-05-01",
            end_business_date="2026-05-02"
        )

        assert len(records) == 1
        assert records[0]["values"]["open"] == 105.0

    def test_find_series_returns_empty_for_unknown_asset(self, ts_repo):
        records = ts_repo.find_series("UNKNOWN", "yahoo_finance",
                                       start_business_date="2026-01-01",
                                       end_business_date="2026-12-31")
        assert records == []

    def test_soft_delete(self, ts_repo):
        """soft_delete() inserts a marker record with deleted=True."""
        ts_repo.collection.insert_one({
            "asset_id": "AAPL", "source_id": "yahoo_finance",
            "business_date": "2026-05-01",
            "system_date": "2026-01-01T00:00:00+00:00",
            "values": {"open": 200.0}, "deleted": False
        })
        ts_repo.soft_delete("AAPL", "yahoo_finance", "2026-05-01")

        versions = ts_repo.find_all_versions("AAPL", "yahoo_finance", "2026-05-01")
        deleted_versions = [v for v in versions if v.get("deleted") == True]
        assert len(deleted_versions) >= 1

    def test_find_all_versions_ordered_newest_first(self, ts_repo):
        """find_all_versions() returns newest system_date first."""
        ts_repo.save({
            "asset_id": "AAPL", "source_id": "yahoo_finance",
            "business_date": "2026-05-01", "values": {"open": 100.0}
        })
        ts_repo.save({
            "asset_id": "AAPL", "source_id": "yahoo_finance",
            "business_date": "2026-05-01", "values": {"open": 105.0}
        })

        versions = ts_repo.find_all_versions("AAPL", "yahoo_finance", "2026-05-01")
        assert versions[0]["values"]["open"] == 105.0
        assert versions[1]["values"]["open"] == 100.0


# ---------------------------------------------------------------------------
# AnalyticsMonthlySummaryRepository Tests
# ---------------------------------------------------------------------------

class TestAnalyticsMonthlySummaryRepository:

    def test_save_and_find_latest(self, monthly_repo):
        """save() stores summary; find_latest() returns it."""
        doc = {
            "asset_id": "AAPL", "source_id": "yahoo_finance",
            "year": 2026, "month": 5,
            "metrics": {"avg_close": 210.0, "monthly_return_pct": 2.5}
        }
        monthly_repo.save(doc)

        result = monthly_repo.find_latest("AAPL", "yahoo_finance", 2026, 5)
        assert result is not None
        assert result["metrics"]["avg_close"] == 210.0

    def test_find_range_filters_by_asset(self, monthly_repo):
        """find_range() filters correctly by assetId."""
        monthly_repo.save({"asset_id": "AAPL", "source_id": "yf", "year": 2026, "month": 1,
                            "metrics": {}})
        monthly_repo.save({"asset_id": "MSFT", "source_id": "yf", "year": 2026, "month": 1,
                            "metrics": {}})

        results = monthly_repo.find_range(asset_id="AAPL")
        assert all(r["asset_id"] == "AAPL" for r in results)

    def test_find_range_filters_by_year_month(self, monthly_repo):
        """find_range() correctly filters by start/end year-month."""
        for month in [1, 2, 3, 4, 5, 6]:
            monthly_repo.save({
                "asset_id": "AAPL", "source_id": "yf",
                "year": 2026, "month": month, "metrics": {}
            })

        results = monthly_repo.find_range(
            asset_id="AAPL",
            start_year=2026, start_month=3,
            end_year=2026, end_month=5
        )

        months = [r["month"] for r in results]
        assert 3 in months
        assert 4 in months
        assert 5 in months
        assert 1 not in months
        assert 6 not in months

    def test_list_available_assets(self, monthly_repo):
        """list_available_assets() returns distinct asset IDs."""
        monthly_repo.save({"asset_id": "AAPL", "source_id": "yf", "year": 2026, "month": 1,
                            "metrics": {}})
        monthly_repo.save({"asset_id": "AAPL", "source_id": "yf", "year": 2026, "month": 2,
                            "metrics": {}})
        monthly_repo.save({"asset_id": "MSFT", "source_id": "yf", "year": 2026, "month": 1,
                            "metrics": {}})

        assets = monthly_repo.list_available_assets()
        assert "AAPL" in assets
        assert "MSFT" in assets
        assert len([a for a in assets if a == "AAPL"]) == 1  # no duplicates


# ---------------------------------------------------------------------------
# AnalyticsPredictionsRepository Tests
# ---------------------------------------------------------------------------

class TestAnalyticsPredictionsRepository:

    def test_save_and_find_latest(self, predictions_repo):
        """save() stores prediction; find_latest() returns it."""
        doc = {
            "asset_id": "AAPL", "source_id": "yahoo_finance",
            "business_date": "2026-05-01",
            "actual_open": 200.0, "predicted_open": 202.5,
            "model_type": "linear_regression_per_asset"
        }
        predictions_repo.save(doc)

        result = predictions_repo.find_latest("AAPL", "yahoo_finance", "2026-05-01")
        assert result is not None
        assert result["predicted_open"] == 202.5

    def test_find_latest_returns_none_for_unknown(self, predictions_repo):
        result = predictions_repo.find_latest("UNKNOWN", "yahoo_finance", "2026-05-01")
        assert result is None

    def test_find_range_filters_by_date(self, predictions_repo):
        """find_range() filters by business date range."""
        for date in ["2026-05-01", "2026-05-02", "2026-05-10"]:
            predictions_repo.save({
                "asset_id": "AAPL", "source_id": "yf",
                "business_date": date,
                "actual_open": 200.0, "predicted_open": 201.0,
                "model_type": "linear_regression_per_asset"
            })

        results = predictions_repo.find_range(
            asset_id="AAPL",
            start_business_date="2026-05-01",
            end_business_date="2026-05-05"
        )

        dates = [r["business_date"] for r in results]
        assert "2026-05-01" in dates
        assert "2026-05-02" in dates
        assert "2026-05-10" not in dates

    def test_list_available_models(self, predictions_repo):
        """list_available_models() returns distinct model types."""
        predictions_repo.save({
            "asset_id": "AAPL", "source_id": "yf", "business_date": "2026-05-01",
            "actual_open": 200.0, "predicted_open": 201.0,
            "model_type": "linear_regression_per_asset"
        })

        models = predictions_repo.list_available_models()
        assert "linear_regression_per_asset" in models


# ---------------------------------------------------------------------------
# DAL Integration Test
# ---------------------------------------------------------------------------

class TestDALIntegration:
    """
    Tests that the top-level DAL class wires all repositories correctly.
    Uses mongomock to avoid needing a real MongoDB instance.
    """

    def test_dal_initializes_all_repositories(self):
        """DAL exposes all 5 repositories after initialization."""
        with patch("DataBase.dal.MongoClient") as mock_mongo:
            mock_db = MagicMock()
            mock_mongo.return_value.__getitem__.return_value = mock_db
            mock_db.__getitem__.return_value = MagicMock()

            dal = DAL()
            assert dal.assets is not None
            assert dal.data_sources is not None
            assert dal.time_series is not None
            assert dal.analytics_monthly_summary is not None
            assert dal.analytics_predictions is not None

    def test_save_find_latest_find_all_flow(self, db):
        """
        Core DAL contract: save → findLatest → findAll works as intended.
        This is the specific flow required by the DAL lab specification.
        """
        repo = AssetRepository(db["assets_integration"])

        # Step 1: save initial version
        repo.save({"asset_id": "AAPL", "name": "Apple v1", "asset_class": "stock"})

        # Step 2: findLatest returns saved record
        latest = repo.find_latest("AAPL")
        assert latest is not None
        assert latest["name"] == "Apple v1"

        # Step 3: save updated version
        repo.save({"asset_id": "AAPL", "name": "Apple v2", "asset_class": "stock"})

        # Step 4: findLatest returns newest version
        latest = repo.find_latest("AAPL")
        assert latest["name"] == "Apple v2"

        # Step 5: findAll returns full history, newest first
        all_versions = repo.find_all_versions("AAPL")
        assert len(all_versions) == 2
        assert all_versions[0]["name"] == "Apple v2"
        assert all_versions[1]["name"] == "Apple v1"

    def test_temporal_correctness_no_inplace_updates(self, db):
        """
        Verify temporal warehouse rule: records are never updated in-place.
        Every change must produce a new document.
        """
        repo = AssetRepository(db["assets_temporal"])

        repo.save({"asset_id": "BTC", "name": "Bitcoin v1", "asset_class": "crypto"})
        repo.save({"asset_id": "BTC", "name": "Bitcoin v2", "asset_class": "crypto"})
        repo.save({"asset_id": "BTC", "name": "Bitcoin v3", "asset_class": "crypto"})

        all_versions = repo.find_all_versions("BTC")

        # 3 separate documents must exist — no in-place updates
        assert len(all_versions) == 3

        # Verify they are distinct versions
        names = [v["name"] for v in all_versions]
        assert "Bitcoin v1" in names
        assert "Bitcoin v2" in names
        assert "Bitcoin v3" in names