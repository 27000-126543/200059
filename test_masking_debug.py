import sys
sys.path.insert(0, '.')
from dqgovernance.collectors import CollectorFactory
from dqgovernance.masking import MaskingEngine
from datetime import date, timedelta

factory = CollectorFactory()
masking = MaskingEngine()
test_date = date.today() - timedelta(days=1)

print('采集订单系统数据...')
data = factory.collect_system('order_system')

for table_name, df in data.items():
    print(f'\n表: {table_name}, 行数: {len(df)}')
    print(f'列名: {list(df.columns)}')
    if len(df) > 0:
        print('第一行数据:')
        for col in df.columns:
            val = df[col].iloc[0]
            print(f'  {col}: {val}')

print('\n\n开始脱敏...')
masked_data, sensitive_records = masking.scan_and_mask(
    'order_system', data, scan_date=test_date
)

print(f'\n识别到的敏感字段数量: {len(sensitive_records)}')
for s in sensitive_records:
    print(f'  - {s.field_name}: {s.data_type}, {s.record_count} 条记录')

orders_df = masked_data.get('orders')
if orders_df is not None and len(orders_df) > 0:
    print('\n脱敏后的数据示例:')
    for col in ['customer_phone', 'customer_id_card', 'receiver_phone']:
        if col in orders_df.columns:
            print(f'  {col}: {orders_df[col].iloc[0]}')
