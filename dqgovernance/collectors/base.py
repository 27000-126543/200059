from abc import ABC, abstractmethod
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import json

from ..utils import ConfigManager, DatabaseManager, generate_id, parse_date
from ..logging import DQLogger


class BaseCollector(ABC):
    def __init__(self, system_code: str):
        self.system_code = system_code
        self.config = ConfigManager()
        self.db = DatabaseManager()
        self.logger = DQLogger()
        self.system_config = self.config.get(f"business_systems.{system_code}")
        if not self.system_config:
            raise ValueError(f"未找到系统配置: {system_code}")

        self._ensure_data_source_registered()

    def _ensure_data_source_registered(self):
        existing = self.db.execute_query(
            "SELECT * FROM data_sources WHERE system_code = ?",
            (self.system_code,),
        )
        if not existing:
            source_data = {
                "system_code": self.system_code,
                "system_name": self.system_config.get("name", self.system_code),
                "data_domain": self.system_config.get("data_domain"),
                "owner": self.system_config.get("owner"),
                "dept": self.system_config.get("dept"),
                "status": "active",
            }
            self.db.insert_record("data_sources", source_data)
            self.logger.info(f"注册数据源: {self.system_code}")

    @abstractmethod
    def collect(self, start_date: Optional[date] = None,
                end_date: Optional[date] = None) -> Dict[str, pd.DataFrame]:
        pass

    @abstractmethod
    def collect_table(self, table_name: str,
                      start_date: Optional[date] = None,
                      end_date: Optional[date] = None) -> pd.DataFrame:
        pass

    def validate_connection(self) -> bool:
        try:
            test_data = self.collect_table(
                self.system_config["tables"][0]["name"],
                date.today() - timedelta(days=1),
                date.today(),
            )
            return test_data is not None
        except Exception as e:
            self.logger.error(f"连接验证失败: {self.system_code} - {e}")
            return False

    def get_table_list(self) -> List[str]:
        return [t["name"] for t in self.system_config.get("tables", [])]

    def get_data_domain(self) -> str:
        return self.system_config.get("data_domain", "未知域")

    def get_owner(self) -> str:
        return self.system_config.get("owner", "未知负责人")

    def get_dept(self) -> str:
        return self.system_config.get("dept", "未知部门")


class MockBaseCollector(BaseCollector):
    def __init__(self, system_code: str):
        super().__init__(system_code)
        self._mock_data_generators = {}

    def collect(self, start_date: Optional[date] = None,
                end_date: Optional[date] = None) -> Dict[str, pd.DataFrame]:
        if start_date is None:
            start_date = date.today() - timedelta(days=1)
        if end_date is None:
            end_date = date.today()

        results = {}
        for table_info in self.system_config.get("tables", []):
            table_name = table_info["name"]
            try:
                df = self.collect_table(table_name, start_date, end_date)
                results[table_name] = df
                self.logger.log_operation(
                    "data_collection",
                    {
                        "table": table_name,
                        "records": len(df),
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                    },
                    system_code=self.system_code,
                    data_domain=self.get_data_domain(),
                )
            except Exception as e:
                self.logger.error(f"采集表 {table_name} 失败: {e}", exc_info=True)

        return results

    def collect_table(self, table_name: str,
                      start_date: Optional[date] = None,
                      end_date: Optional[date] = None) -> pd.DataFrame:
        if table_name in self._mock_data_generators:
            return self._mock_data_generators[table_name](start_date, end_date)
        return self._generate_default_mock_data(table_name, start_date, end_date)

    def register_mock_generator(self, table_name: str, generator_func):
        self._mock_data_generators[table_name] = generator_func

    def _generate_default_mock_data(
        self, table_name: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        from faker import Faker
        import random

        fake = Faker("zh_CN")
        date_range = (end_date - start_date).days + 1
        records_per_day = random.randint(50, 200)
        total_records = date_range * records_per_day

        data = []
        current_date = start_date
        record_id = 1

        for _ in range(date_range):
            for _ in range(records_per_day):
                record = {
                    "id": record_id,
                    "created_at": datetime.combine(
                        current_date,
                        datetime.min.time().replace(
                            hour=random.randint(0, 23),
                            minute=random.randint(0, 59),
                        ),
                    ),
                    "updated_at": datetime.combine(
                        current_date,
                        datetime.min.time().replace(
                            hour=random.randint(0, 23),
                            minute=random.randint(0, 59),
                        ),
                    ),
                    "created_by": fake.name(),
                    "status": random.choice(["active", "inactive", "pending"]),
                }
                data.append(record)
                record_id += 1
            current_date += timedelta(days=1)

        df = pd.DataFrame(data)

        if random.random() < 0.1:
            null_idx = random.sample(range(len(df)), int(len(df) * 0.05))
            df.loc[null_idx, "updated_at"] = None

        return df
