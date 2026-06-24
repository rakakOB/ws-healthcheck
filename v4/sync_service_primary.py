"""
Primary WS Service – Monitors SECONDARY (port 1434)
Install : python ws_primary.py install
Start   : net start SCADAPrimaryWS
Stop    : net stop SCADAPrimaryWS
Remove  : python ws_primary.py remove
"""

import sys
import time
import logging
import os
import threading
import pymssql
from datetime import datetime

import win32serviceutil
import win32service
import win32event

# ================== CONFIGURATION ==================
SA_PASSWORD = 'YourStrong!Passw0rd'

LOCAL_DB = {
    'server': 'localhost',
    'port': 1433,
    'user': 'sa',
    'password': SA_PASSWORD,
    'database': 'scada_historian'
}

REMOTE_DB = {
    'server': 'localhost',
    'port': 1434,
    'user': 'sa',
    'password': SA_PASSWORD,
    'database': 'scada_historian'
}

MONITORED_SERVER_NAME = 'SECONDARY'
MY_SERVER_NAME = 'PRIMARY'
CHECK_INTERVAL = 30
DEBOUNCE_THRESHOLD = 1

LOG_DIR = r'C:\ScadaLogs'
LOG_FILE = os.path.join(LOG_DIR, 'primary_logs.log')
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('primary')

# ================== HELPERS ==================
def is_db_online(db_config):
    try:
        conn = pymssql.connect(**db_config, login_timeout=3, timeout=3)
        conn.cursor().execute("SELECT 1")
        conn.close()
        return True
    except:
        return False

def log_outage_event(event_type):
    try:
        conn = pymssql.connect(**LOCAL_DB, autocommit=True)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO OutageLog (ServerName, ServerEvents, EventDateTime, SyncStatus) "
            "VALUES (%s, %s, %s, 'Pending')",
            (MONITORED_SERVER_NAME, event_type, datetime.now())
        )
        conn.close()
        logger.info(f"Outage event logged: {event_type}")
    except Exception as e:
        logger.error(f"Failed to log outage event: {e}")

def get_last_outage_event():
    try:
        conn = pymssql.connect(**LOCAL_DB, autocommit=True)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ServerEvents, EventDateTime FROM OutageLog "
            "WHERE ServerName = %s ORDER BY EventDateTime DESC",
            (MONITORED_SERVER_NAME,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0], row[1]
        return None, None
    except:
        return None, None

def capture_rows(outage_start):
    try:
        conn = pymssql.connect(**LOCAL_DB, autocommit=True)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO SyncRecordsStatus (RowGUID, SensorTimestamp, TagID, SensorDate, Value, Quality, SyncSuccess) "
            "SELECT RowGUID, SensorTimestamp, TagID, SensorDate, Value, Quality, 0 "
            "FROM SensorReadings "
            "WHERE SensorTimestamp >= %s "
            "AND RowGUID NOT IN (SELECT RowGUID FROM SyncRecordsStatus)",
            (outage_start,)
        )
        rows = cursor.rowcount
        conn.commit()
        conn.close()
        logger.info(f"Captured {rows} rows into SyncRecordsStatus.")
        return rows
    except Exception as e:
        logger.error(f"Failed to capture rows: {e}")
        return 0

def sync_to_remote():
    try:
        local_conn = pymssql.connect(**LOCAL_DB, autocommit=True)
        local_cursor = local_conn.cursor()
        local_cursor.execute(
            "SELECT RowGUID, SensorTimestamp, TagID, SensorDate, Value, Quality "
            "FROM SyncRecordsStatus WHERE SyncSuccess = 0"
        )
        rows = local_cursor.fetchall()

        if not rows:
            logger.info("No unsynced rows to push.")
            local_conn.close()
            return 0

        remote_conn = pymssql.connect(**REMOTE_DB, autocommit=True)
        remote_cursor = remote_conn.cursor()
        synced = 0
        for row_guid, sensor_ts, tag_id, sensor_date, value, quality in rows:
            remote_cursor.execute("SELECT 1 FROM SensorReadings WHERE RowGUID = %s", (row_guid,))
            if remote_cursor.fetchone():
                continue
            remote_cursor.execute(
                "INSERT INTO SensorReadings (RowGUID, SensorTimestamp, TagID, SensorDate, Value, Quality) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (row_guid, sensor_ts, tag_id, sensor_date, value, quality)
            )
            synced += 1

        remote_conn.commit()
        remote_conn.close()

        local_cursor.execute("UPDATE SyncRecordsStatus SET SyncSuccess = 1 WHERE SyncSuccess = 0")
        local_conn.commit()
        local_conn.close()

        logger.info(f"Synced {synced} rows to remote {MONITORED_SERVER_NAME}.")
        return synced
    except Exception as e:
        logger.error(f"Sync to remote failed: {e}")
        return 0

# ================== MONITOR ==================
class PrimaryMonitor:
    def __init__(self):
        last_event, last_time = get_last_outage_event()
        if last_event == 'offline':
            self.remote_status = -1
            self.outage_start = last_time
            logger.warning(f"Startup: {MONITORED_SERVER_NAME} was OFFLINE since {self.outage_start}. Resuming capture.")
        else:
            self.remote_status = 0
            self.outage_start = None
            logger.info(f"Startup: assuming {MONITORED_SERVER_NAME} is ONLINE (will verify).")
        self.fail_count = 0
        self._stop = threading.Event()

    def run(self):
        logger.info(f"{MY_SERVER_NAME} WS started. Monitoring {MONITORED_SERVER_NAME} every {CHECK_INTERVAL}s.")
        while not self._stop.is_set():
            remote_online = is_db_online(REMOTE_DB)

            if not remote_online:
                self.fail_count += 1
                if self.fail_count >= DEBOUNCE_THRESHOLD and self.remote_status != -1:
                    self.remote_status = -1
                    self.outage_start = datetime.now()
                    logger.warning(f"{MONITORED_SERVER_NAME} is OFFLINE at {self.outage_start}")
                    log_outage_event('offline')
                if self.remote_status == -1:
                    capture_rows(self.outage_start)
            else:
                if self.fail_count >= DEBOUNCE_THRESHOLD and self.remote_status == -1:
                    self.remote_status = 1
                    logger.info(f"{MONITORED_SERVER_NAME} is back ONLINE.")
                    log_outage_event('online')
                    synced = sync_to_remote()
                    logger.info(f"Recovery sync complete: {synced} rows synced.")
                    self.outage_start = None
                elif self.fail_count == 0:
                    self.remote_status = 1
                    logger.info(f"{MONITORED_SERVER_NAME} is ONLINE.")
                self.fail_count = 0

            self._stop.wait(CHECK_INTERVAL)

    def stop(self):
        self._stop.set()

# ================== WINDOWS SERVICE ==================
class PrimaryService(win32serviceutil.ServiceFramework):
    _svc_name_ = 'SCADAPrimaryWS'
    _svc_display_name_ = 'SCADA Primary WS'

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.monitor = PrimaryMonitor()
        self.thread = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.monitor.stop()
        if self.thread:
            self.thread.join()
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)
        self.thread = threading.Thread(target=self.monitor.run)
        self.thread.start()
        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)

if __name__ == '__main__':
    if len(sys.argv) == 1:
        # Run interactively
        monitor = PrimaryMonitor()
        try:
            monitor.run()
        except KeyboardInterrupt:
            monitor.stop()
    else:
        win32serviceutil.HandleCommandLine(PrimaryService)