"""
Managed Prefix List CIDR Updater
==================================
Adds CIDR entries to "CIDR-US" prefix list across  regions.
Skips duplicates — only adds CIDRs not already present.

Credentials — set these in PowerShell before running:
  $env:AWS_ACCESS_KEY_ID     = "AKIAxxxxxxxxxxxxxxxxx"
  $env:AWS_SECRET_ACCESS_KEY = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  $env:AWS_SESSION_TOKEN     = "xxxxx..."   # only if using temporary/SSO creds

Usage:
  python update_aws_prefix_list.py

Requirements:
  pip install boto3
"""

import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, NoCredentialsError

# ---------------------------------------------------------------------------
# CONFIGURE HERE
# ---------------------------------------------------------------------------

REGIONS = [
    "ap-northeast-1",   # Tokyo
    "us-west-2",        # Oregon
    "eu-west-1",        # Ireland
]

PREFIX_LIST_NAME = "CIDR-us-east-1"

# ✏️  Add your CIDRs here
CIDRS_TO_ADD = [
   
    # Add more entries below:
    #{"Cidr": "10.10.10.10/32", "Description": "test"},
    #{"Cidr": "20.10.10.10/32", "Description": "test"
]

# ---------------------------------------------------------------------------
# Boto3 config
# ---------------------------------------------------------------------------

BOTO_CONFIG = Config(retries={"max_attempts": 10, "mode": "adaptive"})

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Credential check — fail fast with a clear message if env vars are missing
# ---------------------------------------------------------------------------

def check_credentials() -> None:
    missing = [
        var for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
        if not os.environ.get(var)
    ]
    if missing:
        log.error("Missing environment variable(s): %s", ", ".join(missing))
        log.error("Set them in PowerShell before running:")
        log.error('  $env:AWS_ACCESS_KEY_ID     = "AKIAxxxxxxxxxxxxxxxxx"')
        log.error('  $env:AWS_SECRET_ACCESS_KEY = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"')
        log.error('  $env:AWS_SESSION_TOKEN     = "xxxxx..."  # if using SSO/temporary creds')
        sys.exit(1)
    log.info("Credentials found — AWS_ACCESS_KEY_ID=%s***",
             os.environ["AWS_ACCESS_KEY_ID"][:8])


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def get_prefix_list(ec2, region: str):
    try:
        paginator = ec2.get_paginator("describe_managed_prefix_lists")
        for page in paginator.paginate(
            Filters=[{"Name": "prefix-list-name", "Values": [PREFIX_LIST_NAME]}]
        ):
            lists = page.get("PrefixLists", [])
            if lists:
                return lists[0]
        log.warning("[%s] Prefix list '%s' not found.", region, PREFIX_LIST_NAME)
        return None
    except Exception as exc:
        log.error("[%s] Failed to describe prefix list: %s", region, exc)
        return None


def get_existing_cidrs(ec2, prefix_list_id: str, region: str):
    existing = set()
    try:
        paginator = ec2.get_paginator("get_managed_prefix_list_entries")
        for page in paginator.paginate(PrefixListId=prefix_list_id):
            for entry in page.get("Entries", []):
                existing.add(entry["Cidr"])
    except Exception as exc:
        log.error("[%s] Failed to fetch existing entries: %s", region, exc)
    return existing


def wait_for_modify_complete(ec2, prefix_list_id: str, region: str, timeout: int = 120) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = ec2.describe_managed_prefix_lists(PrefixListIds=[prefix_list_id])
            state = resp["PrefixLists"][0]["State"]
            if state in ("modify-complete", "create-complete"):
                return True
            if "failed" in state:
                log.error("[%s] Prefix list entered failed state: %s", region, state)
                return False
            log.info("[%s] Prefix list state: %s — waiting…", region, state)
            time.sleep(5)
        except Exception as exc:
            log.error("[%s] Error polling prefix list state: %s", region, exc)
            return False
    log.error("[%s] Timed out waiting for prefix list to be ready.", region)
    return False


def update_region(region: str) -> dict:
    result = {
        "region": region,
        "status": "ok",
        "added": [],
        "skipped": [],
        "error": None,
    }

    try:
        # Explicitly read from env vars — no profile lookup at all
        ec2 = boto3.client(
            "ec2",
            region_name=region,
            config=BOTO_CONFIG,
            aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
            aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),  # None if not set
        )

        pl = get_prefix_list(ec2, region)
        if not pl:
            result["status"] = "not_found"
            return result

        pl_id       = pl["PrefixListId"]
        pl_version  = pl["Version"]
        max_entries = pl["MaxEntries"]

        log.info("[%s] Found: %s  (id=%s, version=%d, max=%d)",
                 region, PREFIX_LIST_NAME, pl_id, pl_version, max_entries)

        existing_cidrs = get_existing_cidrs(ec2, pl_id, region)
        log.info("[%s] Existing entries: %d", region, len(existing_cidrs))

        new_entries = [e for e in CIDRS_TO_ADD if e["Cidr"] not in existing_cidrs]
        skipped     = [e["Cidr"] for e in CIDRS_TO_ADD if e["Cidr"] in existing_cidrs]

        result["skipped"] = skipped

        if skipped:
            log.info("[%s] Skipping %d duplicate(s): %s", region, len(skipped), ", ".join(skipped))

        if not new_entries:
            log.info("[%s] Nothing new to add — prefix list is already up to date.", region)
            result["status"] = "up_to_date"
            return result

        if len(existing_cidrs) + len(new_entries) > max_entries:
            log.error("[%s] Not enough capacity. Current=%d, Adding=%d, Max=%d",
                      region, len(existing_cidrs), len(new_entries), max_entries)
            result["status"] = "capacity_exceeded"
            result["error"]  = f"Max entries ({max_entries}) would be exceeded"
            return result

        if not wait_for_modify_complete(ec2, pl_id, region):
            result["status"] = "error"
            result["error"]  = "Prefix list not in modifiable state"
            return result

        log.info("[%s] Adding %d new CIDR(s): %s",
                 region, len(new_entries), ", ".join(e["Cidr"] for e in new_entries))

        ec2.modify_managed_prefix_list(
            PrefixListId=pl_id,
            CurrentVersion=pl_version,
            AddEntries=new_entries,
        )

        wait_for_modify_complete(ec2, pl_id, region)

        result["added"] = [e["Cidr"] for e in new_entries]
        log.info("[%s] ✓ Successfully added %d CIDR(s)", region, len(new_entries))

    except NoCredentialsError as exc:
        log.error("[%s] No credentials found: %s", region, exc)
        result["status"] = "error"
        result["error"]  = str(exc)

    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        error_msg  = exc.response["Error"]["Message"]
        log.error("[%s] AWS error (%s): %s", region, error_code, error_msg)
        result["status"] = "error"
        result["error"]  = f"{error_code}: {error_msg}"

    except Exception as exc:
        log.error("[%s] Unexpected error: %s", region, exc)
        result["status"] = "error"
        result["error"]  = str(exc)

    return result


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def main() -> None:
    check_credentials()

    log.info("=" * 60)
    log.info("Prefix List Updater — %s", PREFIX_LIST_NAME)
    log.info("Regions : %s", ", ".join(REGIONS))
    log.info("CIDRs   : %d to process", len(CIDRS_TO_ADD))
    log.info("=" * 60)

    results = []
    with ThreadPoolExecutor(max_workers=len(REGIONS)) as executor:
        future_map = {executor.submit(update_region, r): r for r in REGIONS}
        for future in as_completed(future_map):
            results.append(future.result())

    print("\n" + "=" * 65)
    print(f"  {'Region':<22} {'Status':<18} {'Added':<6} {'Skipped'}")
    print("-" * 65)

    for r in sorted(results, key=lambda x: x["region"]):
        skipped = len(r["skipped"])
        error   = f"  ERROR: {r['error']}" if r["error"] else ""
        print(f"  {r['region']:<22} {r['status']:<18} {len(r['added']):<6} {skipped}{error}")

    print("=" * 65)

    total_added   = sum(len(r["added"])   for r in results)
    total_skipped = sum(len(r["skipped"]) for r in results)
    total_errors  = sum(1 for r in results if r["status"] == "error")

    print(f"  Total added  : {total_added}")
    print(f"  Total skipped: {total_skipped}  (already existed)")
    print(f"  Errors       : {total_errors}")
    print("=" * 65 + "\n")

    if total_errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
