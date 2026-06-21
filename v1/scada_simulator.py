import pymssql
import time
import random
import datetime
import uuid
import logging
from threading import Event, Thread

# ================== CONFIGURATION ==================
# Local MSSQL (port 1433 on this machine)
LOCAL_DB = {
    'server': 'localhost',
    'port': 1433,
    'user': 'sa',
    'password': 'rak!@#123',
    'database': 'SCADA_Historian'
}

# Remote MSSQL (the other machine – adjust IP or Tailscale IP)
REMOTE_DB = {
    'server': '192.168.0.165',   # or Tailscale IP
    'port': 1433,
    'user': 'sa',
    'password': 'YourStrong!Passw0rd',   # password of the remote machine
    'database': 'SCADA_Historian'
}

# Simulation parameters
INTERVAL_SEC = 5               # insert a batch every 5 seconds
BATCH_SIZE = 5                 # number of measurements per batch
TAG_IDS = [1, 2, 3]            # IDs from the Tags table (must exist in SCADA_Config)
# 1 = TT-101 (Temperature, analog), 2 = PT-202 (Pressure, analog), 3 = a digital tag (e.g., pump status)
# Adjust to match your actual TagIDs.

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# Stop signal
stop_event = Event()

# ================== HELPER FUNCTIONS ==================
def get_connection(db_config):
    """Create a new connection to the database."""
    return pymssql.connect(**db_config, autocommit=True)

def generate_analog_value(tag_id, base=50, amplitude=10):
    """Generate a realistic analog value with some randomness."""
    # Use a simple sine wave with noise
    t = time.time()
    value = base + amplitude * (0.5 * (1 + __import__('math').sin(t / 60)) + random.uniform(-2, 2))
    return round(value, 2)

def generate_digital_value():
    """Random on/off (0 or 1)."""
    return random.randint(0, 1)

def insert_batch():
    """Insert a batch of measurements into both databases."""
    timestamp = datetime.datetime.now()
    rows = []
    for _ in range(BATCH_SIZE):
        tag_id = random.choice(TAG_IDS)
        if tag_id == 1:   # Temperature analog
            value = generate_analog_value(1, base=25, amplitude=10)
            row_type = 'analog'
        elif tag_id == 2: # Pressure analog
            value = generate_analog_value(2, base=3.2, amplitude=1)
            row_type = 'analog'
        else:             # Digital tag
            value = generate_digital_value()
            row_type = 'digital'

        row_guid = str(uuid.uuid4())
        rows.append((row_guid, tag_id, timestamp, value, row_type))

    # Insert into local DB
    local_conn = None
    remote_conn = None
    try:
        local_conn = get_connection(LOCAL_DB)
        local_cursor = local_conn.cursor()
        for row in rows:
            guid, tag_id, ts, val, typ = row
            if typ == 'analog':
                local_cursor.execute(
                    "INSERT INTO AnalogValues (RowGUID, TagID, Timestamp, Value, Quality) VALUES (%s, %s, %s, %s, 'Good')",
                    (guid, tag_id, ts, val)
                )
            else:
                local_cursor.execute(
                    "INSERT INTO DigitalValues (RowGUID, TagID, Timestamp, Value, Quality) VALUES (%s, %s, %s, %s, 'Good')",
                    (guid, tag_id, ts, val)
                )
        logging.info(f"Inserted {len(rows)} rows into LOCAL DB.")
    except Exception as e:
        logging.error(f"Local DB insert failed: {e}")
    finally:
        if local_conn:
            local_conn.close()

    # Insert into remote DB (same rows)
    try:
        remote_conn = get_connection(REMOTE_DB)
        remote_cursor = remote_conn.cursor()
        for row in rows:
            guid, tag_id, ts, val, typ = row
            if typ == 'analog':
                remote_cursor.execute(
                    "INSERT INTO AnalogValues (RowGUID, TagID, Timestamp, Value, Quality) VALUES (%s, %s, %s, %s, 'Good')",
                    (guid, tag_id, ts, val)
                )
            else:
                remote_cursor.execute(
                    "INSERT INTO DigitalValues (RowGUID, TagID, Timestamp, Value, Quality) VALUES (%s, %s, %s, %s, 'Good')",
                    (guid, tag_id, ts, val)
                )
        logging.info(f"Inserted {len(rows)} rows into REMOTE DB.")
    except Exception as e:
        logging.error(f"Remote DB insert failed: {e}")
    finally:
        if remote_conn:
            remote_conn.close()

# ================== MAIN LOOP ==================
def main():
    logging.info("SCADA Simulator started. Press Ctrl+C to stop.")
    while not stop_event.is_set():
        insert_batch()
        stop_event.wait(INTERVAL_SEC)   # wait, but can be interrupted

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Simulator stopped by user.")
        stop_event.set()
        