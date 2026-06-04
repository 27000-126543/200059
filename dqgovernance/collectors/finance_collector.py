from datetime import datetime, date, timedelta
from typing import Optional
import pandas as pd
import random
from faker import Faker

from .base import MockBaseCollector


class FinanceCollector(MockBaseCollector):
    def __init__(self):
        super().__init__("finance_system")
        self.register_mock_generator("general_ledger", self._generate_general_ledger)
        self.register_mock_generator("expense_reports", self._generate_expense_reports)
        self.register_mock_generator("invoices", self._generate_invoices)

    def _generate_general_ledger(
        self, start_date: date, end_date: date
    ) -> pd.DataFrame:
        fake = Faker("zh_CN")
        date_range = (end_date - start_date).days + 1
        records_per_day = random.randint(30, 80)

        accounts = [
            ("1001", "银行存款", "asset"),
            ("1002", "应收账款", "asset"),
            ("1003", "库存商品", "asset"),
            ("2001", "应付账款", "liability"),
            ("2002", "应付职工薪酬", "liability"),
            ("3001", "实收资本", "equity"),
            ("4001", "主营业务收入", "revenue"),
            ("5001", "主营业务成本", "expense"),
            ("5002", "管理费用", "expense"),
            ("5003", "销售费用", "expense"),
        ]

        data = []
        voucher_id = 1

        for day_offset in range(date_range):
            current_date = start_date + timedelta(days=day_offset)
            for _ in range(records_per_day):
                account = random.choice(accounts)
                is_debit = random.choice([True, False])
                amount = round(random.uniform(100, 50000), 2)

                entry = {
                    "id": voucher_id,
                    "voucher_no": f"VOUCH{current_date.strftime('%Y%m%d')}{voucher_id:04d}",
                    "account_code": account[0],
                    "account_name": account[1],
                    "account_type": account[2],
                    "debit": amount if is_debit else 0,
                    "credit": 0 if is_debit else amount,
                    "balance": round(random.uniform(0, 1000000), 2),
                    "currency": "CNY",
                    "department": random.choice(["财务部", "销售部", "技术部", "行政部", "人力资源部"]),
                    "operator": fake.name(),
                    "description": fake.sentence(nb_words=10),
                    "posting_date": datetime.combine(current_date, datetime.min.time()),
                    "created_at": datetime.combine(current_date, datetime.min.time()),
                    "updated_at": datetime.now(),
                    "status": random.choice(["posted", "draft", "reversed"]),
                }

                if random.random() < 0.02:
                    entry["operator"] = None
                if random.random() < 0.03:
                    entry["description"] = ""

                data.append(entry)
                voucher_id += 1

        df = pd.DataFrame(data)

        if random.random() < 0.1:
            idx = random.sample(range(len(df)), int(len(df) * 0.02))
            for i in idx:
                df.loc[i, "debit"] = round(random.uniform(100, 10000), 2)
                df.loc[i, "credit"] = round(random.uniform(100, 10000), 2)

        return df

    def _generate_expense_reports(
        self, start_date: date, end_date: date
    ) -> pd.DataFrame:
        fake = Faker("zh_CN")
        date_range = (end_date - start_date).days + 1
        records_per_day = random.randint(10, 30)

        expense_types = ["差旅费", "餐饮费", "交通费", "办公费", "招待费", "通讯费", "培训费"]

        data = []
        report_id = 1

        for day_offset in range(date_range):
            current_date = start_date + timedelta(days=day_offset)
            for _ in range(records_per_day):
                amount = round(random.uniform(50, 5000), 2)
                created_at = datetime.combine(
                    current_date,
                    datetime.min.time().replace(
                        hour=random.randint(9, 18), minute=random.randint(0, 59)
                    ),
                )

                report = {
                    "id": report_id,
                    "report_no": f"EXP{report_id:06d}",
                    "employee_id": random.randint(1000, 9999),
                    "employee_name": fake.name(),
                    "employee_id_card": fake.ssn(),
                    "employee_phone": fake.phone_number(),
                    "department": random.choice(["财务部", "销售部", "技术部", "行政部", "人力资源部"]),
                    "expense_type": random.choice(expense_types),
                    "amount": amount,
                    "currency": "CNY",
                    "start_date": current_date - timedelta(days=random.randint(0, 7)),
                    "end_date": current_date,
                    "purpose": fake.sentence(nb_words=8),
                    "invoice_no": f"INV{random.randint(100000, 999999)}" if random.random() > 0.1 else "",
                    "bank_card_no": fake.credit_card_number(),
                    "status": random.choice(["draft", "submitted", "approved", "rejected", "paid"]),
                    "approver": fake.name() if random.random() > 0.3 else "",
                    "created_at": created_at,
                    "approved_at": created_at + timedelta(hours=random.randint(1, 72))
                    if random.random() > 0.2 else None,
                    "paid_at": None,
                    "updated_at": datetime.now(),
                    "remark": "",
                }

                if report["status"] == "paid" and report["approved_at"] is not None:
                    report["paid_at"] = report["approved_at"] + timedelta(days=random.randint(1, 7))

                if random.random() < 0.02:
                    report["employee_phone"] = None
                if random.random() < 0.03:
                    report["amount"] = None

                data.append(report)
                report_id += 1

        return pd.DataFrame(data)

    def _generate_invoices(
        self, start_date: date, end_date: date
    ) -> pd.DataFrame:
        fake = Faker("zh_CN")
        date_range = (end_date - start_date).days + 1
        records_per_day = random.randint(20, 50)

        invoice_types = ["增值税专用发票", "增值税普通发票", "电子发票"]

        data = []
        invoice_id = 1

        for day_offset in range(date_range):
            current_date = start_date + timedelta(days=day_offset)
            for _ in range(records_per_day):
                amount = round(random.uniform(100, 100000), 2)
                tax_amount = round(amount * 0.13, 2)
                total_amount = amount + tax_amount

                invoice = {
                    "id": invoice_id,
                    "invoice_no": f"INV{current_date.strftime('%Y%m%d')}{invoice_id:05d}",
                    "invoice_code": f"{random.randint(100000000000, 999999999999)}",
                    "invoice_type": random.choice(invoice_types),
                    "buyer_name": fake.company(),
                    "buyer_tax_id": f"{random.randint(100000000000000000, 999999999999999999)}",
                    "buyer_address": fake.address(),
                    "buyer_phone": fake.phone_number(),
                    "buyer_bank": fake.company() + "银行",
                    "buyer_bank_account": fake.credit_card_number(),
                    "seller_name": "XX有限公司",
                    "seller_tax_id": "91110100MA00XXXXX1",
                    "seller_address": "北京市朝阳区XX大厦",
                    "seller_phone": "010-12345678",
                    "seller_bank": "中国工商银行北京分行",
                    "seller_bank_account": "6222021234567890123",
                    "amount": amount,
                    "tax_amount": tax_amount,
                    "total_amount": total_amount,
                    "invoice_date": datetime.combine(current_date, datetime.min.time()),
                    "status": random.choice(["valid", "invalid", "red_flushed"]),
                    "created_at": datetime.combine(current_date, datetime.min.time()),
                    "updated_at": datetime.now(),
                    "remark": "",
                }

                if random.random() < 0.02:
                    invoice["buyer_phone"] = ""
                if random.random() < 0.03:
                    invoice["tax_amount"] = None

                data.append(invoice)
                invoice_id += 1

        df = pd.DataFrame(data)

        if random.random() < 0.1:
            idx = random.sample(range(len(df)), int(len(df) * 0.02))
            for i in idx:
                df.loc[i, "total_amount"] = df.loc[i, "amount"] + round(random.uniform(1, 100), 2)

        return df
