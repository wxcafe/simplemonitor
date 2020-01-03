# coding=utf-8
try:
    import sqlite3

    sqlite_available = True
except ImportError:
    sqlite_available = False

import time
from socket import gethostname

from Monitors.monitor import Monitor

from .logger import Logger, register

CREATE_SQL = [
    """
-- sqlite3 schema for monitor.db
-- version 1
CREATE TABLE IF NOT EXISTS results(
result_id integer primary key,
monitor_host varchar(50),
monitor_name varchar(50),
monitor_type varchar(50),
monitor_params varchar(100),
monitor_result int,
timestamp int,
monitor_info varchar(255));

CREATE TABLE IF NOT EXISTS status (
monitor_host varchar(50),
monitor_name varchar(50),
monitor_result int,
monitor_info varchar(255));

CREATE TABLE IF NOT EXISTS monitor_schema (
    k varchar(50) primary key,
    v varchar(255)
);

INSERT OR IGNORE INTO monitor_schema (k, v) VALUES ('monitor_schema_version', 1)
"""
]


class DBLogger(Logger):
    """Abstract class which uses a sqlite3 backend."""

    hostname = gethostname()
    connected = False

    def __init__(self, config_options: dict) -> None:
        """Open the database connection."""
        Logger.__init__(self, config_options)
        if not sqlite_available:
            raise RuntimeError("SQLite module not loaded.")
        self.db_path = Logger.get_config_option(
            config_options, "db_path", required=True, allow_empty=False
        )

        self.db_handle = sqlite3.connect(self.db_path, isolation_level=None)
        self.db_handle.row_factory = sqlite3.Row
        self.connected = True
        self.check_schema()

    def check_schema(self) -> None:
        """Create tables if needed, and check the schema."""
        self.db_handle.executescript(CREATE_SQL[0])
        cursor = self.db_handle.cursor()
        current_schema = None
        expected_schema = len(CREATE_SQL)
        for row in cursor.execute(
            "SELECT v AS value FROM monitor_schema where k = 'monitor_schema_version'"
        ):
            current_schema = int(row["value"])
        if current_schema is None:
            self.logger_logger.error(
                "Could not check current schema version! Expect weirdness."
            )
            return
        if current_schema < expected_schema:
            self.logger_logger.warning(
                "Schema for %s is out of date: current is %d, latest is %d.",
                self.db_path,
                current_schema,
                expected_schema,
            )
            self.roll_schema_forward(current_schema)
        elif current_schema > expected_schema:
            self.logger_logger.critical(
                "Schema for %s is newer than this code! Cannot use this database file.",
                self.db_path,
            )
            self.connected = False
        else:
            self.logger_logger.debug("Schema for %s is current", self.db_path)

    def roll_schema_forward(self, start: int) -> None:
        for sql in CREATE_SQL[start:]:
            self.logger_logger.info("Applying SQL schema update")
            self.logger_logger.debug(sql)
            try:
                self.db_handle.executescript(sql)
            except Exception:
                self.logger_logger.exception("Failed to apply schema update")
                self.logger_logger.critical(
                    "Cannot use this DB logger until schema is fixed!"
                )
                self.connected = False


@register
class DBFullLogger(DBLogger):
    """Logs results to a sqlite3 db."""

    type = "db"

    def save_result(
        self,
        monitor_name: str,
        monitor_type: str,
        monitor_params: str,
        monitor_result: int,
        monitor_info: str,
        hostname: str = "",
    ) -> None:
        """Write to the database."""
        if not self.connected:
            self.logger_logger.warning("cannot send results, a dependency failed")
            return
        sql = "INSERT INTO results (result_id, monitor_host, monitor_name, monitor_type, monitor_params, monitor_result, timestamp, monitor_info) VALUES (null, ?, ?, ?, ?, ?, ?, ?)"

        c = self.db_handle.cursor()

        join_string = ":"
        timestamp = int(time.time())
        if hostname == "":
            hostname = self.hostname

        params = (
            hostname,
            monitor_name,
            monitor_type,
            join_string.join([str(x) for x in monitor_params]),
            monitor_result,
            timestamp,
            monitor_info,
        )
        try:
            c.execute(sql, params)
        except sqlite3.OperationalError as e:
            self.logger_logger.critical("sqlite failed to write to database: %s", e)

    def save_result2(self, name: str, monitor: Monitor) -> None:
        """new interface."""
        if monitor.test_success():
            result = 1
        else:
            result = 0
        self.save_result(
            name, monitor.type, str(monitor.get_params()), result, monitor.describe()
        )

    def describe(self) -> str:
        return "Logging results to {0}".format(self.db_path)


@register
class DBStatusLogger(DBLogger):
    """Maintains status snapshot in db."""

    type = "dbstatus"

    def save_result(
        self,
        monitor_name: str,
        monitor_type: str,
        monitor_params: str,
        monitor_result: int,
        monitor_info: str,
        hostname: str = "",
    ) -> None:
        if hostname == "":
            hostname = self.hostname
        c = self.db_handle.cursor()
        try:
            c.execute(
                "DELETE FROM status WHERE monitor_host = ? AND monitor_name = ?",
                (self.hostname, monitor_name),
            )
            c.execute(
                "REPLACE INTO status (monitor_host, monitor_name, monitor_result, monitor_info) VALUES (?, ?, ?, ?)",
                (hostname, monitor_name, monitor_result, monitor_info),
            )
        except sqlite3.OperationalError as e:
            self.logger_logger.critical("sqlite failed to write to database: %s", e)

    def save_result2(self, name: str, monitor: Monitor) -> None:
        """new interface."""
        if monitor.test_success():
            result = 1
        else:
            result = 0
        self.save_result(
            name, monitor.type, str(monitor.get_params()), result, monitor.describe()
        )

    def describe(self) -> str:
        return "Logging status to {0}".format(self.db_path)
