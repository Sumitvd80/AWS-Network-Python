import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import sys
import pandas as pd
from datetime import datetime

def get_enis_by_security_group(security_group_id, region='us-east-1', profile=None):
    """
    Retrieve all ENIs that have the specified security group attached.
    
    Args:
        security_group_id (str): The security group ID to search for
        region (str): AWS region (default: us-east-1)
        profile (str): AWS CLI profile name (optional)
    
    Returns:
        list: List of ENI details with the specified security group
    """
    try:
        # Initialize boto3 session
        if profile:
            session = boto3.Session(profile_name=profile, region_name=region)
        else:
            session = boto3.Session(region_name=region)
        
        ec2_client = session.client('ec2')
        
        # Get account ID for ARN construction
        sts_client = session.client('sts')
        account_id = sts_client.get_caller_identity()['Account']
        
        # Describe network interfaces with the specified security group
        response = ec2_client.describe_network_interfaces(
            Filters=[
                {
                    'Name': 'group-id',
                    'Values': [security_group_id]
                }
            ]
        )
        
        enis = response['NetworkInterfaces']
        
        if not enis:
            print(f"\nNo ENIs found with security group: {security_group_id}")
            return []
        
        print(f"\nFound {len(enis)} ENI(s) with security group {security_group_id}:\n")
        print("-" * 120)
        
        eni_details = []
        
        for eni in enis:
            eni_id = eni['NetworkInterfaceId']
            # Construct ENI ARN
            eni_arn = f"arn:aws:ec2:{region}:{account_id}:network-interface/{eni_id}"
            
            eni_info = {
                'NetworkInterfaceId': eni_id,
                'ARN': eni_arn,
                'Status': eni['Status'],
                'PrivateIpAddress': eni.get('PrivateIpAddress', 'N/A'),
                'SubnetId': eni.get('SubnetId', 'N/A'),
                'VpcId': eni.get('VpcId', 'N/A'),
                'AvailabilityZone': eni.get('AvailabilityZone', 'N/A'),
                'Description': eni.get('Description', 'N/A'),
                'AttachmentInstanceId': eni.get('Attachment', {}).get('InstanceId', 'Not Attached'),
                'AttachmentStatus': eni.get('Attachment', {}).get('Status', 'N/A'),
                'SecurityGroups': ', '.join([sg['GroupId'] for sg in eni.get('Groups', [])]),
                'InterfaceType': eni.get('InterfaceType', 'N/A'),
                'PublicIp': eni.get('Association', {}).get('PublicIp', 'N/A')
            }
            
            eni_details.append(eni_info)
            
            # Print ENI details
            print(f"ENI ID: {eni_info['NetworkInterfaceId']}")
            print(f"  ARN: {eni_info['ARN']}")
            print(f"  Status: {eni_info['Status']}")
            print(f"  Private IP: {eni_info['PrivateIpAddress']}")
            print(f"  Public IP: {eni_info['PublicIp']}")
            print(f"  VPC ID: {eni_info['VpcId']}")
            print(f"  Subnet ID: {eni_info['SubnetId']}")
            print(f"  Availability Zone: {eni_info['AvailabilityZone']}")
            print(f"  Interface Type: {eni_info['InterfaceType']}")
            print(f"  Description: {eni_info['Description']}")
            print(f"  Attached to Instance: {eni_info['AttachmentInstanceId']}")
            print(f"  Attachment Status: {eni_info['AttachmentStatus']}")
            print(f"  All Security Groups: {eni_info['SecurityGroups']}")
            print("-" * 120)
        
        return eni_details
    
    except NoCredentialsError:
        print("Error: AWS credentials not found. Please configure your credentials.")
        sys.exit(1)
    except ClientError as e:
        print(f"Error: {e.response['Error']['Message']}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        sys.exit(1)


def export_to_excel(eni_list, security_group_id, region):
    """
    Export ENI details to Excel file.
    
    Args:
        eni_list (list): List of ENI details
        security_group_id (str): Security group ID used for search
        region (str): AWS region
    """
    if not eni_list:
        print("No data to export.")
        return
    
    try:
        # Create DataFrame
        df = pd.DataFrame(eni_list)
        
        # Reorder columns for better readability
        column_order = [
            'NetworkInterfaceId',
            'ARN',
            'Status',
            'PrivateIpAddress',
            'PublicIp',
            'VpcId',
            'SubnetId',
            'AvailabilityZone',
            'InterfaceType',
            'AttachmentInstanceId',
            'AttachmentStatus',
            'SecurityGroups',
            'Description'
        ]
        df = df[column_order]
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'ENI_SecurityGroup_{security_group_id}_{region}_{timestamp}.xlsx'
        
        # Export to Excel with formatting
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='ENI Details', index=False)
            
            # Get the worksheet
            worksheet = writer.sheets['ENI Details']
            
            # Adjust column widths
            for idx, col in enumerate(df.columns, 1):
                max_length = max(
                    df[col].astype(str).apply(len).max(),
                    len(col)
                ) + 2
                worksheet.column_dimensions[chr(64 + idx)].width = min(max_length, 50)
        
        print(f"\n✓ Excel file created successfully: {filename}")
        return filename
        
    except Exception as e:
        print(f"Error exporting to Excel: {str(e)}")
        print("Note: Make sure pandas and openpyxl are installed:")
        print("  pip install pandas openpyxl")
        sys.exit(1)


def main():
    """
    Main function to run the ENI checker.
    """
    # Configuration
    SECURITY_GROUP_ID = 'sg-0fb22'  # Replace with your security group ID
    AWS_REGION = 'us-east-1'  # Replace with your AWS region
    AWS_PROFILE = None  # Optional: specify AWS CLI profile name
    
    print(f"Searching for ENIs with Security Group: {SECURITY_GROUP_ID}")
    print(f"Region: {AWS_REGION}")
    
    # Get ENIs
    eni_list = get_enis_by_security_group(
        security_group_id=SECURITY_GROUP_ID,
        region=AWS_REGION,
        profile=AWS_PROFILE
    )
    
    print(f"\nTotal ENIs found: {len(eni_list)}")
    
    # Export to Excel
    if eni_list:
        export_to_excel(eni_list, SECURITY_GROUP_ID, AWS_REGION)


if __name__ == "__main__":
    main()
