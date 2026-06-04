from pyspark.sql import SparkSession, functions as F
from pyspark.sql.window import Window
from pyspark.ml.feature import VectorAssembler
from pyspark.ml.regression import LinearRegression
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, LongType, TimestampType


MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "financial_dwh"
SOURCE_COLLECTION = "time_series"
TARGET_COLLECTION = "analytics_predictions"


def build_spark() -> SparkSession:
    return (
        SparkSession.builder
        .appName("FinancialDWH-PredictionJob-AllAssets")
        .config("spark.mongodb.read.connection.uri", MONGO_URI)
        .config("spark.mongodb.write.connection.uri", MONGO_URI)
        .getOrCreate()
    )


def main():
    spark = build_spark()
    spark.sparkContext.setLogLevel("WARN")

    raw_df = (
        spark.read.format("mongodb")
        .option("database", DB_NAME)
        .option("collection", SOURCE_COLLECTION)
        .load()
    )

    raw_df = raw_df.filter(F.coalesce(F.col("deleted"), F.lit(False)) == F.lit(False))

    latest_window = Window.partitionBy(
        "asset_id", "source_id", "business_date"
    ).orderBy(F.col("system_date").desc())

    latest_df = (
        raw_df
        .withColumn("rn", F.row_number().over(latest_window))
        .filter(F.col("rn") == 1)
        .drop("rn")
    )

    ml_df = (
        latest_df
        .withColumn("open", F.col("values.Open").cast("double"))
        .withColumn("close", F.col("values.Close").cast("double"))
        .withColumn("low", F.col("values.Low").cast("double"))
        .withColumn("high", F.col("values.High").cast("double"))
        .withColumn("seconds", F.unix_timestamp(F.to_date("business_date")))
        .select(
            "asset_id",
            "source_id",
            "business_date",
            "seconds",
            "open",
            "close",
            "low",
            "high"
        )
        .dropna(subset=["asset_id", "source_id", "business_date", "seconds", "open", "close", "low", "high"])
    )

    if ml_df.count() == 0:
        print("No usable rows found for prediction job.")
        spark.stop()
        return

    print("Rows available for ML:")
    ml_df.groupBy("source_id").count().orderBy("source_id").show(truncate=False)

    asset_pairs = [
        (row["source_id"], row["asset_id"])
        for row in ml_df.select("source_id", "asset_id").distinct().collect()
    ]

    print(f"Found {len(asset_pairs)} asset/source pairs to process.")

    result_schema = StructType([
        StructField("asset_id", StringType(), True),
        StructField("source_id", StringType(), True),
        StructField("business_date", StringType(), True),
        StructField("actual_open", DoubleType(), True),
        StructField("predicted_open", DoubleType(), True),
        StructField("close", DoubleType(), True),
        StructField("low", DoubleType(), True),
        StructField("high", DoubleType(), True),
        StructField("seconds", LongType(), True),
        StructField("model_type", StringType(), True),
        StructField("generated_at", TimestampType(), True),
    ])

    all_results = spark.createDataFrame([], schema=result_schema)

    for source_id, asset_id in asset_pairs:
        asset_df = ml_df.filter(
            (F.col("source_id") == source_id) &
            (F.col("asset_id") == asset_id)
        )

        row_count = asset_df.count()
        if row_count < 10:
            print(f"Skipping {source_id} / {asset_id}: not enough rows ({row_count})")
            continue

        assembler = VectorAssembler(
            inputCols=["seconds", "close", "low", "high"],
            outputCol="features"
        )

        featured_df = assembler.transform(asset_df)

        train_df, test_df = featured_df.randomSplit([0.8, 0.2], seed=42)

        train_count = train_df.count()
        test_count = test_df.count()

        if train_count < 5 or test_count < 1:
            print(f"Skipping {source_id} / {asset_id}: insufficient train/test split ({train_count}/{test_count})")
            continue

        try:
            lr = LinearRegression(
                featuresCol="features",
                labelCol="open",
                maxIter=20,
                regParam=0.1,
                elasticNetParam=0.0
            )

            model = lr.fit(train_df)
            predictions = model.transform(test_df)

            result_df = (
                predictions.select(
                    "asset_id",
                    "source_id",
                    "business_date",
                    F.col("open").alias("actual_open"),
                    F.col("prediction").alias("predicted_open"),
                    "close",
                    "low",
                    "high",
                    "seconds"
                )
                .withColumn("model_type", F.lit("linear_regression_per_asset"))
                .withColumn("generated_at", F.current_timestamp())
            )

            all_results = all_results.unionByName(result_df)
            print(f"Processed {source_id} / {asset_id}: {row_count} rows")

        except Exception as e:
            print(f"Failed for {source_id} / {asset_id}: {str(e)}")

    final_count = all_results.count()

    if final_count == 0:
        print("No prediction results were generated.")
        spark.stop()
        return

    print(f"Generated {final_count} prediction rows.")
    all_results.orderBy("source_id", "asset_id", "business_date").show(200, truncate=False)

    (
        all_results.write.format("mongodb")
        .mode("append")
        .option("database", DB_NAME)
        .option("collection", TARGET_COLLECTION)
        .save()
    )

    spark.stop()


if __name__ == "__main__":
    main()