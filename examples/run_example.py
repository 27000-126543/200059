#!/usr/bin/env python3
"""
数据质量治理系统 - 完整示例运行脚本
演示系统的主要功能流程
"""

import sys
import os
from datetime import date, timedelta
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


def print_separator(title: str):
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80 + "\n")


def main():
    print("""
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║           数据质量治理系统 - 完整功能演示                         ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
    """)

    print_separator("步骤 1: 系统初始化")

    config = ConfigManager()
    db = DatabaseManager()
    logger = DQLogger()

    logger.info("示例脚本 - 系统初始化完成")

    print("✓ 配置管理器已初始化")
    print(f"  - 业务系统: {list(config.get('business_systems').keys())}")
    print("✓ 数据库已初始化")
    print("✓ 日志系统已启动")

    print_separator("步骤 2: 数据采集")

    factory = CollectorFactory()
    process_date = date.today() - timedelta(days=1)

    print(f"采集日期: {process_date}")

    raw_data = factory.collect_all(
        start_date=process_date,
        end_date=process_date + timedelta(days=1),
    )

    for system_code, system_data in raw_data.items():
        total_records = sum(len(df) for df in system_data.values())
        print(f"\n  ✓ {system_code}:")
        for table_name, df in system_data.items():
            print(f"    - {table_name}: {len(df)} 条记录")
            if len(df) > 0:
                print(f"      字段: {list(df.columns[:5])}...")
        print(f"    总计: {total_records} 条记录")

    all_masked_data = {}

    print_separator("步骤 3: 敏感数据识别与脱敏")

    masking_engine = MaskingEngine()
    all_sensitive_data = []

    for system_code, system_data in raw_data.items():
        print(f"\n处理 {system_code} 的敏感数据...")
        masked_data, sensitive_records = masking_engine.scan_and_mask(
            system_code, system_data, scan_date=process_date
        )

        all_masked_data[system_code] = masked_data

        for sensitive in sensitive_records:
            all_sensitive_data.append(sensitive)
            s_dict = sensitive.to_dict()
            print(f"  ✓ {s_dict['field_name']} ({s_dict['data_type']}): "
                  f"{s_dict['record_count']} 条记录, 脱敏方式: {s_dict['masking_method']}")

        if sensitive_records and system_code == "order_system":
            orders_df = masked_data.get('orders')
            if orders_df is not None and len(orders_df) > 0:
                print(f"\n  脱敏示例 (orders 表):")
                if 'customer_phone' in orders_df.columns:
                    print(f"    customer_phone: {orders_df['customer_phone'].iloc[0]}")
                if 'customer_id_card' in orders_df.columns:
                    print(f"    customer_id_card: {orders_df['customer_id_card'].iloc[0]}")

    print_separator("步骤 4: 数据质量扫描")

    quality_engine = QualityRuleEngine()
    all_scores = []
    all_issues = []

    for system_code, system_data in raw_data.items():
        print(f"\n扫描 {system_code} 的数据质量...")

        masked_data = all_masked_data[system_code]

        scan_result = quality_engine.scan_system(
            system_code, masked_data, scan_date=process_date
        )

        print(f"  综合评分: {scan_result['overall_score']:.2f}")
        print(f"  问题数量: {len(scan_result['issues'])}")

        for score in scan_result["scores"]:
            all_scores.append(score)
            print(f"\n    - {score.table_name}:")
            print(f"      完整性: {score.completeness_score:.2f}")
            print(f"      一致性: {score.consistency_score:.2f}")
            print(f"      时效性: {score.timeliness_score:.2f}")
            print(f"      综合: {score.overall_score:.2f}")

        for issue in scan_result["issues"]:
            all_issues.append(issue)

        if scan_result["issues"]:
            print(f"\n  主要问题 (前5个):")
            for issue in scan_result["issues"][:5]:
                print(f"    - [{issue.severity}] {issue.issue_type}: {issue.description[:60]}...")
                print(f"      表: {issue.table_name}, 影响: {issue.affected_records} 条")

    print_separator("步骤 5: 数据血缘更新")

    lineage_engine = LineageEngine()

    for system_code, system_data in raw_data.items():
        masked_data = all_masked_data[system_code]

        for table_name in masked_data.keys():
            lineage_engine.update_lineage(system_code, table_name)

        scan_result = quality_engine.scan_system(
            system_code, masked_data, scan_date=process_date
        )

        for score in scan_result["scores"]:
            if score.overall_score >= 90:
                quality_status = "excellent"
            elif score.overall_score >= 80:
                quality_status = "good"
            elif score.overall_score >= 60:
                quality_status = "warning"
            else:
                quality_status = "critical"
            lineage_engine.mark_quality_status(
                system_code,
                score.table_name,
                quality_status=quality_status,
            )

    print("✓ 数据血缘已更新")
    print("✓ 质量状态已标记")

    print("\n数据血缘图:")
    graph = lineage_engine.get_lineage_graph("order_system")
    for node in graph.get('nodes', []):
        print(f"  - {node}: {graph.get('edges', [])}")

    print_separator("步骤 6: 自动生成治理工单")

    ticket_engine = TicketEngine()

    if all_issues:
        tickets = ticket_engine.create_tickets_from_issues(
            "order_system", all_issues
        )
        print(f"✓ 已创建 {len(tickets)} 张治理工单")

        for ticket in tickets[:5]:
            t_dict = ticket.to_dict()
            print(f"\n  {t_dict['ticket_no']}: {t_dict['title'][:50]}...")
            print(f"    优先级: {t_dict['priority']}, 严重程度: {t_dict['severity']}")
            print(f"    处理人: {t_dict['assignee']}, 部门: {t_dict['dept']}")
            print(f"    SLA: {t_dict['sla_hours']} 小时")

        if len(tickets) > 0:
            sample_ticket = tickets[0]
            print(f"\n模拟解决工单: {sample_ticket.ticket_no}")
            ticket_engine.update_ticket_status(
                sample_ticket.ticket_no,
                "resolved",
                operator="test_user",
                resolution="已修复数据问题，补充了缺失的字段值",
            )
            print("✓ 工单已标记为已解决")

            recheck_result = ticket_engine.recheck_ticket(sample_ticket.ticket_no)
            print(f"✓ 复检结果: {recheck_result.get('status')}")

    print_separator("步骤 7: 数据订正申请")

    correction_engine = CorrectionEngine()

    print("提交数据订正申请...")
    correction_result = correction_engine.submit_correction(
        system_code="order_system",
        table_name="orders",
        record_id="ORD2024000001",
        field_name="order_amount",
        old_value="999.99",
        new_value="1099.99",
        reason="订单金额录入错误，实际应为1099.99元",
        applicant="张三",
        dept="交易部",
    )

    print(f"\n申请编号: {correction_result.get('request_no')}")
    print(f"状态: {correction_result.get('status')}")
    if correction_result.get('errors'):
        print(f"校验错误:")
        for err in correction_result['errors']:
            print(f"  - {err}")

    print_separator("步骤 8: 专项治理检查")

    governance_engine = GovernanceEngine()

    print("检查是否需要触发专项治理...")
    governance_projects = governance_engine.check_and_trigger_special_governance()

    print(f"是否触发: {len(governance_projects) > 0}")
    if governance_projects:
        for proj in governance_projects:
            print(f"\n  ✓ 专项治理项目已创建:")
            print(f"    项目代码: {proj.project_code}")
            print(f"    项目名称: {proj.project_name}")
            print(f"    项目经理: {proj.project_manager}")
            print(f"    目标评分: {proj.target_score} 分")
            print(f"    改善计划已生成 (共 {len(proj.improvement_plan)} 字符)")

    print_separator("步骤 9: 生成报告")

    report_engine = ReportEngine()

    print("生成每日数据质量报告...")
    daily_report = report_engine.generate_daily_quality_report(
        report_date=process_date
    )
    print(f"\n✓ 每日质量报告已生成")
    print(f"  报告编号: {daily_report['report_no']}")
    for fmt, path in daily_report['files'].items():
        print(f"  {fmt.upper()}: {os.path.abspath(path)}")

    print("\n生成每周合规报告...")
    weekly_report = report_engine.generate_weekly_compliance_report(
        report_date=process_date
    )
    print(f"\n✓ 每周合规报告已生成")
    print(f"  报告编号: {weekly_report['report_no']}")
    for fmt, path in weekly_report['files'].items():
        print(f"  {fmt.upper()}: {os.path.abspath(path)}")

    print_separator("步骤 10: 日志查询")

    print("查询最近的操作日志...")
    recent_logs = logger.query_logs(limit=10)
    print(f"\n共找到 {len(recent_logs)} 条日志")
    for log in recent_logs[:5]:
        print(f"\n  [{log['created_at']}] {log['operation_type']}")
        print(f"    系统: {log['system_code']}, 操作人: {log['operator']}")

    print_separator("步骤 11: 脱敏覆盖率统计")

    coverage = masking_engine.get_masking_coverage(process_date)
    print(f"脱敏覆盖率: {coverage.get('coverage_rate', 0):.2%}")
    print(f"总敏感字段: {coverage.get('total_sensitive_fields', 0)}")
    print(f"已脱敏字段: {coverage.get('masked_fields', 0)}")
    if coverage.get('by_type'):
        print("\n按类型统计:")
        for dtype, stats in coverage['by_type'].items():
            print(f"  {dtype}: {stats.get('masked', 0)}/{stats.get('total', 0)} "
                  f"({stats.get('rate', 0):.1%})")

    print_separator("步骤 12: 工单批量导出")

    export_path = ticket_engine.export_tickets(
        output_path="./tickets_export.csv",
        format="csv",
        start_date=process_date - timedelta(days=7),
        end_date=process_date,
    )
    if export_path:
        print(f"✓ 工单已导出: {os.path.abspath(export_path)}")
    else:
        print("✓ 无可导出的工单数据")

    print("""
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║                    演示完成！感谢使用                             ║
║                                                                   ║
║  您可以通过以下命令继续探索系统功能:                              ║
║                                                                   ║
║    python main.py --help              查看所有命令                ║
║    python main.py run --task daily    运行完整每日流程           ║
║    python main.py collect             采集数据                    ║
║    python main.py scan                质量扫描                    ║
║    python main.py reports --type daily 生成日报                   ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
    """)


if __name__ == "__main__":
    main()
