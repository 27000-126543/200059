from datetime import datetime, date, timedelta
from typing import Optional
import pandas as pd
import random
from faker import Faker

from .base import MockBaseCollector


class HRCollector(MockBaseCollector):
    def __init__(self):
        super().__init__("hr_system")
        self.register_mock_generator("employees", self._generate_employees)
        self.register_mock_generator("departments", self._generate_departments)
        self.register_mock_generator("attendance", self._generate_attendance)

    def _generate_employees(
        self, start_date: date, end_date: date
    ) -> pd.DataFrame:
        fake = Faker("zh_CN")
        total_records = random.randint(200, 500)

        departments = ["技术部", "产品部", "设计部", "市场部", "销售部", "财务部",
                       "人力资源部", "行政部", "运营部", "客服部"]
        positions = ["工程师", "经理", "主管", "专员", "总监", "实习生", "助理"]
        education_levels = ["博士", "硕士", "本科", "大专", "高中"]
        statuses = ["active", "resigned", "probation", "suspended"]

        data = []
        emp_id = 10000

        for _ in range(total_records):
            hire_date = start_date - timedelta(days=random.randint(30, 1825))
            birth_date = hire_date - timedelta(days=random.randint(7300, 14600))

            employee = {
                "id": emp_id,
                "employee_no": f"EMP{emp_id}",
                "name": fake.name(),
                "gender": random.choice(["男", "女"]),
                "id_card": fake.ssn(),
                "phone": fake.phone_number(),
                "email": fake.email(),
                "birth_date": birth_date,
                "age": (date.today() - birth_date).days // 365,
                "education": random.choice(education_levels),
                "department": random.choice(departments),
                "position": random.choice(positions),
                "level": f"P{random.randint(1, 10)}",
                "hire_date": hire_date,
                "probation_end_date": hire_date + timedelta(days=random.randint(30, 90)),
                "contract_start": hire_date,
                "contract_end": hire_date + timedelta(days=random.randint(365, 1825)),
                "salary": round(random.uniform(5000, 50000), 2),
                "bank_card": fake.credit_card_number(),
                "address": fake.address(),
                "emergency_contact": fake.name(),
                "emergency_phone": fake.phone_number(),
                "status": random.choice(statuses),
                "resign_date": None,
                "created_at": datetime.combine(hire_date, datetime.min.time()),
                "updated_at": datetime.now(),
                "remark": "",
            }

            if employee["status"] == "resigned":
                employee["resign_date"] = hire_date + timedelta(days=random.randint(365, 1095))

            if random.random() < 0.03:
                employee["phone"] = None
            if random.random() < 0.02:
                employee["email"] = ""
            if random.random() < 0.05:
                employee["id_card"] = None

            data.append(employee)
            emp_id += 1

        return pd.DataFrame(data)

    def _generate_departments(
        self, start_date: date, end_date: date
    ) -> pd.DataFrame:
        departments = [
            ("D001", "技术部", "负责产品研发", 50, "张总监"),
            ("D002", "产品部", "负责产品规划", 15, "李总监"),
            ("D003", "设计部", "负责UI/UX设计", 12, "王总监"),
            ("D004", "市场部", "负责市场营销", 20, "赵总监"),
            ("D005", "销售部", "负责销售业务", 30, "刘总监"),
            ("D006", "财务部", "负责财务管理", 10, "陈总监"),
            ("D007", "人力资源部", "负责人力资源", 8, "周总监"),
            ("D008", "行政部", "负责行政管理", 6, "吴总监"),
            ("D009", "运营部", "负责运营管理", 25, "郑总监"),
            ("D010", "客服部", "负责客户服务", 18, "孙总监"),
        ]

        data = []
        for dept in departments:
            data.append({
                "id": dept[0],
                "dept_code": dept[0],
                "dept_name": dept[1],
                "description": dept[2],
                "headcount": dept[3],
                "manager": dept[4],
                "manager_phone": "138" + str(random.randint(10000000, 99999999)),
                "parent_dept": "总经办",
                "level": random.randint(1, 3),
                "status": "active",
                "created_at": datetime.combine(start_date - timedelta(days=random.randint(365, 1095)), datetime.min.time()),
                "updated_at": datetime.now(),
            })

        df = pd.DataFrame(data)

        if random.random() < 0.1:
            idx = random.choice(range(len(df)))
            df.loc[idx, "manager_phone"] = None

        return df

    def _generate_attendance(
        self, start_date: date, end_date: date
    ) -> pd.DataFrame:
        fake = Faker("zh_CN")
        date_range = (end_date - start_date).days + 1
        employees_count = random.randint(200, 500)

        data = []
        att_id = 1

        for day_offset in range(date_range):
            current_date = start_date + timedelta(days=day_offset)
            if current_date.weekday() >= 5:
                continue

            for emp_id in range(10000, 10000 + employees_count):
                if random.random() < 0.05:
                    continue

                check_in = datetime.combine(
                    current_date,
                    datetime.min.time().replace(
                        hour=random.randint(8, 10),
                        minute=random.randint(0, 59),
                    ),
                )
                check_out = datetime.combine(
                    current_date,
                    datetime.min.time().replace(
                        hour=random.randint(17, 21),
                        minute=random.randint(0, 59),
                    ),
                )

                work_hours = (check_out - check_in).total_seconds() / 3600
                is_late = check_in.hour > 9 or (check_in.hour == 9 and check_in.minute > 0)
                is_early_leave = check_out.hour < 18 or (check_out.hour == 18 and check_out.minute < 0)
                is_absent = work_hours < 4

                status = "normal"
                if is_absent:
                    status = "absent"
                elif is_late and is_early_leave:
                    status = "late_and_early"
                elif is_late:
                    status = "late"
                elif is_early_leave:
                    status = "early_leave"

                attendance = {
                    "id": att_id,
                    "employee_id": emp_id,
                    "employee_no": f"EMP{emp_id}",
                    "employee_name": fake.name(),
                    "department": random.choice(["技术部", "产品部", "设计部", "市场部", "销售部"]),
                    "attendance_date": current_date,
                    "check_in": check_in,
                    "check_out": check_out,
                    "work_hours": round(work_hours, 2),
                    "is_late": is_late,
                    "is_early_leave": is_early_leave,
                    "is_absent": is_absent,
                    "status": status,
                    "leave_type": random.choice(["", "annual", "sick", "personal", "business"])
                    if random.random() < 0.03 else "",
                    "remark": "" if status == "normal" else f"{status}提醒",
                    "created_at": check_in,
                    "updated_at": datetime.now(),
                }

                if random.random() < 0.02:
                    attendance["check_out"] = None
                if random.random() < 0.01:
                    attendance["check_in"] = None

                data.append(attendance)
                att_id += 1

        df = pd.DataFrame(data)

        if random.random() < 0.1:
            idx = random.sample(range(len(df)), int(len(df) * 0.02))
            for i in idx:
                df.loc[i, "work_hours"] = round(random.uniform(15, 24), 2)

        return df
