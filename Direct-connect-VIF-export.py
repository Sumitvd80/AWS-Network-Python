import boto3
import pandas as pd

def get_all_direct_connect_vif_details():
    """Retrieves details for all Direct Connect virtual interfaces (VIFs) in the account across specified regions."""
    regions = ['us-east-1', 'us-west-1', 'eu-central-2', 'eu-west-1', 'ap-northeast-1', 'ap-southeast-2']
    all_vifs = []  # Store VIFs from all regions

    for avail_region in regions:
        try:
            client = boto3.client('directconnect', region_name=avail_region)
            print(f"Checking region: {avail_region}")
            next_token = None

            while True:
                if next_token:
                    response = client.describe_virtual_interfaces(nextToken=next_token)
                else:
                    response = client.describe_virtual_interfaces()

                if 'virtualInterfaces' in response:
                    for vif in response['virtualInterfaces']:
                        vif_details = {
                            'vif_id': vif.get('virtualInterfaceId'),
                            'vif_name': vif.get('virtualInterfaceName'),
                            'vif_type': vif.get('virtualInterfaceType'),
                            'connection_id': vif.get('connectionId'),
                            'vlan': vif.get('vlan'),
                            'customer_address': vif.get('customerAddress'),
                            'amazon_address': vif.get('amazonAddress'),
                            'bgp_asn': vif.get('asn'), #BGP ASN
                            'amazon_asn': vif.get('amazonSideAsn'), #Amazon ASN
                            'auth_type': vif.get('authType'),
                            'vif_state': vif.get('virtualInterfaceState'),
                            'region': avail_region,  # add region to the output.
                            'location': vif.get('location'), #Add location
                            }
                        all_vifs.append(vif_details)

                    next_token = response.get('nextToken')
                    if not next_token:
                        break
                else:
                    print(f"  No VIFs found in {avail_region}")
                    break #break the while loop, and move to next region.

        except Exception as e:
            print(f"  Error in region {avail_region}: {e}")

    return all_vifs

def main():
    vif_data = get_all_direct_connect_vif_details()

    if vif_data:
        df = pd.DataFrame(vif_data)
        df.to_excel('VIF9.xlsx', index=False)
        print("Data has been written to VIF.xlsx")
    else:
        print("No VIF data retrieved.")

if __name__ == "__main__":
    main()
