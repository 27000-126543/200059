import sys
sys.path.insert(0, '.')
from dqgovernance.masking import MaskingEngine

masking = MaskingEngine()
print('Patterns:', list(masking.patterns.keys()))

test_fields = ['customer_phone', 'customer_id_card', 'receiver_phone', 'bank_card_no', 'email', 'address']

for field in test_fields:
    print(f'\n测试字段: {field}')
    field_lower = field.lower()
    print(f'  小写: {field_lower}')
    
    for data_type, pattern_config in masking.patterns.items():
        print(f'  检查类型: {data_type}')
        
        if 'keywords' in pattern_config:
            keywords = pattern_config['keywords']
            print(f'    keywords: {keywords}')
            for kw in keywords:
                match = kw in field or kw in field_lower
                print(f'      {kw}: {match}')
        
        sensitive_field_names = {
            'id_card': ['id_card', 'idcard', '身份证', 'identity', '证件号'],
            'phone': ['phone', 'mobile', 'cell', 'tel', '手机', '电话'],
            'email': ['email', 'mail', '邮箱'],
            'bank_card': ['bank_card', 'bankcard', 'card_no', 'card_number', '银行卡', '卡号'],
            'address': ['address', 'addr', '地址', '住址'],
        }
        name_matches = sensitive_field_names.get(data_type, [])
        print(f'    name_matches: {name_matches}')
        for nm in name_matches:
            match = nm in field_lower
            print(f'      {nm}: {match}')
            if match:
                print(f'      -> 匹配成功!')
