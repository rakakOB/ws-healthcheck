import pymssql
import time
import random
import uuid
import logging
from datetime import datetime, timedelta

# ================== CONFIGURATION ==================
PRIMARY_DB = {
    'server': 'localhost',
    'port': 1433,
    'user': 'sa',
    'password': 'rak!@#123',
    'database': 'scada_historian'
}

SECONDARY_DB = {
    'server': 'localhost',
    'port': 1434,
    'user': 'sa',
    'password': 'rak!@#123',
    'database': 'scada_historian'
}

INTERVAL_SEC = 30          # dump every 30 seconds
ROWS_PER_BATCH = 50        # 50 rows each time
TAG_IDS = [1, 2, 3]        # sensor IDs

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)

def insert_batch(conn, cursor, rows):
    for row in rows:
        guid, sensor_ts, tag_id, sensor_date, value, quality = row
        cursor.execute(
            "INSERT INTO SensorReadings (RowGUID, SensorTimestamp, TagID, SensorDate, Value, Quality) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (guid, sensor_ts, tag_id, sensor_date, value, quality)
        )
    conn.commit()

def main():
    logging.info("SCADA Simulator V3 started. Press Ctrl+C to stop.")
    while True:
        # Generate batch
        batch_dump_time = datetime.now()          # SensorTimestamp – same for all rows in this batch
        rows = []
        for _ in range(ROWS_PER_BATCH):
            tag_id = random.choice(TAG_IDS)
            value = round(random.uniform(10, 100), 2)
            quality = random.choice(['Good', 'Good', 'Good', 'Uncertain'])  # occasionally uncertain
            row_guid = str(uuid.uuid4())
            # SensorDate – random time within the last 24 hours
            sensor_date = batch_dump_time - timedelta(
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
                seconds=random.randint(0, 59)
            )
            rows.append((row_guid, batch_dump_time, tag_id, sensor_date, value, quality))

        # Write to PRIMARY
        try:
            with pymssql.connect(**PRIMARY_DB, autocommit=False) as conn:
                insert_batch(conn, conn.cursor(), rows)
            logging.info(f"Inserted {ROWS_PER_BATCH} rows into PRIMARY.")
        except Exception as e:
            logging.error(f"Failed PRIMARY: {e}")

        # Write to SECONDARY
        try:
            with pymssql.connect(**SECONDARY_DB, autocommit=False) as conn:
                insert_batch(conn, conn.cursor(), rows)
            logging.info(f"Inserted {ROWS_PER_BATCH} rows into SECONDARY.")
        except Exception as e:
            logging.error(f"Failed SECONDARY: {e}")

        time.sleep(INTERVAL_SEC)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Simulator stopped.")