import sqlite3
import os
from contextlib import contextmanager
from typing import Dict, Any, List, Optional, Generator
from datetime import datetime, date
import json

from .config import ConfigManager
from .helpers import safe_json_dumps


class DatabaseManager:
    _instance = None
    _conn = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._init_database()
        return cls._instance

    @classmethod
    def _init_database(cls):
        db_path = ConfigManager.get("database.path", "./data/dq_governance.db")
        db_dir = os.path.dirname(db_path)
        if not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        cls._conn = sqlite3.connect(db_path, check_same_thread=False)
        cls._conn.row_factory = sqlite3.Row
        cls._create_tables()

    @classmethod
    def _create_tables(cls):
        cursor = cls._conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                system_code TEXT NOT NULL UNIQUE,
                system_name TEXT NOT NULL,
                data_domain TEXT,
                owner TEXT,
                dept TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quality_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                system_code TEXT NOT NULL,
                table_name TEXT,
                completeness_score REAL,
                consistency_score REAL,
                timeliness_score REAL,
                overall_score REAL,
                scan_date DATE NOT NULL,
                total_records INTEGER,
                issue_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(system_code, table_name, scan_date)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quality_issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_code TEXT UNIQUE,
                system_code TEXT NOT NULL,
                table_name TEXT,
                field_name TEXT,
                issue_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                description TEXT,
                rule_name TEXT,
                affected_records INTEGER,
                sample_data TEXT,
                scan_date DATE NOT NULL,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS governance_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_no TEXT UNIQUE NOT NULL,
                issue_id INTEGER,
                system_code TEXT NOT NULL,
                data_domain TEXT,
                title TEXT NOT NULL,
                description TEXT,
                severity TEXT NOT NULL,
                priority TEXT NOT NULL,
                assignee TEXT,
                dept TEXT,
                sla_hours INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP,
                resolution TEXT,
                FOREIGN KEY (issue_id) REFERENCES quality_issues(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sensitive_data_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                system_code TEXT NOT NULL,
                table_name TEXT,
                field_name TEXT,
                data_type TEXT NOT NULL,
                sensitivity_level TEXT NOT NULL,
                record_count INTEGER,
                masked_count INTEGER,
                masking_method TEXT,
                scan_date DATE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(system_code, table_name, field_name, data_type, scan_date)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS correction_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_no TEXT UNIQUE NOT NULL,
                system_code TEXT NOT NULL,
                table_name TEXT,
                record_id TEXT,
                field_name TEXT,
                old_value TEXT,
                new_value TEXT,
                reason TEXT,
                applicant TEXT,
                dept TEXT,
                validation_result TEXT,
                validation_details TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_lineage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_system TEXT NOT NULL,
                source_table TEXT,
                source_field TEXT,
                target_system TEXT,
                target_table TEXT,
                target_field TEXT,
                transformation_rule TEXT,
                quality_status TEXT,
                last_verified_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS governance_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_code TEXT UNIQUE NOT NULL,
                project_name TEXT NOT NULL,
                system_code TEXT,
                data_domain TEXT,
                trigger_reason TEXT,
                start_date DATE NOT NULL,
                end_date DATE,
                project_manager TEXT,
                status TEXT DEFAULT 'active',
                improvement_plan TEXT,
                target_score REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS operation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_id TEXT UNIQUE NOT NULL,
                operation_type TEXT NOT NULL,
                system_code TEXT,
                data_domain TEXT,
                operator TEXT,
                details TEXT,
                ip_address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_no TEXT UNIQUE NOT NULL,
                report_type TEXT NOT NULL,
                report_date DATE NOT NULL,
                format TEXT,
                file_path TEXT,
                recipients TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_scores_system_date ON quality_scores(system_code, scan_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_issues_system_date ON quality_issues(system_code, scan_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tickets_system_status ON governance_tickets(system_code, status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_logs_operation_date ON operation_logs(operation_type, created_at)
        """)

        cls._conn.commit()

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        try:
            yield self._conn
        except Exception as e:
            self._conn.rollback()
            raise e

    def execute_query(
        self,
        query: str,
        params: Optional[tuple] = None,
        fetch: bool = True,
    ) -> List[Dict[str, Any]]:
        cursor = self._conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)

        if fetch:
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        else:
            self._conn.commit()
            return cursor.lastrowid

    def insert_record(self, table: str, data: Dict[str, Any]) -> int:
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?" for _ in data])
        query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        values = tuple(
            safe_json_dumps(v) if isinstance(v, (dict, list)) else v for v in data.values()
        )
        return self.execute_query(query, values, fetch=False)

    def update_record(
        self, table: str, data: Dict[str, Any], where: str, params: tuple
    ) -> int:
        set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
        query = f"UPDATE {table} SET {set_clause} WHERE {where}"
        values = tuple(
            safe_json_dumps(v) if isinstance(v, (dict, list)) else v for v in data.values()
        ) + params
        return self.execute_query(query, values, fetch=False)

    def close(self):
        if self._conn:
            self._conn.close()
