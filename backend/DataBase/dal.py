from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo import ASCENDING, DESCENDING, MongoClient


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MongoDAL:
    def __init__(
        self,
        mongo_uri: str = "mongodb://localhost:27017",
        db_name: str = "financial_dwh"
    ):
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]

        self.assets = self.db["assets"]
        self.data_sources = self.db["data_sources"]
        self.time_series = self.db["time_series"]
        self.analytics_monthly_summary = self.db["analytics_monthly_summary"]
        self.analytics_predictions = self.db["analytics_predictions"]

    def create_indexes(self) -> None:
        self.assets.create_index(
            [("asset_id", ASCENDING), ("system_date", DESCENDING)]
        )
        self.data_sources.create_index(
            [("source_id", ASCENDING), ("system_date", DESCENDING)]
        )
        self.time_series.create_index(
            [
                ("asset_id", ASCENDING),
                ("source_id", ASCENDING),
                ("business_date", ASCENDING),
                ("system_date", DESCENDING),
            ]
        )
        self.time_series.create_index(
            [
                ("asset_id", ASCENDING),
                ("source_id", ASCENDING),
                ("business_year", ASCENDING),
                ("business_date", ASCENDING),
            ]
        )
        self.analytics_monthly_summary.create_index(
            [
                ("asset_id", ASCENDING),
                ("source_id", ASCENDING),
                ("year", DESCENDING),
                ("month", DESCENDING),
                ("generated_at", DESCENDING),
            ]
        )
        self.analytics_monthly_summary.create_index(
            [("symbol", ASCENDING), ("year", DESCENDING), ("month", DESCENDING)]
        )
        self.analytics_monthly_summary.create_index(
            [("asset_class", ASCENDING), ("year", DESCENDING), ("month", DESCENDING)]
        )
        self.analytics_predictions.create_index(
            [
                ("asset_id", ASCENDING),
                ("source_id", ASCENDING),
                ("business_date", DESCENDING),
                ("generated_at", DESCENDING),
            ]
        )
        self.analytics_predictions.create_index(
            [("model_type", ASCENDING), ("generated_at", DESCENDING)]
        )


class BaseRepository:
    def __init__(self, collection, key_field: str):
        self.collection = collection
        self.key_field = key_field

    def insert_version(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(doc)
        normalized.setdefault("system_date", utc_now())
        normalized.setdefault("deleted", False)
        self.collection.insert_one(normalized)
        normalized.pop("_id", None)
        return normalized

    def find_latest(self, key_value: str) -> Optional[Dict[str, Any]]:
        return self.collection.find_one(
            {
                self.key_field: key_value,
                "deleted": {"$ne": True}
            },
            {"_id": 0},
            sort=[("system_date", DESCENDING)]
        )

    def find_all_versions(self, key_value: str) -> List[Dict[str, Any]]:
        return list(
            self.collection.find(
                {self.key_field: key_value},
                {"_id": 0}
            ).sort("system_date", DESCENDING)
        )

    def list_distinct_ids(
        self,
        id_field: str,
        offset: int = 0,
        limit: int = 20
    ) -> List[str]:
        ids = self.collection.distinct(
            id_field,
            {"deleted": {"$ne": True}}
        )
        ids = sorted(ids)
        return ids[offset:offset + limit]

    def find_latest_by_filter(self, filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        query = dict(filters)
        query["deleted"] = {"$ne": True}

        return self.collection.find_one(
            query,
            {"_id": 0},
            sort=[("system_date", DESCENDING)]
        )

    def find_all_by_filter(
        self,
        filters: Dict[str, Any],
        offset: int = 0,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        query = dict(filters)
        query["deleted"] = {"$ne": True}

        return list(
            self.collection.find(query, {"_id": 0})
            .sort("system_date", DESCENDING)
            .skip(offset)
            .limit(limit)
        )

    def soft_delete(
        self,
        key_value: str,
        extra_fields: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        latest = self.collection.find_one(
            {self.key_field: key_value},
            sort=[("system_date", DESCENDING)]
        )

        if latest is None:
            raise ValueError(f"No record found for {self.key_field}={key_value}")

        delete_doc = dict(latest)
        delete_doc.pop("_id", None)
        delete_doc["system_date"] = utc_now()
        delete_doc["deleted"] = True

        if extra_fields:
            delete_doc.update(extra_fields)

        self.collection.insert_one(delete_doc)
        return delete_doc

    def _save_version_if_changed(
        self,
        doc: Dict[str, Any],
        latest_query: Dict[str, Any],
        timestamp_field: str = "system_date"
    ) -> Dict[str, Any]:
        normalized = dict(doc)
        normalized.setdefault(timestamp_field, utc_now())
        normalized.setdefault("deleted", False)

        latest = self.collection.find_one(
            latest_query,
            sort=[(timestamp_field, DESCENDING)]
        )

        if latest:
            latest_no_id = dict(latest)
            latest_no_id.pop("_id", None)

            compare_latest = dict(latest_no_id)
            compare_new = dict(normalized)

            compare_latest.pop(timestamp_field, None)
            compare_new.pop(timestamp_field, None)

            if compare_latest == compare_new:
                return latest_no_id

        self.collection.insert_one(normalized)
        normalized.pop("_id", None)
        return normalized


class AssetRepository(BaseRepository):
    def __init__(self, collection):
        super().__init__(collection, "asset_id")

    def save_version(self, asset_doc: Dict[str, Any]) -> Dict[str, Any]:
        return self._save_version_if_changed(
            asset_doc,
            {"asset_id": asset_doc["asset_id"]}
        )

    def save(self, asset_doc: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(asset_doc)

        if "asset_id" not in normalized:
            if "id" in normalized:
                normalized["asset_id"] = normalized["id"]
            elif "assetId" in normalized:
                normalized["asset_id"] = normalized["assetId"]
            else:
                raise ValueError("Asset document must include 'asset_id', 'id', or 'assetId'")

        return self.save_version(normalized)

    def list_latest_ids(self, offset: int = 0, limit: int = 20) -> List[str]:
        return self.list_distinct_ids("asset_id", offset, limit)


class DataSourceRepository(BaseRepository):
    def __init__(self, collection):
        super().__init__(collection, "source_id")

    def save_version(self, source_doc: Dict[str, Any]) -> Dict[str, Any]:
        return self._save_version_if_changed(
            source_doc,
            {"source_id": source_doc["source_id"]}
        )

    def save(self, source_doc: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(source_doc)

        if "source_id" not in normalized:
            if "id" in normalized:
                normalized["source_id"] = normalized["id"]
            elif "dataSourceId" in normalized:
                normalized["source_id"] = normalized["dataSourceId"]
            else:
                raise ValueError("Data source document must include 'source_id', 'id', or 'dataSourceId'")

        return self.save_version(normalized)

    def list_latest_ids(self, offset: int = 0, limit: int = 20) -> List[str]:
        return self.list_distinct_ids("source_id", offset, limit)


class TimeSeriesRepository:
    def __init__(self, collection):
        self.collection = collection

    def save_version(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(doc)
        normalized.setdefault("system_date", utc_now())
        normalized.setdefault("deleted", False)

        latest = self.collection.find_one(
            {
                "asset_id": normalized["asset_id"],
                "source_id": normalized["source_id"],
                "business_date": normalized["business_date"],
            },
            sort=[("system_date", DESCENDING)]
        )

        if latest:
            latest_no_id = dict(latest)
            latest_no_id.pop("_id", None)

            compare_latest = dict(latest_no_id)
            compare_new = dict(normalized)

            compare_latest.pop("system_date", None)
            compare_new.pop("system_date", None)

            if compare_latest == compare_new:
                return latest_no_id

        self.collection.insert_one(normalized)
        normalized.pop("_id", None)
        return normalized

    def save(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        return self.save_version(doc)

    def find_latest_version(
        self,
        asset_id: str,
        source_id: str,
        business_date: str
    ) -> Optional[Dict[str, Any]]:
        return self.collection.find_one(
            {
                "asset_id": asset_id,
                "source_id": source_id,
                "business_date": business_date,
                "deleted": {"$ne": True}
            },
            {"_id": 0},
            sort=[("system_date", DESCENDING)]
        )

    def find_all_versions(
        self,
        asset_id: str,
        source_id: str,
        business_date: str
    ) -> List[Dict[str, Any]]:
        return list(
            self.collection.find(
                {
                    "asset_id": asset_id,
                    "source_id": source_id,
                    "business_date": business_date
                },
                {"_id": 0}
            ).sort("system_date", DESCENDING)
        )

    def find_series(
        self,
        asset_id: str,
        source_id: str,
        start_business_date: Optional[str] = None,
        end_business_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {
            "asset_id": asset_id,
            "source_id": source_id,
            "deleted": {"$ne": True}
        }

        if start_business_date or end_business_date:
            query["business_date"] = {}
            if start_business_date:
                query["business_date"]["$gte"] = start_business_date
            if end_business_date:
                query["business_date"]["$lt"] = end_business_date

        rows = list(
            self.collection.find(query, {"_id": 0}).sort(
                [("business_date", DESCENDING), ("system_date", DESCENDING)]
            )
        )

        latest_per_day: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            business_date = row["business_date"]
            if business_date not in latest_per_day:
                latest_per_day[business_date] = row

        return list(latest_per_day.values())

    def find_series_by_filter(
        self,
        filters: Dict[str, Any],
        offset: int = 0,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        query = dict(filters)
        query["deleted"] = {"$ne": True}

        return list(
            self.collection.find(query, {"_id": 0})
            .sort([("business_date", DESCENDING), ("system_date", DESCENDING)])
            .skip(offset)
            .limit(limit)
        )

    def list_available_business_dates(
        self,
        asset_id: str,
        source_id: str
    ) -> List[str]:
        dates = self.collection.distinct(
            "business_date",
            {
                "asset_id": asset_id,
                "source_id": source_id,
                "deleted": {"$ne": True}
            }
        )
        return sorted(dates, reverse=True)

    def soft_delete(
        self,
        asset_id: str,
        source_id: str,
        business_date: str
    ) -> Dict[str, Any]:
        latest = self.collection.find_one(
            {
                "asset_id": asset_id,
                "source_id": source_id,
                "business_date": business_date
            },
            sort=[("system_date", DESCENDING)]
        )

        if latest is None:
            raise ValueError(
                f"No time series record found for asset_id={asset_id}, "
                f"source_id={source_id}, business_date={business_date}"
            )

        delete_doc = dict(latest)
        delete_doc.pop("_id", None)
        delete_doc["system_date"] = utc_now()
        delete_doc["deleted"] = True

        self.collection.insert_one(delete_doc)
        return delete_doc


class AnalyticsMonthlySummaryRepository:
    def __init__(self, collection):
        self.collection = collection

    def save(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        return self.save_version(doc)

    def save_version(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(doc)

        required_fields = ["asset_id", "source_id", "year", "month"]
        missing = [field for field in required_fields if field not in normalized]
        if missing:
            raise ValueError(f"Monthly summary document missing required fields: {missing}")

        normalized.setdefault("generated_at", utc_now())
        normalized.setdefault("deleted", False)

        latest = self.collection.find_one(
            {
                "asset_id": normalized["asset_id"],
                "source_id": normalized["source_id"],
                "year": normalized["year"],
                "month": normalized["month"],
            },
            sort=[("generated_at", DESCENDING)]
        )

        if latest:
            latest_no_id = dict(latest)
            latest_no_id.pop("_id", None)

            compare_latest = dict(latest_no_id)
            compare_new = dict(normalized)

            compare_latest.pop("generated_at", None)
            compare_new.pop("generated_at", None)

            if compare_latest == compare_new:
                return latest_no_id

        self.collection.insert_one(normalized)
        normalized.pop("_id", None)
        return normalized

    def find_latest(
        self,
        asset_id: str,
        source_id: str,
        year: int,
        month: int
    ) -> Optional[Dict[str, Any]]:
        return self.collection.find_one(
            {
                "asset_id": asset_id,
                "source_id": source_id,
                "year": year,
                "month": month,
                "deleted": {"$ne": True}
            },
            {"_id": 0},
            sort=[("generated_at", DESCENDING)]
        )

    def find_by_asset(
        self,
        asset_id: str,
        offset: int = 0,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        return list(
            self.collection.find(
                {
                    "asset_id": asset_id,
                    "deleted": {"$ne": True}
                },
                {"_id": 0}
            )
            .sort([("year", DESCENDING), ("month", DESCENDING), ("generated_at", DESCENDING)])
            .skip(offset)
            .limit(limit)
        )

    def find_by_asset_source(
        self,
        asset_id: str,
        source_id: str,
        offset: int = 0,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        return list(
            self.collection.find(
                {
                    "asset_id": asset_id,
                    "source_id": source_id,
                    "deleted": {"$ne": True}
                },
                {"_id": 0}
            )
            .sort([("year", DESCENDING), ("month", DESCENDING), ("generated_at", DESCENDING)])
            .skip(offset)
            .limit(limit)
        )

    def find_by_symbol(
        self,
        symbol: str,
        offset: int = 0,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        return list(
            self.collection.find(
                {
                    "symbol": symbol,
                    "deleted": {"$ne": True}
                },
                {"_id": 0}
            )
            .sort([("year", DESCENDING), ("month", DESCENDING), ("generated_at", DESCENDING)])
            .skip(offset)
            .limit(limit)
        )

    def find_range(
        self,
        asset_id: Optional[str] = None,
        source_id: Optional[str] = None,
        symbol: Optional[str] = None,
        asset_class: Optional[str] = None,
        start_year: Optional[int] = None,
        start_month: Optional[int] = None,
        end_year: Optional[int] = None,
        end_month: Optional[int] = None,
        offset: int = 0,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"deleted": {"$ne": True}}

        if asset_id:
            query["asset_id"] = asset_id
        if source_id:
            query["source_id"] = source_id
        if symbol:
            query["symbol"] = symbol
        if asset_class:
            query["asset_class"] = asset_class

        rows = list(
            self.collection.find(query, {"_id": 0})
            .sort([("year", DESCENDING), ("month", DESCENDING), ("generated_at", DESCENDING)])
        )

        filtered: List[Dict[str, Any]] = []
        for row in rows:
            ym = int(row["year"]) * 100 + int(row["month"])
            if start_year is not None and start_month is not None:
                if ym < (start_year * 100 + start_month):
                    continue
            if end_year is not None and end_month is not None:
                if ym > (end_year * 100 + end_month):
                    continue
            filtered.append(row)

        return filtered[offset:offset + limit]

    def list_available_assets(self, offset: int = 0, limit: int = 20) -> List[str]:
        ids = self.collection.distinct(
            "asset_id",
            {"deleted": {"$ne": True}}
        )
        return sorted(ids)[offset:offset + limit]

    def list_available_symbols(self, offset: int = 0, limit: int = 20) -> List[str]:
        symbols = self.collection.distinct(
            "symbol",
            {"deleted": {"$ne": True}}
        )
        return sorted([s for s in symbols if s is not None])[offset:offset + limit]

    def list_available_asset_classes(self) -> List[str]:
        classes = self.collection.distinct(
            "asset_class",
            {"deleted": {"$ne": True}}
        )
        return sorted([c for c in classes if c is not None])

    def soft_delete(
        self,
        asset_id: str,
        source_id: str,
        year: int,
        month: int
    ) -> Dict[str, Any]:
        latest = self.collection.find_one(
            {
                "asset_id": asset_id,
                "source_id": source_id,
                "year": year,
                "month": month,
            },
            sort=[("generated_at", DESCENDING)]
        )

        if latest is None:
            raise ValueError(
                f"No monthly summary found for asset_id={asset_id}, "
                f"source_id={source_id}, year={year}, month={month}"
            )

        delete_doc = dict(latest)
        delete_doc.pop("_id", None)
        delete_doc["generated_at"] = utc_now()
        delete_doc["deleted"] = True

        self.collection.insert_one(delete_doc)
        return delete_doc


class AnalyticsPredictionsRepository:
    def __init__(self, collection):
        self.collection = collection

    def save(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        return self.save_version(doc)

    def save_version(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(doc)

        required_fields = ["asset_id", "source_id", "business_date"]
        missing = [field for field in required_fields if field not in normalized]
        if missing:
            raise ValueError(f"Prediction document missing required fields: {missing}")

        normalized.setdefault("generated_at", utc_now())
        normalized.setdefault("deleted", False)

        latest = self.collection.find_one(
            {
                "asset_id": normalized["asset_id"],
                "source_id": normalized["source_id"],
                "business_date": normalized["business_date"],
                "model_type": normalized.get("model_type"),
            },
            sort=[("generated_at", DESCENDING)]
        )

        if latest:
            latest_no_id = dict(latest)
            latest_no_id.pop("_id", None)

            compare_latest = dict(latest_no_id)
            compare_new = dict(normalized)

            compare_latest.pop("generated_at", None)
            compare_new.pop("generated_at", None)

            if compare_latest == compare_new:
                return latest_no_id

        self.collection.insert_one(normalized)
        normalized.pop("_id", None)
        return normalized

    def find_latest(
        self,
        asset_id: str,
        source_id: str,
        business_date: str,
        model_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        query: Dict[str, Any] = {
            "asset_id": asset_id,
            "source_id": source_id,
            "business_date": business_date,
            "deleted": {"$ne": True}
        }
        if model_type is not None:
            query["model_type"] = model_type

        return self.collection.find_one(
            query,
            {"_id": 0},
            sort=[("generated_at", DESCENDING)]
        )

    def find_by_asset(
        self,
        asset_id: str,
        offset: int = 0,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        return list(
            self.collection.find(
                {
                    "asset_id": asset_id,
                    "deleted": {"$ne": True}
                },
                {"_id": 0}
            )
            .sort([("business_date", DESCENDING), ("generated_at", DESCENDING)])
            .skip(offset)
            .limit(limit)
        )

    def find_by_asset_source(
        self,
        asset_id: str,
        source_id: str,
        offset: int = 0,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        return list(
            self.collection.find(
                {
                    "asset_id": asset_id,
                    "source_id": source_id,
                    "deleted": {"$ne": True}
                },
                {"_id": 0}
            )
            .sort([("business_date", DESCENDING), ("generated_at", DESCENDING)])
            .skip(offset)
            .limit(limit)
        )

    def find_range(
        self,
        asset_id: Optional[str] = None,
        source_id: Optional[str] = None,
        model_type: Optional[str] = None,
        start_business_date: Optional[str] = None,
        end_business_date: Optional[str] = None,
        offset: int = 0,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {
            "deleted": {"$ne": True}
        }

        if asset_id:
            query["asset_id"] = asset_id
        if source_id:
            query["source_id"] = source_id
        if model_type:
            query["model_type"] = model_type
        if start_business_date or end_business_date:
            query["business_date"] = {}
            if start_business_date:
                query["business_date"]["$gte"] = start_business_date
            if end_business_date:
                query["business_date"]["$lt"] = end_business_date

        return list(
            self.collection.find(query, {"_id": 0})
            .sort([("business_date", DESCENDING), ("generated_at", DESCENDING)])
            .skip(offset)
            .limit(limit)
        )

    def list_available_assets(self, offset: int = 0, limit: int = 20) -> List[str]:
        ids = self.collection.distinct(
            "asset_id",
            {"deleted": {"$ne": True}}
        )
        return sorted(ids)[offset:offset + limit]

    def list_available_models(self) -> List[str]:
        models = self.collection.distinct(
            "model_type",
            {"deleted": {"$ne": True}}
        )
        return sorted([m for m in models if m is not None])

    def soft_delete(
        self,
        asset_id: str,
        source_id: str,
        business_date: str,
        model_type: Optional[str] = None
    ) -> Dict[str, Any]:
        query: Dict[str, Any] = {
            "asset_id": asset_id,
            "source_id": source_id,
            "business_date": business_date,
        }
        if model_type is not None:
            query["model_type"] = model_type

        latest = self.collection.find_one(
            query,
            sort=[("generated_at", DESCENDING)]
        )

        if latest is None:
            raise ValueError(
                f"No prediction found for asset_id={asset_id}, "
                f"source_id={source_id}, business_date={business_date}, "
                f"model_type={model_type}"
            )

        delete_doc = dict(latest)
        delete_doc.pop("_id", None)
        delete_doc["generated_at"] = utc_now()
        delete_doc["deleted"] = True

        self.collection.insert_one(delete_doc)
        return delete_doc


class DAL:
    def __init__(
        self,
        mongo_uri: str = "mongodb://localhost:27017",
        db_name: str = "financial_dwh"
    ):
        self.mongo = MongoDAL(mongo_uri=mongo_uri, db_name=db_name)
        self.assets = AssetRepository(self.mongo.assets)
        self.data_sources = DataSourceRepository(self.mongo.data_sources)
        self.time_series = TimeSeriesRepository(self.mongo.time_series)
        self.analytics_monthly_summary = AnalyticsMonthlySummaryRepository(
            self.mongo.analytics_monthly_summary
        )
        self.analytics_predictions = AnalyticsPredictionsRepository(
            self.mongo.analytics_predictions
        )

    def create_indexes(self) -> None:
        self.mongo.create_indexes()