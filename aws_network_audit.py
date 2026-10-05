"""
AWS Multi-Region Network Configuration Extractor
=================================================
Pulls networking config from ap-northeast-1, us-east-1, eu-central-1 and
writes each dataset to its own Excel sheet for offline security/architecture audit.

Usage:
  python aws_network_audit.py [--profile PROFILE_NAME] [--dry-run]

Requirements:
  pip install boto3 pandas openpyxl
"""

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import boto3
import pandas as pd
from botocore.config import Config
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REGIONS = ["ap-northeast-1", "us-east-1", "eu-central-1"]

# Adaptive retry handles throttling (Throttling / RequestLimitExceeded)
BOTO_CONFIG = Config(retries={"max_attempts": 10, "mode": "adaptive"})

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: tag extraction
# ---------------------------------------------------------------------------

def get_tag(tags: list | None, key: str = "Name") -> str:
    """Return the value of a named tag, or '' if absent."""
    if not tags:
        return ""
    for t in tags:
        if t.get("Key") == key:
            return t.get("Value", "")
    return ""


def safe_get(d: dict, *keys, default="") -> Any:
    """Safely traverse nested dict keys."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur if cur is not None else default


# ---------------------------------------------------------------------------
# Dataset fetchers  (one per dataset per region)
# ---------------------------------------------------------------------------

def fetch_vpcs(session: boto3.Session, region: str) -> pd.DataFrame:
    """
    ec2.describe_vpcs — paginated.
    Returns one row per VPC; all associated CIDR blocks joined as comma-separated.
    """
    rows = []
    try:
        ec2 = session.client("ec2", region_name=region, config=BOTO_CONFIG)
        paginator = ec2.get_paginator("describe_vpcs")
        for page in paginator.paginate():
            for v in page.get("Vpcs", []):
                cidr_assocs = ",".join(
                    a.get("CidrBlock", "")
                    for a in v.get("CidrBlockAssociationSet", [])
                )
                rows.append({
                    "Region": region,
                    "VpcId": v.get("VpcId", ""),
                    "PrimaryCidr": v.get("CidrBlock", ""),
                    "AllCidrs": cidr_assocs,
                    "State": v.get("State", ""),
                    "Tenancy": safe_get(v, "InstanceTenancy"),
                    "IsDefault": v.get("IsDefault", False),
                    "DhcpOptionsId": v.get("DhcpOptionsId", ""),
                    "Name": get_tag(v.get("Tags")),
                })
    except Exception as exc:
        log.error("[%s] VPCs fetch failed: %s", region, exc)
    return pd.DataFrame(rows)


def fetch_subnets(session: boto3.Session, region: str) -> pd.DataFrame:
    """ec2.describe_subnets — paginated."""
    rows = []
    try:
        ec2 = session.client("ec2", region_name=region, config=BOTO_CONFIG)
        paginator = ec2.get_paginator("describe_subnets")
        for page in paginator.paginate():
            for s in page.get("Subnets", []):
                rows.append({
                    "Region": region,
                    "SubnetId": s.get("SubnetId", ""),
                    "VpcId": s.get("VpcId", ""),
                    "CidrBlock": s.get("CidrBlock", ""),
                    "AvailabilityZone": s.get("AvailabilityZone", ""),
                    "AvailableIpCount": s.get("AvailableIpAddressCount", ""),
                    "AutoAssignPublicIp": s.get("MapPublicIpOnLaunch", False),
                    "State": s.get("State", ""),
                    "Name": get_tag(s.get("Tags")),
                })
    except Exception as exc:
        log.error("[%s] Subnets fetch failed: %s", region, exc)
    return pd.DataFrame(rows)


def fetch_route_tables(session: boto3.Session, region: str) -> pd.DataFrame:
    """
    ec2.describe_route_tables — paginated.
    Normalized/flattened: one row per route within each route table.
    """
    rows = []
    try:
        ec2 = session.client("ec2", region_name=region, config=BOTO_CONFIG)
        paginator = ec2.get_paginator("describe_route_tables")
        for page in paginator.paginate():
            for rt in page.get("RouteTables", []):
                rt_id = rt.get("RouteTableId", "")
                vpc_id = rt.get("VpcId", "")
                name = get_tag(rt.get("Tags"))

                # Determine if this is the main (implicit) route table for the VPC
                is_main = any(
                    a.get("Main", False)
                    for a in rt.get("Associations", [])
                )

                # Collect subnet/gateway associations
                assoc_subnets = ",".join(
                    a.get("SubnetId", a.get("GatewayId", ""))
                    for a in rt.get("Associations", [])
                    if a.get("SubnetId") or a.get("GatewayId")
                )

                # Flatten routes — one row per route
                for route in rt.get("Routes", []):
                    # Determine route target (first non-None wins)
                    target = (
                        route.get("GatewayId")
                        or route.get("NatGatewayId")
                        or route.get("VpcPeeringConnectionId")
                        or route.get("TransitGatewayId")
                        or route.get("NetworkInterfaceId")
                        or route.get("LocalGatewayId")
                        or route.get("CarrierGatewayId")
                        or route.get("EgressOnlyInternetGatewayId")
                        or "local"
                    )
                    rows.append({
                        "Region": region,
                        "RouteTableId": rt_id,
                        "VpcId": vpc_id,
                        "Name": name,
                        "IsMain": is_main,
                        "Associations": assoc_subnets,
                        "DestinationCidr": route.get("DestinationCidrBlock", ""),
                        "DestinationIpv6Cidr": route.get("DestinationIpv6CidrBlock", ""),
                        "DestinationPrefixListId": route.get("DestinationPrefixListId", ""),
                        "Target": target,
                        "State": route.get("State", ""),
                        "Origin": route.get("Origin", ""),
                    })
    except Exception as exc:
        log.error("[%s] RouteTables fetch failed: %s", region, exc)
    return pd.DataFrame(rows)


def fetch_vpc_peering(session: boto3.Session, region: str) -> pd.DataFrame:
    """ec2.describe_vpc_peering_connections — paginated."""
    rows = []
    try:
        ec2 = session.client("ec2", region_name=region, config=BOTO_CONFIG)
        paginator = ec2.get_paginator("describe_vpc_peering_connections")
        for page in paginator.paginate():
            for p in page.get("VpcPeeringConnections", []):
                req = p.get("RequesterVpcInfo", {})
                acc = p.get("AccepterVpcInfo", {})
                rows.append({
                    "Region": region,
                    "PeeringConnectionId": p.get("VpcPeeringConnectionId", ""),
                    "Status": safe_get(p, "Status", "Code"),
                    "StatusMessage": safe_get(p, "Status", "Message"),
                    "RequesterVpcId": req.get("VpcId", ""),
                    "RequesterAccountId": req.get("OwnerId", ""),
                    "RequesterRegion": req.get("Region", ""),
                    "RequesterCidr": req.get("CidrBlock", ""),
                    "AccepterVpcId": acc.get("VpcId", ""),
                    "AccepterAccountId": acc.get("OwnerId", ""),
                    "AccepterRegion": acc.get("Region", ""),
                    "AccepterCidr": acc.get("CidrBlock", ""),
                    "Name": get_tag(p.get("Tags")),
                })
    except Exception as exc:
        log.error("[%s] VPC Peering fetch failed: %s", region, exc)
    return pd.DataFrame(rows)


def fetch_vgws(session: boto3.Session, region: str) -> pd.DataFrame:
    """
    ec2.describe_vpn_gateways — no paginator (API returns all results);
    uses filters to avoid cross-region noise.
    """
    rows = []
    try:
        ec2 = session.client("ec2", region_name=region, config=BOTO_CONFIG)
        # No paginator for describe_vpn_gateways — response is complete
        resp = ec2.describe_vpn_gateways()
        for vgw in resp.get("VpnGateways", []):
            attached_vpcs = ",".join(
                a.get("VpcId", "") for a in vgw.get("VpcAttachments", [])
            )
            rows.append({
                "Region": region,
                "VpnGatewayId": vgw.get("VpnGatewayId", ""),
                "State": vgw.get("State", ""),
                "Type": vgw.get("Type", ""),
                "AmazonSideAsn": vgw.get("AmazonSideAsn", ""),
                "AttachedVpcs": attached_vpcs,
                "AvailabilityZone": vgw.get("AvailabilityZone", ""),
                "Name": get_tag(vgw.get("Tags")),
            })
    except Exception as exc:
        log.error("[%s] VGW fetch failed: %s", region, exc)
    return pd.DataFrame(rows)


def fetch_vpn_connections(session: boto3.Session, region: str) -> pd.DataFrame:
    """
    ec2.describe_vpn_connections — paginated.
    Flattens tunnel telemetry into comma-separated fields.
    """
    rows = []
    try:
        ec2 = session.client("ec2", region_name=region, config=BOTO_CONFIG)
        paginator = ec2.get_paginator("describe_vpn_connections")
        for page in paginator.paginate():
            for vpn in page.get("VpnConnections", []):
                # Tunnel details
                tunnels = vpn.get("VgwTelemetry", [])
                tunnel_outside_ips = ",".join(t.get("OutsideIpAddress", "") for t in tunnels)
                tunnel_statuses = ",".join(t.get("Status", "") for t in tunnels)
                tunnel_bgp_asns = ",".join(str(t.get("AcceptedRouteCount", "")) for t in tunnels)

                # Static routes
                static_routes = ",".join(
                    r.get("DestinationCidrBlock", "")
                    for r in vpn.get("Routes", [])
                )

                # Options
                opts = vpn.get("Options", {})
                rows.append({
                    "Region": region,
                    "VpnConnectionId": vpn.get("VpnConnectionId", ""),
                    "State": vpn.get("State", ""),
                    "Type": vpn.get("Type", ""),
                    "VpnGatewayId": vpn.get("VpnGatewayId", ""),
                    "TransitGatewayId": vpn.get("TransitGatewayId", ""),
                    "CustomerGatewayId": vpn.get("CustomerGatewayId", ""),
                    "CustomerGatewayConfig": "see AWS console",  # raw XML omitted
                    "StaticRoutesOnly": safe_get(opts, "StaticRoutesOnly"),
                    "LocalIpv4NetworkCidr": safe_get(opts, "LocalIpv4NetworkCidr"),
                    "RemoteIpv4NetworkCidr": safe_get(opts, "RemoteIpv4NetworkCidr"),
                    "StaticRoutes": static_routes,
                    "TunnelOutsideIps": tunnel_outside_ips,
                    "TunnelStatuses": tunnel_statuses,
                    "TunnelAcceptedRouteCounts": tunnel_bgp_asns,
                    "Name": get_tag(vpn.get("Tags")),
                })
    except Exception as exc:
        log.error("[%s] VPN Connections fetch failed: %s", region, exc)
    return pd.DataFrame(rows)


def fetch_dx_connections_and_vifs(session: boto3.Session, region: str) -> pd.DataFrame:
    """
    directconnect.describe_connections + describe_virtual_interfaces
    Joined on ConnectionId where possible, then unioned.
    Direct Connect is a global service but connections/VIFs are regional.
    """
    rows = []
    try:
        dx = session.client("directconnect", region_name=region, config=BOTO_CONFIG)

        # Connections (no paginator — describe_connections returns all)
        conn_resp = dx.describe_connections()
        conn_map = {}
        for c in conn_resp.get("Connections", []):
            cid = c.get("connectionId", "")
            conn_map[cid] = {
                "Region": region,
                "ConnectionId": cid,
                "ConnectionName": c.get("connectionName", ""),
                "Location": c.get("location", ""),
                "Bandwidth": c.get("bandwidth", ""),
                "ConnectionState": c.get("connectionState", ""),
                "PartnerName": c.get("partnerName", ""),
                "ProviderName": c.get("providerName", ""),
                "OwnerAccount": c.get("ownerAccount", ""),
                "HasLogicalRedundancy": c.get("hasLogicalRedundancy", ""),
                # VIF-level fields (filled below when matched)
                "VifId": "",
                "VifType": "",
                "VifName": "",
                "Vlan": "",
                "VifState": "",
                "AssociatedVgwId": "",
                "AssociatedDxGatewayId": "",
                "Asn": "",
                "AuthKey": "",
                "AmazonAddress": "",
                "CustomerAddress": "",
            }

        # Virtual Interfaces — no paginator
        vif_resp = dx.describe_virtual_interfaces()
        for vif in vif_resp.get("virtualInterfaces", []):
            cid = vif.get("connectionId", "")
            vif_row = {
                "Region": region,
                "ConnectionId": cid,
                "ConnectionName": conn_map.get(cid, {}).get("ConnectionName", ""),
                "Location": conn_map.get(cid, {}).get("Location", ""),
                "Bandwidth": conn_map.get(cid, {}).get("Bandwidth", ""),
                "ConnectionState": conn_map.get(cid, {}).get("ConnectionState", ""),
                "PartnerName": conn_map.get(cid, {}).get("PartnerName", ""),
                "ProviderName": conn_map.get(cid, {}).get("ProviderName", ""),
                "OwnerAccount": vif.get("ownerAccount", ""),
                "HasLogicalRedundancy": conn_map.get(cid, {}).get("HasLogicalRedundancy", ""),
                "VifId": vif.get("virtualInterfaceId", ""),
                "VifType": vif.get("virtualInterfaceType", ""),
                "VifName": vif.get("virtualInterfaceName", ""),
                "Vlan": vif.get("vlan", ""),
                "VifState": vif.get("virtualInterfaceState", ""),
                "AssociatedVgwId": vif.get("virtualGatewayId", ""),
                "AssociatedDxGatewayId": vif.get("directConnectGatewayId", ""),
                "Asn": vif.get("asn", ""),
                "AuthKey": vif.get("authKey", ""),
                "AmazonAddress": vif.get("amazonAddress", ""),
                "CustomerAddress": vif.get("customerAddress", ""),
            }
            rows.append(vif_row)
            # Remove matched connection from conn_map so we only add un-matched ones below
            conn_map.pop(cid, None)

        # Add connections with no VIFs
        for c in conn_map.values():
            rows.append(c)

    except Exception as exc:
        log.error("[%s] Direct Connect Connections/VIFs fetch failed: %s", region, exc)
    return pd.DataFrame(rows)


def fetch_dx_gateway_associations(session: boto3.Session, region: str) -> pd.DataFrame:
    """
    directconnect.describe_direct_connect_gateways (global, no paginator needed) +
    describe_direct_connect_gateway_associations (paginated via nextToken).
    DX Gateways are global; we fetch from every region but deduplicate on DX GW ID.
    """
    rows = []
    try:
        dx = session.client("directconnect", region_name=region, config=BOTO_CONFIG)

        # Fetch all DX Gateways (uses nextToken pagination manually)
        gateways = []
        kwargs: dict = {}
        while True:
            resp = dx.describe_direct_connect_gateways(**kwargs)
            gateways.extend(resp.get("directConnectGateways", []))
            next_token = resp.get("nextToken")
            if not next_token:
                break
            kwargs = {"nextToken": next_token}

        for gw in gateways:
            gw_id = gw.get("directConnectGatewayId", "")

            # Fetch associations for this DX Gateway (nextToken pagination)
            assoc_kwargs: dict = {"directConnectGatewayId": gw_id}
            while True:
                assoc_resp = dx.describe_direct_connect_gateway_associations(**assoc_kwargs)
                for assoc in assoc_resp.get("directConnectGatewayAssociations", []):
                    allowed_prefixes = ",".join(
                        p.get("cidr", "") for p in assoc.get("allowedPrefixesToDirectConnectGateway", [])
                    )
                    rows.append({
                        "Region": region,
                        "DxGatewayId": gw_id,
                        "DxGatewayName": gw.get("directConnectGatewayName", ""),
                        "DxGatewayState": gw.get("directConnectGatewayState", ""),
                        "DxGatewayOwnerAccount": gw.get("ownerAccount", ""),
                        "AmazonSideAsn": gw.get("amazonSideAsn", ""),
                        "AssociationId": assoc.get("associationId", ""),
                        "AssociatedGatewayId": safe_get(assoc, "associatedGateway", "id"),
                        "AssociatedGatewayType": safe_get(assoc, "associatedGateway", "type"),
                        "AssociatedGatewayOwnerAccount": safe_get(assoc, "associatedGateway", "ownerAccount"),
                        "AssociatedGatewayRegion": safe_get(assoc, "associatedGateway", "region"),
                        "AssociationState": assoc.get("associationState", ""),
                        "AllowedPrefixes": allowed_prefixes,
                    })
                next_token = assoc_resp.get("nextToken")
                if not next_token:
                    break
                assoc_kwargs["nextToken"] = next_token

    except Exception as exc:
        log.error("[%s] DX Gateway Associations fetch failed: %s", region, exc)
    return pd.DataFrame(rows)


def fetch_vpc_vgw_associations(session: boto3.Session, region: str) -> pd.DataFrame:
    """
    Derived from ec2.describe_vpn_gateways VpcAttachments.
    One row per VGW ↔ VPC attachment.
    """
    rows = []
    try:
        ec2 = session.client("ec2", region_name=region, config=BOTO_CONFIG)
        resp = ec2.describe_vpn_gateways()
        for vgw in resp.get("VpnGateways", []):
            vgw_id = vgw.get("VpnGatewayId", "")
            for att in vgw.get("VpcAttachments", []):
                rows.append({
                    "Region": region,
                    "VpnGatewayId": vgw_id,
                    "VpcId": att.get("VpcId", ""),
                    "AttachmentState": att.get("State", ""),
                    "VgwState": vgw.get("State", ""),
                    "VgwName": get_tag(vgw.get("Tags")),
                })
    except Exception as exc:
        log.error("[%s] VPC-VGW Associations fetch failed: %s", region, exc)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Excel writer helpers
# ---------------------------------------------------------------------------

def auto_fit_columns(ws) -> None:
    """Approximate auto-fit column widths based on max content length."""
    for col_cells in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col_cells[0].column)
        for cell in col_cells:
            try:
                cell_len = len(str(cell.value)) if cell.value is not None else 0
                if cell_len > max_len:
                    max_len = cell_len
            except Exception:
                pass
        # Cap at 60 chars wide; add a little padding
        ws.column_dimensions[col_letter].width = min(max_len + 2, 62)


def style_header_row(ws) -> None:
    """Bold + teal fill on header row; freeze pane below it."""
    header_fill = PatternFill(start_color="1F6B75", end_color="1F6B75", fill_type="solid")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
    ws.freeze_panes = "A2"


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

# Map of dataset name → fetcher function
FETCHERS = {
    "VPCs": fetch_vpcs,
    "Subnets": fetch_subnets,
    "RouteTables": fetch_route_tables,
    "VPC_Peering": fetch_vpc_peering,
    "VGWs": fetch_vgws,
    "VPN_Connections": fetch_vpn_connections,
    "DX_Connections_VIFs": fetch_dx_connections_and_vifs,
    "DX_GW_Associations": fetch_dx_gateway_associations,
    "VPC_VGW_Associations": fetch_vpc_vgw_associations,
}


def run_audit(profile: str | None, dry_run: bool) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_file = f"aws_network_audit_{timestamp}.xlsx"

    log.info("Starting AWS Network Audit — regions: %s", ", ".join(REGIONS))
    log.info("Profile: %s", profile or "default credential chain")

    # Build one Session per region (thread-safe; clients created inside threads)
    sessions: dict[str, boto3.Session] = {}
    for region in REGIONS:
        sessions[region] = boto3.Session(profile_name= profile ) if boto3.Session() else boto3.Session()

    # Build task list: all (dataset × region) combinations dispatched concurrently
    tasks: list[tuple[str, str]] = [
        (dataset, region)
        for dataset in FETCHERS
        for region in REGIONS
    ]

    # Collect results: {dataset_name: list of DataFrames (one per region)}
    results: dict[str, list[pd.DataFrame]] = {ds: [] for ds in FETCHERS}

    log.info("Dispatching %d tasks across %d workers…", len(tasks), len(tasks))
    with ThreadPoolExecutor(max_workers=min(len(tasks), 30)) as executor:
        future_map = {
            executor.submit(FETCHERS[ds], sessions[region], region): (ds, region)
            for ds, region in tasks
        }
        for future in as_completed(future_map):
            ds, region = future_map[future]
            try:
                df = future.result()
                results[ds].append(df)
                log.info("  ✓ %-28s [%s]  %d rows", ds, region, len(df))
            except Exception as exc:
                log.error("  ✗ %-28s [%s]  FAILED: %s", ds, region, exc)
                results[ds].append(pd.DataFrame())  # keep sheet even on failure

    # Merge per-region DataFrames for each dataset
    merged: dict[str, pd.DataFrame] = {}
    for ds, frames in results.items():
        non_empty = [f for f in frames if not f.empty]
        merged[ds] = pd.concat(non_empty, ignore_index=True) if non_empty else pd.DataFrame()

    # ------------------------------------------------------------------
    # Dry-run summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"{'Dataset':<30} {'Rows':>8}")
    print("-" * 60)
    for ds, df in merged.items():
        print(f"  {ds:<28} {len(df):>8,}")
    print("=" * 60)
    total = sum(len(df) for df in merged.values())
    print(f"  {'TOTAL':<28} {total:>8,}")
    print()

    if dry_run:
        log.info("--dry-run flag set — skipping Excel output.")
        return

    # ------------------------------------------------------------------
    # Write Excel workbook
    # ------------------------------------------------------------------
    log.info("Writing workbook → %s", output_file)
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        for ds, df in merged.items():
            sheet_name = ds[:31]  # Excel sheet names max 31 chars
            if df.empty:
                # Write empty sheet with a placeholder row so the tab exists
                placeholder = pd.DataFrame(
                    [{"Info": f"No data found for {ds} across queried regions."}]
                )
                placeholder.to_excel(writer, sheet_name=sheet_name, index=False)
            else:
                df.to_excel(writer, sheet_name=sheet_name, index=False)

            ws = writer.sheets[sheet_name]
            style_header_row(ws)
            auto_fit_columns(ws)

    log.info("Done. Workbook saved: %s", output_file)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AWS Multi-Region Network Configuration Extractor"
    )
    parser.add_argument(
        "--profile",
        metavar=boto3.session,
        default=None,
        help="AWS named profile (default: use environment/instance role)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print row-count summary only; do not write the Excel file",
    )
    args = parser.parse_args()
    run_audit(profile=args.profile, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
