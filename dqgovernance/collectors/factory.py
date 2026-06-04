from typing import Dict, Optional
from datetime import date, timedelta
import pandas as pd

from .order_collector import OrderCollector
from .finance_collector import FinanceCollector
from .hr_collector import HRCollector
from .base import BaseCollector
from ..utils import ConfigManager
from ..logging import DQLogger


class CollectorFactory:
    _collectors: Dict[str, BaseCollector] = {}
    _logger = DQLogger()
    _config = ConfigManager()

    @classmethod
    def get_collector(cls, system_code: str) -> Optional[BaseCollector]:
        if system_code not in cls._collectors:
            try:
                if system_code == "order_system":
                    cls._collectors[system_code] = OrderCollector()
                elif system_code == "finance_system":
                    cls._collectors[system_code] = FinanceCollector()
                elif system_code == "hr_system":
                    cls._collectors[system_code] = HRCollector()
                else:
                    cls._logger.warning(f"未找到采集器: {system_code}")
                    return None
            except Exception as e:
                cls._logger.error(f"创建采集器失败: {system_code} - {e}", exc_info=True)
                return None
        return cls._collectors[system_code]

    @classmethod
    def get_all_collectors(cls) -> Dict[str, BaseCollector]:
        systems = cls._config.get("business_systems", {})
        collectors = {}
        for system_code in systems.keys():
            collector = cls.get_collector(system_code)
            if collector:
                collectors[system_code] = collector
        return collectors

    @classmethod
    def collect_all(
        cls,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Dict[str, pd.DataFrame]]:
        if start_date is None:
            start_date = date.today() - timedelta(days=1)
        if end_date is None:
            end_date = date.today()

        results = {}
        collectors = cls.get_all_collectors()

        for system_code, collector in collectors.items():
            try:
                cls._logger.info(f"开始采集: {system_code}")
                data = collector.collect(start_date, end_date)
                results[system_code] = data
                total_records = sum(len(df) for df in data.values())
                cls._logger.info(f"完成采集: {system_code}, 共 {total_records} 条记录")
            except Exception as e:
                cls._logger.error(f"采集失败: {system_code} - {e}", exc_info=True)

        return results

    @classmethod
    def collect_system(
        cls,
        system_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Optional[Dict[str, pd.DataFrame]]:
        collector = cls.get_collector(system_code)
        if not collector:
            return None
        try:
            cls._logger.info(f"开始采集: {system_code}")
            data = collector.collect(start_date, end_date)
            total_records = sum(len(df) for df in data.values())
            cls._logger.info(f"完成采集: {system_code}, 共 {total_records} 条记录")
            return data
        except Exception as e:
            cls._logger.error(f"采集失败: {system_code} - {e}", exc_info=True)
            return None

    @classmethod
    def validate_all_connections(cls) -> Dict[str, bool]:
        results = {}
        collectors = cls.get_all_collectors()
        for system_code, collector in collectors.items():
            results[system_code] = collector.validate_connection()
        return results
