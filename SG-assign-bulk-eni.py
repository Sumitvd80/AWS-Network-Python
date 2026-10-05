"""
Script to attach additional security groups to ENIs without removing existing ones.
Reads ENI ARNs from Excel file and attaches hardcoded security groups.
"""

import boto3
from botocore.exceptions import ClientError
import pandas as pd
import sys
import os

# ============================================================================
# CONFIGURATION - SECURITY GROUPS TO ADD (Hardcoded)
# ============================================================================
ADDITIONAL_SECURITY_GROUPS = [
    'sg-06e92',
    # Add more security group IDs here
]

AWS_REGION = 'us-east-1'  # Change to your region
EXCEL_FILE_PATH = r'C:\Users\sumit\Downloads\eni_list.xlsx'  # Path to your Excel file
EXCEL_SHEET_NAME = 'Sheet1'  # Sheet name containing ENI ARNs
EXCEL_COLUMN_NAME = 'ENI_ARN'  # Column name containing ENI ARNs
# ============================================================================

def extract_eni_id_from_arn(arn):
    """
    Extract ENI ID from ARN format.
    ARN format: arn:aws:ec2:region:account-id:network-interface/eni-xxxxx
    """
    try:
        arn = str(arn).strip()
        if arn.startswith('eni-'):
            return arn
        return arn.split('/')[-1]
    except Exception as e:
        print(f"Error extracting ENI ID from ARN {arn}: {str(e)}")
        return None

def read_eni_arns_from_excel(file_path, sheet_name, column_name):
    """
    Read ENI ARNs from Excel file.
    Supports both .xlsx and .xls formats.
    """
    try:
        if not os.path.exists(file_path):
            print(f"Error: Excel file not found at {file_path}")
            return None
        
        # Read Excel file
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        
        # Check if column exists
        if column_name not in df.columns:
            print(f"Error: Column '{column_name}' not found in Excel file.")
            print(f"Available columns: {list(df.columns)}")
            return None
        
        # Extract ENI ARNs and remove empty values
        eni_arns = df[column_name].dropna().tolist()
        
        print(f"Successfully read {len(eni_arns)} ENI ARNs from Excel file")
        return eni_arns
    
    except Exception as e:
        print(f"Error reading Excel file: {str(e)}")
        return None

def get_existing_security_groups(ec2_client, eni_id):
    """
    Retrieve existing security groups attached to the ENI.
    """
    try:
        response = ec2_client.describe_network_interfaces(
            NetworkInterfaceIds=[eni_id]
        )
        
        if response['NetworkInterfaces']:
            groups = response['NetworkInterfaces'][0]['Groups']
            return [group['GroupId'] for group in groups]
        return []
    except ClientError as e:
        print(f"Error retrieving security groups for {eni_id}: {str(e)}")
        return None

def attach_security_groups(ec2_client, eni_id, additional_sg_ids):
    """
    Attach additional security groups to ENI while preserving existing ones.
    """
    # Get existing security groups
    existing_sgs = get_existing_security_groups(ec2_client, eni_id)
    
    if existing_sgs is None:
        return False
    
    # Combine existing and new security groups (remove duplicates)
    all_sgs = list(set(existing_sgs + additional_sg_ids))
    
    print(f"\nENI: {eni_id}")
    print(f"  Existing SGs: {existing_sgs}")
    print(f"  Adding SGs: {additional_sg_ids}")
    print(f"  Final SG list: {all_sgs}")
    
    try:
        # Update the ENI with combined security groups
        ec2_client.modify_network_interface_attribute(
            NetworkInterfaceId=eni_id,
            Groups=all_sgs
        )
        print(f"  ✓ Successfully updated security groups for {eni_id}")
        return True
    except ClientError as e:
        print(f"  ✗ Error updating {eni_id}: {str(e)}")
        return False

def main():
    """
    Main function to process ENI ARNs from Excel and attach security groups.
    """
    print("=" * 70)
    print("ENI Security Group Attachment Script")
    print("=" * 70)
    
    # Display configuration
    print(f"\nConfiguration:")
    print(f"  AWS Region: {AWS_REGION}")
    print(f"  Excel File: {EXCEL_FILE_PATH}")
    print(f"  Sheet Name: {EXCEL_SHEET_NAME}")
    print(f"  Column Name: {EXCEL_COLUMN_NAME}")
    print(f"  Security Groups to Add: {ADDITIONAL_SECURITY_GROUPS}")
    print()
    
    # Read ENI ARNs from Excel
    eni_arns = read_eni_arns_from_excel(EXCEL_FILE_PATH, EXCEL_SHEET_NAME, EXCEL_COLUMN_NAME)
    
    if not eni_arns:
        print("No ENI ARNs found. Exiting.")
        sys.exit(1)
    
    # Initialize boto3 EC2 client
    try:
        ec2_client = boto3.client('ec2', region_name=AWS_REGION)
        print(f"✓ Connected to AWS region: {AWS_REGION}")
    except Exception as e:
        print(f"✗ Error initializing boto3 client: {str(e)}")
        sys.exit(1)
    
    # Process each ENI
    success_count = 0
    failure_count = 0
    skipped_count = 0
    
    print(f"\nProcessing {len(eni_arns)} ENIs...")
    print("=" * 70)
    
    for eni_arn in eni_arns:
        # Extract ENI ID from ARN
        eni_id = extract_eni_id_from_arn(eni_arn)
        
        if not eni_id or not eni_id.startswith('eni-'):
            print(f"Skipping invalid ARN/ID: {eni_arn}")
            skipped_count += 1
            continue
        
        # Attach security groups
        if attach_security_groups(ec2_client, eni_id, ADDITIONAL_SECURITY_GROUPS):
            success_count += 1
        else:
            failure_count += 1
    
    # Summary
    print("\n" + "=" * 70)
    print(f"Execution Summary:")
    print(f"  Total ENIs in Excel: {len(eni_arns)}")
    print(f"  Successfully updated: {success_count}")
    print(f"  Failed: {failure_count}")
    print(f"  Skipped (invalid): {skipped_count}")
    print("=" * 70)

if __name__ == "__main__":
    main()
