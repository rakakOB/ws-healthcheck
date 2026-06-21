-- =====================================================
-- DATABASE: scada_historian
-- Run on BOTH instances (PRIMARY port 1433, SECONDARY port 1434)
-- =====================================================
CREATE DATABASE scada_historian;
GO
USE scada_historian;
GO

-- -----------------------------------------------------
-- 1. Main time‑series table (sensor data)
-- -----------------------------------------------------
CREATE TABLE SensorReadings (
    RowGUID CHAR(36) PRIMARY KEY,
    TagID INT NOT NULL,
    Timestamp DATETIME2 NOT NULL,
    Value FLOAT NOT NULL,
    Quality VARCHAR(20) DEFAULT 'Good'
);
GO

-- -----------------------------------------------------
-- 2. Outage log (records when the OTHER server is down)
--    For PRIMARY, ServerName = 'SECONDARY'
--    For SECONDARY, ServerName = 'PRIMARY'
-- -----------------------------------------------------
CREATE TABLE OutageLog (
    OutageID INT IDENTITY PRIMARY KEY,
    ServerName VARCHAR(50) NOT NULL,
    OutageStart DATETIME2 NOT NULL,
    OutageEnd DATETIME2 NULL,
    RowsMissed INT NULL,
    SyncStatus VARCHAR(20) DEFAULT 'Pending',
    Notes VARCHAR(500) NULL
);
GO

-- -----------------------------------------------------
-- 3. Append‑only sync log (replaces old single‑row SyncState)
--    Records every sync or checkpoint event
-- -----------------------------------------------------
CREATE TABLE SyncLog (
    LogID INT IDENTITY PRIMARY KEY,
    SyncTimestamp DATETIME2 NOT NULL,       -- max data timestamp synced up to
    SyncType VARCHAR(20) NOT NULL,          -- 'RECOVERY', 'GAP', or 'PERIODIC'
    RowsSynced INT DEFAULT 0,
    SyncDateTime DATETIME2 DEFAULT GETDATE() -- when this event occurred
);
GO

-- Seed a starting point
INSERT INTO SyncLog (SyncTimestamp, SyncType, RowsSynced)
VALUES ('2000-01-01 00:00:00', 'INITIAL', 0);
GO

-- -----------------------------------------------------
-- 4. Recovery audit (stores rows copied during recovery)
--    Linked to OutageLog.OutageID
-- -----------------------------------------------------
CREATE TABLE RecoveryAudit (
    RecoveryID INT IDENTITY PRIMARY KEY,
    OutageID INT FOREIGN KEY REFERENCES OutageLog(OutageID),
    RowGUID CHAR(36) NOT NULL,
    TagID INT NOT NULL,
    Timestamp DATETIME2 NOT NULL,
    Value FLOAT NOT NULL,
    Quality VARCHAR(20),
    RecoveryTime DATETIME2 DEFAULT GETDATE()
);
GO

-- -----------------------------------------------------

USE scada_historian;
select * from SensorReadings order by Timestamp;
select * from OutageLog;
select * from SyncState;
select * from RecoveryAudit;

-- -----------------------------------------------------

-- USE master;
-- DROP DATABASE scada_historian;
use scada_historian;
DROP TABLE IF EXISTS SensorReadings;
DROP TABLE IF EXISTS OutageLog;
DROP TABLE IF EXISTS SyncLog;
DROP TABLE IF EXISTS SyncState;
DROP TABLE IF EXISTS RecoveryAudit;
