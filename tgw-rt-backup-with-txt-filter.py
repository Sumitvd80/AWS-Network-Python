import boto3
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed


# ── Cache builders (called once per region) ───────────────────────────────────

def build_attachment_cache(ec2_client):
    cache = {}
    try:
        paginator = ec2_client.get_paginator('describe_transit_gateway_attachments')
        for page in paginator.paginate():
            for att in page.get('TransitGatewayAttachments', []):
                att_id = att['TransitGatewayAttachmentId']
                name   = next((t['Value'] for t in att.get('Tags', []) if t['Key'] == 'Name'), att_id)
                cache[att_id] = name
    except Exception as e:
        print(f"    Warning: Could not build attachment cache: {e}")
    return cache


def build_vpc_cache(ec2_client):
    cache = {}
    try:
        paginator = ec2_client.get_paginator('describe_vpcs')
        for page in paginator.paginate():
            for vpc in page.get('Vpcs', []):
                vpc_id = vpc['VpcId']
                name   = next((t['Value'] for t in vpc.get('Tags', []) if t['Key'] == 'Name'), vpc_id)
                cache[vpc_id] = name
    except Exception as e:
        print(f"    Warning: Could not build VPC cache: {e}")
    return cache


# ── Per-region worker (runs in its own thread) ────────────────────────────────

def process_region(region, name_filter):
    """
    Processes a single region — runs in parallel via ThreadPoolExecutor.
    Returns (region, list_of_route_dicts)
    """
    routes_in_region = []
    print(f"[{region}] Starting...")

    try:
        ec2 = boto3.client('ec2', region_name=region)

        # Build caches once per region
        attachment_cache = build_attachment_cache(ec2)
        vpc_cache        = build_vpc_cache(ec2)
        print(f"[{region}] Cached {len(attachment_cache)} attachments, {len(vpc_cache)} VPCs")

        paginator = ec2.get_paginator('describe_transit_gateway_route_tables')
        for page in paginator.paginate():
            for tgw_rt in page.get('TransitGatewayRouteTables', []):

                tgw_rt_id   = tgw_rt['TransitGatewayRouteTableId']
                tgw_rt_name = next(
                    (t['Value'] for t in tgw_rt.get('Tags', []) if t['Key'] == 'Name'),
                    tgw_rt_id
                )

                if name_filter.lower() not in tgw_rt_name.lower():
                    continue

                print(f"[{region}] Matched: {tgw_rt_name} ({tgw_rt_id})")

                routes = ec2.search_transit_gateway_routes(
                    TransitGatewayRouteTableId=tgw_rt_id,
                    Filters=[{'Name': 'state', 'Values': ['active', 'blackhole']}]
                ).get('Routes', [])

                for route in routes:
                    attachments = route.get('TransitGatewayAttachments', [])

                    att_ids   = [a.get('TransitGatewayAttachmentId', '') for a in attachments]
                    att_types = [a.get('ResourceType', '')               for a in attachments]
                    res_ids   = [a.get('ResourceId', '')                 for a in attachments]
                    att_names = [attachment_cache.get(i, i)              for i in att_ids]
                    vpc_names = [
                        vpc_cache.get(r, r) if t == 'vpc' else ''
                        for t, r in zip(att_types, res_ids)
                    ]

                    routes_in_region.append({
                        'Region':                       region,
                        'TransitGatewayRouteTableId':   tgw_rt_id,
                        'TransitGatewayRouteTableName': tgw_rt_name,
                        'DestinationCidrBlock':         route.get('DestinationCidrBlock', ''),
                        'DestinationPrefixListId':      route.get('PrefixListId', ''),
                        'State':                        route.get('State', ''),
                        'Type':                         route.get('Type', ''),
                        'AttachmentIds':                ', '.join(att_ids),
                        'AttachmentNames':              ', '.join(att_names),
                        'AttachmentTypes':              ', '.join(att_types),
                        'AttachmentResourceIds':        ', '.join(res_ids),
                        'VpcName':                      ', '.join(filter(None, vpc_names)),
                    })

                print(f"[{region}] Collected {len(routes)} routes from {tgw_rt_name}.")

    except Exception as e:
        print(f"[{region}] ERROR: {e}")

    print(f"[{region}] Done — {len(routes_in_region)} total routes.")
    return region, routes_in_region


# ── Parallel orchestrator ─────────────────────────────────────────────────────

def get_all_tgw_routes(regions, name_filter, max_workers=7):
    """
    Spawns one thread per region and collects results as they complete.
    Returns dict: { region -> [route_dicts] }
    """
    results = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_region, region, name_filter): region
            for region in regions
        }
        for future in as_completed(futures):
            region, routes = future.result()
            results[region] = routes

    return results


# ── Excel export — one tab per region + summary tab ──────────────────────────

def export_to_excel(region_data, output_file):
    all_routes = []

    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:

        for region in sorted(region_data.keys()):
            routes = region_data[region]

            # Always write a tab even if no routes found in that region
            df = pd.DataFrame(routes) if routes else pd.DataFrame(
                columns=['Region', 'TransitGatewayRouteTableId', 'TransitGatewayRouteTableName',
                         'DestinationCidrBlock', 'DestinationPrefixListId', 'State', 'Type',
                         'AttachmentIds', 'AttachmentNames', 'AttachmentTypes',
                         'AttachmentResourceIds', 'VpcName']
            )

            # Shorten tab name: 'us-east-1' -> 'us-east-1' (Excel limit: 31 chars)
            tab_name = region[:31]
            df.to_excel(writer, sheet_name=tab_name, index=False)
            print(f"  Tab '{tab_name}': {len(routes)} routes")

            all_routes.extend(routes)

        # Summary tab — all regions combined
        if all_routes:
            df_all = pd.DataFrame(all_routes)
            df_all.to_excel(writer, sheet_name='ALL-REGIONS', index=False)
            print(f"  Tab 'ALL-REGIONS': {len(all_routes)} total routes")

    print(f"\nExported to {output_file}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    regions_to_check = [
        'us-east-1', 'us-west-2',
        'eu-central-1'
    ]
    name_filter_string = 'firewall-vpc'
    output_file        = 'firewall-vpcTGWRouteData-after.xlsx'

    print(f"Querying {len(regions_to_check)} regions in parallel...\n")
    region_data = get_all_tgw_routes(regions_to_check, name_filter_string)

    total_routes = sum(len(v) for v in region_data.values())

    if total_routes > 0:
        export_to_excel(region_data, output_file)
    else:
        print("No routes found. Check: AWS credentials, regions, or name filter string.")


if __name__ == "__main__":
    main()
