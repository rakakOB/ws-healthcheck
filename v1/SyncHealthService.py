import time
import sys
import logging
import os
import threading
import pymssql
from datetime import datetime
import socket

import win32serviceutil
import win32service
import win32event
import servicemanager

# ========== CONFIGURATION – CHANGE FOR EACH MACHINE ==========
# Remote server (the OTHER machine)
REMOTE_HOST = '192.168.0.165'      # IP of Machine B on Machine A, and IP of Machine A on Machine B
REMOTE_PORT = 1433

# Local database (on this machine)
LOCAL_DB = {
    'server': 'localhost',
    'port': 1433,
    'user': 'sa',
    'password': 'rak!@#123',
    'database': 'SCADA_Historian'
}

# Health‑check parameters
CHECK_INTERVAL_SEC = 10         # seconds between checks
DEBOUNCE_THRESHOLD = 3          # consecutive failures before declaring OFFLINE

# Logging
LOG_DIR = r'C:\ScadaLogs'
LOG_FILE = os.path.join(LOG_DIR, 'health_service.log')
SERVICE_NAME = 'SCADASyncHealth'
SERVICE_DISPLAY_NAME = 'SCADA Sync Health Service'

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

class HealthMonitor:
    def __init__(self):
        self.current_state = 'UNKNOWN'
        self.fail_count = 0
        self._stop_event = threading.Event()
        self._outage_id = None

    def _is_remote_online(self):
        """Attempt to connect and run SELECT 1 on the remote server."""
        try:
            conn = pymssql.connect(
                server=REMOTE_HOST,
                port=REMOTE_PORT,
                user='sa',
                password='administrator123',
                database='master',
                login_timeout=3,
                timeout=3
            )
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            conn.close()
            return True
        except Exception as e:
            logging.debug(f"Health check failed: {e}")
            return False

    def _insert_outage_start(self):
        try:
            conn = pymssql.connect(**LOCAL_DB, autocommit=True)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO OutageLog (ServerName, OutageStart, SyncStatus) VALUES (%s, %s, 'Pending')",
                (socket.gethostname(), datetime.now())
            )
            self._outage_id = cursor.lastrowid
            conn.close()
            logging.info(f"Outage started – Log ID {self._outage_id}")
        except Exception as e:
            logging.error(f"Failed to insert outage start: {e}")

    def _update_outage_end(self, rows_missed=0):
        if self._outage_id is None:
            return
        try:
            conn = pymssql.connect(**LOCAL_DB, autocommit=True)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE OutageLog SET OutageEnd = %s, RowsMissed = %s, SyncStatus = 'Synced' WHERE OutageID = %s",
                (datetime.now(), rows_missed, self._outage_id)
            )
            conn.close()
            logging.info(f"Outage ended – Log ID {self._outage_id} closed")
            self._outage_id = None
        except Exception as e:
            logging.error(f"Failed to close outage: {e}")

    def run(self):
        logging.info("Health monitor started.")
        while not self._stop_event.is_set():
            online = self._is_remote_online()
            previous_state = self.current_state

            if online:
                self.fail_count = 0
                if self.current_state != 'ONLINE':
                    self.current_state = 'ONLINE'
                    logging.info("Remote server is ONLINE.")
                    if previous_state == 'OFFLINE' and self._outage_id:
                        self._update_outage_end()
            else:
                self.fail_count += 1
                if self.fail_count >= DEBOUNCE_THRESHOLD and self.current_state != 'OFFLINE':
                    self.current_state = 'OFFLINE'
                    logging.warning("Remote server is OFFLINE.")
                    self._insert_outage_start()

            self._stop_event.wait(CHECK_INTERVAL_SEC)

    def stop(self):
        self._stop_event.set()


class SyncHealthService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.monitor = HealthMonitor()
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
    # When run with 'install', 'start', 'stop', etc. it will handle service control
    # When run with no arguments, it will start the service (if installed) or run interactively
    if len(sys.argv) == 1:
        # No arguments – run in interactive mode for debugging
        monitor = HealthMonitor()
        try:
            monitor.run()
        except KeyboardInterrupt:
            monitor.stop()
    else:
        # Service installation/removal commands
        win32serviceutil.HandleCommandLine(SyncHealthService)