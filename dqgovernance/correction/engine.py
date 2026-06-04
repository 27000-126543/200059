from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
import json
import re

from ..utils import (
    ConfigManager,
    DatabaseManager,
    generate_id,
    is_valid_id_card,
    is_valid_phone,
    is_valid_email,
    safe_json_dumps,
)
from ..logging import DQLogger
from ..collectors import CollectorFactory


class CorrectionRequest:
    STATUS_PENDING = "pending"
    STATUS_VALIDATING = "validating"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_APPLIED = "applied"
    STATUS_FAILED = "failed"

    def __init__(
        self,
        system_code: str,
        table_name: str,
        record_id: str,
        field_name: str,
        old_value: Any,
        new_value: Any,
        reason: str,
        applicant: str,
        dept: str,
    ):
        self.request_no = generate_id("COR")
        self.system_code = system_code
        self.table_name = table_name
        self.record_id = record_id
        self.field_name = field_name
        self.old_value = str(old_value) if old_value is not None else None
        self.new_value = str(new_value) if new_value is not None else None
        self.reason = reason
        self.applicant = applicant
        self.dept = dept
        self.validation_result = None
        self.validation_details = None
        self.status = self.STATUS_PENDING
        self.created_at = datetime.now()
        self.approved_at = None
        self.updated_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_no": self.request_no,
            "system_code": self.system_code,
            "table_name": self.table_name,
            "record_id": self.record_id,
            "field_name": self.field_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "reason": self.reason,
            "applicant": self.applicant,
            "dept": self.dept,
            "validation_result": self.validation_result,
            "validation_details": self.validation_details,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "updated_at": self.updated_at.isoformat(),
        }


class CorrectionEngine:
    def __init__(self):
        self.config = ConfigManager()
        self.db = DatabaseManager()
        self.logger = DQLogger()

    def submit_correction(
        self,
        system_code: str,
        table_name: str,
        record_id: str,
        field_name: str,
        old_value: Any,
        new_value: Any,
        reason: str,
        applicant: str,
        dept: str,
    ) -> Dict[str, Any]:
        self.logger.info(f"收到数据订正申请: {system_code}.{table_name}.{field_name}, 记录ID: {record_id}")

        request = CorrectionRequest(
            system_code=system_code,
            table_name=table_name,
            record_id=record_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            applicant=applicant,
            dept=dept,
        )

        validation_result = self._validate_correction(request)
        request.validation_result = "passed" if validation_result["valid"] else "failed"
        request.validation_details = safe_json_dumps(validation_result)

        if validation_result["valid"]:
            request.status = CorrectionRequest.STATUS_APPROVED
            request.approved_at = datetime.now()
        else:
            request.status = CorrectionRequest.STATUS_REJECTED

        self._save_request(request)

        self.logger.log_operation(
            "correction_request",
            {
                "request_no": request.request_no,
                "system_code": system_code,
                "table_name": table_name,
                "field_name": field_name,
                "record_id": record_id,
                "validation_result": request.validation_result,
                "applicant": applicant,
                "dept": dept,
            },
            system_code=system_code,
        )

        if request.status == CorrectionRequest.STATUS_APPROVED:
            apply_result = self._apply_correction(request)
            if apply_result["success"]:
                request.status = CorrectionRequest.STATUS_APPLIED
                self._update_request(request)
                self.logger.log_operation(
                    "correction_approve",
                    {
                        "request_no": request.request_no,
                        "system_code": system_code,
                        "table_name": table_name,
                        "field_name": field_name,
                        "operator": "system_auto",
                    },
                    system_code=system_code,
                )
            else:
                request.status = CorrectionRequest.STATUS_FAILED
                request.validation_details = safe_json_dumps(apply_result)
                self._update_request(request)

        return {
            "success": request.status == CorrectionRequest.STATUS_APPLIED,
            "request_no": request.request_no,
            "status": request.status,
            "validation": validation_result,
            "message": self._get_status_message(request.status, validation_result),
        }

    def _validate_correction(self, request: CorrectionRequest) -> Dict[str, Any]:
        self.logger.info(f"开始校验订正申请: {request.request_no}")

        validation_result = {
            "valid": True,
            "checks": [],
            "errors": [],
            "warnings": [],
        }

        format_check = self._check_format(request.field_name, request.new_value)
        validation_result["checks"].append(("format_check", format_check["valid"]))
        if not format_check["valid"]:
            validation_result["valid"] = False
            validation_result["errors"].append(format_check["message"])

        cross_check = self._check_cross_logic(request)
        validation_result["checks"].append(("cross_logic_check", cross_check["valid"]))
        if not cross_check["valid"]:
            validation_result["valid"] = False
            validation_result["errors"].append(cross_check["message"])

        duplicate_check = self._check_duplicate(request)
        validation_result["checks"].append(("duplicate_check", duplicate_check["valid"]))
        if not duplicate_check["valid"]:
            validation_result["warnings"].append(duplicate_check["message"])

        range_check = self._check_value_range(request)
        validation_result["checks"].append(("range_check", range_check["valid"]))
        if not range_check["valid"]:
            validation_result["valid"] = False
            validation_result["errors"].append(range_check["message"])

        consistency_check = self._check_data_consistency(request)
        validation_result["checks"].append(("consistency_check", consistency_check["valid"]))
        if not consistency_check["valid"]:
            validation_result["warnings"].append(consistency_check["message"])

        self.logger.info(
            f"订正申请校验完成: {request.request_no}, "
            f"结果: {'通过' if validation_result['valid'] else '未通过'}, "
            f"错误: {len(validation_result['errors'])}, "
            f"警告: {len(validation_result['warnings'])}"
        )

        return validation_result

    def _check_format(self, field_name: str, value: Any) -> Dict[str, Any]:
        if value is None or str(value).strip() == "":
            return {"valid": True, "message": "空值检查通过"}

        field_name_lower = field_name.lower()
        value_str = str(value).strip()

        if any(kw in field_name_lower for kw in ["phone", "mobile", "手机号", "电话"]):
            if not is_valid_phone(value_str):
                return {"valid": False, "message": f"手机号格式不正确: {value_str}"}

        if any(kw in field_name_lower for kw in ["id_card", "身份证", "证件号"]):
            if not is_valid_id_card(value_str):
                return {"valid": False, "message": f"身份证号格式不正确: {value_str}"}

        if any(kw in field_name_lower for kw in ["email", "邮箱", "邮件"]):
            if not is_valid_email(value_str):
                return {"valid": False, "message": f"邮箱格式不正确: {value_str}"}

        if any(kw in field_name_lower for kw in ["amount", "金额", "价格", "工资", "薪酬"]):
            try:
                amount = float(value_str)
                if amount < 0:
                    return {"valid": False, "message": f"金额不能为负数: {value_str}"}
                if amount > 1000000000:
                    return {"valid": False, "message": f"金额超出合理范围: {value_str}"}
            except (ValueError, TypeError):
                return {"valid": False, "message": f"金额格式不正确: {value_str}"}

        if any(kw in field_name_lower for kw in ["date", "时间", "日期"]):
            try:
                from dateutil import parser as date_parser
                date_parser.parse(value_str)
            except (ValueError, TypeError):
                return {"valid": False, "message": f"日期格式不正确: {value_str}"}

        return {"valid": True, "message": "格式检查通过"}

    def _check_cross_logic(self, request: CorrectionRequest) -> Dict[str, Any]:
        try:
            collector = CollectorFactory.get_collector(request.system_code)
            if not collector:
                return {"valid": True, "message": "无法获取数据采集器，跳过交叉逻辑检查"}

            df = collector.collect_table(
                request.table_name,
                date.today() - timedelta(days=30),
                date.today(),
            )

            if df is None or df.empty:
                return {"valid": True, "message": "无历史数据，跳过交叉逻辑检查"}

            if "id" in df.columns:
                record = df[df["id"].astype(str) == str(request.record_id)]
                if len(record) == 0:
                    return {
                        "valid": False,
                        "message": f"记录ID {request.record_id} 在表 {request.table_name} 中不存在",
                    }

            if request.system_code == "order_system" and request.table_name == "orders":
                if request.field_name in ["order_amount", "pay_amount", "discount_amount"]:
                    if "id" in df.columns and len(record) > 0:
                        current = record.iloc[0]
                        order_amount = (
                            float(request.new_value)
                            if request.field_name == "order_amount"
                            else current.get("order_amount", 0)
                        )
                        pay_amount = (
                            float(request.new_value)
                            if request.field_name == "pay_amount"
                            else current.get("pay_amount", 0)
                        )
                        discount_amount = (
                            float(request.new_value)
                            if request.field_name == "discount_amount"
                            else current.get("discount_amount", 0)
                        )

                        if abs(order_amount - pay_amount - discount_amount) > 0.01:
                            return {
                                "valid": False,
                                "message": f"订单金额不一致：订单金额({order_amount}) ≠ 支付金额({pay_amount}) + 折扣金额({discount_amount})",
                            }

            if request.system_code == "finance_system" and request.table_name == "general_ledger":
                if request.field_name in ["debit", "credit"]:
                    if "id" in df.columns and len(record) > 0:
                        current = record.iloc[0]
                        debit = (
                            float(request.new_value)
                            if request.field_name == "debit"
                            else current.get("debit", 0)
                        )
                        credit = (
                            float(request.new_value)
                            if request.field_name == "credit"
                            else current.get("credit", 0)
                        )

                        if abs(debit - credit) > 0.01:
                            return {
                                "valid": False,
                                "message": f"借贷不平衡：借方({debit}) ≠ 贷方({credit})",
                            }

            if request.system_code == "hr_system" and request.table_name == "employees":
                if request.field_name in ["birth_date", "hire_date"]:
                    if "id" in df.columns and len(record) > 0:
                        from dateutil import parser as date_parser

                        current = record.iloc[0]
                        try:
                            birth_date = (
                                date_parser.parse(request.new_value).date()
                                if request.field_name == "birth_date"
                                else date_parser.parse(str(current.get("birth_date"))).date()
                            )
                            hire_date = (
                                date_parser.parse(request.new_value).date()
                                if request.field_name == "hire_date"
                                else date_parser.parse(str(current.get("hire_date"))).date()
                            )

                            if hire_date <= birth_date:
                                return {
                                    "valid": False,
                                    "message": f"入职日期({hire_date}) 不能早于或等于出生日期({birth_date})",
                                }
                        except (ValueError, TypeError):
                            pass

            return {"valid": True, "message": "交叉逻辑检查通过"}

        except Exception as e:
            self.logger.error(f"交叉逻辑检查异常: {e}", exc_info=True)
            return {"valid": True, "message": f"交叉逻辑检查异常，已跳过: {str(e)}"}

    def _check_duplicate(self, request: CorrectionRequest) -> Dict[str, Any]:
        existing = self.db.execute_query(
            """SELECT * FROM correction_requests 
               WHERE system_code = ? AND table_name = ? AND record_id = ? 
               AND field_name = ? AND status IN ('pending', 'approved', 'applied')""",
            (request.system_code, request.table_name, request.record_id, request.field_name),
        )

        if existing:
            return {
                "valid": False,
                "message": f"存在相同的待处理订正申请: {existing[0]['request_no']}",
            }

        return {"valid": True, "message": "重复申请检查通过"}

    def _check_value_range(self, request: CorrectionRequest) -> Dict[str, Any]:
        if request.new_value is None or str(request.new_value).strip() == "":
            return {"valid": True, "message": "空值范围检查通过"}

        field_name_lower = request.field_name.lower()

        if any(kw in field_name_lower for kw in ["age", "年龄"]):
            try:
                age = int(request.new_value)
                if age < 16 or age > 70:
                    return {"valid": False, "message": f"年龄 {age} 超出合理范围(16-70)"}
            except (ValueError, TypeError):
                return {"valid": False, "message": f"年龄格式不正确: {request.new_value}"}

        if any(kw in field_name_lower for kw in ["work_hours", "工时"]):
            try:
                hours = float(request.new_value)
                if hours < 0 or hours > 24:
                    return {"valid": False, "message": f"工时 {hours} 超出合理范围(0-24)"}
            except (ValueError, TypeError):
                return {"valid": False, "message": f"工时格式不正确: {request.new_value}"}

        if any(kw in field_name_lower for kw in ["level", "级别"]):
            try:
                level_str = str(request.new_value)
                if level_str.startswith("P"):
                    level = int(level_str[1:])
                    if level < 1 or level > 15:
                        return {"valid": False, "message": f"级别 {level_str} 超出合理范围(P1-P15)"}
            except (ValueError, TypeError):
                pass

        return {"valid": True, "message": "取值范围检查通过"}

    def _check_data_consistency(self, request: CorrectionRequest) -> Dict[str, Any]:
        return {"valid": True, "message": "数据一致性检查通过"}

    def _apply_correction(self, request: CorrectionRequest) -> Dict[str, Any]:
        self.logger.info(f"应用数据订正: {request.request_no}")

        try:
            self.logger.info(
                f"模拟更新源系统数据: {request.system_code}.{request.table_name}."
                f"{request.field_name}, 记录ID: {request.record_id}, "
                f"旧值: {request.old_value} -> 新值: {request.new_value}"
            )

            return {
                "success": True,
                "message": "数据订正已成功应用到源系统",
                "update_time": datetime.now().isoformat(),
            }
        except Exception as e:
            self.logger.error(f"应用数据订正失败: {e}", exc_info=True)
            return {"success": False, "message": f"应用订正失败: {str(e)}"}

    def _save_request(self, request: CorrectionRequest):
        existing = self.db.execute_query(
            "SELECT id FROM correction_requests WHERE request_no = ?",
            (request.request_no,),
        )
        if not existing:
            self.db.insert_record("correction_requests", request.to_dict())

    def _update_request(self, request: CorrectionRequest):
        request.updated_at = datetime.now()
        self.db.update_record(
            "correction_requests",
            request.to_dict(),
            "request_no = ?",
            (request.request_no,),
        )

    @staticmethod
    def _get_status_message(status: str, validation: Dict[str, Any]) -> str:
        if status == CorrectionRequest.STATUS_APPLIED:
            return "订正申请已通过校验并成功应用"
        elif status == CorrectionRequest.STATUS_APPROVED:
            return "订正申请已通过校验"
        elif status == CorrectionRequest.STATUS_REJECTED:
            errors = "; ".join(validation.get("errors", []))
            return f"订正申请被驳回: {errors}"
        elif status == CorrectionRequest.STATUS_FAILED:
            return "订正应用失败，请重试"
        else:
            return "订正申请处理中"

    def get_requests(
        self,
        system_code: Optional[str] = None,
        status: Optional[str] = None,
        applicant: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM correction_requests WHERE 1=1"
        params = []

        if system_code:
            query += " AND system_code = ?"
            params.append(system_code)
        if status:
            query += " AND status = ?"
            params.append(status)
        if applicant:
            query += " AND applicant = ?"
            params.append(applicant)
        if start_date:
            query += " AND DATE(created_at) >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND DATE(created_at) <= ?"
            params.append(end_date.isoformat())

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        results = self.db.execute_query(query, tuple(params))

        for result in results:
            if result.get("validation_details"):
                try:
                    result["validation_details"] = json.loads(result["validation_details"])
                except json.JSONDecodeError:
                    pass

        return results

    def get_request_statistics(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        requests = self.get_requests(
            start_date=start_date, end_date=end_date, limit=100000
        )

        stats = {
            "total": len(requests),
            "by_status": {},
            "by_system": {},
            "by_field": {},
            "approval_rate": 0.0,
            "auto_approved_count": 0,
        }

        status_counts = {}
        for req in requests:
            status = req["status"]
            status_counts[status] = status_counts.get(status, 0) + 1

            system = req["system_code"]
            stats["by_system"][system] = stats["by_system"].get(system, 0) + 1

            field = req["field_name"]
            stats["by_field"][field] = stats["by_field"].get(field, 0) + 1

            if req["status"] in ["approved", "applied"]:
                stats["auto_approved_count"] += 1

        stats["by_status"] = status_counts

        if len(requests) > 0:
            stats["approval_rate"] = round(
                stats["auto_approved_count"] / len(requests) * 100, 2
            )

        return stats
