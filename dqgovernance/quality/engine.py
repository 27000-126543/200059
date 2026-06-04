from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import numpy as np
import re
import json

from ..utils import (
    ConfigManager,
    DatabaseManager,
    generate_id,
    get_severity_weight,
    safe_eval,
    safe_json_dumps,
)
from ..logging import DQLogger


class QualityIssue:
    def __init__(
        self,
        issue_type: str,
        severity: str,
        description: str,
        system_code: str,
        table_name: str,
        field_name: Optional[str] = None,
        rule_name: Optional[str] = None,
        affected_records: int = 0,
        sample_data: Optional[List[Any]] = None,
    ):
        self.issue_code = generate_id("ISS")
        self.issue_type = issue_type
        self.severity = severity
        self.description = description
        self.system_code = system_code
        self.table_name = table_name
        self.field_name = field_name
        self.rule_name = rule_name
        self.affected_records = affected_records
        self.sample_data = sample_data or []
        self.scan_date = date.today()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_code": self.issue_code,
            "system_code": self.system_code,
            "table_name": self.table_name,
            "field_name": self.field_name,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "description": self.description,
            "rule_name": self.rule_name,
            "affected_records": self.affected_records,
            "sample_data": safe_json_dumps(self.sample_data) if self.sample_data else None,
            "scan_date": self.scan_date.isoformat(),
            "status": "open",
        }


class QualityScore:
    def __init__(
        self,
        system_code: str,
        table_name: str,
        completeness_score: float = 100.0,
        consistency_score: float = 100.0,
        timeliness_score: float = 100.0,
        total_records: int = 0,
        issue_count: int = 0,
    ):
        self.system_code = system_code
        self.table_name = table_name
        self.completeness_score = completeness_score
        self.consistency_score = consistency_score
        self.timeliness_score = timeliness_score
        self.total_records = total_records
        self.issue_count = issue_count
        self.scan_date = date.today()

        config = ConfigManager()
        self.weight_completeness = config.get("scoring.weight_completeness", 30) / 100
        self.weight_consistency = config.get("scoring.weight_consistency", 40) / 100
        self.weight_timeliness = config.get("scoring.weight_timeliness", 30) / 100

    @property
    def overall_score(self) -> float:
        return round(
            self.completeness_score * self.weight_completeness
            + self.consistency_score * self.weight_consistency
            + self.timeliness_score * self.weight_timeliness,
            2,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "system_code": self.system_code,
            "table_name": self.table_name,
            "completeness_score": self.completeness_score,
            "consistency_score": self.consistency_score,
            "timeliness_score": self.timeliness_score,
            "overall_score": self.overall_score,
            "scan_date": self.scan_date.isoformat(),
            "total_records": self.total_records,
            "issue_count": self.issue_count,
        }


class QualityRuleEngine:
    def __init__(self):
        self.config = ConfigManager()
        self.db = DatabaseManager()
        self.logger = DQLogger()
        self.rules = self.config.get("quality_rules", {})

    def scan_system(
        self,
        system_code: str,
        data: Dict[str, pd.DataFrame],
        scan_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        if scan_date is None:
            scan_date = date.today()

        self.logger.info(f"开始质量扫描: {system_code}, 扫描日期: {scan_date}")

        all_scores = []
        all_issues = []

        for table_name, df in data.items():
            score, issues = self.scan_table(
                system_code, table_name, df, scan_date
            )
            if score:
                all_scores.append(score)
            all_issues.extend(issues)

        overall_score = (
            round(sum(s.overall_score for s in all_scores) / len(all_scores), 2)
            if all_scores else 0
        )

        self.logger.log_operation(
            "quality_scan",
            {
                "system_code": system_code,
                "scan_date": scan_date.isoformat(),
                "tables_scanned": len(data),
                "total_issues": len(all_issues),
                "average_score": overall_score,
            },
            system_code=system_code,
        )

        return {
            "overall_score": overall_score,
            "scores": all_scores,
            "issues": all_issues,
        }

    def scan_table(
        self,
        system_code: str,
        table_name: str,
        df: pd.DataFrame,
        scan_date: Optional[date] = None,
    ) -> Tuple[Optional[QualityScore], List[QualityIssue]]:
        if scan_date is None:
            scan_date = date.today()

        if df is None or df.empty:
            self.logger.warning(f"表 {table_name} 无数据，跳过扫描")
            return None, []

        total_records = len(df)
        issues = []

        completeness_score, completeness_issues = self._check_completeness(
            system_code, table_name, df
        )
        issues.extend(completeness_issues)

        consistency_score, consistency_issues = self._check_consistency(
            system_code, table_name, df
        )
        issues.extend(consistency_issues)

        timeliness_score, timeliness_issues = self._check_timeliness(
            system_code, table_name, df, scan_date
        )
        issues.extend(timeliness_issues)

        score = QualityScore(
            system_code=system_code,
            table_name=table_name,
            completeness_score=completeness_score,
            consistency_score=consistency_score,
            timeliness_score=timeliness_score,
            total_records=total_records,
            issue_count=len(issues),
        )

        self._save_scan_results(score, issues)

        return score, issues

    def _check_completeness(
        self, system_code: str, table_name: str, df: pd.DataFrame
    ) -> Tuple[float, List[QualityIssue]]:
        issues = []
        total_fields = len(df.columns)
        field_scores = []

        completeness_rules = self.rules.get("completeness", {}).get("rules", [])

        for rule in completeness_rules:
            field_name = rule.get("field")
            if field_name not in df.columns:
                continue

            null_count = df[field_name].isnull().sum()
            empty_string_count = (
                df[field_name].astype(str).str.strip().eq("").sum()
                if df[field_name].dtype == object
                else 0
            )
            total_missing = null_count + empty_string_count

            if total_missing > 0:
                field_score = max(0, 100 - (total_missing / len(df) * 100))
                severity = rule.get("severity", "medium")
                weight = get_severity_weight(severity)
                weighted_score = field_score * (1 - weight / 200)

                sample_data = (
                    df[df[field_name].isnull()]["id"].head(5).tolist()
                    if "id" in df.columns
                    else df[df[field_name].isnull()].head(5).index.tolist()
                )

                issues.append(
                    QualityIssue(
                        issue_type="completeness",
                        severity=severity,
                        description=f"字段 {field_name} 存在 {total_missing} 条空值记录",
                        system_code=system_code,
                        table_name=table_name,
                        field_name=field_name,
                        rule_name=f"not_null_{field_name}",
                        affected_records=total_missing,
                        sample_data=sample_data,
                    )
                )
            else:
                weighted_score = 100.0

            field_scores.append(weighted_score)

        for column in df.columns:
            if column not in [r.get("field") for r in completeness_rules]:
                null_count = df[column].isnull().sum()
                if null_count > 0 and null_count / len(df) > 0.1:
                    field_score = max(0, 100 - (null_count / len(df) * 100))
                    severity = "low"
                    weight = get_severity_weight(severity)
                    weighted_score = field_score * (1 - weight / 200)
                    field_scores.append(weighted_score)

                    issues.append(
                        QualityIssue(
                            issue_type="completeness",
                            severity=severity,
                            description=f"字段 {column} 存在 {null_count} 条空值记录，占比 {null_count/len(df)*100:.2f}%",
                            system_code=system_code,
                            table_name=table_name,
                            field_name=column,
                            rule_name="auto_null_check",
                            affected_records=null_count,
                        )
                    )

        overall_score = (
            round(sum(field_scores) / len(field_scores), 2) if field_scores else 100.0
        )
        return overall_score, issues

    def _check_consistency(
        self, system_code: str, table_name: str, df: pd.DataFrame
    ) -> Tuple[float, List[QualityIssue]]:
        issues = []
        consistency_rules = self.rules.get("consistency", {}).get("rules", [])
        rule_scores = []

        for rule in consistency_rules:
            rule_name = rule.get("name", "")
            expression = rule.get("expression", "")
            severity = rule.get("severity", "high")

            if not expression:
                continue

            try:
                if table_name == "orders" and "order_amount" in df.columns and "pay_amount" in df.columns:
                    invalid_mask = (df["order_amount"] - df["pay_amount"] - df.get("discount_amount", 0)).abs() > 0.01
                    invalid_count = invalid_mask.sum()
                    if invalid_count > 0:
                        issues.append(
                            QualityIssue(
                                issue_type="consistency",
                                severity=severity,
                                description=f"订单金额不一致：{invalid_count} 条记录订单金额不等于支付金额加折扣金额",
                                system_code=system_code,
                                table_name=table_name,
                                field_name="order_amount,pay_amount",
                                rule_name="订单金额一致性",
                                affected_records=invalid_count,
                                sample_data=df[invalid_mask]["id"].head(5).tolist() if "id" in df.columns else None,
                            )
                        )
                        rule_scores.append(max(0, 100 - (invalid_count / len(df) * 100)))
                    else:
                        rule_scores.append(100.0)

                elif table_name == "general_ledger" and "debit" in df.columns and "credit" in df.columns:
                    invalid_mask = (df["debit"] - df["credit"]).abs() > 0.01
                    invalid_count = invalid_mask.sum()
                    if invalid_count > 0:
                        issues.append(
                            QualityIssue(
                                issue_type="consistency",
                                severity=severity,
                                description=f"借贷不平衡：{invalid_count} 条记录借方不等于贷方",
                                system_code=system_code,
                                table_name=table_name,
                                field_name="debit,credit",
                                rule_name="财务借贷平衡",
                                affected_records=invalid_count,
                                sample_data=df[invalid_mask]["id"].head(5).tolist() if "id" in df.columns else None,
                            )
                        )
                        rule_scores.append(max(0, 100 - (invalid_count / len(df) * 100)))
                    else:
                        rule_scores.append(100.0)

                elif table_name == "invoices" and "total_amount" in df.columns:
                    expected_total = df.get("amount", 0) + df.get("tax_amount", 0)
                    invalid_mask = (df["total_amount"] - expected_total).abs() > 0.01
                    invalid_count = invalid_mask.sum()
                    if invalid_count > 0:
                        issues.append(
                            QualityIssue(
                                issue_type="consistency",
                                severity=severity,
                                description=f"发票金额不一致：{invalid_count} 条记录价税合计不等于金额加税额",
                                system_code=system_code,
                                table_name=table_name,
                                field_name="total_amount,amount,tax_amount",
                                rule_name="发票金额一致性",
                                affected_records=invalid_count,
                                sample_data=df[invalid_mask]["id"].head(5).tolist() if "id" in df.columns else None,
                            )
                        )
                        rule_scores.append(max(0, 100 - (invalid_count / len(df) * 100)))
                    else:
                        rule_scores.append(100.0)

                elif table_name == "attendance" and "work_hours" in df.columns:
                    invalid_mask = (df["work_hours"] < 0) | (df["work_hours"] > 24)
                    invalid_count = invalid_mask.sum()
                    if invalid_count > 0:
                        issues.append(
                            QualityIssue(
                                issue_type="consistency",
                                severity="medium",
                                description=f"考勤时长异常：{invalid_count} 条记录工时不在合理范围内(0-24小时)",
                                system_code=system_code,
                                table_name=table_name,
                                field_name="work_hours",
                                rule_name="考勤时长合理性",
                                affected_records=invalid_count,
                                sample_data=df[invalid_mask]["id"].head(5).tolist() if "id" in df.columns else None,
                            )
                        )
                        rule_scores.append(max(0, 100 - (invalid_count / len(df) * 100)))
                    else:
                        rule_scores.append(100.0)

            except Exception as e:
                self.logger.error(f"一致性规则检查失败 {rule_name}: {e}", exc_info=True)

        if "id" in df.columns:
            dup_count = df.duplicated(subset=["id"]).sum()
            if dup_count > 0:
                severity = "high" if dup_count / len(df) > 0.01 else "medium"
                issues.append(
                    QualityIssue(
                        issue_type="consistency",
                        severity=severity,
                        description=f"存在重复ID：{dup_count} 条重复记录",
                        system_code=system_code,
                        table_name=table_name,
                        field_name="id",
                        rule_name="唯一键检查",
                        affected_records=dup_count,
                    )
                )
                rule_scores.append(max(0, 100 - (dup_count / len(df) * 100)))

        overall_score = (
            round(sum(rule_scores) / len(rule_scores), 2) if rule_scores else 100.0
        )
        return overall_score, issues

    def _check_timeliness(
        self,
        system_code: str,
        table_name: str,
        df: pd.DataFrame,
        scan_date: date,
    ) -> Tuple[float, List[QualityIssue]]:
        issues = []
        timeliness_rules = self.rules.get("timeliness", {}).get("rules", [])
        rule_scores = []

        if "created_at" in df.columns:
            df["created_at_date"] = pd.to_datetime(df["created_at"]).dt.date
            today_records = df[df["created_at_date"] == scan_date]

            if len(today_records) == 0:
                issues.append(
                    QualityIssue(
                        issue_type="timeliness",
                        severity="high",
                        description=f"{scan_date} 无新增数据，可能存在数据延迟",
                        system_code=system_code,
                        table_name=table_name,
                        field_name="created_at",
                        rule_name="数据延迟阈值",
                        affected_records=0,
                    )
                )
                rule_scores.append(50.0)
            else:
                rule_scores.append(100.0)

            max_hours = 24
            for rule in timeliness_rules:
                if rule.get("name") == "数据延迟阈值":
                    max_hours = rule.get("max_hours", 24)
                    break

            now = datetime.now()
            if "updated_at" in df.columns:
                df["updated_at_dt"] = pd.to_datetime(df["updated_at"])
                latest_update = df["updated_at_dt"].max()
                delay_hours = (now - latest_update).total_seconds() / 3600

                if delay_hours > max_hours:
                    severity = "high" if delay_hours > max_hours * 2 else "medium"
                    issues.append(
                        QualityIssue(
                            issue_type="timeliness",
                            severity=severity,
                            description=f"数据更新延迟：最新数据更新于 {latest_update}，延迟 {delay_hours:.1f} 小时",
                            system_code=system_code,
                            table_name=table_name,
                            field_name="updated_at",
                            rule_name="数据延迟阈值",
                            affected_records=len(df),
                        )
                    )
                    score = max(0, 100 - (delay_hours - max_hours) / max_hours * 50)
                    rule_scores.append(score)

        if "paid_at" in df.columns:
            df["paid_at_dt"] = pd.to_datetime(df["paid_at"])
            df["created_at_dt"] = pd.to_datetime(df["created_at"])
            payment_delay = (df["paid_at_dt"] - df["created_at_dt"]).dt.total_seconds() / 3600
            abnormal_delays = payment_delay[(payment_delay > 72) & (payment_delay.notna())]

            if len(abnormal_delays) > 0:
                issues.append(
                    QualityIssue(
                        issue_type="timeliness",
                        severity="low",
                        description=f"支付时效异常：{len(abnormal_delays)} 笔订单支付时间超过72小时",
                        system_code=system_code,
                        table_name=table_name,
                        field_name="paid_at",
                        rule_name="支付时效检查",
                        affected_records=len(abnormal_delays),
                    )
                )
                score = max(0, 100 - (len(abnormal_delays) / len(df) * 100))
                rule_scores.append(score)

        overall_score = (
            round(sum(rule_scores) / len(rule_scores), 2) if rule_scores else 100.0
        )
        return overall_score, issues

    def _save_scan_results(
        self, score: QualityScore, issues: List[QualityIssue]
    ):
        try:
            existing = self.db.execute_query(
                "SELECT id FROM quality_scores WHERE system_code = ? AND table_name = ? AND scan_date = ?",
                (score.system_code, score.table_name, score.scan_date.isoformat()),
            )
            if existing:
                self.db.update_record(
                    "quality_scores",
                    score.to_dict(),
                    "id = ?",
                    (existing[0]["id"],),
                )
            else:
                self.db.insert_record("quality_scores", score.to_dict())

            for issue in issues:
                existing_issue = self.db.execute_query(
                    "SELECT id FROM quality_issues WHERE issue_code = ?",
                    (issue.issue_code,),
                )
                if not existing_issue:
                    self.db.insert_record("quality_issues", issue.to_dict())
                else:
                    self.db.update_record(
                        "quality_issues",
                        issue.to_dict(),
                        "id = ?",
                        (existing_issue[0]["id"],),
                    )

        except Exception as e:
            self.logger.error(f"保存扫描结果失败: {e}", exc_info=True)

    def get_system_scores(
        self,
        system_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM quality_scores WHERE system_code = ?"
        params = [system_code]

        if start_date:
            query += " AND scan_date >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND scan_date <= ?"
            params.append(end_date.isoformat())

        query += " ORDER BY scan_date DESC"
        return self.db.execute_query(query, tuple(params))

    def get_open_issues(
        self,
        system_code: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM quality_issues WHERE status = 'open'"
        params = []

        if system_code:
            query += " AND system_code = ?"
            params.append(system_code)
        if severity:
            query += " AND severity = ?"
            params.append(severity)

        query += " ORDER BY created_at DESC"
        return self.db.execute_query(query, tuple(params))
