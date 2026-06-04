import logging
import os
import json
from datetime import datetime, date, timedelta
from logging.handlers import RotatingFileHandler
from typing import Dict, Any, List, Optional
from io import StringIO
import csv
import numpy as np

from ..utils import ConfigManager, DatabaseManager, generate_id, safe_json_dumps, json_serializer


class DQLogger:
    _instance = None
    _logger = None
    _db = None

    OPERATION_TYPES = [
        "data_collection",
        "quality_scan",
        "ticket_create",
        "ticket_update",
        "ticket_resolve",
        "data_masking",
        "correction_request",
        "correction_approve",
        "correction_reject",
        "report_generate",
        "report_export",
        "governance_project",
        "lineage_update",
        "system_config",
        "manual_trigger",
    ]

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._init_logger()
            cls._db = DatabaseManager()
        return cls._instance

    @classmethod
    def _init_logger(cls):
        log_level = ConfigManager.get("logging.level", "INFO")
        log_path = ConfigManager.get("logging.file_path", "./logs")
        max_size = ConfigManager.get("logging.max_file_size", "10MB")
        backup_count = ConfigManager.get("logging.backup_count", 30)

        if not os.path.exists(log_path):
            os.makedirs(log_path, exist_ok=True)

        max_bytes = cls._parse_size(max_size)

        cls._logger = logging.getLogger("DQGovernance")
        cls._logger.setLevel(getattr(logging, log_level.upper()))
        cls._logger.handlers.clear()

        file_handler = RotatingFileHandler(
            os.path.join(log_path, "dq_governance.log"),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        cls._logger.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        cls._logger.addHandler(console_handler)

    @staticmethod
    def _parse_size(size_str: str) -> int:
        units = {"MB": 1024 * 1024, "KB": 1024, "GB": 1024 * 1024 * 1024}
        size_str = size_str.strip().upper()
        for unit, multiplier in units.items():
            if size_str.endswith(unit):
                return int(float(size_str[:-len(unit)]) * multiplier)
        return int(size_str)

    def log_operation(
        self,
        operation_type: str,
        details: Dict[str, Any],
        system_code: Optional[str] = None,
        data_domain: Optional[str] = None,
        operator: str = "system",
        ip_address: Optional[str] = None,
    ) -> str:
        if operation_type not in self.OPERATION_TYPES:
            self.warning(f"未知操作类型: {operation_type}")

        log_id = generate_id("LOG")
        log_data = {
            "log_id": log_id,
            "operation_type": operation_type,
            "system_code": system_code,
            "data_domain": data_domain,
            "operator": operator,
            "details": safe_json_dumps(details) if details else None,
            "ip_address": ip_address,
        }

        try:
            self._db.insert_record("operation_logs", log_data)
            self.info(f"操作日志已记录: {operation_type} - {log_id}")
        except Exception as e:
            self.error(f"记录操作日志失败: {e}")

        return log_id

    def query_logs(
        self,
        operation_type: Optional[str] = None,
        system_code: Optional[str] = None,
        data_domain: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        operator: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM operation_logs WHERE 1=1"
        params = []

        if operation_type:
            query += " AND operation_type = ?"
            params.append(operation_type)
        if system_code:
            query += " AND system_code = ?"
            params.append(system_code)
        if data_domain:
            query += " AND data_domain = ?"
            params.append(data_domain)
        if operator:
            query += " AND operator = ?"
            params.append(operator)
        if start_date:
            query += " AND DATE(created_at) >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND DATE(created_at) <= ?"
            params.append(end_date.isoformat())

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        results = self._db.execute_query(query, tuple(params))

        for result in results:
            if result.get("details"):
                try:
                    result["details"] = json.loads(result["details"])
                except json.JSONDecodeError:
                    pass

        return results

    def export_logs(
        self,
        output_path: str,
        format: str = "csv",
        **query_kwargs,
    ) -> str:
        logs = self.query_logs(limit=100000, **query_kwargs)

        if not logs:
            self.warning("没有可导出的日志数据")
            return ""

        if format.lower() == "csv":
            if not output_path.endswith(".csv"):
                output_path += ".csv"

            with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
                if logs:
                    writer = csv.DictWriter(f, fieldnames=logs[0].keys())
                    writer.writeheader()
                    for log in logs:
                        log_copy = log.copy()
                        if isinstance(log_copy.get("details"), (dict, list)):
                            log_copy["details"] = safe_json_dumps(log_copy["details"])
                        writer.writerow(log_copy)

        elif format.lower() == "json":
            if not output_path.endswith(".json"):
                output_path += ".json"
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(logs, f, ensure_ascii=False, indent=2, default=str)
        else:
            raise ValueError(f"不支持的导出格式: {format}")

        self.info(f"日志已导出到: {output_path}, 共 {len(logs)} 条记录")
        return output_path

    def cleanup_old_logs(self, days: Optional[int] = None) -> int:
        if days is None:
            days = ConfigManager.get("logging.retention_days", 90)

        cutoff_date = datetime.now() - timedelta(days=days)
        query = "DELETE FROM operation_logs WHERE created_at < ?"
        deleted = self._db.execute_query(
            query, (cutoff_date.isoformat(),), fetch=False
        )

        self.info(f"清理了 {days} 天前的日志，共删除 {deleted or 0} 条记录")
        return deleted or 0

    def info(self, message: str):
        self._logger.info(message)

    def warning(self, message: str):
        self._logger.warning(message)

    def error(self, message: str, exc_info: bool = False):
        self._logger.error(message, exc_info=exc_info)

    def debug(self, message: str):
        self._logger.debug(message)

    def critical(self, message: str):
        self._logger.critical(message)
