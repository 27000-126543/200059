from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional, Tuple
import json

from ..utils import (
    ConfigManager,
    DatabaseManager,
    generate_id,
    calculate_priority,
    calculate_sla_hours,
    get_severity_weight,
)
from ..logging import DQLogger
from ..quality import QualityIssue, QualityRuleEngine
from ..collectors import CollectorFactory


class GovernanceTicket:
    STATUS_PENDING = "pending"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_RESOLVED = "resolved"
    STATUS_VERIFIED = "verified"
    STATUS_CLOSED = "closed"
    STATUS_REOPENED = "reopened"

    PRIORITY_P0 = "P0"
    PRIORITY_P1 = "P1"
    PRIORITY_P2 = "P2"
    PRIORITY_P3 = "P3"
    PRIORITY_P4 = "P4"

    def __init__(
        self,
        system_code: str,
        title: str,
        description: str,
        severity: str,
        issue_id: Optional[int] = None,
        data_domain: Optional[str] = None,
        priority: Optional[str] = None,
        assignee: Optional[str] = None,
        dept: Optional[str] = None,
        sla_hours: Optional[int] = None,
        affected_records: int = 0,
        business_impact: float = 0.0,
    ):
        self.ticket_no = generate_id("TKT")
        self.system_code = system_code
        self.issue_id = issue_id
        self.data_domain = data_domain
        self.title = title
        self.description = description
        self.severity = severity
        self.affected_records = affected_records
        self.business_impact = business_impact
        self.priority = priority or calculate_priority(severity, affected_records, business_impact)
        self.assignee = assignee
        self.dept = dept
        self.sla_hours = sla_hours or calculate_sla_hours(severity)
        self.status = self.STATUS_PENDING
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.resolved_at = None
        self.resolution = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticket_no": self.ticket_no,
            "issue_id": self.issue_id,
            "system_code": self.system_code,
            "data_domain": self.data_domain,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "priority": self.priority,
            "assignee": self.assignee,
            "dept": self.dept,
            "sla_hours": self.sla_hours,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution": self.resolution,
        }


class TicketEngine:
    def __init__(self):
        self.config = ConfigManager()
        self.db = DatabaseManager()
        self.logger = DQLogger()
        self.quality_engine = QualityRuleEngine()
        self.ticket_config = self.config.get("ticket_system", {})
        self.assignees = self.ticket_config.get("assignees", {})
        self.priority_rules = self.ticket_config.get("priority_rules", {})

    def create_tickets_from_issues(
        self,
        system_code: str,
        issues: List[QualityIssue],
        auto_assign: bool = True,
    ) -> List[GovernanceTicket]:
        self.logger.info(f"开始为 {system_code} 创建治理工单，问题数: {len(issues)}")

        tickets = []
        for issue in issues:
            if not self._should_create_ticket(issue):
                continue

            ticket = self._create_ticket_from_issue(system_code, issue, auto_assign)
            if ticket:
                tickets.append(ticket)
                self._save_ticket(ticket)

                self.logger.log_operation(
                    "ticket_create",
                    {
                        "ticket_no": ticket.ticket_no,
                        "issue_code": issue.issue_code,
                        "severity": issue.severity,
                        "priority": ticket.priority,
                        "assignee": ticket.assignee,
                        "sla_hours": ticket.sla_hours,
                    },
                    system_code=system_code,
                    data_domain=ticket.data_domain,
                )

        self.logger.info(f"完成创建治理工单，共 {len(tickets)} 张")
        return tickets

    def _should_create_ticket(self, issue: QualityIssue) -> bool:
        if issue.severity in ["critical", "high"]:
            return True
        if issue.severity == "medium" and issue.affected_records > 100:
            return True
        if issue.severity == "low" and issue.affected_records > 1000:
            return True
        return False

    def _create_ticket_from_issue(
        self,
        system_code: str,
        issue: QualityIssue,
        auto_assign: bool,
    ) -> Optional[GovernanceTicket]:
        system_config = self.config.get(f"business_systems.{system_code}", {})
        data_domain = system_config.get("data_domain", "未知域")
        dept = system_config.get("dept", "")

        title = self._generate_ticket_title(issue)
        description = self._generate_ticket_description(issue)

        assignee = None
        if auto_assign:
            assignee = self._get_assignee(data_domain, issue.severity)

        business_impact = self._calculate_business_impact(issue, data_domain)

        ticket = GovernanceTicket(
            system_code=system_code,
            title=title,
            description=description,
            severity=issue.severity,
            data_domain=data_domain,
            assignee=assignee,
            dept=dept,
            affected_records=issue.affected_records,
            business_impact=business_impact,
        )

        return ticket

    def _generate_ticket_title(self, issue: QualityIssue) -> str:
        type_names = {
            "completeness": "数据完整性",
            "consistency": "数据一致性",
            "timeliness": "数据时效性",
        }
        type_name = type_names.get(issue.issue_type, issue.issue_type)
        return f"[{issue.severity.upper()}] {type_name}问题 - {issue.system_code}.{issue.table_name}"

    def _generate_ticket_description(self, issue: QualityIssue) -> str:
        desc_parts = [
            f"问题类型: {issue.issue_type}",
            f"严重等级: {issue.severity}",
            f"系统/表: {issue.system_code}.{issue.table_name}",
        ]
        if issue.field_name:
            desc_parts.append(f"字段: {issue.field_name}")
        if issue.rule_name:
            desc_parts.append(f"规则: {issue.rule_name}")
        desc_parts.append(f"影响记录数: {issue.affected_records}")
        desc_parts.append(f"问题描述: {issue.description}")
        if issue.sample_data:
            desc_parts.append(f"示例数据ID: {issue.sample_data[:10]}")

        return "\n".join(desc_parts)

    def _get_assignee(self, data_domain: str, severity: str) -> str:
        if severity == "critical" and data_domain in self.assignees:
            return self.assignees[data_domain]
        elif data_domain in self.assignees:
            return self.assignees[data_domain]

        escalation_map = {
            "critical": 3,
            "high": 2,
            "medium": 1,
            "low": 0,
        }
        escalation_level = escalation_map.get(severity, 0)

        if escalation_level >= 3:
            managers = self.config.get("governance.project_managers", [])
            return managers[0] if managers else "未分配"
        elif escalation_level >= 2:
            return self.assignees.get(data_domain, "未分配")
        else:
            return self.assignees.get(data_domain, "未分配")

    def _calculate_business_impact(
        self, issue: QualityIssue, data_domain: str
    ) -> float:
        domain_weight = {
            "交易域": 1.0,
            "财务域": 0.9,
            "人事域": 0.6,
        }
        severity_weight = get_severity_weight(issue.severity) / 100
        volume_weight = min(issue.affected_records / 10000, 1.0)
        domain_weight_val = domain_weight.get(data_domain, 0.5)

        return (severity_weight * 0.5 + volume_weight * 0.3 + domain_weight_val * 0.2)

    def _save_ticket(self, ticket: GovernanceTicket):
        existing = self.db.execute_query(
            "SELECT id FROM governance_tickets WHERE ticket_no = ?",
            (ticket.ticket_no,),
        )
        if not existing:
            self.db.insert_record("governance_tickets", ticket.to_dict())

    def update_ticket_status(
        self,
        ticket_no: str,
        status: str,
        operator: str = "system",
        resolution: Optional[str] = None,
    ) -> bool:
        valid_statuses = [
            GovernanceTicket.STATUS_PENDING,
            GovernanceTicket.STATUS_IN_PROGRESS,
            GovernanceTicket.STATUS_RESOLVED,
            GovernanceTicket.STATUS_VERIFIED,
            GovernanceTicket.STATUS_CLOSED,
            GovernanceTicket.STATUS_REOPENED,
        ]

        if status not in valid_statuses:
            self.logger.error(f"无效的工单状态: {status}")
            return False

        update_data = {
            "status": status,
            "updated_at": datetime.now().isoformat(),
        }

        if status == GovernanceTicket.STATUS_RESOLVED:
            update_data["resolved_at"] = datetime.now().isoformat()
            if resolution:
                update_data["resolution"] = resolution

        try:
            self.db.update_record(
                "governance_tickets",
                update_data,
                "ticket_no = ?",
                (ticket_no,),
            )

            self.logger.log_operation(
                "ticket_update",
                {
                    "ticket_no": ticket_no,
                    "new_status": status,
                    "operator": operator,
                    "resolution": resolution,
                },
            )

            if status == GovernanceTicket.STATUS_RESOLVED:
                self.logger.info(f"工单 {ticket_no} 已标记为已解决，等待自动复检")

            return True
        except Exception as e:
            self.logger.error(f"更新工单状态失败: {e}", exc_info=True)
            return False

    def recheck_ticket(self, ticket_no: str) -> Dict[str, Any]:
        self.logger.info(f"开始复检工单: {ticket_no}")

        ticket = self.db.execute_query(
            "SELECT * FROM governance_tickets WHERE ticket_no = ?",
            (ticket_no,),
        )
        if not ticket:
            return {"success": False, "message": "工单不存在"}

        ticket = ticket[0]
        if ticket["status"] != GovernanceTicket.STATUS_RESOLVED:
            return {"success": False, "message": "工单未处于已解决状态，无需复检"}

        issue = self.db.execute_query(
            "SELECT * FROM quality_issues WHERE id = ?",
            (ticket["issue_id"],),
        )
        if not issue:
            return {"success": False, "message": "关联的质量问题不存在"}

        issue = issue[0]

        try:
            collector = CollectorFactory.get_collector(ticket["system_code"])
            if not collector:
                return {"success": False, "message": "数据采集器不存在"}

            table_name = issue["table_name"]
            scan_date = date.today()
            df = collector.collect_table(
                table_name, scan_date - timedelta(days=1), scan_date
            )

            if df is None or df.empty:
                return {
                    "success": False,
                    "message": "无最新数据可用于复检",
                    "data_available": False,
                }

            field_name = issue["field_name"]
            issue_type = issue["issue_type"]
            remaining_issues = 0

            if issue_type == "completeness" and field_name:
                null_count = df[field_name].isnull().sum()
                empty_count = (
                    df[field_name].astype(str).str.strip().eq("").sum()
                    if df[field_name].dtype == object
                    else 0
                )
                remaining_issues = null_count + empty_count

            elif issue_type == "consistency":
                if table_name == "orders" and "order_amount" in df.columns:
                    invalid_mask = (
                        df["order_amount"] - df["pay_amount"] - df.get("discount_amount", 0)
                    ).abs() > 0.01
                    remaining_issues = invalid_mask.sum()
                elif table_name == "general_ledger" and "debit" in df.columns:
                    invalid_mask = (df["debit"] - df["credit"]).abs() > 0.01
                    remaining_issues = invalid_mask.sum()

            elif issue_type == "timeliness":
                if "updated_at" in df.columns:
                    now = datetime.now()
                    df["updated_at_dt"] = pd.to_datetime(df["updated_at"])
                    latest_update = df["updated_at_dt"].max()
                    delay_hours = (now - latest_update).total_seconds() / 3600
                    remaining_issues = 0 if delay_hours <= 24 else len(df)

            passed = remaining_issues == 0

            if passed:
                self.db.update_record(
                    "quality_issues",
                    {"status": "resolved", "updated_at": datetime.now().isoformat()},
                    "id = ?",
                    (ticket["issue_id"],),
                )

                self.update_ticket_status(
                    ticket_no,
                    GovernanceTicket.STATUS_VERIFIED,
                    operator="system_auto_check",
                    resolution=f"自动复检通过，剩余问题数: {remaining_issues}",
                )

                self.logger.log_operation(
                    "ticket_resolve",
                    {
                        "ticket_no": ticket_no,
                        "recheck_result": "passed",
                        "remaining_issues": remaining_issues,
                    },
                )
            else:
                self.update_ticket_status(
                    ticket_no,
                    GovernanceTicket.STATUS_REOPENED,
                    operator="system_auto_check",
                    resolution=f"自动复检未通过，仍存在 {remaining_issues} 条问题记录",
                )

                self.db.update_record(
                    "quality_issues",
                    {"status": "open", "updated_at": datetime.now().isoformat()},
                    "id = ?",
                    (ticket["issue_id"],),
                )

            return {
                "success": True,
                "passed": passed,
                "remaining_issues": remaining_issues,
                "total_records": len(df),
                "ticket_no": ticket_no,
                "message": "复检通过" if passed else "复检未通过，工单已重新打开",
            }

        except Exception as e:
            self.logger.error(f"复检工单失败: {e}", exc_info=True)
            return {"success": False, "message": f"复检异常: {str(e)}"}

    def get_tickets(
        self,
        system_code: Optional[str] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        priority: Optional[str] = None,
        assignee: Optional[str] = None,
        data_domain: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM governance_tickets WHERE 1=1"
        params = []

        if system_code:
            query += " AND system_code = ?"
            params.append(system_code)
        if status:
            query += " AND status = ?"
            params.append(status)
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        if priority:
            query += " AND priority = ?"
            params.append(priority)
        if assignee:
            query += " AND assignee = ?"
            params.append(assignee)
        if data_domain:
            query += " AND data_domain = ?"
            params.append(data_domain)
        if start_date:
            query += " AND DATE(created_at) >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND DATE(created_at) <= ?"
            params.append(end_date.isoformat())

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        return self.db.execute_query(query, tuple(params))

    def get_ticket_statistics(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        query = "SELECT * FROM governance_tickets WHERE 1=1"
        params = []

        if start_date:
            query += " AND DATE(created_at) >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND DATE(created_at) <= ?"
            params.append(end_date.isoformat())

        tickets = self.db.execute_query(query, tuple(params))

        stats = {
            "total": len(tickets),
            "by_status": {},
            "by_severity": {},
            "by_priority": {},
            "by_system": {},
            "by_domain": {},
            "resolution_rate": 0.0,
            "avg_resolution_hours": 0.0,
            "sla_breach_count": 0,
        }

        resolved_tickets = []
        for t in tickets:
            status = t["status"]
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1

            severity = t["severity"]
            stats["by_severity"][severity] = stats["by_severity"].get(severity, 0) + 1

            priority = t["priority"]
            stats["by_priority"][priority] = stats["by_priority"].get(priority, 0) + 1

            system = t["system_code"]
            stats["by_system"][system] = stats["by_system"].get(system, 0) + 1

            domain = t["data_domain"] or "未知域"
            stats["by_domain"][domain] = stats["by_domain"].get(domain, 0) + 1

            if t["status"] in [
                GovernanceTicket.STATUS_VERIFIED,
                GovernanceTicket.STATUS_CLOSED,
                GovernanceTicket.STATUS_RESOLVED,
            ]:
                resolved_tickets.append(t)

            if t["created_at"] and t["sla_hours"]:
                try:
                    created = datetime.fromisoformat(t["created_at"])
                    now = datetime.now()
                    hours_since_creation = (now - created).total_seconds() / 3600
                    if hours_since_creation > t["sla_hours"] and t["status"] in [
                        GovernanceTicket.STATUS_PENDING,
                        GovernanceTicket.STATUS_IN_PROGRESS,
                    ]:
                        stats["sla_breach_count"] += 1
                except (ValueError, TypeError):
                    pass

        if len(tickets) > 0:
            stats["resolution_rate"] = round(
                len(resolved_tickets) / len(tickets) * 100, 2
            )

        resolution_times = []
        for t in resolved_tickets:
            if t["created_at"] and t["resolved_at"]:
                try:
                    created = datetime.fromisoformat(t["created_at"])
                    resolved = datetime.fromisoformat(t["resolved_at"])
                    hours = (resolved - created).total_seconds() / 3600
                    resolution_times.append(hours)
                except (ValueError, TypeError):
                    pass

        if resolution_times:
            stats["avg_resolution_hours"] = round(sum(resolution_times) / len(resolution_times), 2)

        return stats

    def export_tickets(
        self,
        output_path: str,
        format: str = "csv",
        **query_kwargs,
    ) -> str:
        tickets = self.get_tickets(limit=100000, **query_kwargs)

        if not tickets:
            self.logger.warning("没有可导出的工单数据")
            return ""

        import csv

        if format.lower() == "csv":
            if not output_path.endswith(".csv"):
                output_path += ".csv"

            with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
                if tickets:
                    writer = csv.DictWriter(f, fieldnames=tickets[0].keys())
                    writer.writeheader()
                    writer.writerows(tickets)

        elif format.lower() == "excel":
            import pandas as pd

            if not output_path.endswith(".xlsx"):
                output_path += ".xlsx"
            df = pd.DataFrame(tickets)
            df.to_excel(output_path, index=False)

        elif format.lower() == "json":
            if not output_path.endswith(".json"):
                output_path += ".json"
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(tickets, f, ensure_ascii=False, indent=2, default=str)
        else:
            raise ValueError(f"不支持的导出格式: {format}")

        self.logger.info(f"工单已导出到: {output_path}, 共 {len(tickets)} 条记录")
        return output_path

    def auto_recheck_resolved_tickets(self) -> List[Dict[str, Any]]:
        self.logger.info("开始自动复检已解决的工单")

        resolved_tickets = self.get_tickets(
            status=GovernanceTicket.STATUS_RESOLVED,
            limit=100,
        )

        results = []
        for ticket in resolved_tickets:
            try:
                result = self.recheck_ticket(ticket["ticket_no"])
                results.append(result)
            except Exception as e:
                self.logger.error(
                    f"自动复检工单 {ticket['ticket_no']} 失败: {e}", exc_info=True
                )
                results.append(
                    {
                        "success": False,
                        "ticket_no": ticket["ticket_no"],
                        "message": str(e),
                    }
                )

        self.logger.info(
            f"自动复检完成，共处理 {len(resolved_tickets)} 张工单，"
            f"通过 {sum(1 for r in results if r.get('passed'))} 张"
        )

        return results
