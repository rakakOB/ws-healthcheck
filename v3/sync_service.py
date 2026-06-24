import pymssql
import logging
import os
import time
from datetime import datetime
import threading

# ================== CONFIGURATION ==================
SA_PASSWORD = 'rak!@#123'

PRIMARY = {
    'server': 'localhost', 'port': 1433,
    'user': 'sa', 'password': SA_PASSWORD, 'database': 'scada_historian'
}
SECONDARY = {
    'server': 'localhost', 'port': 1434,
    'user': 'sa', 'password': SA_PASSWORD, 'database': 'scada_historian'
}

CHECK_INTERVAL = 30          # seconds
DEBOUNCE_THRESHOLD = 1       # immediate detection

LOG_DIR = r'C:\ScadaLogs'
PRIMARY_LOG = os.path.join(LOG_DIR, 'primary_logs.log')
SECONDARY_LOG = os.path.join(LOG_DIR, 'secondary_logs.log')
os.makedirs(LOG_DIR, exist_ok=True)

# Loggers
prim_logger = logging.getLogger('primary')
prim_logger.setLevel(logging.INFO)
prim_handler = logging.FileHandler(PRIMARY_LOG)
prim_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
prim_logger.addHandler(prim_handler)

sec_logger = logging.getLogger('secondary')
sec_logger.setLevel(logging.INFO)
sec_handler = logging.FileHandler(SECONDARY_LOG)
sec_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
sec_logger.addHandler(sec_handler)

console = logging.StreamHandler()
console.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
prim_logger.addHandler(console)
sec_logger.addHandler(console)

# ================== HELPERS ==================
def is_db_online(db_config):
    try:
        conn = pymssql.connect(**db_config, login_timeout=3, timeout=3)
        conn.cursor().execute("SELECT 1")
        conn.close()
        return True
    except:
        return False

def log_outage_event(db, server_name, event_type, logger):
    """Insert a row into OutageLog for an offline/online event."""
    try:
        conn = pymssql.connect(**db, autocommit=True)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO OutageLog (ServerName, ServerEvents, EventDateTime, SyncStatus) "
            "VALUES (%s, %s, %s, 'Pending')",
            (server_name, event_type, datetime.now())
        )
        conn.close()
        logger.info(f"OutageLog: {server_name} -> {event_type}")
    except Exception as e:
        logger.error(f"Failed to log outage event: {e}")

def capture_rows_for_sync(source_db, outage_start, logger):
    """
    Copy rows from SensorReadings (where SensorTimestamp >= outage_start)
    into SyncRecordsStatus with SyncSuccess=0.
    """
    try:
        conn = pymssql.connect(**source_db, autocommit=True)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO SyncRecordsStatus (RowGUID, SensorTimestamp, TagID, SensorDate, Value, Quality, SyncSuccess) "
            "SELECT RowGUID, SensorTimestamp, TagID, SensorDate, Value, Quality, 0 "
            "FROM SensorReadings "
            "WHERE SensorTimestamp >= %s "
            "AND RowGUID NOT IN (SELECT RowGUID FROM SyncRecordsStatus)",
            (outage_start,)
        )
        rows_captured = cursor.rowcount
        conn.commit()
        conn.close()
        logger.info(f"Captured {rows_captured} rows into SyncRecordsStatus.")
        return rows_captured
    except Exception as e:
        logger.error(f"Failed to capture rows: {e}")
        return 0

def sync_to_remote(source_db, target_db, logger):
    """
    Push all unsynced rows from source's SyncRecordsStatus to target's SensorReadings.
    Then mark them SyncSuccess=1.
    """
    try:
        source_conn = pymssql.connect(**source_db, autocommit=True)
        source_cursor = source_conn.cursor()
        # Get unsynced rows
        source_cursor.execute(
            "SELECT RowGUID, SensorTimestamp, TagID, SensorDate, Value, Quality "
            "FROM SyncRecordsStatus WHERE SyncSuccess = 0"
        )
        rows = source_cursor.fetchall()

        if not rows:
            logger.info("No unsynced rows to push.")
            source_conn.close()
            return 0

        # Push to target
        target_conn = pymssql.connect(**target_db, autocommit=True)
        target_cursor = target_conn.cursor()
        synced = 0
        for row_guid, sensor_ts, tag_id, sensor_date, value, quality in rows:
            target_cursor.execute("SELECT 1 FROM SensorReadings WHERE RowGUID = %s", (row_guid,))
            if target_cursor.fetchone():
                continue
            target_cursor.execute(
                "INSERT INTO SensorReadings (RowGUID, SensorTimestamp, TagID, SensorDate, Value, Quality) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (row_guid, sensor_ts, tag_id, sensor_date, value, quality)
            )
            synced += 1

        target_conn.commit()
        target_conn.close()

        # Mark as synced in source
        source_cursor.execute("UPDATE SyncRecordsStatus SET SyncSuccess = 1 WHERE SyncSuccess = 0")
        source_conn.commit()
        source_conn.close()

        logger.info(f"Synced {synced} rows to remote.")
        return synced
    except Exception as e:
        logger.error(f"Sync to remote failed: {e}")
        return 0

# ================== MAIN MONITOR ==================
class HealthMonitor:
    def __init__(self):
        self.primary_status = 0       # 1=online, -1=offline
        self.secondary_status = 0
        self.primary_fail_count = 0
        self.secondary_fail_count = 0
        self.secondary_outage_start = None   # tracks when current outage began
        self.primary_outage_start = None
        self._stop = threading.Event()

    def run(self):
        prim_logger.info("V3 Monitor started. Interval: %s seconds.", CHECK_INTERVAL)
        while not self._stop.is_set():
            primary_online = is_db_online(PRIMARY)
            secondary_online = is_db_online(SECONDARY)

            # ===== PRIMARY monitors SECONDARY =====
            if not secondary_online:
                self.secondary_fail_count += 1
                if self.secondary_fail_count >= DEBOUNCE_THRESHOLD and self.secondary_status != -1:
                    self.secondary_status = -1
                    self.secondary_outage_start = datetime.now()
                    prim_logger.warning("SECONDARY OFFLINE at %s", self.secondary_outage_start)
                    log_outage_event(PRIMARY, 'SECONDARY', 'offline', prim_logger)
                # While offline, continuously capture new rows
                if self.secondary_status == -1 and self.secondary_outage_start:
                    capture_rows_for_sync(PRIMARY, self.secondary_outage_start, prim_logger)
            else:
                if self.secondary_fail_count >= DEBOUNCE_THRESHOLD and self.secondary_status == -1:
                    # Transition: OFFLINE -> ONLINE
                    self.secondary_status = 1
                    prim_logger.info("SECONDARY back ONLINE.")
                    log_outage_event(PRIMARY, 'SECONDARY', 'online', prim_logger)
                    # Sync missing rows
                    synced = sync_to_remote(PRIMARY, SECONDARY, prim_logger)
                    prim_logger.info("Recovery sync complete: %s rows synced.", synced)
                    self.secondary_outage_start = None
                elif self.secondary_fail_count == 0:
                    self.secondary_status = 1
                    prim_logger.info("SECONDARY is ONLINE.")
                self.secondary_fail_count = 0

            # ===== SECONDARY monitors PRIMARY =====
            if not primary_online:
                self.primary_fail_count += 1
                if self.primary_fail_count >= DEBOUNCE_THRESHOLD and self.primary_status != -1:
                    self.primary_status = -1
                    self.primary_outage_start = datetime.now()
                    sec_logger.warning("PRIMARY OFFLINE at %s", self.primary_outage_start)
                    log_outage_event(SECONDARY, 'PRIMARY', 'offline', sec_logger)
                if self.primary_status == -1 and self.primary_outage_start:
                    capture_rows_for_sync(SECONDARY, self.primary_outage_start, sec_logger)
            else:
                if self.primary_fail_count >= DEBOUNCE_THRESHOLD and self.primary_status == -1:
                    self.primary_status = 1
                    sec_logger.info("PRIMARY back ONLINE.")
                    log_outage_event(SECONDARY, 'PRIMARY', 'online', sec_logger)
                    synced = sync_to_remote(SECONDARY, PRIMARY, sec_logger)
                    sec_logger.info("Recovery sync complete: %s rows synced.", synced)
                    self.primary_outage_start = None
                elif self.primary_fail_count == 0:
                    self.primary_status = 1
                    sec_logger.info("PRIMARY is ONLINE.")
                self.primary_fail_count = 0

            self._stop.wait(CHECK_INTERVAL)

    def stop(self):
        self._stop.set()

if __name__ == '__main__':
    monitor = HealthMonitor()
    try:
        monitor.run()
    except KeyboardInterrupt:
        monitor.stop()
