from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
import json
import os

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    PageBreak,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from ..utils import ConfigManager, DatabaseManager, generate_id, safe_json_dumps
from ..logging import DQLogger
from ..quality import QualityRuleEngine
from ..tickets import TicketEngine
from ..masking import MaskingEngine
from ..governance import GovernanceEngine


rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS"]
rcParams["axes.unicode_minus"] = False


class ReportEngine:
    def __init__(self):
        self.config = ConfigManager()
        self.db = DatabaseManager()
        self.logger = DQLogger()
        self.quality_engine = QualityRuleEngine()
        self.ticket_engine = TicketEngine()
        self.masking_engine = MaskingEngine()
        self.governance_engine = GovernanceEngine()
        self.company_name = self.config.get("reporting.pdf_company_name", "数据管理部")
        self.report_dir = "./reports"
        os.makedirs(self.report_dir, exist_ok=True)

    def generate_daily_quality_report(
        self,
        report_date: Optional[date] = None,
        export_formats: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if report_date is None:
            report_date = date.today() - timedelta(days=1)

        self.logger.info(f"生成每日数据质量报告: {report_date}")

        report_no = generate_id("RPT")
        report_data = self._collect_daily_report_data(report_date)

        result = {
            "report_no": report_no,
            "report_type": "daily_quality",
            "report_date": report_date.isoformat(),
            "generated_at": datetime.now().isoformat(),
            "data": report_data,
            "files": {},
        }

        if export_formats is None:
            export_formats = self.config.get("reporting.export_formats", ["pdf", "excel"])

        for fmt in export_formats:
            try:
                if fmt.lower() == "pdf":
                    file_path = self._generate_daily_pdf_report(report_date, report_data, report_no)
                    result["files"]["pdf"] = file_path
                elif fmt.lower() == "excel":
                    file_path = self._generate_daily_excel_report(report_date, report_data, report_no)
                    result["files"]["excel"] = file_path
            except Exception as e:
                self.logger.error(f"生成{fmt}格式报告失败: {e}", exc_info=True)

        self._save_report_record(report_no, "daily_quality", report_date, export_formats, result["files"])

        self.logger.log_operation(
            "report_generate",
            {
                "report_no": report_no,
                "report_type": "daily_quality",
                "report_date": report_date.isoformat(),
                "formats": export_formats,
                "files": result["files"],
            },
        )

        self.logger.info(f"每日质量报告生成完成: {report_no}")
        return result

    def generate_weekly_compliance_report(
        self,
        report_date: Optional[date] = None,
        export_formats: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if report_date is None:
            report_date = date.today()

        self.logger.info(f"生成每周数据安全合规报告: {report_date}")

        report_no = generate_id("RPT")
        end_date = report_date
        start_date = end_date - timedelta(days=6)

        report_data = self._collect_compliance_report_data(start_date, end_date)

        result = {
            "report_no": report_no,
            "report_type": "weekly_compliance",
            "report_date": report_date.isoformat(),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "generated_at": datetime.now().isoformat(),
            "data": report_data,
            "files": {},
        }

        if export_formats is None:
            export_formats = self.config.get("reporting.export_formats", ["pdf", "excel"])

        for fmt in export_formats:
            try:
                if fmt.lower() == "pdf":
                    file_path = self._generate_compliance_pdf_report(
                        start_date, end_date, report_data, report_no
                    )
                    result["files"]["pdf"] = file_path
                elif fmt.lower() == "excel":
                    file_path = self._generate_compliance_excel_report(
                        start_date, end_date, report_data, report_no
                    )
                    result["files"]["excel"] = file_path
            except Exception as e:
                self.logger.error(f"生成{fmt}格式合规报告失败: {e}", exc_info=True)

        self._save_report_record(report_no, "weekly_compliance", report_date, export_formats, result["files"])

        self.logger.log_operation(
            "report_generate",
            {
                "report_no": report_no,
                "report_type": "weekly_compliance",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "formats": export_formats,
                "files": result["files"],
            },
        )

        self.logger.info(f"每周合规报告生成完成: {report_no}")
        return result

    def _collect_daily_report_data(self, report_date: date) -> Dict[str, Any]:
        data = {
            "system_scores": [],
            "trend_data": [],
            "issue_summary": {},
            "ticket_summary": {},
            "governance_stats": {},
        }

        systems = self.config.get("business_systems", {})
        for system_code in systems.keys():
            scores = self.quality_engine.get_system_scores(
                system_code, report_date, report_date
            )
            if scores:
                avg_score = sum(s["overall_score"] for s in scores) / len(scores)
                system_info = systems[system_code]
                data["system_scores"].append(
                    {
                        "system_code": system_code,
                        "system_name": system_info.get("name", system_code),
                        "data_domain": system_info.get("data_domain", ""),
                        "avg_score": round(avg_score, 2),
                        "completeness": round(
                            sum(s["completeness_score"] for s in scores) / len(scores), 2
                        ),
                        "consistency": round(
                            sum(s["consistency_score"] for s in scores) / len(scores), 2
                        ),
                        "timeliness": round(
                            sum(s["timeliness_score"] for s in scores) / len(scores), 2
                        ),
                        "total_records": sum(s["total_records"] for s in scores),
                        "issue_count": sum(s["issue_count"] for s in scores),
                        "table_scores": [
                            {
                                "table_name": s["table_name"],
                                "score": s["overall_score"],
                                "issues": s["issue_count"],
                            }
                            for s in scores
                        ],
                    }
                )

        start_date = report_date - timedelta(days=29)
        for system_code in systems.keys():
            history_scores = self.quality_engine.get_system_scores(
                system_code, start_date, report_date
            )
            if history_scores:
                daily_scores = {}
                for s in history_scores:
                    d = s["scan_date"]
                    if isinstance(d, str):
                        d = date.fromisoformat(d)
                    d_str = d.isoformat()
                    if d_str not in daily_scores:
                        daily_scores[d_str] = []
                    daily_scores[d_str].append(s["overall_score"])

                for d_str, scores_list in sorted(daily_scores.items()):
                    data["trend_data"].append(
                        {
                            "date": d_str,
                            "system_code": system_code,
                            "avg_score": round(sum(scores_list) / len(scores_list), 2),
                        }
                    )

        issues = self.db.execute_query(
            """SELECT issue_type, severity, status, COUNT(*) as cnt
               FROM quality_issues
               WHERE DATE(scan_date) = ?
               GROUP BY issue_type, severity, status""",
            (report_date.isoformat(),),
        )

        data["issue_summary"] = {
            "by_type": {},
            "by_severity": {},
            "by_status": {},
            "total": 0,
        }

        for issue in issues:
            data["issue_summary"]["by_type"][issue["issue_type"]] = (
                data["issue_summary"]["by_type"].get(issue["issue_type"], 0) + issue["cnt"]
            )
            data["issue_summary"]["by_severity"][issue["severity"]] = (
                data["issue_summary"]["by_severity"].get(issue["severity"], 0) + issue["cnt"]
            )
            data["issue_summary"]["by_status"][issue["status"]] = (
                data["issue_summary"]["by_status"].get(issue["status"], 0) + issue["cnt"]
            )
            data["issue_summary"]["total"] += issue["cnt"]

        data["ticket_summary"] = self.ticket_engine.get_ticket_statistics(
            report_date, report_date
        )

        data["governance_stats"] = self.governance_engine.get_governance_statistics(
            report_date - timedelta(days=30), report_date
        )

        return data

    def _collect_compliance_report_data(
        self, start_date: date, end_date: date
    ) -> Dict[str, Any]:
        data = {
            "masking_coverage": {},
            "access_anomalies": [],
            "sensitive_data_summary": {},
            "permission_audit": {},
        }

        data["masking_coverage"] = self.masking_engine.get_masking_coverage(
            start_date=start_date, end_date=end_date
        )

        data["access_anomalies"] = self.masking_engine.get_access_anomalies(
            start_date=start_date, end_date=end_date
        )

        sensitive_records = self.db.execute_query(
            """SELECT data_type, sensitivity_level, SUM(record_count) as total_records,
               SUM(masked_count) as total_masked
               FROM sensitive_data_records
               WHERE scan_date >= ? AND scan_date <= ?
               GROUP BY data_type, sensitivity_level""",
            (start_date.isoformat(), end_date.isoformat()),
        )

        data["sensitive_data_summary"] = {
            "by_type": {},
            "by_level": {},
            "total_records": 0,
            "total_masked": 0,
        }

        for rec in sensitive_records:
            data["sensitive_data_summary"]["by_type"][rec["data_type"]] = (
                data["sensitive_data_summary"]["by_type"].get(rec["data_type"], 0)
                + rec["total_records"]
            )
            data["sensitive_data_summary"]["by_level"][rec["sensitivity_level"]] = (
                data["sensitive_data_summary"]["by_level"].get(rec["sensitivity_level"], 0)
                + rec["total_records"]
            )
            data["sensitive_data_summary"]["total_records"] += rec["total_records"]
            data["sensitive_data_summary"]["total_masked"] += rec["total_masked"]

        dept_permissions = self.config.get("sensitive_data.dept_permissions", {})
        data["permission_audit"] = {
            "configured_departments": list(dept_permissions.keys()),
            "permissions": dept_permissions,
        }

        return data

    def _generate_daily_pdf_report(
        self, report_date: date, report_data: Dict[str, Any], report_no: str
    ) -> str:
        file_path = os.path.join(
            self.report_dir, f"daily_quality_{report_date.isoformat()}_{report_no}.pdf"
        )

        doc = SimpleDocTemplate(file_path, pagesize=A4, title="数据质量日报")
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "CustomTitle",
            parent=styles["Heading1"],
            fontSize=24,
            textColor=colors.HexColor("#1a365d"),
            alignment=TA_CENTER,
            spaceAfter=20,
        )

        section_style = ParagraphStyle(
            "SectionTitle",
            parent=styles["Heading2"],
            fontSize=16,
            textColor=colors.HexColor("#2b6cb0"),
            spaceBefore=15,
            spaceAfter=10,
        )

        normal_style = ParagraphStyle(
            "NormalText",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
        )

        story = []

        story.append(Paragraph(self.company_name, title_style))
        story.append(
            Paragraph(
                f"数据质量每日监测报告 - {report_date.isoformat()}",
                ParagraphStyle(
                    "SubTitle",
                    parent=styles["Heading2"],
                    fontSize=18,
                    textColor=colors.HexColor("#4a5568"),
                    alignment=TA_CENTER,
                    spaceAfter=30,
                ),
            )
        )
        story.append(
            Paragraph(
                f"报告编号: {report_no} | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                ParagraphStyle(
                    "Meta",
                    parent=styles["Normal"],
                    fontSize=9,
                    textColor=colors.HexColor("#718096"),
                    alignment=TA_CENTER,
                    spaceAfter=20,
                ),
            )
        )

        story.append(Paragraph("一、各系统数据质量评分", section_style))

        if report_data["system_scores"]:
            header = ["系统名称", "数据域", "综合评分", "完整性", "一致性", "时效性", "问题数"]
            table_data = [header]

            for sys in report_data["system_scores"]:
                score_color = self._get_score_color(sys["avg_score"])
                table_data.append(
                    [
                        sys["system_name"],
                        sys["data_domain"],
                        str(sys["avg_score"]),
                        str(sys["completeness"]),
                        str(sys["consistency"]),
                        str(sys["timeliness"]),
                        str(sys["issue_count"]),
                    ]
                )

            t = Table(table_data, colWidths=[1.2 * inch, 0.8 * inch, 0.8 * inch, 0.8 * inch, 0.8 * inch, 0.8 * inch, 0.6 * inch])
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b6cb0")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f7fafc")),
                        ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f7fafc"), colors.white]),
                        ("FONTSIZE", (0, 1), (-1, -1), 9),
                    ]
                )
            )
            story.append(t)
        else:
            story.append(Paragraph("暂无数据", normal_style))

        story.append(Spacer(1, 20))
        story.append(Paragraph("二、数据质量趋势分析", section_style))

        trend_chart = self._generate_trend_chart(report_data["trend_data"], report_date)
        if trend_chart:
            story.append(Image(trend_chart, width=7 * inch, height=3 * inch))

        story.append(Spacer(1, 20))
        story.append(Paragraph("三、问题分布统计", section_style))

        issue_chart = self._generate_issue_chart(report_data["issue_summary"])
        if issue_chart:
            story.append(Image(issue_chart, width=5 * inch, height=3 * inch))

        story.append(Spacer(1, 20))
        story.append(Paragraph("四、治理工单统计", section_style))

        ticket_stats = report_data["ticket_summary"]
        ticket_data = [
            ["指标", "数值"],
            ["总工单数", str(ticket_stats.get("total", 0))],
            ["已解决", str(ticket_stats.get("by_status", {}).get("verified", 0) + ticket_stats.get("by_status", {}).get("closed", 0))],
            ["处理中", str(ticket_stats.get("by_status", {}).get("in_progress", 0))],
            ["待处理", str(ticket_stats.get("by_status", {}).get("pending", 0))],
            ["解决率", f"{ticket_stats.get('resolution_rate', 0)}%"],
            ["平均解决时长", f"{ticket_stats.get('avg_resolution_hours', 0)}小时"],
            ["SLA违规数", str(ticket_stats.get("sla_breach_count", 0))],
        ]

        t = Table(ticket_data, colWidths=[2 * inch, 2 * inch])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b6cb0")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                ]
            )
        )
        story.append(t)

        story.append(Spacer(1, 30))
        story.append(
            Paragraph(
                "本报告由数据质量自动化监控系统自动生成",
                ParagraphStyle(
                    "Footer",
                    parent=styles["Normal"],
                    fontSize=8,
                    textColor=colors.HexColor("#a0aec0"),
                    alignment=TA_CENTER,
                ),
            )
        )

        doc.build(story)
        self.logger.info(f"PDF报告已生成: {file_path}")
        return file_path

    def _generate_daily_excel_report(
        self, report_date: date, report_data: Dict[str, Any], report_no: str
    ) -> str:
        file_path = os.path.join(
            self.report_dir, f"daily_quality_{report_date.isoformat()}_{report_no}.xlsx"
        )

        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            if report_data["system_scores"]:
                scores_df = pd.DataFrame(
                    [
                        {
                            "系统代码": s["system_code"],
                            "系统名称": s["system_name"],
                            "数据域": s["data_domain"],
                            "综合评分": s["avg_score"],
                            "完整性": s["completeness"],
                            "一致性": s["consistency"],
                            "时效性": s["timeliness"],
                            "总记录数": s["total_records"],
                            "问题数": s["issue_count"],
                        }
                        for s in report_data["system_scores"]
                    ]
                )
                scores_df.to_excel(writer, sheet_name="系统评分", index=False)

            if report_data["trend_data"]:
                trend_df = pd.DataFrame(report_data["trend_data"])
                trend_df.to_excel(writer, sheet_name="趋势数据", index=False)

            issue_summary = report_data["issue_summary"]
            issues_df = pd.DataFrame(
                [
                    {"维度": "按类型", "分类": k, "数量": v}
                    for k, v in issue_summary.get("by_type", {}).items()
                ]
                + [
                    {"维度": "按严重程度", "分类": k, "数量": v}
                    for k, v in issue_summary.get("by_severity", {}).items()
                ]
                + [
                    {"维度": "按状态", "分类": k, "数量": v}
                    for k, v in issue_summary.get("by_status", {}).items()
                ]
            )
            issues_df.to_excel(writer, sheet_name="问题统计", index=False)

            ticket_stats = report_data["ticket_summary"]
            ticket_df = pd.DataFrame(
                [
                    {"指标": "总工单数", "数值": ticket_stats.get("total", 0)},
                    {
                        "指标": "已解决",
                        "数值": ticket_stats.get("by_status", {}).get("verified", 0)
                        + ticket_stats.get("by_status", {}).get("closed", 0),
                    },
                    {"指标": "解决率", "数值": f"{ticket_stats.get('resolution_rate', 0)}%"},
                    {"指标": "平均解决时长", "数值": f"{ticket_stats.get('avg_resolution_hours', 0)}小时"},
                ]
            )
            ticket_df.to_excel(writer, sheet_name="工单统计", index=False)

            for sys in report_data["system_scores"]:
                if sys.get("table_scores"):
                    table_df = pd.DataFrame(sys["table_scores"])
                    sheet_name = f"{sys['system_code']}_明细"[:31]
                    table_df.to_excel(writer, sheet_name=sheet_name, index=False)

        self.logger.info(f"Excel报告已生成: {file_path}")
        return file_path

    def _generate_compliance_pdf_report(
        self,
        start_date: date,
        end_date: date,
        report_data: Dict[str, Any],
        report_no: str,
    ) -> str:
        file_path = os.path.join(
            self.report_dir, f"weekly_compliance_{end_date.isoformat()}_{report_no}.pdf"
        )

        doc = SimpleDocTemplate(file_path, pagesize=A4, title="数据安全合规周报")
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "CustomTitle",
            parent=styles["Heading1"],
            fontSize=24,
            textColor=colors.HexColor("#742a2a"),
            alignment=TA_CENTER,
            spaceAfter=20,
        )

        section_style = ParagraphStyle(
            "SectionTitle",
            parent=styles["Heading2"],
            fontSize=16,
            textColor=colors.HexColor("#c53030"),
            spaceBefore=15,
            spaceAfter=10,
        )

        story = []

        story.append(Paragraph(self.company_name, title_style))
        story.append(
            Paragraph(
                f"数据安全合规周报 - {start_date.isoformat()} 至 {end_date.isoformat()}",
                ParagraphStyle(
                    "SubTitle",
                    parent=styles["Heading2"],
                    fontSize=18,
                    textColor=colors.HexColor("#4a5568"),
                    alignment=TA_CENTER,
                    spaceAfter=30,
                ),
            )
        )
        story.append(
            Paragraph(
                f"报告编号: {report_no} | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                ParagraphStyle(
                    "Meta",
                    parent=styles["Normal"],
                    fontSize=9,
                    textColor=colors.HexColor("#718096"),
                    alignment=TA_CENTER,
                    spaceAfter=20,
                ),
            )
        )

        story.append(Paragraph("一、敏感数据脱敏覆盖率", section_style))

        masking = report_data["masking_coverage"]
        coverage_data = [
            ["指标", "数值"],
            ["敏感数据总记录数", str(masking.get("total_sensitive_records", 0))],
            ["已脱敏记录数", str(masking.get("total_masked_records", 0))],
            ["脱敏覆盖率", f"{masking.get('masking_coverage', 0)}%"],
            ["涉及字段数", str(masking.get("record_count", 0))],
        ]

        for level, data in masking.get("by_sensitivity_level", {}).items():
            coverage = (
                round(data["masked"] / data["total"] * 100, 2) if data["total"] > 0 else 100
            )
            level_name = {"high": "高", "medium": "中", "low": "低"}.get(level, level)
            coverage_data.append(
                [f"{level_name}级别覆盖率", f"{coverage}% ({data['masked']}/{data['total']})"]
            )

        t = Table(coverage_data, colWidths=[2.5 * inch, 3.5 * inch])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#c53030")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                ]
            )
        )
        story.append(t)

        story.append(Spacer(1, 20))
        story.append(Paragraph("二、敏感数据类型分布", section_style))

        type_chart = self._generate_sensitive_type_chart(
            report_data["sensitive_data_summary"].get("by_type", {})
        )
        if type_chart:
            story.append(Image(type_chart, width=5 * inch, height=3 * inch))

        story.append(Spacer(1, 20))
        story.append(Paragraph("三、敏感数据访问异常", section_style))

        anomalies = report_data["access_anomalies"]
        if anomalies:
            anomaly_data = [
                ["时间", "系统", "操作人", "异常类型", "描述"],
            ]
            for a in anomalies[:10]:
                anomaly_data.append(
                    [
                        a.get("created_at", "")[:16],
                        a.get("system_code", ""),
                        a.get("operator", ""),
                        a.get("anomaly_type", ""),
                        a.get("description", "")[:30],
                    ]
                )
            t = Table(anomaly_data, colWidths=[1.2 * inch, 1 * inch, 0.8 * inch, 1 * inch, 2 * inch])
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#c53030")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                        ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            story.append(t)
            if len(anomalies) > 10:
                story.append(
                    Paragraph(
                        f"... 还有 {len(anomalies) - 10} 条异常记录",
                        ParagraphStyle(
                            "Note",
                            parent=styles["Normal"],
                            fontSize=9,
                            textColor=colors.HexColor("#c53030"),
                        ),
                    )
                )
        else:
            story.append(
                Paragraph(
                    "本周未发现敏感数据访问异常",
                    ParagraphStyle(
                        "NormalText",
                        parent=styles["Normal"],
                        fontSize=10,
                        textColor=colors.HexColor("#38a169"),
                    ),
                )
            )

        story.append(Spacer(1, 20))
        story.append(Paragraph("四、部门权限配置审计", section_style))

        perms = report_data["permission_audit"]
        perm_data = [["部门", "允许访问级别", "特殊权限字段"]]
        for dept, perm in perms.get("permissions", {}).items():
            perm_data.append(
                [
                    dept,
                    ", ".join(perm.get("allowed_levels", [])),
                    ", ".join(perm.get("special_fields", [])),
                ]
            )

        t = Table(perm_data, colWidths=[1.5 * inch, 2 * inch, 2.5 * inch])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#c53030")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                ]
            )
        )
        story.append(t)

        story.append(Spacer(1, 30))
        story.append(
            Paragraph(
                "本报告由数据质量自动化监控系统自动生成，如有疑问请联系数据管理部",
                ParagraphStyle(
                    "Footer",
                    parent=styles["Normal"],
                    fontSize=8,
                    textColor=colors.HexColor("#a0aec0"),
                    alignment=TA_CENTER,
                ),
            )
        )

        doc.build(story)
        self.logger.info(f"合规PDF报告已生成: {file_path}")
        return file_path

    def _generate_compliance_excel_report(
        self,
        start_date: date,
        end_date: date,
        report_data: Dict[str, Any],
        report_no: str,
    ) -> str:
        file_path = os.path.join(
            self.report_dir, f"weekly_compliance_{end_date.isoformat()}_{report_no}.xlsx"
        )

        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            masking = report_data["masking_coverage"]
            masking_df = pd.DataFrame(
                [
                    {"指标": "敏感数据总记录数", "数值": masking.get("total_sensitive_records", 0)},
                    {"指标": "已脱敏记录数", "数值": masking.get("total_masked_records", 0)},
                    {"指标": "脱敏覆盖率", "数值": f"{masking.get('masking_coverage', 0)}%"},
                ]
            )
            masking_df.to_excel(writer, sheet_name="脱敏覆盖率", index=False)

            sensitive = report_data["sensitive_data_summary"]
            type_df = pd.DataFrame(
                list(sensitive.get("by_type", {}).items()),
                columns=["数据类型", "记录数"],
            )
            type_df.to_excel(writer, sheet_name="类型分布", index=False)

            level_df = pd.DataFrame(
                list(sensitive.get("by_level", {}).items()),
                columns=["敏感级别", "记录数"],
            )
            level_df.to_excel(writer, sheet_name="级别分布", index=False)

            anomalies = report_data["access_anomalies"]
            if anomalies:
                anomaly_df = pd.DataFrame(anomalies)
                anomaly_df.to_excel(writer, sheet_name="访问异常", index=False)

            perms = report_data["permission_audit"].get("permissions", {})
            perm_list = []
            for dept, perm in perms.items():
                perm_list.append(
                    {
                        "部门": dept,
                        "允许访问级别": ", ".join(perm.get("allowed_levels", [])),
                        "特殊权限字段": ", ".join(perm.get("special_fields", [])),
                    }
                )
            if perm_list:
                perm_df = pd.DataFrame(perm_list)
                perm_df.to_excel(writer, sheet_name="权限配置", index=False)

        self.logger.info(f"合规Excel报告已生成: {file_path}")
        return file_path

    @staticmethod
    def _get_score_color(score: float) -> str:
        if score >= 90:
            return "#38a169"
        elif score >= 80:
            return "#ecc94b"
        elif score >= 60:
            return "#ed8936"
        else:
            return "#e53e3e"

    def _generate_trend_chart(
        self, trend_data: List[Dict[str, Any]], report_date: date
    ) -> Optional[str]:
        if not trend_data:
            return None

        try:
            systems = set(d["system_code"] for d in trend_data)
            dates = sorted(set(d["date"] for d in trend_data))

            plt.figure(figsize=(10, 4))

            for system in systems:
                sys_data = [d for d in trend_data if d["system_code"] == system]
                sys_data.sort(key=lambda x: x["date"])
                scores = [d["avg_score"] for d in sys_data]
                sys_dates = [d["date"][5:] for d in sys_data]
                plt.plot(sys_dates, scores, marker="o", label=system, linewidth=2)

            plt.axhline(y=80, color="r", linestyle="--", alpha=0.7, label="合格线(80分)")
            plt.axhline(y=90, color="g", linestyle="--", alpha=0.7, label="优秀线(90分)")

            plt.title(f"数据质量评分趋势 (近30天)")
            plt.xlabel("日期")
            plt.ylabel("评分")
            plt.legend(bbox_to_anchor=(1.05, 1), loc="upper left")
            plt.grid(True, alpha=0.3)
            plt.ylim(50, 105)
            plt.tight_layout()

            chart_path = os.path.join(
                self.report_dir, f"trend_{report_date.isoformat()}.png"
            )
            plt.savefig(chart_path, dpi=100, bbox_inches="tight")
            plt.close()

            return chart_path
        except Exception as e:
            self.logger.error(f"生成趋势图表失败: {e}", exc_info=True)
            return None

    def _generate_issue_chart(self, issue_summary: Dict[str, Any]) -> Optional[str]:
        try:
            by_severity = issue_summary.get("by_severity", {})
            if not by_severity:
                return None

            labels = []
            sizes = []
            colors_map = {"critical": "#e53e3e", "high": "#ed8936", "medium": "#ecc94b", "low": "#48bb78"}
            color_list = []

            severity_names = {"critical": "严重", "high": "高", "medium": "中", "low": "低"}

            for severity, count in by_severity.items():
                if count > 0:
                    labels.append(f"{severity_names.get(severity, severity)} ({count})")
                    sizes.append(count)
                    color_list.append(colors_map.get(severity, "#718096"))

            plt.figure(figsize=(6, 4))
            plt.pie(sizes, labels=labels, colors=color_list, autopct="%1.1f%%", startangle=90)
            plt.title("问题严重程度分布")
            plt.axis("equal")

            chart_path = os.path.join(
                self.report_dir, f"issues_{date.today().isoformat()}.png"
            )
            plt.savefig(chart_path, dpi=100, bbox_inches="tight")
            plt.close()

            return chart_path
        except Exception as e:
            self.logger.error(f"生成问题图表失败: {e}", exc_info=True)
            return None

    def _generate_sensitive_type_chart(self, by_type: Dict[str, int]) -> Optional[str]:
        try:
            if not by_type:
                return None

            type_names = {
                "id_card": "身份证",
                "phone": "手机号",
                "email": "邮箱",
                "bank_card": "银行卡",
                "address": "地址",
            }

            labels = [type_names.get(k, k) for k in by_type.keys()]
            sizes = list(by_type.values())

            plt.figure(figsize=(6, 4))
            plt.bar(labels, sizes, color="#c53030", alpha=0.7)
            plt.title("敏感数据类型分布")
            plt.ylabel("记录数")
            plt.xticks(rotation=45)
            plt.tight_layout()

            chart_path = os.path.join(
                self.report_dir, f"sensitive_types_{date.today().isoformat()}.png"
            )
            plt.savefig(chart_path, dpi=100, bbox_inches="tight")
            plt.close()

            return chart_path
        except Exception as e:
            self.logger.error(f"生成敏感类型图表失败: {e}", exc_info=True)
            return None

    def _save_report_record(
        self,
        report_no: str,
        report_type: str,
        report_date: date,
        formats: List[str],
        files: Dict[str, str],
    ):
        recipients = self.config.get(
            f"reporting.recipients.{report_type.split('_')[0]}", []
        )

        record = {
            "report_no": report_no,
            "report_type": report_type,
            "report_date": report_date.isoformat(),
            "format": ",".join(formats),
            "file_path": safe_json_dumps(files),
            "recipients": ",".join(recipients),
        }

        self.db.insert_record("reports", record)

    def export_tickets(
        self,
        output_path: str,
        format: str = "excel",
        **query_kwargs,
    ) -> str:
        return self.ticket_engine.export_tickets(output_path, format, **query_kwargs)

    def export_logs(
        self,
        output_path: str,
        format: str = "csv",
        **query_kwargs,
    ) -> str:
        return self.logger.export_logs(output_path, format, **query_kwargs)
