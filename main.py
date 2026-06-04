#!/usr/bin/env python3
"""
企业级数据质量自动化监控与治理闭环系统
主入口程序
"""

import argparse
import sys
import os
from datetime import date, timedelta
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dqgovernance import (
    ConfigManager,
    DatabaseManager,
    DQLogger,
    SchedulerEngine,
    CollectorFactory,
    QualityRuleEngine,
    MaskingEngine,
    TicketEngine,
    CorrectionEngine,
    LineageEngine,
    GovernanceEngine,
    ReportEngine,
)
from dqgovernance.utils.helpers import generate_id


def print_banner():
    banner = """
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║      企业级数据质量自动化监控与治理闭环系统 (DQ Governance)       ║
║                                                                   ║
║      Version 1.0.0                                                ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
    """
    print(banner)


def init_system():
    config = ConfigManager()
    db = DatabaseManager()
    logger = DQLogger()

    db.init_database()

    logger.info("系统初始化完成")
    print("✓ 系统初始化完成")
    print(f"  - 配置文件已加载: {config.get('business_systems')}")
    print(f"  - 数据库已初始化")
    print(f"  - 日志系统已启动")

    return config, db, logger


def cmd_run(args):
    print_banner()
    init_system()

    scheduler = SchedulerEngine()

    if args.daemon:
        print("\n启动守护模式，按 Ctrl+C 停止...")
        scheduler.start()
        try:
            while True:
                import time
                time.sleep(3600)
        except KeyboardInterrupt:
            print("\n正在停止调度器...")
            scheduler.stop()
            print("调度器已停止")
    elif args.task:
        result = scheduler.run_once(args.task)
        print_task_result(args.task, result)
    else:
        result = scheduler.run_once("daily")
        print_task_result("daily", result)


def print_task_result(task_name: str, result: dict):
    print(f"\n{'='*60}")
    print(f"任务执行结果: {task_name}")
    print(f"{'='*60}")
    print(f"状态: {result.get('status', 'unknown')}")

    if task_name == "daily":
        print(f"处理日期: {result.get('process_date')}")
        print(f"耗时: {result.get('duration_seconds', 0):.2f} 秒")
        print(f"\n各系统处理情况:")
        for sys_code, sys_info in result.get('systems', {}).items():
            print(f"\n  {sys_code}:")
            print(f"    数据表: {', '.join(sys_info.get('tables', []))}")
            print(f"    记录数: {sys_info.get('total_records', 0)}")
            print(f"    质量评分: {sys_info.get('quality_score', 0):.2f}")
            print(f"    问题数量: {sys_info.get('issue_count', 0)}")
            print(f"    敏感字段: {sys_info.get('sensitive_fields', 0)}")
            print(f"    工单创建: {sys_info.get('tickets_created', 0)}")

        if 'daily_report' in result:
            report = result['daily_report']
            print(f"\n  每日报告:")
            for fmt, path in report.get('files', {}).items():
                print(f"    {fmt.upper()}: {path}")

        if 'special_governance' in result:
            sg = result['special_governance']
            print(f"\n  专项治理:")
            print(f"    触发: {sg.get('triggered', False)}")
            if sg.get('triggered'):
                for proj in sg.get('projects', []):
                    print(f"    - {proj.project_code}: {proj.project_name}")
                    print(f"      项目经理: {proj.project_manager}")

    if result.get('error'):
        print(f"\n错误信息: {result['error']}")


def cmd_collect(args):
    print_banner()
    init_system()

    factory = CollectorFactory()

    if args.system:
        data = factory.collect_system(args.system)
        if data:
            print(f"\n✓ 采集完成: {args.system}")
            for table_name, df in data.items():
                print(f"  - {table_name}: {len(df)} 条记录")
    else:
        data = factory.collect_all()
        print(f"\n✓ 全部系统采集完成")
        for sys_code, sys_data in data.items():
            print(f"\n  {sys_code}:")
            for table_name, df in sys_data.items():
                print(f"    - {table_name}: {len(df)} 条记录")


def cmd_scan(args):
    print_banner()
    init_system()

    scheduler = SchedulerEngine()
    results = scheduler.run_quality_scan(system_code=args.system)

    print(f"\n{'='*60}")
    print("质量扫描结果")
    print(f"{'='*60}")

    for sys_code, result in results.items():
        print(f"\n{sys_code}:")
        print(f"  综合评分: {result['overall_score']:.2f}")
        print(f"  问题数量: {len(result['issues'])}")
        print(f"  详细评分:")
        for score in result['scores']:
            print(f"    - {score.table_name}:")
            print(f"      完整性: {score.completeness_score:.2f}")
            print(f"      一致性: {score.consistency_score:.2f}")
            print(f"      时效性: {score.timeliness_score:.2f}")
            print(f"      综合: {score.overall_score:.2f}")

        if result['issues']:
            print(f"  问题列表:")
            for issue in result['issues'][:10]:
                print(f"    - [{issue.severity}] {issue.issue_type}: {issue.description}")
                print(f"      表: {issue.table_name}, 影响记录: {issue.affected_records}")
            if len(result['issues']) > 10:
                print(f"    ... 还有 {len(result['issues']) - 10} 个问题")


def cmd_tickets(args):
    print_banner()
    _, db, _ = init_system()

    if args.list:
        tickets = db.execute_query(
            "SELECT * FROM governance_tickets ORDER BY created_at DESC LIMIT 50"
        )
        print(f"\n{'='*60}")
        print("治理工单列表")
        print(f"{'='*60}")
        for t in tickets:
            print(f"\n  {t['ticket_no']} - {t['title']}")
            print(f"    状态: {t['status']}, 优先级: {t['priority']}, 处理人: {t['assignee']}")
            print(f"    系统: {t['system_code']}, 创建时间: {t['created_at']}")

    elif args.export:
        ticket_engine = TicketEngine()
        output_path = ticket_engine.export_tickets(
            output_format=args.format,
            start_date=args.start_date,
            end_date=args.end_date,
            system_code=args.system,
            status=args.status,
        )
        print(f"\n✓ 工单已导出: {output_path}")

    elif args.recheck:
        scheduler = SchedulerEngine()
        result = scheduler.run_ticket_recheck()
        print(f"\n✓ 复检完成")
        print(f"  已检查: {result.get('checked', 0)}")
        print(f"  已验证: {result.get('verified', 0)}")
        print(f"  已重开: {result.get('reopened', 0)}")


def cmd_correction(args):
    print_banner()
    init_system()

    correction_engine = CorrectionEngine()

    if args.submit:
        result = correction_engine.submit_correction(
            system_code=args.system,
            table_name=args.table,
            record_id=args.record_id,
            field_name=args.field,
            old_value=args.old_value,
            new_value=args.new_value,
            reason=args.reason,
            applicant=args.applicant or "current_user",
        )
        print(f"\n{'='*60}")
        print("数据订正结果")
        print(f"{'='*60}")
        print(f"申请编号: {result.get('request_no')}")
        print(f"状态: {result.get('status')}")
        if result.get('errors'):
            print(f"校验错误:")
            for err in result['errors']:
                print(f"  - {err}")

    elif args.list:
        _, db, _ = init_system()
        requests = db.execute_query(
            "SELECT * FROM correction_requests ORDER BY created_at DESC LIMIT 50"
        )
        print(f"\n{'='*60}")
        print("订正申请列表")
        print(f"{'='*60}")
        for r in requests:
            print(f"\n  {r['request_no']}")
            print(f"    {r['system_code']}.{r['table_name']}.{r['field_name']}")
            print(f"    {r['old_value']} -> {r['new_value']}")
            print(f"    状态: {r['status']}, 申请人: {r['applicant']}")


def cmd_reports(args):
    print_banner()
    init_system()

    scheduler = SchedulerEngine()

    if args.type == "daily":
        report_date = None
        if args.date:
            from datetime import datetime
            report_date = datetime.strptime(args.date, "%Y-%m-%d").date()

        result = scheduler.run_report_generation("daily", report_date)
        print(f"\n✓ 每日质量报告已生成")
        print(f"  报告编号: {result['report_no']}")
        for fmt, path in result['files'].items():
            print(f"  {fmt.upper()}: {path}")

    elif args.type == "weekly":
        result = scheduler.run_report_generation("weekly_compliance")
        print(f"\n✓ 每周合规报告已生成")
        print(f"  报告编号: {result['report_no']}")
        for fmt, path in result['files'].items():
            print(f"  {fmt.upper()}: {path}")


def cmd_logs(args):
    print_banner()
    _, db, logger = init_system()

    if args.query:
        results = logger.query_logs(
            operation_type=args.operation_type,
            system_code=args.system,
            operator=args.operator,
            start_date=args.start_date,
            end_date=args.end_date,
            limit=args.limit,
        )
        print(f"\n{'='*60}")
        print(f"查询结果: 共 {len(results)} 条记录")
        print(f"{'='*60}")
        for log in results:
            print(f"\n  [{log['operation_time']}] {log['operation_type']}")
            print(f"    系统: {log['system_code']}, 操作人: {log['operator']}, 状态: {log['status']}")
            if log.get('error_message'):
                print(f"    错误: {log['error_message']}")

    elif args.export:
        output_path = logger.export_logs(
            output_format=args.format,
            start_date=args.start_date,
            end_date=args.end_date,
            operation_type=args.operation_type,
            system_code=args.system,
        )
        print(f"\n✓ 日志已导出: {output_path}")


def cmd_lineage(args):
    print_banner()
    init_system()

    lineage_engine = LineageEngine()

    if args.graph:
        graph = lineage_engine.get_lineage_graph(args.system)
        print(f"\n{'='*60}")
        print(f"数据血缘图 - {args.system or '全部'}")
        print(f"{'='*60}")
        for node in graph.get('nodes', []):
            print(f"\n  {node['id']} ({node['type']})")
            print(f"    质量状态: {node.get('quality_status', 'unknown')}")
            print(f"    最后更新: {node.get('last_updated', 'N/A')}")

        for edge in graph.get('edges', []):
            print(f"\n  {edge['source']} -> {edge['target']}")
            print(f"    关系: {edge['relationship']}")

    elif args.impact:
        impact = lineage_engine.get_impact_analysis(args.system, args.table)
        print(f"\n{'='*60}")
        print(f"影响分析 - {args.system}.{args.table}")
        print(f"{'='*60}")
        print(f"直接影响: {impact.get('direct_impact_count', 0)} 个下游对象")
        print(f"间接影响: {impact.get('indirect_impact_count', 0)} 个下游对象")
        if impact.get('downstream_objects'):
            print(f"\n下游对象:")
            for obj in impact['downstream_objects'][:20]:
                print(f"  - {obj['id']} ({obj['type']})")


def cmd_governance(args):
    print_banner()
    init_system()

    scheduler = SchedulerEngine()
    governance_engine = GovernanceEngine()

    if args.check:
        result = scheduler.run_governance_check()
        print(f"\n{'='*60}")
        print("专项治理检查结果")
        print(f"{'='*60}")
        print(f"是否触发: {result.get('triggered', False)}")
        if result.get('triggered'):
            for proj in result.get('projects', []):
                print(f"\n  项目代码: {proj.project_code}")
                print(f"  项目名称: {proj.project_name}")
                print(f"  项目经理: {proj.project_manager}")
                print(f"  目标评分: {proj.target_score}")
                print(f"  改善计划已生成")

    elif args.list:
        _, db, _ = init_system()
        projects = db.execute_query(
            "SELECT * FROM governance_projects ORDER BY created_at DESC"
        )
        print(f"\n{'='*60}")
        print("治理项目列表")
        print(f"{'='*60}")
        for p in projects:
            print(f"\n  {p['project_code']} - {p['project_name']}")
            print(f"    状态: {p['status']}, 系统: {p['system_code']}")
            print(f"    项目经理: {p['project_manager']}, 目标评分: {p['target_score']}")
            print(f"    开始日期: {p['start_date']}")

    elif args.progress:
        progress = governance_engine.get_project_progress(args.project_code)
        print(f"\n{'='*60}")
        print(f"项目进度 - {args.project_code}")
        print(f"{'='*60}")
        for key, value in progress.items():
            if isinstance(value, float):
                print(f"  {key}: {value:.2f}")
            else:
                print(f"  {key}: {value}")


def cmd_masking(args):
    print_banner()
    init_system()

    masking_engine = MaskingEngine()

    if args.coverage:
        coverage = masking_engine.get_masking_coverage(args.date)
        print(f"\n{'='*60}")
        print(f"脱敏覆盖率统计 - {args.date or '今日'}")
        print(f"{'='*60}")
        print(f"总敏感字段: {coverage.get('total_sensitive_fields', 0)}")
        print(f"已脱敏字段: {coverage.get('masked_fields', 0)}")
        print(f"脱敏覆盖率: {coverage.get('coverage_rate', 0):.2%}")
        if coverage.get('by_type'):
            print(f"\n按类型统计:")
            for dtype, stats in coverage['by_type'].items():
                print(f"  {dtype}: {stats.get('masked', 0)}/{stats.get('total', 0)}")

    elif args.anomalies:
        anomalies = masking_engine.get_access_anomalies(
            start_date=args.start_date,
            end_date=args.end_date,
        )
        print(f"\n{'='*60}")
        print(f"敏感数据访问异常 - {len(anomalies)} 条")
        print(f"{'='*60}")
        for a in anomalies:
            print(f"\n  [{a['timestamp']}] {a['user']}")
            print(f"    系统: {a['system_code']}, 字段: {a['field_name']}")
            print(f"    异常类型: {a['anomaly_type']}")
            print(f"    描述: {a['description']}")


def main():
    parser = argparse.ArgumentParser(
        description="企业级数据质量自动化监控与治理闭环系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    run_parser = subparsers.add_parser("run", help="运行调度任务")
    run_parser.add_argument("--daemon", action="store_true", help="以守护进程模式运行")
    run_parser.add_argument("--task", choices=[
        "daily", "quality_scan", "ticket_recheck",
        "governance_check", "daily_report", "weekly_report"
    ], help="执行指定任务")

    collect_parser = subparsers.add_parser("collect", help="数据采集")
    collect_parser.add_argument("--system", help="指定系统代码")

    scan_parser = subparsers.add_parser("scan", help="质量扫描")
    scan_parser.add_argument("--system", help="指定系统代码")

    tickets_parser = subparsers.add_parser("tickets", help="工单管理")
    tickets_parser.add_argument("--list", action="store_true", help="列出工单")
    tickets_parser.add_argument("--export", action="store_true", help="导出工单")
    tickets_parser.add_argument("--recheck", action="store_true", help="执行复检")
    tickets_parser.add_argument("--format", default="excel", choices=["excel", "csv", "json"])
    tickets_parser.add_argument("--start-date", help="开始日期 YYYY-MM-DD")
    tickets_parser.add_argument("--end-date", help="结束日期 YYYY-MM-DD")
    tickets_parser.add_argument("--system", help="系统代码")
    tickets_parser.add_argument("--status", help="工单状态")

    correction_parser = subparsers.add_parser("correction", help="数据订正")
    correction_parser.add_argument("--submit", action="store_true", help="提交订正申请")
    correction_parser.add_argument("--list", action="store_true", help="列出申请")
    correction_parser.add_argument("--system", required=False, help="系统代码")
    correction_parser.add_argument("--table", help="表名")
    correction_parser.add_argument("--record-id", help="记录ID")
    correction_parser.add_argument("--field", help="字段名")
    correction_parser.add_argument("--old-value", help="原值")
    correction_parser.add_argument("--new-value", help="新值")
    correction_parser.add_argument("--reason", help="订正原因")
    correction_parser.add_argument("--applicant", help="申请人")

    reports_parser = subparsers.add_parser("reports", help="报告管理")
    reports_parser.add_argument("--type", required=True, choices=["daily", "weekly"], help="报告类型")
    reports_parser.add_argument("--date", help="报告日期 YYYY-MM-DD")

    logs_parser = subparsers.add_parser("logs", help="日志查询")
    logs_parser.add_argument("--query", action="store_true", help="查询日志")
    logs_parser.add_argument("--export", action="store_true", help="导出日志")
    logs_parser.add_argument("--format", default="excel", choices=["excel", "csv", "json"])
    logs_parser.add_argument("--operation-type", help="操作类型")
    logs_parser.add_argument("--system", help="系统代码")
    logs_parser.add_argument("--operator", help="操作人")
    logs_parser.add_argument("--start-date", help="开始日期 YYYY-MM-DD")
    logs_parser.add_argument("--end-date", help="结束日期 YYYY-MM-DD")
    logs_parser.add_argument("--limit", type=int, default=100, help="返回数量限制")

    lineage_parser = subparsers.add_parser("lineage", help="数据血缘")
    lineage_parser.add_argument("--graph", action="store_true", help="查看血缘图")
    lineage_parser.add_argument("--impact", action="store_true", help="影响分析")
    lineage_parser.add_argument("--system", help="系统代码")
    lineage_parser.add_argument("--table", help="表名")

    governance_parser = subparsers.add_parser("governance", help="专项治理")
    governance_parser.add_argument("--check", action="store_true", help="检查并触发专项治理")
    governance_parser.add_argument("--list", action="store_true", help="列出治理项目")
    governance_parser.add_argument("--progress", action="store_true", help="查看项目进度")
    governance_parser.add_argument("--project-code", help="项目代码")

    masking_parser = subparsers.add_parser("masking", help="脱敏管理")
    masking_parser.add_argument("--coverage", action="store_true", help="查看脱敏覆盖率")
    masking_parser.add_argument("--anomalies", action="store_true", help="查看访问异常")
    masking_parser.add_argument("--date", help="日期 YYYY-MM-DD")
    masking_parser.add_argument("--start-date", help="开始日期 YYYY-MM-DD")
    masking_parser.add_argument("--end-date", help="结束日期 YYYY-MM-DD")

    args = parser.parse_args()

    if args.command is None:
        print_banner()
        parser.print_help()
        return

    commands = {
        "run": cmd_run,
        "collect": cmd_collect,
        "scan": cmd_scan,
        "tickets": cmd_tickets,
        "correction": cmd_correction,
        "reports": cmd_reports,
        "logs": cmd_logs,
        "lineage": cmd_lineage,
        "governance": cmd_governance,
        "masking": cmd_masking,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
