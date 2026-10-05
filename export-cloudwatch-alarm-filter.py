import subprocess
import json
import openpyxl

def get_cloudwatch_alarms(region):
    try:
        command = [
            'aws', 'cloudwatch', 'describe-alarms',
            '--alarm-name-prefix', 'aviatrix',
            '--region', region,
            '--output', 'json'
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        alarms_data = json.loads(result.stdout)
        return alarms_data.get('MetricAlarms', []) + alarms_data.get('CompositeAlarms', [])
    except subprocess.CalledProcessError as e:
        print(f"Error describing CloudWatch alarms in {region}: {e.stderr}")
        return []
    except FileNotFoundError:
        print("Error: AWS CLI not found. Please ensure it is installed and in your PATH.")
        return []
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response for CloudWatch alarms in {region}: {e}")
        return []

def get_instance_id_from_alarm(alarm):
    dimensions = alarm.get('Dimensions', [])
    for dimension in dimensions:
        if dimension.get('Name') == 'InstanceId':
            return dimension.get('Value')
    return None

def main():
    regions = [
        'ap-northeast-1',
        'eu-central-1',      
        'us-east-1'       
    ]

    all_alarms_data = []

    for region in regions:
        print(f"Fetching alarms for region: {region}")
        alarms = get_cloudwatch_alarms(region)
        for alarm in alarms:
            instance_id = get_instance_id_from_alarm(alarm)
            all_alarms_data.append({
                'AlarmName': alarm['AlarmName'],
                'AlarmArn': alarm['AlarmArn'],  # Added Alarm ARN
                'InstanceId': instance_id if instance_id else 'N/A',
                'Region': region
            })

    if all_alarms_data:
        # Create a new Excel workbook
        workbook = openpyxl.Workbook()
        sheet = workbook.active

        # Write the header row
        header = ['Alarm Name', 'Alarm ARN', 'Instance ID', 'Region'] # Added 'Alarm ARN' to header
        sheet.append(header)

        # Write the alarm data to the Excel sheet
        for alarm_info in all_alarms_data:
            row_data = [
                alarm_info['AlarmName'],
                alarm_info['AlarmArn'],   # Added Alarm ARN to row data
                alarm_info['InstanceId'],
                alarm_info['Region']
            ]
            sheet.append(row_data)

        # Save the Excel file
        excel_filename = "aviatrix_alarms_regions.xlsx"
        try:
            workbook.save(excel_filename)
            print(f"\nAlarm data for given region has been written to '{excel_filename}'")
        except Exception as e:
            print(f"Error saving Excel file: {e}")
    else:
        print("No CloudWatch alarms found with the specified prefix in the selected regions.")

if __name__ == "__main__":
    main()
