import pymssql
import time
import random
import uuid
import logging
from datetime import datetime

# ================== CONFIGURATION ==================
PRIMARY_DB = {
    'server': 'localhost',
    'port': 1433,
    'user': 'sa',
    'password': 'rak!@#123',   # same on both instances
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
TAG_IDS = [1, 2, 3]        # must match the tags you'll define (we'll just use 1-3)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)

def insert_batch(conn, cursor, rows):
    """Insert a list of rows into the given connection."""
    for row in rows:
        guid, tag_id, ts, val, quality = row
        cursor.execute(
            "INSERT INTO SensorReadings (RowGUID, TagID, Timestamp, Value, Quality) VALUES (%s, %s, %s, %s, %s)",
            (guid, tag_id, ts, val, quality)
        )
    conn.commit()

def main():
    logging.info("SCADA Simulator started. Press Ctrl+C to stop.")
    while True:
        # Generate a batch of 50 rows with the same timestamp
        batch_timestamp = datetime.now()
        rows = []
        for _ in range(ROWS_PER_BATCH):
            tag_id = random.choice(TAG_IDS)
            value = round(random.uniform(10, 100), 2)
            quality = 'Good'
            row_guid = str(uuid.uuid4())
            rows.append((row_guid, tag_id, batch_timestamp, value, quality))

        # Write to PRIMARY
        try:
            with pymssql.connect(**PRIMARY_DB, autocommit=False) as conn:
                cursor = conn.cursor()
                insert_batch(conn, cursor, rows)
            logging.info(f"Inserted {ROWS_PER_BATCH} rows into PRIMARY.")
        except Exception as e:
            logging.error(f"Failed to write to PRIMARY: {e}")

        # Write to SECONDARY (identical rows)
        try:
            with pymssql.connect(**SECONDARY_DB, autocommit=False) as conn:
                cursor = conn.cursor()
                insert_batch(conn, cursor, rows)
            logging.info(f"Inserted {ROWS_PER_BATCH} rows into SECONDARY.")
        except Exception as e:
            logging.error(f"Failed to write to SECONDARY: {e}")

        time.sleep(INTERVAL_SEC)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Simulator stopped.")
