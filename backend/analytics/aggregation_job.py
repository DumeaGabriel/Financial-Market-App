from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window


MONGO_URI = "mongodb://localhost:27017/financial_dwh"
DATABASE = "financial_dwh"
TIME_SERIES_COLLECTION = "time_series"
ASSETS_COLLECTION = "assets"
OUTPUT_COLLECTION = "analytics_monthly_summary"

def build_spark():
    return (
        SparkSession.builder
        .appName("FinancialDWH-MonthlySummary")
        .config("spark.mongodb.read.connection.uri", MONGO_URI)
        .config("spark.mongodb.write.connection.uri", MONGO_URI)
        .getOrCreate()
    )


def load_latest_assets(spark):
    assets = (
        spark.read.format("mongodb")
        .option("database", DATABASE)
        .option("collection", ASSETS_COLLECTION)
        .load()
    )

    w = Window.partitionBy("asset_id").orderBy(F.col("system_date").desc())

    latest_assets = (
        assets
        .withColumn("rn", F.row_number().over(w))
        .filter((F.col("rn") == 1) & (F.col("deleted") != True))
        .select(
            "asset_id",
            "asset_class",
            "symbol",
            "name"
        )
    )

    return latest_assets


def load_latest_time_series(spark):
    ts = (
        spark.read.format("mongodb")
        .option("database", DATABASE)
        .option("collection", TIME_SERIES_COLLECTION)
        .load()
    )

    w = Window.partitionBy("asset_id", "source_id", "business_date").orderBy(F.col("system_date").desc())

    latest_ts = (
        ts
        .withColumn("rn", F.row_number().over(w))
        .filter((F.col("rn") == 1) & (F.col("deleted") != True))
        .withColumn("business_date_dt", F.to_date("business_date"))
        .withColumn("year", F.year("business_date_dt"))
        .withColumn("month", F.month("business_date_dt"))
        .select(
            "asset_id",
            "source_id",
            "business_date",
            "business_date_dt",
            "year",
            "month",
            F.col("values.open").cast("double").alias("open"),
            F.col("values.high").cast("double").alias("high"),
            F.col("values.low").cast("double").alias("low"),
            F.col("values.close").cast("double").alias("close"),
            F.col("values.volume").cast("double").alias("volume")
        )
    )

    return latest_ts


def compute_monthly_summary(latest_ts, latest_assets):
    enriched = latest_ts.join(latest_assets, on="asset_id", how="left")

    monthly_base = (
        enriched
        .groupBy("asset_id", "asset_class", "symbol", "name", "source_id", "year", "month")
        .agg(
            F.count("*").alias("count"),
            F.round(F.avg("open"), 4).alias("avg_open"),
            F.round(F.avg("close"), 4).alias("avg_close"),
            F.round(F.min("low"), 4).alias("min_low"),
            F.round(F.max("high"), 4).alias("max_high"),
            F.round(F.sum("volume"), 4).alias("total_volume"),
            F.round(F.avg("volume"), 4).alias("avg_volume")
        )
    )

    first_last_window_asc = Window.partitionBy("asset_id", "source_id", "year", "month").orderBy(F.col("business_date_dt").asc())
    first_last_window_desc = Window.partitionBy("asset_id", "source_id", "year", "month").orderBy(F.col("business_date_dt").desc())

    with_first_last = (
        enriched
        .withColumn("first_close", F.first("close", ignorenulls=True).over(first_last_window_asc))
        .withColumn("last_close", F.first("close", ignorenulls=True).over(first_last_window_desc))
        .select("asset_id", "source_id", "year", "month", "first_close", "last_close")
        .dropDuplicates(["asset_id", "source_id", "year", "month"])
        .withColumn(
            "monthly_return_pct",
            F.when(
                (F.col("first_close").isNotNull()) &
                (F.col("last_close").isNotNull()) &
                (F.col("first_close") != 0),
                F.round(((F.col("last_close") - F.col("first_close")) / F.col("first_close")) * 100, 4)
            ).otherwise(None)
        )
        .select("asset_id", "source_id", "year", "month", "monthly_return_pct")
    )

    result = (
        monthly_base
        .join(with_first_last, on=["asset_id", "source_id", "year", "month"], how="left")
        .withColumn(
            "metrics",
            F.struct(
                F.col("count").alias("count"),
                F.col("avg_open").alias("avg_open"),
                F.col("avg_close").alias("avg_close"),
                F.col("min_low").alias("min_low"),
                F.col("max_high").alias("max_high"),
                F.col("total_volume").alias("total_volume"),
                F.col("avg_volume").alias("avg_volume"),
                F.col("monthly_return_pct").alias("monthly_return_pct")
            )
        )
        .withColumn(
            "computed_metrics",
            F.expr("""
                filter(
                    array(
                        IF(count IS NOT NULL, 'count', NULL),
                        IF(avg_open IS NOT NULL, 'avg_open', NULL),
                        IF(avg_close IS NOT NULL, 'avg_close', NULL),
                        IF(min_low IS NOT NULL, 'min_low', NULL),
                        IF(max_high IS NOT NULL, 'max_high', NULL),
                        IF(total_volume IS NOT NULL, 'total_volume', NULL),
                        IF(avg_volume IS NOT NULL, 'avg_volume', NULL),
                        IF(monthly_return_pct IS NOT NULL, 'monthly_return_pct', NULL)
                    ),
                    x -> x IS NOT NULL
                )
            """)
        )
        .withColumn("generated_at", F.current_timestamp())
        .withColumn("deleted", F.lit(False))
        .select(
            "asset_id",
            "asset_class",
            "symbol",
            "name",
            "source_id",
            "year",
            "month",
            "metrics",
            "computed_metrics",
            "generated_at",
            "deleted"
        )
    )

    return result


def write_output(df):
    (
        df.write
        .format("mongodb")
        .mode("overwrite")
        .option("database", DATABASE)
        .option("collection", OUTPUT_COLLECTION)
        .save()
    )


def main():
    spark = build_spark()

    latest_assets = load_latest_assets(spark)
    latest_ts = load_latest_time_series(spark)

    monthly_summary = compute_monthly_summary(latest_ts, latest_assets)

    monthly_summary.show(50, truncate=False)
    write_output(monthly_summary)

    spark.stop()


if __name__ == "__main__":
    main()