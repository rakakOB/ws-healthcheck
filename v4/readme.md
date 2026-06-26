# SCADA High‑Availability Synchronisation System

A professional, industrial‑grade system that ensures two SQL Server instances remain perfectly synchronised, even when one server goes offline for any length of time.

The project simulates a real‑world SCADA environment: a data simulator continuously writes sensor readings to two independent MS SQL Server Express instances. Two separate Windows Services (one per server) monitor each other, log outages, and automatically recover any data missed while the partner was unreachable.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [1. SQL Server Instances](#1-sql-server-instances)
  - [2. Firewall Configuration](#2-firewall-configuration)
  - [3. Database Setup](#3-database-setup)
  - [4. Python Environment & Dependencies](#4-python-environment--dependencies)
  - [5. SCADA Simulator](#5-scada-simulator)
  - [6. Windows Services (WS)](#6-windows-services-ws)
- [Configuration](#configuration)
- [Testing the System](#testing-the-system)
- [Monitoring and Logs](#monitoring-and-logs)
- [Repository Structure](#repository-structure)
- [Troubleshooting](#troubleshooting)
- [Future Enhancements](#future-enhancements)

---

## Architecture Overview


**System Architecture:**

![System Architecture](docs/architecture_diagram.png)


**Comprehensive System Flowchart:**

![Comprehensive System Flowchart](docs/comprehensive_system_flowchart.png)


**Components:**

- **SCADA Simulator** (`simulator/scada_simulator.py`) – generates realistic sensor data and writes the same batches to both databases every 30 seconds.
- **Two MS SQL Server Express Instances** – `PRIMARY` on port 1433, `SECONDARY` on port 1434. Each hosts an identical `scada_historian` database with three tables:
  - `SensorReadings` – the live sensor data.
  - `OutageLog` – a timeline of every offline/online event detected by the monitors.
  - `SyncRecordsStatus` – captures rows that were missed by the remote server during an outage, with a `SyncSuccess` flag.
- **Two independent Windows Services** – `SCADAPrimaryWS` and `SCADASecondaryWS`.  
  Each service runs on its own server and:
  1. Checks the remote server’s SQL port every 30 seconds.
  2. Logs state changes (offline → online, online → offline) to its local `OutageLog`.
  3. While the remote is offline, continuously copies new local rows into `SyncRecordsStatus`.
  4. When the remote comes back online, pushes all captured rows to the remote database and marks them as synced.

The two services never communicate directly – they only interact with the databases. This makes the system fully distributed and resilient to individual service crashes or reboots.

---

## Features

- **Zero data loss** – all rows inserted during an outage are automatically recovered.
- **GUID‑based deduplication** – safe to run recovery multiple times; duplicates are automatically skipped.
- **Crash‑safe** – if a server (or its service) reboots mid‑outage, the service reads the last known outage timestamp from the database and resumes capturing.
- **Audit trail** – every outage and every recovered row is permanently stored in the database tables.
- **Human‑readable logs** – each service writes detailed log files to `C:\ScadaLogs\`.
- **Windows Service ready** – install, start, stop, and remove using standard `net` commands.
- **Scalable** – works on two separate physical machines (use Tailscale / static IPs) or locally for testing.

---

## Prerequisites

- Windows 10/11 or Windows Server (64‑bit)
- Administrator rights on both machines
- Python 3.8 or newer (Anaconda is fine)
- MS SQL Server 2022 Express (free) – [Download](https://www.microsoft.com/en-us/sql-server/sql-server-downloads)
- Git (optional)

---

## Installation

### 1. SQL Server Instances

We need two separate instances on the same machine (or one on each machine).

**a) Install the first instance (PRIMARY):**
1. Run the SQL Server installer → **Custom**.
2. On **Instance Configuration**, select **Named instance** and enter `PRIMARY`.
3. On **Database Engine Configuration**:
   - Choose **Mixed Mode** (SQL Server and Windows Authentication).
   - Set a strong `sa` password (e.g., `YourStrong!Passw0rd`).
   - Add your current Windows user as an administrator.
4. Complete the installation.

**b) Install the second instance (SECONDARY):**
1. Run the installer again.
2. On **Instance Configuration**, select **Named instance** and enter `SECONDARY`.
3. Use the **exact same `sa` password**.
4. Finish the installation.

**c) Configure static ports:**
1. Open **SQL Server Configuration Manager**.
2. Go to **SQL Server Network Configuration** → **Protocols for PRIMARY**:
   - Enable **TCP/IP**.
   - Double‑click TCP/IP → **IP Addresses** tab → scroll to **IPAll** → set **TCP Port** = `1433`, clear **TCP Dynamic Ports**.
3. Repeat for **Protocols for SECONDARY**, setting port **1434**.
4. Restart both services: `SQL Server (PRIMARY)` and `SQL Server (SECONDARY)`.

---

### 2. Firewall Configuration

If the two services will ever run on different physical machines, open the SQL ports.

In an **elevated PowerShell** on both machines:

```powershell
New-NetFirewallRule -DisplayName "SQL Primary" -Direction Inbound -Protocol TCP -LocalPort 1433 -Action Allow
New-NetFirewallRule -DisplayName "SQL Secondary" -Direction Inbound -Protocol TCP -LocalPort 1434 -Action Allow