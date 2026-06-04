from datetime import datetime, date, timedelta
from typing import Optional
import pandas as pd
import random
from faker import Faker

from .base import MockBaseCollector


class OrderCollector(MockBaseCollector):
    def __init__(self):
        super().__init__("order_system")
        self.register_mock_generator("orders", self._generate_orders)
        self.register_mock_generator("order_items", self._generate_order_items)
        self.register_mock_generator("payments", self._generate_payments)

    def _generate_orders(
        self, start_date: date, end_date: date
    ) -> pd.DataFrame:
        fake = Faker("zh_CN")
        date_range = (end_date - start_date).days + 1
        records_per_day = random.randint(80, 150)
        total_records = date_range * records_per_day

        data = []
        current_date = start_date
        order_id = 100000

        for _ in range(date_range):
            for _ in range(records_per_day):
                order_amount = round(random.uniform(10, 10000), 2)
                created_at = datetime.combine(
                    current_date,
                    datetime.min.time().replace(
                        hour=random.randint(0, 23),
                        minute=random.randint(0, 59),
                        second=random.randint(0, 59),
                    ),
                )

                order = {
                    "id": order_id,
                    "order_no": f"ORD{order_id}",
                    "customer_id": random.randint(1000, 9999),
                    "customer_name": fake.name(),
                    "customer_phone": fake.phone_number(),
                    "customer_id_card": fake.ssn() if random.random() > 0.5 else "",
                    "order_amount": order_amount,
                    "discount_amount": round(order_amount * random.uniform(0, 0.3), 2),
                    "pay_amount": round(order_amount * (1 - random.uniform(0, 0.3)), 2),
                    "status": random.choice(
                        ["pending", "paid", "shipped", "completed", "cancelled", "refunded"]
                    ),
                    "payment_method": random.choice(
                        ["alipay", "wechat", "bank_card", "credit_card"]
                    ),
                    "receiver_name": fake.name(),
                    "receiver_phone": fake.phone_number(),
                    "receiver_address": fake.address(),
                    "created_at": created_at,
                    "updated_at": created_at + timedelta(hours=random.randint(0, 48)),
                    "paid_at": created_at + timedelta(minutes=random.randint(1, 120))
                    if random.random() > 0.1 else None,
                    "shipped_at": None,
                    "completed_at": None,
                    "remark": fake.sentence() if random.random() > 0.7 else "",
                }

                if order["status"] in ["shipped", "completed"]:
                    order["shipped_at"] = created_at + timedelta(hours=random.randint(1, 72))
                if order["status"] == "completed":
                    order["completed_at"] = order["shipped_at"] + timedelta(days=random.randint(1, 7))

                if random.random() < 0.03:
                    order["customer_phone"] = None
                if random.random() < 0.02:
                    order["receiver_address"] = ""

                data.append(order)
                order_id += 1
            current_date += timedelta(days=1)

        df = pd.DataFrame(data)

        if random.random() < 0.15:
            dup_count = int(len(df) * 0.02)
            dup_idx = random.sample(range(len(df)), dup_count)
            for idx in dup_idx:
                df.loc[idx, "order_amount"] = df.loc[idx, "pay_amount"] + random.uniform(10, 100)

        return df

    def _generate_order_items(
        self, start_date: date, end_date: date
    ) -> pd.DataFrame:
        fake = Faker("zh_CN")
        date_range = (end_date - start_date).days + 1
        records_per_day = random.randint(150, 300)
        total_records = date_range * records_per_day

        products = [
            ("商品A", 99.0), ("商品B", 199.0), ("商品C", 299.0),
            ("商品D", 499.0), ("商品E", 999.0), ("商品F", 1999.0),
        ]

        data = []
        item_id = 1
        order_id = 100000

        for _ in range(date_range):
            daily_orders = records_per_day // random.randint(1, 3)
            for _ in range(daily_orders):
                item_count = random.randint(1, 5)
                for _ in range(item_count):
                    product = random.choice(products)
                    quantity = random.randint(1, 10)
                    unit_price = product[1]
                    item_amount = round(unit_price * quantity, 2)

                    item = {
                        "id": item_id,
                        "order_id": order_id,
                        "product_id": random.randint(100, 999),
                        "product_name": product[0],
                        "product_sku": f"SKU{random.randint(10000, 99999)}",
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "item_amount": item_amount,
                        "discount_amount": round(item_amount * random.uniform(0, 0.2), 2),
                        "created_at": datetime.combine(
                            start_date + timedelta(days=random.randint(0, date_range - 1)),
                            datetime.min.time(),
                        ),
                        "updated_at": datetime.now(),
                    }

                    if random.random() < 0.02:
                        item["quantity"] = None
                    if random.random() < 0.05:
                        item["product_sku"] = ""

                    data.append(item)
                    item_id += 1
                order_id += 1

        return pd.DataFrame(data)

    def _generate_payments(
        self, start_date: date, end_date: date
    ) -> pd.DataFrame:
        fake = Faker("zh_CN")
        date_range = (end_date - start_date).days + 1
        records_per_day = random.randint(70, 140)
        total_records = date_range * records_per_day

        data = []
        payment_id = 50000
        order_id = 100000

        for _ in range(date_range):
            for _ in range(records_per_day):
                amount = round(random.uniform(10, 10000), 2)
                created_at = datetime.combine(
                    start_date + timedelta(days=random.randint(0, date_range - 1)),
                    datetime.min.time().replace(
                        hour=random.randint(0, 23),
                        minute=random.randint(0, 59),
                    ),
                )

                payment = {
                    "id": payment_id,
                    "payment_no": f"PAY{payment_id}",
                    "order_id": order_id,
                    "amount": amount,
                    "currency": "CNY",
                    "payment_method": random.choice(
                        ["alipay", "wechat", "bank_card", "credit_card"]
                    ),
                    "bank_card_no": fake.credit_card_number()
                    if random.choice(["alipay", "wechat", "bank_card", "credit_card"]) in ["bank_card", "credit_card"]
                    else "",
                    "payer_name": fake.name(),
                    "payer_phone": fake.phone_number(),
                    "status": random.choice(["success", "failed", "pending", "refunded"]),
                    "transaction_id": f"TXN{random.randint(1000000, 9999999)}",
                    "created_at": created_at,
                    "paid_at": created_at + timedelta(seconds=random.randint(1, 300))
                    if random.random() > 0.1 else None,
                    "refunded_at": None,
                    "remark": "",
                }

                if payment["status"] == "refunded" and payment["paid_at"] is not None:
                    payment["refunded_at"] = payment["paid_at"] + timedelta(days=random.randint(1, 15))

                if random.random() < 0.03:
                    payment["payer_phone"] = None
                if random.random() < 0.02:
                    payment["transaction_id"] = ""

                data.append(payment)
                payment_id += 1
                order_id += 1

        df = pd.DataFrame(data)

        if random.random() < 0.1:
            null_idx = random.sample(range(len(df)), int(len(df) * 0.03))
            df.loc[null_idx, "paid_at"] = None

        return df
