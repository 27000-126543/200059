from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
import json

from ..utils import ConfigManager, DatabaseManager, generate_id
from ..logging import DQLogger
from ..quality import QualityRuleEngine


class GovernanceProject:
    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_ON_HOLD = "on_hold"

    def __init__(
        self,
        project_name: str,
        system_code: str,
        data_domain: str,
        trigger_reason: str,
        project_manager: str,
        target_score: float = 90.0,
        start_date: Optional[date] = None,
        improvement_plan: Optional[str] = None,
    ):
        self.project_code = generate_id("PRJ")
        self.project_name = project_name
        self.system_code = system_code
        self.data_domain = data_domain
        self.trigger_reason = trigger_reason
        self.project_manager = project_manager
        self.target_score = target_score
        self.start_date = start_date or date.today()
        self.end_date = None
        self.status = self.STATUS_ACTIVE
        self.improvement_plan = improvement_plan or self._generate_improvement_plan()
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def _generate_improvement_plan(self) -> str:
        plan = f"""# 数据质量专项治理项目 - {self.project_name}

## 项目概述
- 项目代码: {self.project_code}
- 涉及系统: {self.system_code}
- 数据域: {self.data_domain}
- 触发原因: {self.trigger_reason}
- 项目经理: {self.project_manager}
- 目标评分: {self.target_score}分

## 治理阶段

### 第一阶段: 现状分析 (第1-2周)
1. 全面数据质量评估
2. 问题根因分析
3. 影响范围评估
4. 利益相关者访谈

### 第二阶段: 方案设计 (第3-4周)
1. 数据标准制定
2. 清洗规则设计
3. 监控指标定义
4. 改进方案评审

### 第三阶段: 实施落地 (第5-8周)
1. 数据清洗执行
2. 流程优化实施
3. 系统改造对接
4. 人员培训

### 第四阶段: 验证巩固 (第9-12周)
1. 效果验证
2. 持续监控
3. 流程固化
4. 项目验收

## 关键里程碑
- 第2周末: 完成现状分析报告
- 第4周末: 确定治理方案
- 第8周末: 完成主要治理工作
- 第12周末: 项目验收，评分达到{self.target_score}分

## 预期成果
1. 数据质量评分提升至{self.target_score}分以上
2. 建立持续监控机制
3. 完善数据标准和流程
4. 提升数据团队能力
"""
        return plan

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_code": self.project_code,
            "project_name": self.project_name,
            "system_code": self.system_code,
            "data_domain": self.data_domain,
            "trigger_reason": self.trigger_reason,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "project_manager": self.project_manager,
            "status": self.status,
            "improvement_plan": self.improvement_plan,
            "target_score": self.target_score,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class GovernanceEngine:
    def __init__(self):
        self.config = ConfigManager()
        self.db = DatabaseManager()
        self.logger = DQLogger()
        self.quality_engine = QualityRuleEngine()
        self.low_score_months = self.config.get("governance.low_score_months", 1)
        self.low_score_threshold = self.config.get("governance.low_score_threshold", 80)
        self.project_managers = self.config.get("governance.project_managers", [])

    def check_and_trigger_special_governance(
        self,
        system_code: Optional[str] = None,
    ) -> List[GovernanceProject]:
        self.logger.info("检查是否需要触发专项治理项目")

        triggered_projects = []
        systems = (
            [system_code]
            if system_code
            else list(self.config.get("business_systems", {}).keys())
        )

        for sys_code in systems:
            try:
                if self._should_trigger_governance(sys_code):
                    project = self._create_governance_project(sys_code)
                    if project:
                        triggered_projects.append(project)
            except Exception as e:
                self.logger.error(
                    f"检查系统 {sys_code} 专项治理触发失败: {e}", exc_info=True
                )

        self.logger.info(
            f"专项治理检查完成，共触发 {len(triggered_projects)} 个项目"
        )
        return triggered_projects

    def _should_trigger_governance(self, system_code: str) -> bool:
        self.logger.info(f"检查系统 {system_code} 是否需要触发专项治理")

        days = self.low_score_months * 30
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        scores = self.quality_engine.get_system_scores(system_code, start_date, end_date)

        if not scores:
            self.logger.warning(f"系统 {system_code} 无历史评分数据，跳过检查")
            return False

        monthly_scores = self._calculate_monthly_average_scores(scores, end_date)

        if len(monthly_scores) < self.low_score_months:
            self.logger.info(
                f"系统 {system_code} 评分数据不足 {self.low_score_months} 个月，跳过检查"
            )
            return False

        recent_scores = list(monthly_scores.values())[-self.low_score_months :]
        all_below_threshold = all(
            score < self.low_score_threshold for score in recent_scores
        )

        existing_projects = self.db.execute_query(
            """SELECT * FROM governance_projects 
               WHERE system_code = ? AND status = 'active'""",
            (system_code,),
        )

        if all_below_threshold and not existing_projects:
            self.logger.warning(
                f"系统 {system_code} 连续 {self.low_score_months} 个月评分低于 "
                f"{self.low_score_threshold}分，需要触发专项治理。"
                f"最近 {len(recent_scores)} 个月评分: {recent_scores}"
            )
            return True
        elif all_below_threshold and existing_projects:
            self.logger.info(
                f"系统 {system_code} 评分持续低于阈值，但已有进行中的治理项目: "
                f"{existing_projects[0]['project_code']}"
            )
            return False
        else:
            self.logger.info(
                f"系统 {system_code} 评分正常，最近 {len(recent_scores)} 个月评分: {recent_scores}"
            )
            return False

    def _calculate_monthly_average_scores(
        self, scores: List[Dict[str, Any]], end_date: date
    ) -> Dict[str, float]:
        monthly_scores = {}

        for score in scores:
            scan_date = score.get("scan_date")
            if isinstance(scan_date, str):
                try:
                    scan_date = date.fromisoformat(scan_date)
                except ValueError:
                    continue

            month_key = f"{scan_date.year}-{scan_date.month:02d}"
            if month_key not in monthly_scores:
                monthly_scores[month_key] = []
            monthly_scores[month_key].append(score.get("overall_score", 0))

        monthly_averages = {}
        for month, scores_list in sorted(monthly_scores.items()):
            monthly_averages[month] = round(sum(scores_list) / len(scores_list), 2)

        return monthly_averages

    def _create_governance_project(self, system_code: str) -> Optional[GovernanceProject]:
        try:
            system_config = self.config.get(f"business_systems.{system_code}", {})
            data_domain = system_config.get("data_domain", "未知域")
            system_name = system_config.get("name", system_code)

            project_manager = self._assign_project_manager(system_code, data_domain)

            trigger_reason = (
                f"系统 {system_name} 连续 {self.low_score_months} 个月"
                f"数据质量评分低于 {self.low_score_threshold} 分，"
                f"触发专项治理项目"
            )

            project_name = f"[{data_domain}] {system_name} 数据质量专项治理"

            project = GovernanceProject(
                project_name=project_name,
                system_code=system_code,
                data_domain=data_domain,
                trigger_reason=trigger_reason,
                project_manager=project_manager,
                target_score=self.low_score_threshold + 10,
            )

            self._save_project(project)

            self.logger.log_operation(
                "governance_project",
                {
                    "project_code": project.project_code,
                    "project_name": project.project_name,
                    "system_code": system_code,
                    "data_domain": data_domain,
                    "trigger_reason": trigger_reason,
                    "project_manager": project_manager,
                    "target_score": project.target_score,
                },
                system_code=system_code,
                data_domain=data_domain,
            )

            self.logger.critical(
                f"已触发专项治理项目: {project.project_code} - {project.project_name}, "
                f"项目经理: {project_manager}"
            )

            return project

        except Exception as e:
            self.logger.error(f"创建专项治理项目失败: {e}", exc_info=True)
            return None

    def _assign_project_manager(
        self, system_code: str, data_domain: str
    ) -> str:
        if not self.project_managers:
            return "未分配"

        existing_projects = self.db.execute_query(
            """SELECT project_manager, COUNT(*) as cnt 
               FROM governance_projects 
               WHERE status = 'active'
               GROUP BY project_manager"""
        )

        workload = {pm: 0 for pm in self.project_managers}
        for proj in existing_projects:
            pm = proj.get("project_manager")
            if pm in workload:
                workload[pm] = proj.get("cnt", 0)

        sorted_managers = sorted(workload.items(), key=lambda x: x[1])
        return sorted_managers[0][0]

    def _save_project(self, project: GovernanceProject):
        existing = self.db.execute_query(
            "SELECT id FROM governance_projects WHERE project_code = ?",
            (project.project_code,),
        )
        if not existing:
            self.db.insert_record("governance_projects", project.to_dict())

    def update_project_status(
        self,
        project_code: str,
        status: str,
        operator: str = "system",
    ) -> bool:
        valid_statuses = [
            GovernanceProject.STATUS_ACTIVE,
            GovernanceProject.STATUS_COMPLETED,
            GovernanceProject.STATUS_CANCELLED,
            GovernanceProject.STATUS_ON_HOLD,
        ]

        if status not in valid_statuses:
            self.logger.error(f"无效的项目状态: {status}")
            return False

        update_data = {
            "status": status,
            "updated_at": datetime.now().isoformat(),
        }

        if status == GovernanceProject.STATUS_COMPLETED:
            update_data["end_date"] = date.today().isoformat()

        try:
            self.db.update_record(
                "governance_projects",
                update_data,
                "project_code = ?",
                (project_code,),
            )

            self.logger.log_operation(
                "governance_project",
                {
                    "project_code": project_code,
                    "new_status": status,
                    "operator": operator,
                },
            )

            self.logger.info(
                f"项目 {project_code} 状态已更新为: {status}"
            )
            return True
        except Exception as e:
            self.logger.error(f"更新项目状态失败: {e}", exc_info=True)
            return False

    def get_projects(
        self,
        system_code: Optional[str] = None,
        status: Optional[str] = None,
        data_domain: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM governance_projects WHERE 1=1"
        params = []

        if system_code:
            query += " AND system_code = ?"
            params.append(system_code)
        if status:
            query += " AND status = ?"
            params.append(status)
        if data_domain:
            query += " AND data_domain = ?"
            params.append(data_domain)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        return self.db.execute_query(query, tuple(params))

    def get_project_progress(self, project_code: str) -> Dict[str, Any]:
        project = self.db.execute_query(
            "SELECT * FROM governance_projects WHERE project_code = ?",
            (project_code,),
        )
        if not project:
            return {"error": "项目不存在"}

        project = project[0]
        system_code = project["system_code"]

        start_date = project["start_date"]
        if isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)

        days_passed = (date.today() - start_date).days
        total_days = 90

        scores = self.quality_engine.get_system_scores(
            system_code, start_date, date.today()
        )

        initial_score = None
        current_score = None
        if scores:
            sorted_scores = sorted(scores, key=lambda x: x["scan_date"])
            initial_score = sorted_scores[0].get("overall_score")
            current_score = sorted_scores[-1].get("overall_score")

        target_score = project.get("target_score", 90)

        score_progress = 0
        if initial_score and current_score:
            if current_score >= target_score:
                score_progress = 100
            else:
                improvement = current_score - initial_score
                target_improvement = target_score - initial_score
                if target_improvement > 0:
                    score_progress = round(improvement / target_improvement * 100, 2)

        time_progress = min(round(days_passed / total_days * 100, 2), 100)

        return {
            "project_code": project_code,
            "project_name": project["project_name"],
            "status": project["status"],
            "start_date": start_date.isoformat(),
            "days_passed": days_passed,
            "time_progress": time_progress,
            "initial_score": initial_score,
            "current_score": current_score,
            "target_score": target_score,
            "score_progress": score_progress,
            "is_on_track": score_progress >= time_progress,
            "project_manager": project["project_manager"],
        }

    def get_governance_statistics(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        query = "SELECT * FROM governance_projects WHERE 1=1"
        params = []

        if start_date:
            query += " AND DATE(start_date) >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND DATE(start_date) <= ?"
            params.append(end_date.isoformat())

        projects = self.db.execute_query(query, tuple(params))

        stats = {
            "total_projects": len(projects),
            "by_status": {},
            "by_domain": {},
            "by_system": {},
            "completed_on_time": 0,
            "avg_score_improvement": 0.0,
        }

        for proj in projects:
            status = proj["status"]
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1

            domain = proj.get("data_domain", "未知域")
            stats["by_domain"][domain] = stats["by_domain"].get(domain, 0) + 1

            system = proj["system_code"]
            stats["by_system"][system] = stats["by_system"].get(system, 0) + 1

        return stats
