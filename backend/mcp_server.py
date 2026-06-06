"""
Financial Data Warehouse - MCP Server
======================================
Exposes the Financial DWH REST API as MCP tools for Claude Desktop (and other MCP clients).
All tools are read-only and call the existing FastAPI consumption layer.

Usage:
    pip install mcp httpx
    python mcp_server.py

Claude Desktop config (claude_desktop_config.json):
    {
        "mcpServers": {
            "financial-dwh": {
                "command": "python",
                "args": ["C:/full/path/to/mcp_server.py"]
            }
        }
    }
"""

import json
import re
from datetime import datetime, date
from typing import Any, Dict, Optional

import httpx
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE_URL = "http://localhost:8000"   # Your FastAPI base URL
MAX_LIMIT = 100                          # Hard cap on page size
MAX_DATE_RANGE_DAYS = 365               # Max allowed date range for time-series queries
DEFAULT_LIMIT = 20
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_date(value: str, field_name: str) -> date:
    """Parse and validate a YYYY-MM-DD date string."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"'{field_name}' must be in YYYY-MM-DD format, got: '{value}'")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"'{field_name}' is not a valid calendar date: '{value}'")


def _validate_pagination(offset: Any, limit: Any) -> tuple[int, int]:
    """Validate and clamp pagination parameters."""
    try:
        offset = int(offset)
        limit = int(limit)
    except (TypeError, ValueError):
        raise ValueError("'offset' and 'limit' must be integers.")
    if offset < 0:
        raise ValueError("'offset' must be >= 0.")
    if limit < 1:
        raise ValueError("'limit' must be >= 1.")
    if limit > MAX_LIMIT:
        raise ValueError(f"'limit' must be <= {MAX_LIMIT}. Requested: {limit}.")
    return offset, limit


def _error(message: str) -> list[types.TextContent]:
    """Return a structured error response."""
    payload = {"error": True, "message": message}
    return [types.TextContent(type="text", text=json.dumps(payload, indent=2))]


def _ok(data: Any) -> list[types.TextContent]:
    """Return a structured success response."""
    return [types.TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


async def _get(path: str, params: Optional[Dict] = None) -> Any:
    """Perform an async GET against the FastAPI backend."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{API_BASE_URL}{path}", params=params)
        if response.status_code == 404:
            raise LookupError(response.json().get("detail", "Resource not found."))
        if response.status_code != 200:
            detail = response.text
            try:
                detail = response.json().get("detail", detail)
            except Exception:
                pass
            raise RuntimeError(f"Backend returned HTTP {response.status_code}: {detail}")
        return response.json()

# ---------------------------------------------------------------------------
# MCP Server setup
# ---------------------------------------------------------------------------

server = Server("financial-dwh")

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_assets",
            description=(
                "Returns a paginated list of asset identifiers available in the financial "
                "data warehouse. Use this tool first to discover which assets exist before "
                "fetching details or time-series data. "
                "Inputs: offset (default 0), limit (default 20, max 100). "
                "Output: { items: [...], offset, limit, count }."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "offset": {
                        "type": "integer",
                        "description": "Number of items to skip (for pagination). Default: 0.",
                        "default": DEFAULT_OFFSET,
                        "minimum": 0,
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Number of items to return. Default: {DEFAULT_LIMIT}, max: {MAX_LIMIT}.",
                        "default": DEFAULT_LIMIT,
                        "minimum": 1,
                        "maximum": MAX_LIMIT,
                    },
                },
                "required": [],
            },
        ),

        types.Tool(
            name="get_asset_details",
            description=(
                "Returns the latest known details for a single asset identified by assetId. "
                "The result reflects the most recent version of the asset record stored in the warehouse. "
                "Use list_assets first if you do not know the assetId. "
                "Inputs: assetId (required). "
                "Output: asset entity object with all available fields."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "assetId": {
                        "type": "string",
                        "description": "The unique identifier of the asset (e.g. 'AAPL', 'BTC-USD').",
                        "minLength": 1,
                    },
                },
                "required": ["assetId"],
            },
        ),

        types.Tool(
            name="list_data_sources",
            description=(
                "Returns a paginated list of data source identifiers available in the warehouse. "
                "A data source represents the origin of time-series records (e.g. a market feed). "
                "Use this tool to discover which sources exist before querying time-series data. "
                "Inputs: offset (default 0), limit (default 20, max 100). "
                "Output: { items: [...], offset, limit, count }."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "offset": {
                        "type": "integer",
                        "description": "Number of items to skip (for pagination). Default: 0.",
                        "default": DEFAULT_OFFSET,
                        "minimum": 0,
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Number of items to return. Default: {DEFAULT_LIMIT}, max: {MAX_LIMIT}.",
                        "default": DEFAULT_LIMIT,
                        "minimum": 1,
                        "maximum": MAX_LIMIT,
                    },
                },
                "required": [],
            },
        ),

        types.Tool(
            name="get_data_source_details",
            description=(
                "Returns the latest known details for a single data source identified by dataSourceId. "
                "The result reflects the most recent version of the source record stored in the warehouse. "
                "Use list_data_sources first if you do not know the dataSourceId. "
                "Inputs: dataSourceId (required). "
                "Output: data source entity object with all available fields."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "dataSourceId": {
                        "type": "string",
                        "description": "The unique identifier of the data source.",
                        "minLength": 1,
                    },
                },
                "required": ["dataSourceId"],
            },
        ),

        types.Tool(
            name="get_time_series_data",
            description=(
                "Returns daily OHLCV time-series records for a specific asset and data source "
                "within a bounded date range. Only the latest version of each business date is returned. "
                "Records are ordered newest-first. "
                "The date range [startBusinessDate, endBusinessDate) is half-open (start inclusive, end exclusive). "
                f"Maximum allowed range: {MAX_DATE_RANGE_DAYS} days. Requests exceeding this will be rejected. "
                "Inputs: assetId, dataSourceId, startBusinessDate (YYYY-MM-DD), endBusinessDate (YYYY-MM-DD), "
                "includeAttributes (optional bool, default false). "
                "Output: { data: { assetId, dataSourceId, records: [...] }, attributes? }."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "assetId": {
                        "type": "string",
                        "description": "The unique identifier of the asset.",
                        "minLength": 1,
                    },
                    "dataSourceId": {
                        "type": "string",
                        "description": "The unique identifier of the data source.",
                        "minLength": 1,
                    },
                    "startBusinessDate": {
                        "type": "string",
                        "description": "Start of the date range, inclusive. Format: YYYY-MM-DD.",
                        "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    },
                    "endBusinessDate": {
                        "type": "string",
                        "description": "End of the date range, exclusive. Format: YYYY-MM-DD.",
                        "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    },
                    "includeAttributes": {
                        "type": "boolean",
                        "description": "If true, includes the list of attribute keys found across all records. Default: false.",
                        "default": False,
                    },
                },
                "required": ["assetId", "dataSourceId", "startBusinessDate", "endBusinessDate"],
            },
        ),

        types.Tool(
            name="get_monthly_analytics",
            description=(
                "Returns pre-computed monthly analytics summaries from the warehouse. "
                "Each record contains aggregated metrics for a given asset/source/year/month combination: "
                "avg open, avg close, min low, max high, total volume, avg volume, and monthly return %. "
                "Filter by assetId, dataSourceId, symbol, assetClass, and/or a year-month range. "
                "Inputs: all optional filters + offset/limit for pagination. "
                "Output: { items: [...], offset, limit, count }."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "assetId": {"type": "string", "description": "Filter by asset identifier."},
                    "dataSourceId": {"type": "string", "description": "Filter by data source identifier."},
                    "symbol": {"type": "string", "description": "Filter by ticker symbol (e.g. 'AAPL')."},
                    "assetClass": {"type": "string", "description": "Filter by asset class (e.g. 'stock', 'crypto')."},
                    "startYear": {"type": "integer", "description": "Start year (inclusive)."},
                    "startMonth": {"type": "integer", "description": "Start month 1-12 (inclusive).", "minimum": 1, "maximum": 12},
                    "endYear": {"type": "integer", "description": "End year (inclusive)."},
                    "endMonth": {"type": "integer", "description": "End month 1-12 (inclusive).", "minimum": 1, "maximum": 12},
                    "offset": {"type": "integer", "description": "Pagination offset. Default: 0.", "default": 0, "minimum": 0},
                    "limit": {"type": "integer", "description": f"Page size. Default: {DEFAULT_LIMIT}, max: {MAX_LIMIT}.", "default": DEFAULT_LIMIT, "minimum": 1, "maximum": MAX_LIMIT},
                },
                "required": [],
            },
        ),

        types.Tool(
            name="get_predictions",
            description=(
                "Returns ML price predictions stored in the warehouse. "
                "Predictions are produced by a linear regression model trained per asset/source pair. "
                "Each record contains actual_open, predicted_open, close, low, high, model_type, and generated_at. "
                "Filter by assetId, dataSourceId, modelType, and/or a business date range. "
                "Inputs: all optional filters + offset/limit for pagination. "
                "Output: { items: [...], offset, limit, count }. "
                "Do not use predictions as financial advice; they reflect model output only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "assetId": {"type": "string", "description": "Filter by asset identifier."},
                    "dataSourceId": {"type": "string", "description": "Filter by data source identifier."},
                    "modelType": {"type": "string", "description": "Filter by model type (e.g. 'linear_regression_per_asset')."},
                    "startBusinessDate": {"type": "string", "description": "Start date inclusive. Format: YYYY-MM-DD.", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                    "endBusinessDate": {"type": "string", "description": "End date exclusive. Format: YYYY-MM-DD.", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                    "offset": {"type": "integer", "description": "Pagination offset. Default: 0.", "default": 0, "minimum": 0},
                    "limit": {"type": "integer", "description": f"Page size. Default: {DEFAULT_LIMIT}, max: {MAX_LIMIT}.", "default": DEFAULT_LIMIT, "minimum": 1, "maximum": MAX_LIMIT},
                },
                "required": [],
            },
        ),
    ]

# ---------------------------------------------------------------------------
# Tool call handlers
# ---------------------------------------------------------------------------

@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> list[types.TextContent]:

    # -----------------------------------------------------------------------
    # list_assets
    # -----------------------------------------------------------------------
    if name == "list_assets":
        try:
            offset, limit = _validate_pagination(
                arguments.get("offset", DEFAULT_OFFSET),
                arguments.get("limit", DEFAULT_LIMIT),
            )
            data = await _get("/api/v1/assets", params={"offset": offset, "limit": limit})
            data["_provenance"] = {
                "warehouse": "financial-dwh",
                "endpoint": "/api/v1/assets",
                "semantics": "latest non-deleted version per asset",
                "retrievedAt": datetime.utcnow().isoformat() + "Z",
            }
            return _ok(data)
        except ValueError as e:
            return _error(f"Invalid input: {e}")
        except (LookupError, RuntimeError) as e:
            return _error(str(e))
        except httpx.ConnectError:
            return _error("Cannot reach the Financial DWH API. Make sure the FastAPI server is running on " + API_BASE_URL)

    # -----------------------------------------------------------------------
    # get_asset_details
    # -----------------------------------------------------------------------
    elif name == "get_asset_details":
        try:
            asset_id = arguments.get("assetId", "").strip()
            if not asset_id:
                return _error("Invalid input: 'assetId' is required and must not be empty.")
            data = await _get(f"/api/v1/assets/{asset_id}")
            data["_provenance"] = {
                "warehouse": "financial-dwh",
                "endpoint": f"/api/v1/assets/{asset_id}",
                "assetId": asset_id,
                "semantics": "latest non-deleted version of the asset record",
                "retrievedAt": datetime.utcnow().isoformat() + "Z",
            }
            return _ok(data)
        except LookupError as e:
            return _error(f"Asset not found: {e}")
        except (ValueError, RuntimeError) as e:
            return _error(str(e))
        except httpx.ConnectError:
            return _error("Cannot reach the Financial DWH API. Make sure the FastAPI server is running on " + API_BASE_URL)

    # -----------------------------------------------------------------------
    # list_data_sources
    # -----------------------------------------------------------------------
    elif name == "list_data_sources":
        try:
            offset, limit = _validate_pagination(
                arguments.get("offset", DEFAULT_OFFSET),
                arguments.get("limit", DEFAULT_LIMIT),
            )
            data = await _get("/api/v1/data-sources", params={"offset": offset, "limit": limit})
            data["_provenance"] = {
                "warehouse": "financial-dwh",
                "endpoint": "/api/v1/data-sources",
                "semantics": "latest non-deleted version per data source",
                "retrievedAt": datetime.utcnow().isoformat() + "Z",
            }
            return _ok(data)
        except ValueError as e:
            return _error(f"Invalid input: {e}")
        except (LookupError, RuntimeError) as e:
            return _error(str(e))
        except httpx.ConnectError:
            return _error("Cannot reach the Financial DWH API. Make sure the FastAPI server is running on " + API_BASE_URL)

    # -----------------------------------------------------------------------
    # get_data_source_details
    # -----------------------------------------------------------------------
    elif name == "get_data_source_details":
        try:
            source_id = arguments.get("dataSourceId", "").strip()
            if not source_id:
                return _error("Invalid input: 'dataSourceId' is required and must not be empty.")
            data = await _get(f"/api/v1/data-sources/{source_id}")
            data["_provenance"] = {
                "warehouse": "financial-dwh",
                "endpoint": f"/api/v1/data-sources/{source_id}",
                "dataSourceId": source_id,
                "semantics": "latest non-deleted version of the data source record",
                "retrievedAt": datetime.utcnow().isoformat() + "Z",
            }
            return _ok(data)
        except LookupError as e:
            return _error(f"Data source not found: {e}")
        except (ValueError, RuntimeError) as e:
            return _error(str(e))
        except httpx.ConnectError:
            return _error("Cannot reach the Financial DWH API. Make sure the FastAPI server is running on " + API_BASE_URL)

    # -----------------------------------------------------------------------
    # get_time_series_data
    # -----------------------------------------------------------------------
    elif name == "get_time_series_data":
        try:
            asset_id = arguments.get("assetId", "").strip()
            source_id = arguments.get("dataSourceId", "").strip()
            start_str = arguments.get("startBusinessDate", "").strip()
            end_str = arguments.get("endBusinessDate", "").strip()
            include_attrs = bool(arguments.get("includeAttributes", False))

            if not asset_id:
                return _error("Invalid input: 'assetId' is required.")
            if not source_id:
                return _error("Invalid input: 'dataSourceId' is required.")
            if not start_str:
                return _error("Invalid input: 'startBusinessDate' is required.")
            if not end_str:
                return _error("Invalid input: 'endBusinessDate' is required.")

            start_date = _validate_date(start_str, "startBusinessDate")
            end_date = _validate_date(end_str, "endBusinessDate")

            if end_date <= start_date:
                return _error(
                    f"Invalid range: 'endBusinessDate' ({end_str}) must be after 'startBusinessDate' ({start_str}). "
                    "Note: the range is half-open [start, end)."
                )

            delta = (end_date - start_date).days
            if delta > MAX_DATE_RANGE_DAYS:
                return _error(
                    f"Date range too large: {delta} days requested, maximum allowed is {MAX_DATE_RANGE_DAYS} days. "
                    "Please narrow your date range and make multiple requests if needed."
                )

            data = await _get("/api/v1/data", params={
                "assetId": asset_id,
                "dataSourceId": source_id,
                "startBusinessDate": start_str,
                "endBusinessDate": end_str,
                "includeAttributes": str(include_attrs).lower(),
            })

            # Enrich response with provenance metadata
            data["_provenance"] = {
                "assetId": asset_id,
                "dataSourceId": source_id,
                "startBusinessDate": start_str,
                "endBusinessDate": end_str,
                "semantics": "half-open interval [startBusinessDate, endBusinessDate), latest version per business date, ordered newest-first",
            }
            return _ok(data)

        except ValueError as e:
            return _error(f"Invalid input: {e}")
        except LookupError as e:
            return _error(f"Not found: {e}")
        except RuntimeError as e:
            return _error(str(e))
        except httpx.ConnectError:
            return _error("Cannot reach the Financial DWH API. Make sure the FastAPI server is running on " + API_BASE_URL)

    # -----------------------------------------------------------------------
    # get_monthly_analytics
    # -----------------------------------------------------------------------
    elif name == "get_monthly_analytics":
        try:
            offset, limit = _validate_pagination(
                arguments.get("offset", DEFAULT_OFFSET),
                arguments.get("limit", DEFAULT_LIMIT),
            )

            params: Dict[str, Any] = {"offset": offset, "limit": limit}

            if arguments.get("assetId"):
                params["assetId"] = arguments["assetId"].strip()
            if arguments.get("dataSourceId"):
                params["dataSourceId"] = arguments["dataSourceId"].strip()
            if arguments.get("symbol"):
                params["symbol"] = arguments["symbol"].strip()
            if arguments.get("assetClass"):
                params["assetClass"] = arguments["assetClass"].strip()
            if arguments.get("startYear") is not None:
                params["startYear"] = int(arguments["startYear"])
            if arguments.get("startMonth") is not None:
                params["startMonth"] = int(arguments["startMonth"])
            if arguments.get("endYear") is not None:
                params["endYear"] = int(arguments["endYear"])
            if arguments.get("endMonth") is not None:
                params["endMonth"] = int(arguments["endMonth"])

            data = await _get("/api/v1/analytics/monthly", params=params)
            data["_provenance"] = {
                "warehouse": "financial-dwh",
                "endpoint": "/api/v1/analytics/monthly",
                "filters": {k: v for k, v in params.items() if k not in ("offset", "limit")},
                "semantics": "pre-computed monthly aggregations from warehouse time-series data",
                "retrievedAt": datetime.utcnow().isoformat() + "Z",
            }
            return _ok(data)

        except ValueError as e:
            return _error(f"Invalid input: {e}")
        except (LookupError, RuntimeError) as e:
            return _error(str(e))
        except httpx.ConnectError:
            return _error("Cannot reach the Financial DWH API. Make sure the FastAPI server is running on " + API_BASE_URL)

    # -----------------------------------------------------------------------
    # get_predictions
    # -----------------------------------------------------------------------
    elif name == "get_predictions":
        try:
            offset, limit = _validate_pagination(
                arguments.get("offset", DEFAULT_OFFSET),
                arguments.get("limit", DEFAULT_LIMIT),
            )

            params: Dict[str, Any] = {"offset": offset, "limit": limit}

            if arguments.get("assetId"):
                params["assetId"] = arguments["assetId"].strip()
            if arguments.get("dataSourceId"):
                params["dataSourceId"] = arguments["dataSourceId"].strip()
            if arguments.get("modelType"):
                params["modelType"] = arguments["modelType"].strip()

            start_str = arguments.get("startBusinessDate", "").strip()
            end_str = arguments.get("endBusinessDate", "").strip()

            if start_str:
                _validate_date(start_str, "startBusinessDate")
                params["startBusinessDate"] = start_str
            if end_str:
                _validate_date(end_str, "endBusinessDate")
                params["endBusinessDate"] = end_str

            if start_str and end_str:
                start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
                if end_date <= start_date:
                    return _error("'endBusinessDate' must be after 'startBusinessDate'.")
                delta = (end_date - start_date).days
                if delta > MAX_DATE_RANGE_DAYS:
                    return _error(
                        f"Date range too large: {delta} days. Maximum allowed is {MAX_DATE_RANGE_DAYS} days."
                    )

            data = await _get("/api/v1/analytics/predictions", params=params)
            data["_disclaimer"] = "Predictions are model output only and do not constitute financial advice."
            data["_provenance"] = {
                "warehouse": "financial-dwh",
                "endpoint": "/api/v1/analytics/predictions",
                "filters": {k: v for k, v in params.items() if k not in ("offset", "limit")},
                "semantics": "ML model predictions stored in warehouse, not real-time inference",
                "retrievedAt": datetime.utcnow().isoformat() + "Z",
            }
            return _ok(data)

        except ValueError as e:
            return _error(f"Invalid input: {e}")
        except (LookupError, RuntimeError) as e:
            return _error(str(e))
        except httpx.ConnectError:
            return _error("Cannot reach the Financial DWH API. Make sure the FastAPI server is running on " + API_BASE_URL)

    # -----------------------------------------------------------------------
    # Unknown tool
    # -----------------------------------------------------------------------
    else:
        return _error(f"Unknown tool: '{name}'.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())