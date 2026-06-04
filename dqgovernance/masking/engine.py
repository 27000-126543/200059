from datetime import datetime, date
from typing import Dict, Any, List, Optional, Tuple, Set
import pandas as pd
import re
import json

from ..utils import (
    ConfigManager,
    DatabaseManager,
    generate_id,
    mask_string,
    hash_value,
    is_valid_id_card,
    is_valid_phone,
    is_valid_email,
)
from ..logging import DQLogger


class SensitiveData:
    def __init__(
        self,
        data_type: str,
        sensitivity_level: str,
        field_name: str,
        record_count: int,
        masking_method: str,
        system_code: str,
        table_name: str,
        masked_count: int = 0,
    ):
        self.data_type = data_type
        self.sensitivity_level = sensitivity_level
        self.field_name = field_name
        self.record_count = record_count
        self.masking_method = masking_method
        self.system_code = system_code
        self.table_name = table_name
        self.masked_count = masked_count
        self.scan_date = date.today()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "data_type": self.data_type,
            "sensitivity_level": self.sensitivity_level,
            "field_name": self.field_name,
            "record_count": self.record_count,
            "masking_method": self.masking_method,
            "system_code": self.system_code,
            "table_name": self.table_name,
            "masked_count": self.masked_count,
            "scan_date": self.scan_date.isoformat(),
        }


class MaskingEngine:
    MASKING_METHODS = ["full_mask", "partial_mask", "hash_mask", "replace"]

    def __init__(self):
        self.config = ConfigManager()
        self.db = DatabaseManager()
        self.logger = DQLogger()
        self.patterns = self.config.get("sensitive_data.patterns", {})
        self.masking_rules = self.config.get("sensitive_data.masking_rules", {})
        self.dept_permissions = self.config.get("sensitive_data.dept_permissions", {})

    def scan_and_mask(
        self,
        system_code: str,
        data: Dict[str, pd.DataFrame],
        dept: Optional[str] = None,
        scan_date: Optional[date] = None,
    ) -> Tuple[Dict[str, pd.DataFrame], List[SensitiveData]]:
        if scan_date is None:
            scan_date = date.today()

        self.logger.info(f"开始敏感数据扫描与脱敏: {system_code}, 部门: {dept or '通用'}")

        masked_data = {}
        all_sensitive_data = []

        for table_name, df in data.items():
            masked_df, sensitive_fields = self.scan_table(
                system_code, table_name, df, dept, scan_date
            )
            masked_data[table_name] = masked_df
            all_sensitive_data.extend(sensitive_fields)

        self._save_sensitive_records(system_code, all_sensitive_data)

        self.logger.log_operation(
            "data_masking",
            {
                "system_code": system_code,
                "dept": dept,
                "scan_date": scan_date.isoformat(),
                "tables_scanned": len(data),
                "sensitive_fields_count": len(all_sensitive_data),
                "total_records_masked": sum(s.masked_count for s in all_sensitive_data),
            },
            system_code=system_code,
        )

        return masked_data, all_sensitive_data

    def scan_table(
        self,
        system_code: str,
        table_name: str,
        df: pd.DataFrame,
        dept: Optional[str] = None,
        scan_date: Optional[date] = None,
    ) -> Tuple[pd.DataFrame, List[SensitiveData]]:
        if scan_date is None:
            scan_date = date.today()

        if df is None or df.empty:
            return df, []

        masked_df = df.copy()
        sensitive_fields = []

        for column in df.columns:
            if pd.api.types.is_string_dtype(df[column]):
                data_type, sensitivity_level = self._identify_sensitive_data(
                    df[column], column
                )
                if data_type:
                    masking_method = self._get_masking_method(
                        sensitivity_level, dept, data_type
                    )
                    record_count = self._count_sensitive_records(df[column], data_type)

                    if masking_method:
                        masked_df[column] = self._mask_field(
                            df[column], data_type, masking_method
                        )
                        masked_count = record_count
                    else:
                        masked_count = 0

                    sensitive_data = SensitiveData(
                        data_type=data_type,
                        sensitivity_level=sensitivity_level,
                        field_name=column,
                        record_count=record_count,
                        masking_method=masking_method or "none",
                        system_code=system_code,
                        table_name=table_name,
                        masked_count=masked_count,
                    )
                    sensitive_fields.append(sensitive_data)

                    self.logger.info(
                        f"识别敏感字段: {table_name}.{column}, "
                        f"类型: {data_type}, 级别: {sensitivity_level}, "
                        f"记录数: {record_count}, 脱敏方式: {masking_method}"
                    )

        return masked_df, sensitive_fields

    def _identify_sensitive_data(
        self, series: pd.Series, field_name: str
    ) -> Tuple[Optional[str], Optional[str]]:
        field_name_lower = field_name.lower()

        for data_type, pattern_config in self.patterns.items():
            if "keywords" in pattern_config:
                keywords = pattern_config["keywords"]
                if any(kw in field_name or kw in field_name_lower for kw in keywords):
                    return data_type, pattern_config.get("level", "medium")

            sensitive_field_names = {
                "id_card": ["id_card", "idcard", "身份证", "identity", "证件号"],
                "phone": ["phone", "mobile", "cell", "tel", "手机", "电话"],
                "email": ["email", "mail", "邮箱"],
                "bank_card": ["bank_card", "bankcard", "card_no", "card_number", "银行卡", "卡号"],
                "address": ["address", "addr", "地址", "住址"],
            }

            name_matches = sensitive_field_names.get(data_type, [])
            if any(nm in field_name_lower for nm in name_matches):
                return data_type, pattern_config.get("level", "medium")

            if "pattern" in pattern_config:
                pattern = pattern_config["pattern"]
                sample_data = series.dropna().astype(str).head(100)

                if len(sample_data) > 0:
                    match_count = sum(
                        1 for val in sample_data if re.match(pattern, str(val))
                    )
                    if match_count / len(sample_data) > 0.5:
                        return data_type, pattern_config.get("level", "medium")

            if data_type == "id_card":
                sample_data = series.dropna().astype(str).head(100)
                valid_count = sum(
                    1 for val in sample_data if is_valid_id_card(str(val))
                )
                if len(sample_data) > 0 and valid_count / len(sample_data) > 0.2:
                    return data_type, pattern_config.get("level", "high")

            elif data_type == "phone":
                sample_data = series.dropna().astype(str).head(100)
                valid_count = sum(
                    1 for val in sample_data if is_valid_phone(str(val))
                )
                if len(sample_data) > 0 and valid_count / len(sample_data) > 0.2:
                    return data_type, pattern_config.get("level", "medium")

            elif data_type == "email":
                sample_data = series.dropna().astype(str).head(100)
                valid_count = sum(
                    1 for val in sample_data if is_valid_email(str(val))
                )
                if len(sample_data) > 0 and valid_count / len(sample_data) > 0.2:
                    return data_type, pattern_config.get("level", "low")

        return None, None

    def _count_sensitive_records(self, series: pd.Series, data_type: str) -> int:
        if data_type == "id_card":
            return sum(1 for val in series.dropna() if is_valid_id_card(str(val)))
        elif data_type == "phone":
            return sum(1 for val in series.dropna() if is_valid_phone(str(val)))
        elif data_type == "email":
            return sum(1 for val in series.dropna() if is_valid_email(str(val)))
        elif data_type in self.patterns and "pattern" in self.patterns[data_type]:
            pattern = self.patterns[data_type]["pattern"]
            return sum(
                1
                for val in series.dropna()
                if re.match(pattern, str(val))
            )
        else:
            return series.notna().sum()

    def _get_masking_method(
        self, sensitivity_level: str, dept: Optional[str], data_type: str
    ) -> Optional[str]:
        if dept and dept in self.dept_permissions:
            dept_perm = self.dept_permissions[dept]
            allowed_levels = dept_perm.get("allowed_levels", [])
            special_fields = dept_perm.get("special_fields", [])

            if sensitivity_level in allowed_levels or data_type in special_fields:
                return None

        rule = self.masking_rules.get(sensitivity_level, {})
        return rule.get("method", "partial_mask")

    def _mask_field(
        self, series: pd.Series, data_type: str, masking_method: str
    ) -> pd.Series:
        if masking_method == "full_mask":
            return series.apply(
                lambda x: mask_string(str(x), 0, 0) if pd.notna(x) else x
            )

        elif masking_method == "partial_mask":
            if data_type == "phone":
                return series.apply(
                    lambda x: mask_string(str(x), 3, 4) if pd.notna(x) else x
                )
            elif data_type == "id_card":
                return series.apply(
                    lambda x: mask_string(str(x), 6, 4) if pd.notna(x) else x
                )
            elif data_type == "bank_card":
                return series.apply(
                    lambda x: mask_string(str(x), 4, 4) if pd.notna(x) else x
                )
            elif data_type == "email":
                return series.apply(
                    lambda x: self._mask_email(str(x)) if pd.notna(x) else x
                )
            else:
                rule = self.masking_rules.get("medium", {})
                visible_start = rule.get("visible_start", 3)
                visible_end = rule.get("visible_end", 4)
                return series.apply(
                    lambda x: mask_string(str(x), visible_start, visible_end)
                    if pd.notna(x)
                    else x
                )

        elif masking_method == "hash_mask":
            return series.apply(
                lambda x: hash_value(str(x)) if pd.notna(x) else x
            )

        elif masking_method == "replace":
            replace_values = {
                "phone": "138****0000",
                "id_card": "110101********1234",
                "email": "****@example.com",
                "bank_card": "6222 **** **** 1234",
                "address": "***省***市***区",
            }
            replace_val = replace_values.get(data_type, "***")
            return series.apply(lambda x: replace_val if pd.notna(x) else x)

        else:
            return series

    @staticmethod
    def _mask_email(email: str) -> str:
        if "@" not in email:
            return mask_string(email, 2, 2)
        username, domain = email.split("@", 1)
        masked_username = mask_string(username, 2, 0)
        return f"{masked_username}@{domain}"

    def _save_sensitive_records(
        self, system_code: str, sensitive_data_list: List[SensitiveData]
    ):
        try:
            for sd in sensitive_data_list:
                record = {
                    "system_code": sd.system_code,
                    "table_name": sd.table_name,
                    "field_name": sd.field_name,
                    "data_type": sd.data_type,
                    "sensitivity_level": sd.sensitivity_level,
                    "record_count": sd.record_count,
                    "masked_count": sd.masked_count,
                    "masking_method": sd.masking_method,
                    "scan_date": sd.scan_date.isoformat(),
                }

                existing = self.db.execute_query(
                    """SELECT id FROM sensitive_data_records 
                       WHERE system_code = ? AND table_name = ? AND field_name = ? 
                       AND data_type = ? AND scan_date = ?""",
                    (
                        sd.system_code,
                        sd.table_name,
                        sd.field_name,
                        sd.data_type,
                        sd.scan_date.isoformat(),
                    ),
                )

                if existing:
                    self.db.update_record(
                        "sensitive_data_records",
                        record,
                        "id = ?",
                        (existing[0]["id"],),
                    )
                else:
                    self.db.insert_record("sensitive_data_records", record)

        except Exception as e:
            self.logger.error(f"保存敏感数据记录失败: {e}", exc_info=True)

    def get_masking_coverage(
        self,
        system_code: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        query = "SELECT * FROM sensitive_data_records WHERE 1=1"
        params = []

        if system_code:
            query += " AND system_code = ?"
            params.append(system_code)
        if start_date:
            query += " AND scan_date >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND scan_date <= ?"
            params.append(end_date.isoformat())

        records = self.db.execute_query(query, tuple(params))

        total_sensitive = sum(r["record_count"] for r in records)
        total_masked = sum(r["masked_count"] for r in records)

        coverage = (total_masked / total_sensitive * 100) if total_sensitive > 0 else 100.0

        by_level = {}
        for r in records:
            level = r["sensitivity_level"]
            if level not in by_level:
                by_level[level] = {"total": 0, "masked": 0}
            by_level[level]["total"] += r["record_count"]
            by_level[level]["masked"] += r["masked_count"]

        return {
            "total_sensitive_records": total_sensitive,
            "total_masked_records": total_masked,
            "masking_coverage": round(coverage, 2),
            "by_sensitivity_level": by_level,
            "record_count": len(records),
        }

    def get_access_anomalies(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        anomalies = []

        query = "SELECT * FROM operation_logs WHERE operation_type = 'data_masking'"
        params = []

        if start_date:
            query += " AND DATE(created_at) >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND DATE(created_at) <= ?"
            params.append(end_date.isoformat())

        query += " ORDER BY created_at DESC"
        logs = self.db.execute_query(query, tuple(params))

        for log in logs:
            try:
                details = json.loads(log["details"])
            except (json.JSONDecodeError, TypeError):
                details = {}

            if details.get("total_records_masked", 0) == 0 and details.get(
                "sensitive_fields_count", 0
            ) > 0:
                anomalies.append(
                    {
                        "log_id": log["log_id"],
                        "system_code": log["system_code"],
                        "operator": log["operator"],
                        "created_at": log["created_at"],
                        "anomaly_type": "未脱敏访问",
                        "description": "访问了敏感数据但未执行脱敏",
                        "details": details,
                    }
                )

        return anomalies

    def validate_masking_config(self) -> Dict[str, Any]:
        issues = []

        for data_type, pattern_config in self.patterns.items():
            if "pattern" not in pattern_config and "keywords" not in pattern_config:
                issues.append(
                    f"敏感数据类型 {data_type} 缺少匹配规则（pattern或keywords）"
                )
            if "level" not in pattern_config:
                issues.append(f"敏感数据类型 {data_type} 缺少敏感度级别配置")

        for level in ["high", "medium", "low"]:
            if level not in self.masking_rules:
                issues.append(f"缺少敏感度级别 {level} 的脱敏规则配置")
            else:
                method = self.masking_rules[level].get("method")
                if method not in self.MASKING_METHODS:
                    issues.append(
                        f"敏感度级别 {level} 的脱敏方法 {method} 无效，"
                        f"有效方法: {self.MASKING_METHODS}"
                    )

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "configured_types": list(self.patterns.keys()),
            "configured_levels": list(self.masking_rules.keys()),
            "configured_depts": list(self.dept_permissions.keys()),
        }
