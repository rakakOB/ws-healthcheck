import pymssql
import logging
import os
import time
from datetime import datetime, timezone
import threading
import sys

# ================== CONFIGURATION ==================
SA_PASSWORD = 'rak!@#123'   # same for both instances

PRIMARY = {
    'server': 'localhost',
    'port': 1433,
    'user': 'sa',
    'password': SA_PASSWORD,
    'database': 'scada_historian'
}

SECONDARY = {
    'server': 'localhost',
    'port': 1434,
    'user': 'sa',
    'password': SA_PASSWORD,
    'database': 'scada_historian'
}

CHECK_INTERVAL = 60          # seconds
DEBOUNCE_THRESHOLD = 1       # mark offline after first failed check

LOG_DIR = r'C:\ScadaLogs'
PRIMARY_LOG = os.path.join(LOG_DIR, 'primary_logs.log')
SECONDARY_LOG = os.path.join(LOG_DIR, 'secondary_logs.log')

os.makedirs(LOG_DIR, exist_ok=True)

# Two loggers – one for each perspective
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

# Also log to console for debugging
console = logging.StreamHandler()
console.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
prim_logger.addHandler(console)
sec_logger.addHandler(console)

# ================== HELPERS ==================
def is_db_online(db_config):
    """Return True if we can connect and execute SELECT 1."""
    try:
        conn = pymssql.connect(**db_config, login_timeout=3, timeout=3)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        conn.close()
        return True
    except:
        return False

def get_max_timestamp(db):
    """Return the maximum Timestamp in SensorReadings, or a very old date."""
    try:
        conn = pymssql.connect(**db, autocommit=True)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(Timestamp) FROM SensorReadings")
        max_ts = cursor.fetchone()[0]
        conn.close()
        return max_ts if max_ts else datetime(2000, 1, 1)
    except:
        return datetime(2000, 1, 1)

def log_outage_start(db, server_name, outage_id_holder):
    """Insert a new outage row into the local OutageLog."""
    try:
        conn = pymssql.connect(**db, autocommit=True)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO OutageLog (ServerName, OutageStart, SyncStatus) VALUES (%s, %s, 'Pending')",
            (server_name, datetime.now())
        )
        outage_id_holder[0] = cursor.lastrowid
        conn.close()
        return outage_id_holder[0]
    except Exception as e:
        prim_logger.error(f"Failed to insert outage start in {server_name}: {e}")
        return None

def log_outage_end(db, outage_id, rows_missed=0):
    """Close the outage record."""
    if outage_id is None:
        return
    try:
        conn = pymssql.connect(**db, autocommit=True)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE OutageLog SET OutageEnd = %s, RowsMissed = %s, SyncStatus = 'Synced' WHERE OutageID = %s",
            (datetime.now(), rows_missed, outage_id)
        )
        conn.close()
    except Exception as e:
        prim_logger.error(f"Failed to close outage {outage_id}: {e}")

def sync_data(source_db, target_db, outage_id=None, target_server_name='', logger=None):
    """
    Copy new SensorReadings from source to target.
    If outage_id is given, also write audit rows to source_db.
    Returns number of rows inserted.
    """
    if logger is None:
        logger = prim_logger
    try:
        # Read last sync timestamp from TARGET's SyncLog
        target_conn = pymssql.connect(**target_db, autocommit=True)
        cursor = target_conn.cursor()
        cursor.execute("SELECT MAX(SyncTimestamp) FROM SyncLog")
        row = cursor.fetchone()
        last_sync_ts = row[0] if row[0] else datetime(2000, 1, 1)
        target_conn.close()

        # Fetch newer rows from SOURCE
        source_conn = pymssql.connect(**source_db, autocommit=True)
        source_cursor = source_conn.cursor()
        source_cursor.execute(
            "SELECT RowGUID, TagID, Timestamp, Value, Quality FROM SensorReadings WHERE Timestamp > %s ORDER BY Timestamp",
            (last_sync_ts,)
        )
        new_rows = source_cursor.fetchall()

        if not new_rows:
            source_conn.close()
            logger.info(f"No new rows to sync from {source_db['database']} to {target_db['database']}.")
            return 0

        # Insert into TARGET
        target_conn = pymssql.connect(**target_db, autocommit=True)
        target_cursor = target_conn.cursor()
        inserted = 0
        max_ts = last_sync_ts
        for row_guid, tag_id, ts, value, quality in new_rows:
            target_cursor.execute("SELECT 1 FROM SensorReadings WHERE RowGUID = %s", (row_guid,))
            if target_cursor.fetchone():
                continue
            target_cursor.execute(
                "INSERT INTO SensorReadings (RowGUID, TagID, Timestamp, Value, Quality) VALUES (%s, %s, %s, %s, %s)",
                (row_guid, tag_id, ts, value, quality)
            )
            if outage_id is not None:
                source_cursor.execute(
                    "INSERT INTO RecoveryAudit (OutageID, RowGUID, TagID, Timestamp, Value, Quality) VALUES (%s, %s, %s, %s, %s, %s)",
                    (outage_id, row_guid, tag_id, ts, value, quality)
                )
            inserted += 1
            if ts > max_ts:
                max_ts = ts

        target_conn.commit()
        if outage_id is not None:
            source_conn.commit()
        else:
            source_conn.close()

        # Record sync event in TARGET's SyncLog
        if max_ts > last_sync_ts:
            sync_type = 'RECOVERY' if outage_id is not None else 'GAP'
            target_cursor.execute(
                "INSERT INTO SyncLog (SyncTimestamp, SyncType, RowsSynced) VALUES (%s, %s, %s)",
                (max_ts, sync_type, inserted)
            )
            target_conn.commit()

        target_conn.close()
        logger.info(f"Synced {inserted} rows to {target_server_name}.")
        return inserted
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        return 0

def detect_and_sync_gap():
    """
    If both servers are online, compare max timestamps.
    If one is behind, silently sync the missing rows.
    """
    max_primary = get_max_timestamp(PRIMARY)
    max_secondary = get_max_timestamp(SECONDARY)

    if max_primary > max_secondary:
        prim_logger.info(f"Gap detected: PRIMARY ahead ({max_primary}) > SECONDARY ({max_secondary}). Silent sync.")
        sync_data(PRIMARY, SECONDARY, outage_id=None, target_server_name='SECONDARY', logger=prim_logger)
    elif max_secondary > max_primary:
        sec_logger.info(f"Gap detected: SECONDARY ahead ({max_secondary}) > PRIMARY ({max_primary}). Silent sync.")
        sync_data(SECONDARY, PRIMARY, outage_id=None, target_server_name='PRIMARY', logger=sec_logger)

def periodic_sync_state_advance():
    """
    Advance each server's SyncLog to the safe minimum timestamp.
    Runs only at hours 0,6,12,18 when both are online.
    """
    max_primary = get_max_timestamp(PRIMARY)
    max_secondary = get_max_timestamp(SECONDARY)
    safe_ts = min(max_primary, max_secondary)

    def update_if_newer(db, logger, server_name):
        try:
            conn = pymssql.connect(**db, autocommit=True)
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(SyncTimestamp) FROM SyncLog")
            row = cursor.fetchone()
            current_ts = row[0] if row[0] else datetime(2000, 1, 1)
            if safe_ts > current_ts:
                cursor.execute(
                    "INSERT INTO SyncLog (SyncTimestamp, SyncType, RowsSynced) VALUES (%s, 'PERIODIC', 0)",
                    (safe_ts,)
                )
                conn.commit()
                logger.info(f"Periodic SyncLog entry for {server_name}: {current_ts} -> {safe_ts}")
            conn.close()
        except Exception as e:
            logger.error(f"Failed to insert periodic SyncLog for {server_name}: {e}")

    update_if_newer(PRIMARY, prim_logger, 'PRIMARY')
    update_if_newer(SECONDARY, sec_logger, 'SECONDARY')

# ================== MAIN MONITOR ==================
class HealthMonitor:
    def __init__(self):
        self.primary_status = 0      # 1=online, -1=offline, 0=unknown
        self.secondary_status = 0
        self.primary_fail_count = 0
        self.secondary_fail_count = 0
        self.primary_outage_id = [None]
        self.secondary_outage_id = [None]
        self._stop = threading.Event()
        self.last_advance_hour = -1

    def run(self):
        prim_logger.info("Monitoring started. Checking every {} seconds.".format(CHECK_INTERVAL))
        while not self._stop.is_set():
            primary_online = is_db_online(PRIMARY)
            secondary_online = is_db_online(SECONDARY)

            # ----- Primary -> monitor Secondary -----
            if not secondary_online:
                self.secondary_fail_count += 1
                if self.secondary_fail_count >= DEBOUNCE_THRESHOLD and self.secondary_status != -1:
                    self.secondary_status = -1
                    prim_logger.warning("SECONDARY is OFFLINE.")
                    log_outage_start(PRIMARY, 'SECONDARY', self.secondary_outage_id)
            else:
                if self.secondary_fail_count >= DEBOUNCE_THRESHOLD and self.secondary_status == -1:
                    self.secondary_status = 1
                    prim_logger.info("SECONDARY is back ONLINE.")
                    if self.secondary_outage_id[0]:
                        rows = sync_data(PRIMARY, SECONDARY, self.secondary_outage_id[0], 'SECONDARY', prim_logger)
                        log_outage_end(PRIMARY, self.secondary_outage_id[0], rows)
                        self.secondary_outage_id[0] = None
                elif self.secondary_fail_count == 0:
                    self.secondary_status = 1
                    prim_logger.info("SECONDARY is ONLINE.")
                self.secondary_fail_count = 0

            # ----- Secondary -> monitor Primary -----
            if not primary_online:
                self.primary_fail_count += 1
                if self.primary_fail_count >= DEBOUNCE_THRESHOLD and self.primary_status != -1:
                    self.primary_status = -1
                    sec_logger.warning("PRIMARY is OFFLINE.")
                    log_outage_start(SECONDARY, 'PRIMARY', self.primary_outage_id)
            else:
                if self.primary_fail_count >= DEBOUNCE_THRESHOLD and self.primary_status == -1:
                    self.primary_status = 1
                    sec_logger.info("PRIMARY is back ONLINE.")
                    if self.primary_outage_id[0]:
                        rows = sync_data(SECONDARY, PRIMARY, self.primary_outage_id[0], 'PRIMARY', sec_logger)
                        log_outage_end(SECONDARY, self.primary_outage_id[0], rows)
                        self.primary_outage_id[0] = None
                elif self.primary_fail_count == 0:
                    self.primary_status = 1
                    sec_logger.info("PRIMARY is ONLINE.")
                self.primary_fail_count = 0

            # ----- Both online actions -----
            if self.primary_status == 1 and self.secondary_status == 1:
                detect_and_sync_gap()
                now = datetime.now()
                if now.hour in (0, 6, 12, 18) and now.hour != self.last_advance_hour:
                    periodic_sync_state_advance()
                    self.last_advance_hour = now.hour
            else:
                # Reset advance hour tracker if any server offline
                if datetime.now().hour not in (0, 6, 12, 18):
                    self.last_advance_hour = -1

            self._stop.wait(CHECK_INTERVAL)

    def stop(self):
        self._stop.set()

if __name__ == '__main__':
    monitor = HealthMonitor()
    try:
        monitor.run()
    except KeyboardInterrupt:
        monitor.stop()
