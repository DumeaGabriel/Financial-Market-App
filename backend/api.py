from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from DataBase.dal import DAL

from datetime import datetime, timedelta, timezone

app = FastAPI(
    title="Financial Data Warehouse API",
    version="1.0.0",
    description="REST API for consuming assets, data sources, time-series data, and analytics from the financial DWH."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

dal = DAL()
dal.create_indexes()


class UpdateRequest(BaseModel):
    period: str = "3mo"


class EntityFieldsUpdateRequest(BaseModel):
    fields: Dict[str, Any]


class TimeSeriesUpdateRequest(BaseModel):
    businessDate: str
    values: Dict[str, Any]


def not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=404, detail=detail)


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "message": "Financial DWH API is running",
        "docs": "/docs",
        "basePath": "/api/v1"
    }


@app.get("/api/v1/assets")
def list_assets(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100)
) -> Dict[str, Any]:
    items = dal.assets.list_latest_ids(offset=offset, limit=limit)

    return {
        "items": items,
        "offset": offset,
        "limit": limit,
        "count": len(items)
    }


@app.get("/api/v1/assets/{asset_id}")
def get_asset(
    asset_id: str,
    history: bool = Query(False)
) -> Dict[str, Any]:
    if history:
        versions = dal.assets.find_all_versions(asset_id)
        if not versions:
            raise not_found(f"Asset '{asset_id}' not found")
        return {
            "assetId": asset_id,
            "versions": versions
        }

    asset = dal.assets.find_latest(asset_id)
    if not asset:
        raise not_found(f"Asset '{asset_id}' not found")

    return asset


@app.put("/api/v1/admin/assets/{asset_id}")
def update_asset_admin(
    asset_id: str,
    req: EntityFieldsUpdateRequest
) -> Dict[str, Any]:
    current = dal.assets.find_latest(asset_id)
    if not current:
        raise not_found(f"Asset '{asset_id}' not found")

    updated = dict(current)
    updated.update(req.fields)
    updated["asset_id"] = asset_id
    updated["id"] = asset_id
    updated["assetId"] = asset_id

    saved = dal.assets.save(updated)
    return saved


@app.get("/api/v1/data-sources")
def list_data_sources(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100)
) -> Dict[str, Any]:
    items = dal.data_sources.list_latest_ids(offset=offset, limit=limit)

    return {
        "items": items,
        "offset": offset,
        "limit": limit,
        "count": len(items)
    }


@app.get("/api/v1/data-sources/{source_id}")
def get_data_source(
    source_id: str,
    history: bool = Query(False)
) -> Dict[str, Any]:
    if history:
        versions = dal.data_sources.find_all_versions(source_id)
        if not versions:
            raise not_found(f"Data source '{source_id}' not found")
        return {
            "dataSourceId": source_id,
            "versions": versions
        }

    source = dal.data_sources.find_latest(source_id)
    if not source:
        raise not_found(f"Data source '{source_id}' not found")

    return source


@app.put("/api/v1/admin/data-sources/{source_id}")
def update_data_source_admin(
    source_id: str,
    req: EntityFieldsUpdateRequest
) -> Dict[str, Any]:
    current = dal.data_sources.find_latest(source_id)
    if not current:
        raise not_found(f"Data source '{source_id}' not found")

    updated = dict(current)
    updated.update(req.fields)
    updated["source_id"] = source_id
    updated["id"] = source_id
    updated["dataSourceId"] = source_id

    saved = dal.data_sources.save(updated)
    return saved


@app.get("/api/v1/data")
def get_time_series(
    assetId: str = Query(...),
    dataSourceId: str = Query(...),
    startBusinessDate: str = Query(...),
    endBusinessDate: str = Query(...),
    includeAttributes: bool = Query(False),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=365)
) -> Dict[str, Any]:
    records = dal.time_series.find_series_by_filter(
        filters={"asset_id": assetId, "source_id": dataSourceId,
                 "business_date": {"$gte": startBusinessDate, "$lt": endBusinessDate}},
        offset=offset,
        limit=limit
    )

    response: Dict[str, Any] = {
        "data": {
            "assetId": assetId,
            "dataSourceId": dataSourceId,
            "records": [
                {
                    "businessDate": record["business_date"],
                    "systemDate": record["system_date"],
                    "values": record.get("values", {})
                }
                for record in records
            ]
        }
    }

    if includeAttributes:
        attributes = set()
        for record in records:
            values = record.get("values", {})
            for key in values.keys():
                attributes.add(key)

        response["attributes"] = sorted(attributes)

    return response


@app.get("/api/v1/data/history")
def get_time_series_versions_for_day(
    assetId: str = Query(..., min_length=1),
    dataSourceId: str = Query(..., min_length=1),
    businessDate: str = Query(..., min_length=10)
) -> Dict[str, Any]:
    versions = dal.time_series.find_all_versions(
        asset_id=assetId,
        source_id=dataSourceId,
        business_date=businessDate
    )

    if not versions:
        raise not_found(
            f"No time-series versions found for assetId='{assetId}', "
            f"dataSourceId='{dataSourceId}', businessDate='{businessDate}'"
        )

    return {
        "assetId": assetId,
        "dataSourceId": dataSourceId,
        "businessDate": businessDate,
        "versions": versions
    }


@app.put("/api/v1/admin/time-series/{asset_id}/{source_id}")
def update_time_series_admin(
    asset_id: str,
    source_id: str,
    req: TimeSeriesUpdateRequest
) -> Dict[str, Any]:
    next_date = (
            datetime.strptime(req.businessDate, "%Y-%m-%d") + timedelta(days=1)
    ).strftime("%Y-%m-%d")

    records = dal.time_series.find_series_by_filter(
        filters={
            "asset_id": asset_id,
            "source_id": source_id,
            "business_date": {"$gte": req.businessDate, "$lt": next_date}
        },
        offset=0,
        limit=100
    )

    if not records:
        raise not_found(
            f"No time-series record found for assetId='{asset_id}', "
            f"dataSourceId='{source_id}', businessDate='{req.businessDate}'"
        )

    # Pick the record with the latest system_date
    record = max(records, key=lambda r: r.get("system_date", ""))

    updated = dict(record)
    updated["values"] = req.values
    updated["system_date"] = datetime.now(timezone.utc).isoformat()

    saved = dal.time_series.save(updated)
    return saved

@app.post("/api/v1/admin/update/stocks")
def update_stocks(req: UpdateRequest) -> Dict[str, Any]:
    try:
        from DataBase.stocks_ingestion import run
        run(period=req.period)
        return {
            "status": "ok",
            "message": "Stocks update completed",
            "period": req.period
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stocks update failed: {str(e)}")


@app.post("/api/v1/admin/update/crypto")
def update_crypto(req: UpdateRequest) -> Dict[str, Any]:
    try:
        from DataBase.crypto_ingestion import run
        run(period=req.period)
        return {
            "status": "ok",
            "message": "Crypto update completed",
            "period": req.period
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Crypto update failed: {str(e)}")


@app.post("/api/v1/admin/update/commodities")
def update_commodities(req: UpdateRequest) -> Dict[str, Any]:
    try:
        from DataBase.comodities_ingestion import run
        run(period=req.period)
        return {
            "status": "ok",
            "message": "Commodities update completed",
            "period": req.period
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Commodities update failed: {str(e)}")


@app.get("/api/v1/admin/summary")
def admin_summary() -> Dict[str, Any]:
    return {
        "assets": dal.assets.collection.count_documents({}),
        "data_sources": dal.data_sources.collection.count_documents({}),
        "time_series": dal.time_series.collection.count_documents({}),
        "analytics_monthly_summary": dal.analytics_monthly_summary.collection.count_documents({}),
        "analytics_predictions": dal.analytics_predictions.collection.count_documents({})
    }


@app.get("/api/v1/health")
def health() -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={"status": "ok"}
    )


@app.get("/api/v1/analytics/monthly/assets")
def list_analytics_assets(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100)
) -> Dict[str, Any]:
    items = dal.analytics_monthly_summary.list_available_assets(offset=offset, limit=limit)
    return {
        "items": items,
        "offset": offset,
        "limit": limit,
        "count": len(items)
    }


@app.get("/api/v1/analytics/monthly/symbols")
def list_analytics_symbols(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100)
) -> Dict[str, Any]:
    items = dal.analytics_monthly_summary.list_available_symbols(offset=offset, limit=limit)
    return {
        "items": items,
        "offset": offset,
        "limit": limit,
        "count": len(items)
    }


@app.get("/api/v1/analytics/monthly/asset-classes")
def list_analytics_asset_classes() -> Dict[str, Any]:
    items = dal.analytics_monthly_summary.list_available_asset_classes()
    return {
        "items": items,
        "count": len(items)
    }


@app.get("/api/v1/analytics/monthly")
def get_monthly_analytics(
    assetId: Optional[str] = Query(None),
    dataSourceId: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    assetClass: Optional[str] = Query(None),
    startYear: Optional[int] = Query(None),
    startMonth: Optional[int] = Query(None, ge=1, le=12),
    endYear: Optional[int] = Query(None),
    endMonth: Optional[int] = Query(None, ge=1, le=12),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100)
) -> Dict[str, Any]:
    items = dal.analytics_monthly_summary.find_range(
        asset_id=assetId,
        source_id=dataSourceId,
        symbol=symbol,
        asset_class=assetClass,
        start_year=startYear,
        start_month=startMonth,
        end_year=endYear,
        end_month=endMonth,
        offset=offset,
        limit=limit
    )

    return {
        "items": items,
        "offset": offset,
        "limit": limit,
        "count": len(items)
    }


@app.get("/api/v1/analytics/predictions/assets")
def list_prediction_assets(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100)
) -> Dict[str, Any]:
    items = dal.analytics_predictions.list_available_assets(offset=offset, limit=limit)
    return {
        "items": items,
        "offset": offset,
        "limit": limit,
        "count": len(items)
    }


@app.get("/api/v1/analytics/predictions/models")
def list_prediction_models() -> Dict[str, Any]:
    items = dal.analytics_predictions.list_available_models()
    return {
        "items": items,
        "count": len(items)
    }


@app.get("/api/v1/analytics/predictions")
def get_predictions(
    assetId: Optional[str] = Query(None),
    dataSourceId: Optional[str] = Query(None),
    modelType: Optional[str] = Query(None),
    startBusinessDate: Optional[str] = Query(None, min_length=10),
    endBusinessDate: Optional[str] = Query(None, min_length=10),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100)
) -> Dict[str, Any]:
    items = dal.analytics_predictions.find_range(
        asset_id=assetId,
        source_id=dataSourceId,
        model_type=modelType,
        start_business_date=startBusinessDate,
        end_business_date=endBusinessDate,
        offset=offset,
        limit=limit
    )

    return {
        "items": items,
        "offset": offset,
        "limit": limit,
        "count": len(items)
    }


@app.get("/api/v1/analytics/predictions/latest")
def get_latest_prediction(
    assetId: str = Query(..., min_length=1),
    dataSourceId: str = Query(..., min_length=1),
    businessDate: str = Query(..., min_length=10),
    modelType: Optional[str] = Query(None)
) -> Dict[str, Any]:
    item = dal.analytics_predictions.find_latest(
        asset_id=assetId,
        source_id=dataSourceId,
        business_date=businessDate,
        model_type=modelType
    )

    if not item:
        raise not_found(
            f"No prediction found for assetId='{assetId}', "
            f"dataSourceId='{dataSourceId}', businessDate='{businessDate}'"
        )

    return item