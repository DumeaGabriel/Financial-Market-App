from pymongo import MongoClient
from pymongo import ASCENDING, DESCENDING


client = MongoClient("mongodb://localhost:27017")
db = client["financial_dwh"]

assets_col = db["assets"]
sources_col = db["data_sources"]
timeseries_col = db["time_series"]


def create_indexes():
    assets_col.create_index([("asset_id", ASCENDING)], unique=True)
    sources_col.create_index([("source_id", ASCENDING)], unique=True)
    timeseries_col.create_index([
        ("asset_id", ASCENDING),
        ("source_id", ASCENDING),
        ("business_date", ASCENDING),
        ("system_date", DESCENDING)
    ])


def list_assets():
    return list(assets_col.find({}, {"_id": 0}))

def get_asset(asset_id):
    return assets_col.find_one({"asset_id": asset_id}, {"_id": 0})

def list_sources():
    return list(sources_col.find({}, {"_id": 0}))

def get_source(source_id):
    return sources_col.find_one({"source_id": source_id}, {"_id": 0})

def get_time_series(asset_id, source_id):
    return list(timeseries_col.find(
        {"asset_id": asset_id, "source_id": source_id},
        {"_id": 0}
    ).sort("business_date", ASCENDING))

def get_latest_version(asset_id, source_id, business_date):
    return timeseries_col.find_one(
        {
            "asset_id": asset_id,
            "source_id": source_id,
            "business_date": business_date
        },
        {"_id": 0},
        sort=[("system_date", DESCENDING)]
    )