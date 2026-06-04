from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional, Callable
import schedule
import time
import threading
import json

from ..utils import ConfigManager, DatabaseManager, safe_json_dumps
from ..logging import DQLogger
from ..collectors import CollectorFactory
from ..quality import QualityRuleEngine
from ..masking import MaskingEngine
from ..tickets import TicketEngine
from ..lineage import LineageEngine
from ..governance import GovernanceEngine
from ..reports import ReportEngine
from ..correction import CorrectionEngine


class SchedulerEngine:
    def __init__(self):
        self.config = ConfigManager()
        self.db = DatabaseManager()
        self.logger = DQLogger()
        self.collector_factory = CollectorFactory()
        self.quality_engine = QualityRuleEngine()
        self.masking_engine = MaskingEngine()
        self.ticket_engine = TicketEngine()
        self.lineage_engine = LineageEngine()
        self.governance_engine = GovernanceEngine()
        self.report_engine = ReportEngine()
        self.correction_engine = CorrectionEngine()

        self._running = False
        self._schedule_thread: Optional[threading.Thread] = None
        self._jobs: Dict[str, schedule.Job] = {}

    def run_daily_data_collection(self, process_date: Optional[date] = None) -> Dict[str, Any]:
        if process_date is None:
            process_date = date.today() - timedelta(days=1)

        self.logger.info(f"开始执行每日数据采集任务: {process_date}")

        start_time = datetime.now()
        results = {
            "process_date": process_date.isoformat(),
            "start_time": start_time.isoformat(),
            "status": "running",
            "systems": {},
        }

        try:
            raw_data = self.collector_factory.collect_all(
                start_date=process_date,
                end_date=process_date + timedelta(days=1),
            )

            for system_code, system_data in raw_data.items():
                total_records = sum(len(df) for df in system_data.values())
                results["systems"][system_code] = {
                    "tables": list(system_data.keys()),
                    "total_records": total_records,
                    "status": "collected",
                }

                masked_data, sensitive_records = self.masking_engine.scan_and_mask(
                    system_code, system_data, scan_date=process_date
                )

                for sensitive in sensitive_records:
                    self.db.insert_record("sensitive_data_records", sensitive.to_dict())

                scan_result = self.quality_engine.scan_system(
                    system_code, masked_data, scan_date=process_date
                )

                for score in scan_result["scores"]:
                    self.db.insert_record("quality_scores", score.to_dict())

                for issue in scan_result["issues"]:
                    issue_dict = issue.to_dict()
                    issue_id = self.db.insert_record("quality_issues", issue_dict)
                    issue_dict["id"] = issue_id

                results["systems"][system_code]["quality_score"] = scan_result["overall_score"]
                results["systems"][system_code]["issue_count"] = len(scan_result["issues"])
                results["systems"][system_code]["sensitive_fields"] = len(sensitive_records)

                self.lineage_engine.update_lineage(system_code, masked_data, process_date)
                self.lineage_engine.mark_quality_status(
                    system_code,
                    scan_result["overall_score"],
                    process_date,
                )

                if scan_result["issues"]:
                    tickets = self.ticket_engine.create_tickets_from_issues(
                        scan_result["issues"], system_code
                    )
                    results["systems"][system_code]["tickets_created"] = len(tickets)

            self.ticket_engine.auto_recheck_resolved_tickets()

            project_result = self.governance_engine.check_and_trigger_special_governance()
            if project_result.get("triggered"):
                results["special_governance"] = project_result

            report_result = self.report_engine.generate_daily_quality_report(
                report_date=process_date
            )
            results["daily_report"] = report_result

            if process_date.weekday() == 0:
                compliance_report = self.report_engine.generate_weekly_compliance_report(
                    week_start=process_date - timedelta(days=7)
                )
                results["weekly_compliance_report"] = compliance_report

            results["status"] = "completed"
            results["end_time"] = datetime.now().isoformat()
            duration = (datetime.now() - start_time).total_seconds()
            results["duration_seconds"] = duration

            self.logger.info(f"每日数据采集任务完成: {process_date}, 耗时: {duration:.2f}秒")

            self.db.insert_record("operation_logs", {
                "operation_type": "daily_pipeline",
                "system_code": "all",
                "operator": "system",
                "status": "success",
                "details": safe_json_dumps(results),
                "operation_time": datetime.now().isoformat(),
            })

        except Exception as e:
            results["status"] = "failed"
            results["error"] = str(e)
            results["end_time"] = datetime.now().isoformat()
            self.logger.error(f"每日数据采集任务失败: {e}", exc_info=True)

            self.db.insert_record("operation_logs", {
                "operation_type": "daily_pipeline",
                "system_code": "all",
                "operator": "system",
                "status": "failed",
                "error_message": str(e),
                "operation_time": datetime.now().isoformat(),
            })

        return results

    def run_quality_scan(
        self,
        system_code: Optional[str] = None,
        process_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        if process_date is None:
            process_date = date.today()

        self.logger.info(f"执行质量扫描: 系统={system_code or 'all'}, 日期={process_date}")

        results = {}

        if system_code:
            data = self.collector_factory.collect_system(system_code)
            if data:
                masked_data, _ = self.masking_engine.scan_and_mask(system_code, data)
                scan_result = self.quality_engine.scan_system(system_code, masked_data, process_date)
                results[system_code] = scan_result

                for score in scan_result["scores"]:
                    self.db.insert_record("quality_scores", score.to_dict())

                for issue in scan_result["issues"]:
                    self.db.insert_record("quality_issues", issue.to_dict())
        else:
            all_data = self.collector_factory.collect_all()
            for sys_code, sys_data in all_data.items():
                masked_data, _ = self.masking_engine.scan_and_mask(sys_code, sys_data)
                scan_result = self.quality_engine.scan_system(sys_code, masked_data, process_date)
                results[sys_code] = scan_result

                for score in scan_result["scores"]:
                    self.db.insert_record("quality_scores", score.to_dict())

                for issue in scan_result["issues"]:
                    self.db.insert_record("quality_issues", issue.to_dict())

        return results

    def run_ticket_recheck(self) -> Dict[str, Any]:
        self.logger.info("执行工单自动复检")
        results = self.ticket_engine.auto_recheck_resolved_tickets()
        return {
            "success": True,
            "total_processed": len(results),
            "passed_count": sum(1 for r in results if r.get("passed")),
            "failed_count": sum(1 for r in results if not r.get("passed")),
            "details": results,
        }

    def run_governance_check(self) -> Dict[str, Any]:
        self.logger.info("执行专项治理检查")
        results = self.governance_engine.check_and_trigger_special_governance()
        if isinstance(results, dict):
            return results
        return {
            "success": True,
            "total_triggered": len(results) if isinstance(results, list) else 0,
            "details": results,
        }

    def run_report_generation(
        self,
        report_type: str = "daily",
        report_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        self.logger.info(f"生成报告: 类型={report_type}, 日期={report_date}")

        if report_type == "daily":
            return self.report_engine.generate_daily_quality_report(report_date)
        elif report_type == "weekly_compliance":
            week_start = report_date or (date.today() - timedelta(days=7))
            return self.report_engine.generate_weekly_compliance_report(week_start)
        else:
            raise ValueError(f"不支持的报告类型: {report_type}")

    def _job_wrapper(self, job_name: str, func: Callable, *args, **kwargs) -> None:
        def wrapper():
            try:
                self.logger.info(f"定时任务开始执行: {job_name}")
                func(*args, **kwargs)
                self.logger.info(f"定时任务执行完成: {job_name}")
            except Exception as e:
                self.logger.error(f"定时任务执行失败 {job_name}: {e}", exc_info=True)
        return wrapper

    def setup_schedules(self) -> None:
        daily_time = self.config.get("scheduler.daily_run_time", "02:00")
        weekly_day = self.config.get("scheduler.weekly_run_day", 0)
        weekly_time = self.config.get("scheduler.weekly_run_time", "08:00")

        self.logger.info(f"配置定时任务: 每日 {daily_time}, 每周周{weekly_day} {weekly_time}")

        daily_job = schedule.every().day.at(daily_time).do(
            self._job_wrapper("daily_data_collection", self.run_daily_data_collection)
        )
        self._jobs["daily_data_collection"] = daily_job

        recheck_job = schedule.every().day.at("10:00").do(
            self._job_wrapper("ticket_recheck", self.run_ticket_recheck)
        )
        self._jobs["ticket_recheck"] = recheck_job

        governance_job = schedule.every().monday.at("09:00").do(
            self._job_wrapper("governance_check", self.run_governance_check)
        )
        self._jobs["governance_check"] = governance_job

        log_cleanup_job = schedule.every().sunday.at("23:00").do(
            self._job_wrapper("log_cleanup", self.logger.cleanup_old_logs)
        )
        self._jobs["log_cleanup"] = log_cleanup_job

    def start(self) -> None:
        if self._running:
            self.logger.warning("调度器已经在运行")
            return

        self.setup_schedules()
        self._running = True

        self._schedule_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._schedule_thread.start()

        self.logger.info("数据质量治理系统调度器已启动")
        self.logger.info("当前调度任务:")
        for job_name, job in self._jobs.items():
            self.logger.info(f"  - {job_name}: {job}")

    def _run_loop(self) -> None:
        while self._running:
            schedule.run_pending()
            time.sleep(60)

    def stop(self) -> None:
        self._running = False
        if self._schedule_thread:
            self._schedule_thread.join(timeout=10)
        self.logger.info("调度器已停止")

    def run_once(self, task_name: str = "daily") -> Dict[str, Any]:
        self.logger.info(f"手动执行任务: {task_name}")

        if task_name == "daily":
            return self.run_daily_data_collection()
        elif task_name == "quality_scan":
            return self.run_quality_scan()
        elif task_name == "ticket_recheck":
            return self.run_ticket_recheck()
        elif task_name == "governance_check":
            return self.run_governance_check()
        elif task_name == "daily_report":
            return self.run_report_generation("daily")
        elif task_name == "weekly_report":
            return self.run_report_generation("weekly_compliance")
        else:
            raise ValueError(f"未知任务: {task_name}")

    def get_jobs(self) -> Dict[str, Any]:
        return {
            name: {
                "next_run": job.next_run.isoformat() if job.next_run else None,
                "interval": str(job.interval),
            }
            for name, job in self._jobs.items()
        }
