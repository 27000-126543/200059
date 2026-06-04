#!/usr/bin/env python3
"""
数据质量治理系统 - 单元测试
"""

import sys
import os
import unittest
from datetime import date, timedelta
import tempfile
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dqgovernance import (
    ConfigManager,
    DatabaseManager,
    DQLogger,
    CollectorFactory,
    QualityRuleEngine,
    QualityIssue,
    QualityScore,
    MaskingEngine,
    SensitiveData,
    TicketEngine,
    GovernanceTicket,
    CorrectionEngine,
    LineageEngine,
    GovernanceEngine,
    GovernanceProject,
    ReportEngine,
    SchedulerEngine,
)
from dqgovernance.utils.helpers import (
    generate_id,
    mask_string,
    is_valid_id_card,
    is_valid_phone,
    is_valid_email,
    calculate_priority,
    hash_value,
)


class TestHelpers(unittest.TestCase):
    def test_generate_id(self):
        id1 = generate_id("TEST")
        id2 = generate_id("TEST")
        self.assertTrue(id1.startswith("TEST"))
        self.assertNotEqual(id1, id2)
        self.assertEqual(len(id1), 20)

    def test_mask_string(self):
        result = mask_string("13800138000", visible_start=3, visible_end=4)
        self.assertEqual(result[:3], "138")
        self.assertEqual(result[-4:], "8000")
        self.assertEqual(len(result), 11)

    def test_is_valid_id_card(self):
        self.assertTrue(is_valid_id_card("110101900307123"))
        self.assertTrue(is_valid_id_card("110101199003071233"))
        self.assertFalse(is_valid_id_card("12345678901234567"))
        self.assertFalse(is_valid_id_card(""))

    def test_is_valid_phone(self):
        self.assertTrue(is_valid_phone("13800138000"))
        self.assertFalse(is_valid_phone("12345"))
        self.assertFalse(is_valid_phone(""))

    def test_is_valid_email(self):
        self.assertTrue(is_valid_email("test@example.com"))
        self.assertFalse(is_valid_email("invalid-email"))
        self.assertFalse(is_valid_email(""))

    def test_calculate_priority(self):
        p1 = calculate_priority("critical", 1000, 0.9)
        p2 = calculate_priority("low", 10, 0.1)
        self.assertEqual(p1, "P0")
        self.assertEqual(p2, "P4")

    def test_hash_value(self):
        h1 = hash_value("test123")
        h2 = hash_value("test123")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)


class TestConfigManager(unittest.TestCase):
    def test_singleton(self):
        c1 = ConfigManager()
        c2 = ConfigManager()
        self.assertIs(c1, c2)

    def test_get_config(self):
        config = ConfigManager()
        systems = config.get("business_systems")
        self.assertIsInstance(systems, dict)
        self.assertIn("order_system", systems)

    def test_get_nested_config(self):
        config = ConfigManager()
        threshold = config.get("scoring.pass_threshold", 80)
        self.assertIsInstance(threshold, (int, float))

    def test_get_default(self):
        config = ConfigManager()
        value = config.get("non.existent.key", "default_value")
        self.assertEqual(value, "default_value")


class TestDatabaseManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()
        pass

    @classmethod
    def tearDownClass(cls):
        pass

    def test_insert_and_query(self):
        test_log_id = generate_id("LOG")
        record_id = self.db.insert_record("operation_logs", {
            "log_id": test_log_id,
            "operation_type": "test",
            "system_code": "test_system",
            "data_domain": "测试域",
            "operator": "test_user",
            "details": '{"action": "test_insert"}',
            "ip_address": "127.0.0.1",
        })
        self.assertIsInstance(record_id, int)

        results = self.db.execute_query(
            "SELECT * FROM operation_logs WHERE log_id = ?",
            (test_log_id,)
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["operator"], "test_user")
        self.assertEqual(results[0]["log_id"], test_log_id)

    def test_update_record(self):
        test_log_id = generate_id("LOG")
        record_id = self.db.insert_record("operation_logs", {
            "log_id": test_log_id,
            "operation_type": "update_test",
            "system_code": "test",
            "data_domain": "测试域",
            "operator": "user1",
            "details": '{"action": "test_update", "status": "pending"}',
            "ip_address": "192.168.1.1",
        })

        updated = self.db.update_record(
            "operation_logs",
            {"operator": "user1_updated", "details": '{"action": "test_update", "status": "completed"}'},
            "id = ?",
            (record_id,)
        )
        self.assertIsInstance(updated, int)

        results = self.db.execute_query(
            "SELECT operator, details FROM operation_logs WHERE log_id = ?",
            (test_log_id,)
        )
        self.assertEqual(results[0]["operator"], "user1_updated")
        self.assertIn("completed", results[0]["details"])


class TestDQLogger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()
        pass
        cls.logger = DQLogger()

    @classmethod
    def tearDownClass(cls):
        pass

    def test_log_operation(self):
        self.logger.log_operation(
            operation_type="test_log",
            details={"key": "value", "status": "success"},
            system_code="test_system",
            operator="test_user",
        )

        logs = self.logger.query_logs(operation_type="test_log", limit=1)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["system_code"], "test_system")

    def test_query_logs_with_filters(self):
        self.logger.log_operation(
            operation_type="filter_test",
            details={"status": "success"},
            system_code="sys1",
            operator="user1",
        )

        logs = self.logger.query_logs(
            operation_type="filter_test",
            system_code="sys1",
            operator="user1",
            limit=10,
        )
        self.assertGreaterEqual(len(logs), 1)


class TestCollectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.factory = CollectorFactory()

    def test_get_collector(self):
        collector = self.factory.get_collector("order_system")
        self.assertIsNotNone(collector)
        self.assertEqual(collector.system_code, "order_system")

    def test_get_invalid_collector(self):
        collector = self.factory.get_collector("nonexistent_system")
        self.assertIsNone(collector)

    def test_collect_order_system(self):
        data = self.factory.collect_system("order_system")
        self.assertIsNotNone(data)
        self.assertIn("orders", data)
        self.assertIn("order_items", data)
        self.assertGreater(len(data["orders"]), 0)

    def test_collect_all(self):
        data = self.factory.collect_all()
        self.assertIn("order_system", data)
        self.assertIn("finance_system", data)
        self.assertIn("hr_system", data)


class TestQualityEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = QualityRuleEngine()
        cls.factory = CollectorFactory()
        cls.masking_engine = MaskingEngine()
        cls.test_date = date.today() - timedelta(days=1)

    def test_quality_issue_creation(self):
        issue = QualityIssue(
            issue_type="completeness",
            severity="high",
            description="测试完整性问题",
            system_code="test",
            table_name="test_table",
            field_name="test_field",
            affected_records=10,
        )
        self.assertTrue(issue.issue_code.startswith("ISS"))
        self.assertEqual(issue.issue_type, "completeness")

    def test_quality_score_creation(self):
        score = QualityScore(
            system_code="test",
            table_name="test_table",
            completeness_score=95.0,
            consistency_score=90.0,
            timeliness_score=85.0,
        )
        self.assertAlmostEqual(score.overall_score, 90.0, places=1)

    def test_scan_system(self):
        raw_data = self.factory.collect_system("order_system")
        masked_data, _ = self.masking_engine.scan_and_mask(
            "order_system", raw_data
        )
        result = self.engine.scan_system(
            "order_system", masked_data, scan_date=self.test_date
        )
        self.assertIn("overall_score", result)
        self.assertIn("scores", result)
        self.assertIn("issues", result)
        self.assertGreaterEqual(result["overall_score"], 0)
        self.assertLessEqual(result["overall_score"], 100)


class TestMaskingEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = MaskingEngine()
        cls.factory = CollectorFactory()
        cls.test_date = date.today() - timedelta(days=1)

    def test_sensitive_data_detection(self):
        raw_data = self.factory.collect_system("order_system")
        masked_data, sensitive_records = self.engine.scan_and_mask(
            "order_system", raw_data, scan_date=self.test_date
        )
        self.assertGreater(len(sensitive_records), 0)

        orders_df = masked_data.get("orders")
        if orders_df is not None and len(orders_df) > 0:
            if "customer_phone" in orders_df.columns:
                phone = orders_df["customer_phone"].iloc[0]
                self.assertNotEqual(phone, raw_data["orders"]["customer_phone"].iloc[0])
                self.assertIn("*", phone)

    def test_dynamic_masking_by_dept(self):
        raw_data = self.factory.collect_system("hr_system")

        masked_hr, _ = self.engine.scan_and_mask(
            "hr_system", raw_data, dept="人力资源部", scan_date=self.test_date
        )
        masked_other, _ = self.engine.scan_and_mask(
            "hr_system", raw_data, dept="技术部", scan_date=self.test_date
        )

        emp_df_hr = masked_hr.get("employees")
        emp_df_other = masked_other.get("employees")

        if emp_df_hr is not None and emp_df_other is not None and len(emp_df_hr) > 0:
            if "id_card" in emp_df_hr.columns and "id_card" in emp_df_other.columns:
                self.assertNotEqual(
                    emp_df_hr["id_card"].iloc[0],
                    emp_df_other["id_card"].iloc[0]
                )


class TestTicketEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()
        pass
        cls.engine = TicketEngine()

    @classmethod
    def tearDownClass(cls):
        pass

    def test_ticket_creation(self):
        ticket = GovernanceTicket(
            system_code="test_system",
            title="测试工单",
            description="这是一个测试工单",
            severity="high",
            affected_records=100,
            business_impact=0.5,
        )
        self.assertTrue(ticket.ticket_no.startswith("TKT"))
        self.assertIn(ticket.priority, ["P0", "P1", "P2", "P3", "P4"])
        self.assertEqual(ticket.status, GovernanceTicket.STATUS_PENDING)

    def test_create_tickets_from_issues(self):
        issues = [
            QualityIssue(
                issue_type="completeness",
                severity="high",
                description="字段缺失",
                system_code="test",
                table_name="orders",
                field_name="customer_name",
                affected_records=50,
            ),
            QualityIssue(
                issue_type="consistency",
                severity="medium",
                description="金额不一致",
                system_code="test",
                table_name="orders",
                field_name="order_amount",
                affected_records=150,
            ),
        ]
        tickets = self.engine.create_tickets_from_issues("test_system", issues)
        self.assertEqual(len(tickets), 2)
        self.assertTrue(all(t.ticket_no.startswith("TKT") for t in tickets))


class TestCorrectionEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()
        pass
        cls.engine = CorrectionEngine()

    @classmethod
    def tearDownClass(cls):
        pass

    def test_submit_correction(self):
        result = self.engine.submit_correction(
            system_code="order_system",
            table_name="orders",
            record_id="ORD2024000001",
            field_name="order_amount",
            old_value="999.99",
            new_value="1099.99",
            reason="录入错误",
            applicant="test_user",
            dept="技术部",
        )
        self.assertIn("status", result)
        self.assertIn("request_no", result)


class TestLineageEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()
        pass
        cls.engine = LineageEngine()
        cls.factory = CollectorFactory()
        cls.masking_engine = MaskingEngine()
        cls.test_date = date.today() - timedelta(days=1)

    @classmethod
    def tearDownClass(cls):
        pass

    def test_update_lineage(self):
        self.engine.update_lineage(
            source_system="order_system",
            source_table="orders",
            source_field="order_id",
            target_system="finance_system",
            target_table="payments",
            target_field="order_id",
            transformation_rule="直接关联",
        )

        lineage = self.engine.get_lineage(system_code="order_system")
        self.assertIsInstance(lineage, list)

    def test_mark_quality_status(self):
        result = self.engine.mark_quality_status(
            system_code="order_system",
            table_name="orders",
            quality_status="good",
        )
        self.assertIsInstance(result, bool)
        lineage = self.engine.get_lineage(system_code="order_system", table_name="orders")
        self.assertIsInstance(lineage, list)


class TestGovernanceEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()
        pass
        cls.engine = GovernanceEngine()

    @classmethod
    def tearDownClass(cls):
        pass

    def test_governance_project_creation(self):
        project = GovernanceProject(
            project_name="测试专项治理项目",
            system_code="order_system",
            data_domain="交易数据",
            trigger_reason="连续一个月评分低于80分",
            project_manager="张三",
            target_score=90.0,
        )
        self.assertTrue(project.project_code.startswith("PRJ"))
        self.assertIsNotNone(project.improvement_plan)
        self.assertIn("现状分析", project.improvement_plan)


class TestReportEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()
        pass
        cls.engine = ReportEngine()
        cls.test_date = date.today() - timedelta(days=1)

    @classmethod
    def tearDownClass(cls):
        pass

    def test_generate_daily_report(self):
        report = self.engine.generate_daily_quality_report(
            report_date=self.test_date,
            export_formats=["pdf", "excel"],
        )
        self.assertIn("report_no", report)
        self.assertIn("files", report)
        self.assertIn("pdf", report["files"])
        self.assertIn("excel", report["files"])
        self.assertTrue(os.path.exists(report["files"]["pdf"]))
        self.assertTrue(os.path.exists(report["files"]["excel"]))

    def test_generate_weekly_report(self):
        report = self.engine.generate_weekly_compliance_report(
            report_date=self.test_date,
            export_formats=["pdf", "excel"],
        )
        self.assertIn("report_no", report)
        self.assertIn("files", report)
        self.assertTrue(os.path.exists(report["files"]["pdf"]))
        self.assertTrue(os.path.exists(report["files"]["excel"]))


class TestSchedulerEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()
        cls.factory = CollectorFactory()
        cls.masking_engine = MaskingEngine()
        cls.engine = SchedulerEngine()

    @classmethod
    def tearDownClass(cls):
        pass

    def test_run_quality_scan(self):
        test_date = date.today() + timedelta(days=10)
        self.db.execute_query(
            "DELETE FROM quality_scores WHERE system_code = ? AND scan_date = ?",
            ("finance_system", test_date.isoformat()),
            fetch=False,
        )
        self.db.execute_query(
            "DELETE FROM quality_issues WHERE system_code = ? AND scan_date = ?",
            ("finance_system", test_date.isoformat()),
            fetch=False,
        )
        raw_data = self.factory.collect_system("finance_system")
        masked_data, _ = self.masking_engine.scan_and_mask("finance_system", raw_data)
        quality_engine = QualityRuleEngine()
        result = quality_engine.scan_system("finance_system", masked_data, scan_date=test_date)
        self.assertIn("overall_score", result)
        self.assertIn("scores", result)
        self.assertGreaterEqual(result["overall_score"], 0)

    def test_run_ticket_recheck(self):
        result = self.engine.run_ticket_recheck()
        self.assertIsInstance(result, dict)

    def test_run_governance_check(self):
        result = self.engine.run_governance_check()
        self.assertIn("total_triggered", result)
        self.assertIn("success", result)


def run_tests():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestHelpers,
        TestConfigManager,
        TestDatabaseManager,
        TestDQLogger,
        TestCollectors,
        TestQualityEngine,
        TestMaskingEngine,
        TestTicketEngine,
        TestCorrectionEngine,
        TestLineageEngine,
        TestGovernanceEngine,
        TestReportEngine,
        TestSchedulerEngine,
    ]

    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "="*70)
    print("测试结果汇总")
    print("="*70)
    print(f"总测试数: {result.testsRun}")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")

    if result.failures:
        print("\n失败详情:")
        for test, traceback in result.failures:
            print(f"\n  {test}:")
            print(f"    {traceback.split(chr(10))[0]}")

    if result.errors:
        print("\n错误详情:")
        for test, traceback in result.errors:
            print(f"\n  {test}:")
            print(f"    {traceback.split(chr(10))[0]}")

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
