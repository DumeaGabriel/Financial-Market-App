from fastapi.testclient import TestClient
import api


class MockAssetsRepo:
    def list_latest_ids(self, offset=0, limit=20):
        data = ["AAPL", "BTC-USD", "CL=F", "ETH-USD"]
        return data[offset:offset + limit]

    def find_latest(self, asset_id):
        if asset_id == "AAPL":
            return {
                "asset_id": "AAPL",
                "name": "Apple Inc.",
                "asset_class": "stock",
                "system_date": "2026-06-01T00:00:00+00:00",
                "deleted": False
            }
        return None

    def find_all_versions(self, asset_id):
        if asset_id == "AAPL":
            return [
                {
                    "asset_id": "AAPL",
                    "name": "Apple Inc.",
                    "system_date": "2026-06-01T00:00:00+00:00",
                    "deleted": False
                },
                {
                    "asset_id": "AAPL",
                    "name": "Apple Incorporated",
                    "system_date": "2026-05-01T00:00:00+00:00",
                    "deleted": False
                }
            ]
        return []


class MockDataSourcesRepo:
    def list_latest_ids(self, offset=0, limit=20):
        data = ["yahoo_finance_stocks", "yahoo_finance_crypto"]
        return data[offset:offset + limit]

    def find_latest(self, source_id):
        if source_id == "yahoo_finance_stocks":
            return {
                "source_id": "yahoo_finance_stocks",
                "name": "Yahoo Finance",
                "system_date": "2026-06-01T00:00:00+00:00",
                "deleted": False
            }
        return None

    def find_all_versions(self, source_id):
        if source_id == "yahoo_finance_stocks":
            return [
                {
                    "source_id": "yahoo_finance_stocks",
                    "name": "Yahoo Finance",
                    "system_date": "2026-06-01T00:00:00+00:00",
                    "deleted": False
                }
            ]
        return []


class MockTimeSeriesRepo:
    def find_series(self, asset_id, source_id, start_business_date=None, end_business_date=None):
        if asset_id == "AAPL" and source_id == "yahoo_finance_stocks":
            return [
                {
                    "asset_id": "AAPL",
                    "source_id": "yahoo_finance_stocks",
                    "business_date": "2026-05-03",
                    "system_date": "2026-05-03T10:00:00+00:00",
                    "values": {"open": 200.0, "close": 210.0, "volume": 1000},
                    "deleted": False
                },
                {
                    "asset_id": "AAPL",
                    "source_id": "yahoo_finance_stocks",
                    "business_date": "2026-05-02",
                    "system_date": "2026-05-02T10:00:00+00:00",
                    "values": {"open": 190.0, "high": 205.0},
                    "deleted": False
                }
            ]
        return []

    def find_all_versions(self, asset_id, source_id, business_date):
        if asset_id == "AAPL" and source_id == "yahoo_finance_stocks" and business_date == "2026-05-03":
            return [
                {
                    "asset_id": "AAPL",
                    "source_id": "yahoo_finance_stocks",
                    "business_date": "2026-05-03",
                    "system_date": "2026-05-03T10:00:00+00:00",
                    "values": {"open": 200.0, "close": 210.0},
                    "deleted": False
                },
                {
                    "asset_id": "AAPL",
                    "source_id": "yahoo_finance_stocks",
                    "business_date": "2026-05-03",
                    "system_date": "2026-05-03T08:00:00+00:00",
                    "values": {"open": 198.0, "close": 209.0},
                    "deleted": False
                }
            ]
        return []


class MockDAL:
    def __init__(self):
        self.assets = MockAssetsRepo()
        self.data_sources = MockDataSourcesRepo()
        self.time_series = MockTimeSeriesRepo()

    def create_indexes(self):
        pass


api.dal = MockDAL()
client = TestClient(api.app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Financial DWH API is running"
    assert body["basePath"] == "/api/v1"


def test_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_list_assets_default():
    response = client.get("/api/v1/assets")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == ["AAPL", "BTC-USD", "CL=F", "ETH-USD"]
    assert body["offset"] == 0
    assert body["limit"] == 20
    assert body["count"] == 4


def test_list_assets_pagination():
    response = client.get("/api/v1/assets?offset=1&limit=2")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == ["BTC-USD", "CL=F"]
    assert body["offset"] == 1
    assert body["limit"] == 2
    assert body["count"] == 2


def test_get_asset_found():
    response = client.get("/api/v1/assets/AAPL")
    assert response.status_code == 200
    body = response.json()
    assert body["asset_id"] == "AAPL"
    assert body["name"] == "Apple Inc."


def test_get_asset_not_found():
    response = client.get("/api/v1/assets/MSFT")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_asset_history():
    response = client.get("/api/v1/assets/AAPL?history=true")
    assert response.status_code == 200
    body = response.json()
    assert body["assetId"] == "AAPL"
    assert len(body["versions"]) == 2


def test_list_data_sources():
    response = client.get("/api/v1/data-sources")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == ["yahoo_finance_stocks", "yahoo_finance_crypto"]


def test_get_data_source_found():
    response = client.get("/api/v1/data-sources/yahoo_finance_stocks")
    assert response.status_code == 200
    body = response.json()
    assert body["source_id"] == "yahoo_finance_stocks"


def test_get_data_source_not_found():
    response = client.get("/api/v1/data-sources/unknown_source")
    assert response.status_code == 404


def test_get_time_series():
    response = client.get(
        "/api/v1/data",
        params={
            "assetId": "AAPL",
            "dataSourceId": "yahoo_finance_stocks",
            "startBusinessDate": "2026-05-01",
            "endBusinessDate": "2026-05-10",
            "includeAttributes": "false"
        }
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["assetId"] == "AAPL"
    assert body["data"]["dataSourceId"] == "yahoo_finance_stocks"
    assert len(body["data"]["records"]) == 2
    assert body["data"]["records"][0]["businessDate"] == "2026-05-03"


def test_get_time_series_with_attributes():
    response = client.get(
        "/api/v1/data",
        params={
            "assetId": "AAPL",
            "dataSourceId": "yahoo_finance_stocks",
            "startBusinessDate": "2026-05-01",
            "endBusinessDate": "2026-05-10",
            "includeAttributes": "true"
        }
    )
    assert response.status_code == 200
    body = response.json()
    assert "attributes" in body
    assert "open" in body["attributes"]
    assert "close" in body["attributes"]


def test_get_time_series_history_for_day():
    response = client.get(
        "/api/v1/data/history",
        params={
            "assetId": "AAPL",
            "dataSourceId": "yahoo_finance_stocks",
            "businessDate": "2026-05-03"
        }
    )
    assert response.status_code == 200
    body = response.json()
    assert body["assetId"] == "AAPL"
    assert body["dataSourceId"] == "yahoo_finance_stocks"
    assert body["businessDate"] == "2026-05-03"
    assert len(body["versions"]) == 2


def test_get_time_series_history_for_day_not_found():
    response = client.get(
        "/api/v1/data/history",
        params={
            "assetId": "AAPL",
            "dataSourceId": "yahoo_finance_stocks",
            "businessDate": "2026-01-01"
        }
    )
    assert response.status_code == 404