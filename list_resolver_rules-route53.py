import pandas as pd
import boto3


## export credentials in your shell before you start executing this 

available_regions = ['us-east-1', 'us-west-1', 
                     'eu-central-1','eu-west-2',
                     'ap-northeast-1','ap-southeast-2'
                    ]



def list_resolver_rules(region):
    client = boto3.client('route53resolver', region_name=region)
    resolver_rules = []
    paginator = client.get_paginator('list_resolver_rules')
    
    for page in paginator.paginate():
        resolver_rules.extend(page['ResolverRules'])
    
    return resolver_rules

def get_resolver_rule_details():
    rule_map = []
    for region in available_regions:
        print(f"Fetching resolver rules from region: {region}")
        resolver_rules = list_resolver_rules(region)
        for rule in resolver_rules:
            rule_id = rule['Id']
            rule_name = rule['Name']
            domain_name = rule['DomainName']
            target_ips = rule.get('TargetIps', [])
            rule_type = rule['RuleType']
            resolver_endpoint = rule.get('ResolverEndpointId', 'N/A')

            target_ip_details = ', '.join([target['Ip'] for target in target_ips])
            
            rule_map.append({
                'region': region,
                'rule_id': rule_id,
                'rule_name': rule_name,
                'domain_name': domain_name,
                'target_ips': target_ip_details,
                'rule_type' : rule_type,
                'resolver_endpoint' : resolver_endpoint
            })
    
    return rule_map

def main():
    
    pd.DataFrame(get_resolver_rule_details()).to_excel('resolver_rules.xlsx', index=False)
    print(f"Data has been written to {'resolver_rules_nov.xlsx'}")

if __name__ == "__main__":
    main()
