-- Run on PRIMARY (port 1433) and SECONDARY (port 1434)
CREATE DATABASE scada_historian;
GO
USE scada_historian;
GO

-- Table that holds sensor readings (the only table the simulator writes to)
CREATE TABLE SensorReadings (
    RowGUID CHAR(36) PRIMARY KEY,
    TagID INT NOT NULL,
    Timestamp DATETIME2 NOT NULL,
    Value FLOAT NOT NULL,
    Quality VARCHAR(20) DEFAULT 'Good'
);
GO

-- Logs when the other server goes offline / online
CREATE TABLE OutageLog (
    OutageID INT IDENTITY PRIMARY KEY,
    ServerName VARCHAR(50) NOT NULL,       -- 'PRIMARY' or 'SECONDARY'
    OutageStart DATETIME2 NOT NULL,
    OutageEnd DATETIME2 NULL,
    RowsMissed INT NULL,
    SyncStatus VARCHAR(20) DEFAULT 'Pending',
    Notes VARCHAR(500) NULL
);
GO

-- Tracks the last synchronisation timestamp
DROP TABLE IF EXISTS SyncLog;

CREATE TABLE SyncState (
    Id INT PRIMARY KEY DEFAULT 1 CHECK (Id = 1),
    LastSyncTimestamp DATETIME2 NOT NULL DEFAULT '2000-01-01'
);
INSERT INTO SyncState (Id, LastSyncTimestamp) VALUES (1, '2000-01-01');
GO

-- Stores the actual rows that were recovered during a sync (audit trail)
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

--------------------------------------------------

USE scada_historian;
select * from SensorReadings order by Timestamp;
select * from OutageLog;
select * from SyncState;
select * from RecoveryAudit;

select * from SyncLog;

--------------------------------------------------

-- Drop the old single-row table
DROP TABLE IF EXISTS SyncState;

-- Create the new append-only sync log
CREATE TABLE SyncLog (
    LogID INT IDENTITY PRIMARY KEY,
    SyncTimestamp DATETIME2 NOT NULL,       -- the maximum timestamp of data synced during this operation
    SyncType VARCHAR(20) NOT NULL,          -- 'RECOVERY' or 'PERIODIC' or 'GAP'
    RowsSynced INT DEFAULT 0,
    SyncDateTime DATETIME2 DEFAULT GETDATE()  -- when the sync operation was executed
);

-- Insert a seed row to act as the starting point (optional, but helpful)
INSERT INTO SyncLog (SyncTimestamp, SyncType, RowsSynced)
VALUES ('2000-01-01 00:00:00', 'INITIAL', 0);

--------------------------------------------------

USE [scada_historian];

SELECT TABLE_NAME 
FROM INFORMATION_SCHEMA.TABLES 
WHERE TABLE_TYPE = 'BASE TABLE' 
ORDER BY TABLE_NAME;

--------------------------------------------------

-- USE master;
-- DROP DATABASE scada_historian;
use scada_historian;
DROP TABLE IF EXISTS SensorReadings;
DROP TABLE IF EXISTS OutageLog;
DROP TABLE IF EXISTS SyncLog;
DROP TABLE IF EXISTS SyncState;
DROP TABLE IF EXISTS RecoveryAudit;
