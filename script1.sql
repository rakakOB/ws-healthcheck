-- ======================================================
-- SCADA Configuration Database
-- ======================================================
CREATE DATABASE SCADA_Config;
GO
USE SCADA_Config;
GO

CREATE TABLE Sites (
    SiteID INT PRIMARY KEY IDENTITY,
    SiteName NVARCHAR(50) NOT NULL,
    Location NVARCHAR(100)
);

CREATE TABLE EngineeringUnits (
    UnitID INT PRIMARY KEY IDENTITY,
    UnitName NVARCHAR(20) NOT NULL UNIQUE
);

CREATE TABLE Tags (
    TagID INT PRIMARY KEY IDENTITY,
    TagName NVARCHAR(50) NOT NULL UNIQUE,
    Description NVARCHAR(200),
    SiteID INT FOREIGN KEY REFERENCES Sites(SiteID),
    UnitID INT FOREIGN KEY REFERENCES EngineeringUnits(UnitID),
    MinRange FLOAT,
    MaxRange FLOAT
);

-- Seed a few sites and tags for realism
INSERT INTO Sites (SiteName, Location) VALUES ('Plant A', 'Building 1');
INSERT INTO EngineeringUnits (UnitName) VALUES ('°C'), ('bar'), ('kW'), ('%');
INSERT INTO Tags (TagName, Description, SiteID, UnitID, MinRange, MaxRange) 
VALUES 
    ('TT-101', 'Temperature Reactor', 1, 1, 0, 500),
    ('PT-202', 'Pressure Vessel', 1, 2, 0, 100),
    ('KW-303', 'Power Motor', 1, 3, 0, 1000);

-- ======================================================
-- SCADA Historian Database (time‑series data)
-- ======================================================
CREATE DATABASE SCADA_Historian;
GO
USE SCADA_Historian;
GO

CREATE TABLE AnalogValues (
    RowGUID CHAR(36) PRIMARY KEY,
    TagID INT NOT NULL,
    Timestamp DATETIME2 NOT NULL,
    Value FLOAT NOT NULL,
    Quality NVARCHAR(20) DEFAULT 'Good'
);

CREATE TABLE DigitalValues (
    RowGUID CHAR(36) PRIMARY KEY,
    TagID INT NOT NULL,
    Timestamp DATETIME2 NOT NULL,
    Value BIT NOT NULL,
    Quality NVARCHAR(20) DEFAULT 'Good'
);

CREATE TABLE SyncState (
    Id INT PRIMARY KEY DEFAULT 1 CHECK (Id = 1),
    LastSyncTimestamp DATETIME2 NOT NULL DEFAULT '2000-01-01'
);

CREATE TABLE OutageLog (
    OutageID INT PRIMARY KEY IDENTITY,
    ServerName NVARCHAR(50) NOT NULL,
    OutageStart DATETIME2 NOT NULL,
    OutageEnd DATETIME2 NULL,
    RowsMissed INT NULL,
    SyncStatus NVARCHAR(20) DEFAULT 'Pending',
    CSVFilePath NVARCHAR(500) NULL,
    Notes NVARCHAR(500) NULL
);

-- Insert the single SyncState row
INSERT INTO SyncState (Id, LastSyncTimestamp) VALUES (1, '2000-01-01');

use SCADA_Historian;
select * from SyncState;
