import boto3
import pandas as pd

def get_security_groups_with_open_inbound(region):
    """
    Retrieves security groups with inbound rules allowing 0.0.0.0/0 and their rule details for a specific region.

    Args:
        region (str): The AWS region to check.

    Returns:
        list: A list of dictionaries, where each dictionary represents a security group
              and contains its details, or None if an error occurs.
    """
    try:
        ec2 = boto3.client('ec2', region_name=region)
        response = ec2.describe_security_groups()
        security_groups = []

        for sg in response['SecurityGroups']:
            sg_id = sg['GroupId']
            sg_name = sg.get('GroupName', sg_id)
            open_inbound_rules = []

            for rule in sg.get('IpPermissions', []):
                for ip_range in rule.get('IpRanges', []):
                    if ip_range.get('CidrIp') == '0.0.0.0/0':
                        open_inbound_rules.append({
                            'Protocol': rule.get('IpProtocol'),
                            'FromPort': rule.get('FromPort'),
                            'ToPort': rule.get('ToPort'),
                            'IpRanges': rule.get('IpRanges'),
                            'IpProtocol': rule.get('IpProtocol'),
                            'Ipv6Ranges': rule.get('Ipv6Ranges'),
                            'PrefixListIds': rule.get('PrefixListIds'),
                            'UserIdGroupPairs': rule.get('UserIdGroupPairs'),
                            'Region': region
                        })
                        break  # break the inner loop once 0.0.0.0/0 is found.

            if open_inbound_rules:
                security_groups.append({
                    'GroupId': sg_id,
                    'GroupName': sg_name,
                    'OpenInboundRules': open_inbound_rules,
                    'Region': region,
                })

        return security_groups

    except Exception as e:
        print(f"An error occurred in region {region}: {e}")
        return None

def main():
    regions = ['us-east-1', 'ap-southeast-1']
    all_rules = []

    for region in regions:
        open_security_groups = get_security_groups_with_open_inbound(region)

        if open_security_groups:
            ec2 = boto3.client('ec2', region_name=region)
            for sg in open_security_groups:
                # Check instance status
                try:
                    instances = ec2.describe_instances(Filters=[{'Name': 'instance.group-id', 'Values': [sg['GroupId']]}])
                    running_instances = False
                    for reservation in instances['Reservations']:
                        for instance in reservation['Instances']:
                            if instance['State']['Name'] in ['running', 'pending']:
                                running_instances = True
                                break
                        if running_instances:
                            break

                    if running_instances:
                        for rule in sg['OpenInboundRules']:
                            rule['GroupId'] = sg['GroupId']
                            rule['GroupName'] = sg['GroupName']
                            all_rules.append(rule)
                    else:
                        print(f"Security group {sg['GroupId']} in {region} has open inbound rules but no running instances.")

                except Exception as instance_error:
                    print(f"Error checking instances for {sg['GroupId']} in {region}: {instance_error}")

        else:
            print(f"No security groups with open inbound rules found in {region}")

    if all_rules:
        df = pd.DataFrame(all_rules)
        df.to_excel('OpenSecurityGroups.xlsx', index=False)
        print("Security group rules with open inbound access written to OpenSecurityGroups.xlsx")
    else:
        print("No security groups with open inbound rules found in any specified regions, or no running instances using the security groups.")

if __name__ == "__main__":
    main()
