#!/usr/bin/env python3
"""
notion_sync.py - Notion Job Search Sync Engine (Production)
Compatible with Python 3.10+ (you requested 3.11).

What it does:
- Create/update Job Applications, Networking, Interviews, Follow-ups in Notion via API
- Prefill from CSVs
- Run a sync that only acts on project threads that have not been updated for 2+ hours
- Safe: uses NOTION_TOKEN from environment or GitHub Secrets (do NOT paste tokens in chat)

Usage:
    python notion_sync.py run_sync --threads project_threads.json
    python notion_sync.py add_application --company "Meta" --role "Program Manager"
    python notion_sync.py prefill_csv --csv job_applications.csv --type applications

Notes:
- Fill DB IDs in the CONFIG section below (they are already pre-filled from your input).
- Share your Notion DBs with your Notion Integration before running.
"""

from __future__ import annotations
import os
import sys
import json
import time
import csv
import logging
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------- CONFIG ----------------
NOTION_TOKEN = os.getenv("NOTION_TOKEN")  # must be set in environment
if not NOTION_TOKEN:
    print("ERROR: NOTION_TOKEN not set. Set it as an environment variable or GitHub Secret.")
    sys.exit(1)

# Database IDs (provided by you)
DB_JOB_APPS = "2c356c757b0780968c5cc58ea0ef1b30"
DB_NETWORKING = "2c356c757b0780f19699c11e1f5e7db1"
DB_INTERVIEWS = "2c356c757b07803f91d5f1836877fc7b"
DB_FOLLOWUPS = "2c456c757b07807b82aefb0c868a58d4"

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"  # stable version; update if needed

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json"
}

# Logging
LOG_PATH = Path("notion_sync.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler(sys.stdout)]
)

# Retry helper for HTTP calls
def http_request_with_retries(method: str, url: str, headers: dict, json_payload: Optional[dict]=None, params: Optional[dict]=None, retries: int=3, backoff: float=1.0):
    for attempt in range(1, retries+1):
        try:
            if method.lower() == "post":
                r = requests.post(url, headers=headers, json=json_payload, params=params, timeout=30)
            elif method.lower() == "patch":
                r = requests.patch(url, headers=headers, json=json_payload, params=params, timeout=30)
            elif method.lower() == "get":
                r = requests.get(url, headers=headers, params=params, timeout=30)
            else:
                raise ValueError("Unsupported HTTP method")
            if r.ok:
                return r.json()
            else:
                logging.warning(f"HTTP {r.status_code} error on {url}: {r.text}")
        except requests.RequestException as e:
            logging.warning(f"Request exception: {e}")
        time.sleep(backoff * attempt)
    raise RuntimeError(f"Failed HTTP request to {url} after {retries} attempts")

# Notion API helpers
def notion_post(path: str, payload: dict) -> dict:
    url = f"{NOTION_API}{path}"
    return http_request_with_retries("post", url, HEADERS, json_payload=payload)

def notion_patch(path: str, payload: dict) -> dict:
    url = f"{NOTION_API}{path}"
    return http_request_with_retries("patch", url, HEADERS, json_payload=payload)

def notion_get(path: str, params: Optional[dict]=None) -> dict:
    url = f"{NOTION_API}{path}"
    return http_request_with_retries("get", url, HEADERS, params=params)

# Utilities for Notion property formatting
def title_prop(text: str) -> dict:
    return {"title": [{"text": {"content": text}}]}

def rich_text_prop(text: str) -> dict:
    return {"rich_text": [{"text": {"content": text}}]}

def select_prop(name: str) -> dict:
    return {"select": {"name": name}}

def date_prop(iso: Optional[str]) -> dict:
    if iso:
        return {"date": {"start": iso}}
    return {"date": None}

def url_prop(url: Optional[str]) -> dict:
    return {"url": url} if url else {}

def checkbox_prop(value: bool) -> dict:
    return {"checkbox": bool(value)}

def relation_prop(page_id: Optional[str]) -> dict:
    if page_id:
        return {"relation": [{"id": page_id}]}
    return {}

# ---------------- Core operations ----------------
def create_job_application(company: str, role: str, jd_summary: str = "", jd_link: str = "", location: str = "", salary_range: str = "", priority: str = "Medium") -> dict:
    logging.info(f"Creating job application: {company} — {role}")
    now_iso = datetime.now(timezone.utc).isoformat()
    properties = {
        "Company": title_prop(company),
        "Role": rich_text_prop(role),
        "Date Applied": date_prop(now_iso),
        "Status": select_prop("Applied"),
        "JD Summary": rich_text_prop(jd_summary),
        "JD Link": url_prop(jd_link),
        "Location": rich_text_prop(location),
        "Salary Range": rich_text_prop(salary_range),
        "Priority": select_prop(priority)
    }
    payload = {"parent": {"database_id": DB_JOB_APPS}, "properties": properties}
    return notion_post("/pages", payload)

def add_network_contact(name: str, company: str = "", role: str = "", linkedin: str = "", email: str = "", status: str = "Cold") -> dict:
    logging.info(f"Adding network contact: {name} @ {company}")
    properties = {
        "Name": title_prop(name),
        "Company": rich_text_prop(company),
        "Role": rich_text_prop(role),
        "LinkedIn": url_prop(linkedin),
        "Email": {"email": email} if email else {},
        "Status": select_prop(status),
        "Last Contacted": date_prop(None)
    }
    payload = {"parent": {"database_id": DB_NETWORKING}, "properties": properties}
    return notion_post("/pages", payload)

def add_interview(application_page_id: str, stage: str, interviewer: str = "", date_iso: Optional[str] = None, notes: str = "", outcome: str = "Pending") -> dict:
    logging.info(f"Adding interview record for application {application_page_id} stage {stage}")
    props = {
        "Application": relation_prop(application_page_id),
        "Stage": select_prop(stage),
        "Interviewer": rich_text_prop(interviewer),
        "Date": date_prop(date_iso),
        "Notes": rich_text_prop(notes),
        "Outcome": select_prop(outcome)
    }
    payload = {"parent": {"database_id": DB_INTERVIEWS}, "properties": props}
    return notion_post("/pages", payload)

def add_followup(task: str, related_application_page_id: Optional[str] = None, due_date_iso: Optional[str] = None, completed: bool = False, notes: str = "") -> dict:
    logging.info(f"Creating follow-up task: {task}")
    props = {
        "Task": title_prop(task),
        "Related Application": relation_prop(related_application_page_id) if related_application_page_id else {},
        "Due Date": date_prop(due_date_iso) if due_date_iso else {},
        "Completed": checkbox_prop(completed),
        "Notes": rich_text_prop(notes)
    }
    payload = {"parent": {"database_id": DB_FOLLOWUPS}, "properties": props}
    return notion_post("/pages", payload)

# Simple search helper: query database by property (e.g. Company and Role)
def query_database_by_name(db_id: str, property_name: str, value: str) -> List[dict]:
    # Basic filter for 'title' or 'rich_text' depending on property type.
    # Notion's filter JSON is a bit verbose; we'll try common cases.
    payload = {
        "filter": {
            "property": property_name,
            "rich_text": {"contains": value}
        },
        "page_size": 50
    }
    res = notion_post(f"/databases/{db_id}/query", payload)
    return res.get("results", [])

# Prefill CSV utilities
def prefill_from_csv(csv_path: str, db_type: str = "applications"):
    p = Path(csv_path)
    if not p.exists():
        logging.error(f"CSV not found: {csv_path}")
        return
    with p.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            try:
                if db_type == "applications":
                    create_job_application(
                        company=row.get("Company",""),
                        role=row.get("Role",""),
                        jd_summary=row.get("JD Summary",""),
                        jd_link=row.get("JD Link",""),
                        location=row.get("Location",""),
                        salary_range=row.get("Salary Range",""),
                        priority=row.get("Priority","Medium")
                    )
                elif db_type == "networking":
                    add_network_contact(
                        name=row.get("Name",""),
                        company=row.get("Company",""),
                        role=row.get("Role",""),
                        linkedin=row.get("LinkedIn",""),
                        email=row.get("Email",""),
                        status=row.get("Status","Cold")
                    )
                elif db_type == "interviews":
                    add_interview(
                        application_page_id=row.get("Application",""),
                        stage=row.get("Stage",""),
                        interviewer=row.get("Interviewer",""),
                        date_iso=row.get("Date",""),
                        notes=row.get("Notes",""),
                        outcome=row.get("Outcome","Pending")
                    )
                elif db_type == "followups":
                    add_followup(
                        task=row.get("Task",""),
                        related_application_page_id=row.get("Related Application",""),
                        due_date_iso=row.get("Due Date",""),
                        completed=row.get("Completed","False").lower() == "true",
                        notes=row.get("Notes","")
                    )
                count += 1
            except Exception as e:
                logging.exception(f"Failed to insert row: {row} - {e}")
        logging.info(f"Prefilled {count} rows into {db_type}")

# ---------------- Thread-based sync ----------------
# project_threads.json format:
# [
#   {"thread_id":"id","last_updated":"2025-12-08T12:00:00Z","synced":false,"content":"{...json...}"}
# ]

def load_project_threads(path: str = "project_threads.json") -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        logging.info("No project_threads.json found; returning empty list.")
        return []
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data

def write_project_threads(data: List[Dict[str, Any]], path: str = "project_threads.json"):
    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def process_thread_command(cmd: dict):
    action = cmd.get("action")
    if action == "create_application":
        return create_job_application(
            company=cmd.get("company",""),
            role=cmd.get("role",""),
            jd_summary=cmd.get("jd_summary",""),
            jd_link=cmd.get("jd_link",""),
            location=cmd.get("location",""),
            salary_range=cmd.get("salary_range",""),
            priority=cmd.get("priority","Medium")
        )
    elif action == "add_followup":
        return add_followup(
            task=cmd.get("task","Follow up"),
            related_application_page_id=cmd.get("related_application_page_id"),
            due_date_iso=cmd.get("due_date"),
            completed=False,
            notes=cmd.get("notes","")
        )
    elif action == "add_network_contact":
        return add_network_contact(
            name=cmd.get("name",""),
            company=cmd.get("company",""),
            role=cmd.get("role",""),
            linkedin=cmd.get("linkedin",""),
            email=cmd.get("email",""),
            status=cmd.get("status","Cold")
        )
    else:
        raise ValueError(f"Unknown action: {action}")

def run_sync(project_threads_path: str = "project_threads.json"):
    threads = load_project_threads(project_threads_path)
    if not threads:
        logging.info("No threads to sync.")
        return
    now = datetime.now(timezone.utc)
    two_hours = timedelta(hours=2)
    any_synced = False
    for t in threads:
        try:
            last_updated = datetime.fromisoformat(t["last_updated"].replace("Z", "+00:00"))
        except Exception as e:
            logging.warning(f"Invalid last_updated for thread {t.get('thread_id')}: {e}")
            continue
        synced = t.get("synced", False)
        if not synced and (now - last_updated) >= two_hours:
            logging.info(f"Thread {t['thread_id']} eligible for sync (last updated {t['last_updated']}).")
            content = t.get("content", "")
            try:
                cmd = json.loads(content) if isinstance(content, str) and content.strip() else {}
            except Exception as e:
                logging.exception(f"Failed to parse content JSON for thread {t['thread_id']}: {e}")
                continue
            try:
                if cmd:
                    process_thread_command(cmd)
                    t["synced"] = True
                    any_synced = True
                else:
                    logging.info(f"No valid command found in thread {t['thread_id']}; skipping.")
            except Exception as e:
                logging.exception(f"Failed to process thread {t['thread_id']}: {e}")
    if any_synced:
        write_project_threads(threads)
        logging.info("Sync completed and project_threads.json updated.")
    else:
        logging.info("No threads were synced at this time.")

# ---------------- CLI ----------------
def build_cli():
    parser = argparse.ArgumentParser(description="Notion Job Search Sync Engine")
    sub = parser.add_subparsers(dest="cmd")
    sub.required = True

    p_add = sub.add_parser("add_application", help="Add single application")
    p_add.add_argument("--company", required=True)
    p_add.add_argument("--role", required=True)
    p_add.add_argument("--jd_summary", default="")
    p_add.add_argument("--jd_link", default="")
    p_add.add_argument("--location", default="")
    p_add.add_argument("--salary_range", default="")
    p_add.add_argument("--priority", default="Medium")

    p_net = sub.add_parser("add_network", help="Add networking contact")
    p_net.add_argument("--name", required=True)
    p_net.add_argument("--company", default="")
    p_net.add_argument("--role", default="")
    p_net.add_argument("--linkedin", default="")
    p_net.add_argument("--email", default="")
    p_net.add_argument("--status", default="Cold")

    p_prefill = sub.add_parser("prefill_csv", help="Prefill from CSV")
    p_prefill.add_argument("--csv", required=True)
    p_prefill.add_argument("--type", choices=["applications","networking","interviews","followups"], default="applications")

    p_sync = sub.add_parser("run_sync", help="Run thread-based sync")
    p_sync.add_argument("--threads", default="project_threads.json")

    return parser

def main():
    parser = build_cli()
    args = parser.parse_args()
    if args.cmd == "add_application":
        create_job_application(args.company, args.role, args.jd_summary, args.jd_link, args.location, args.salary_range, args.priority)
    elif args.cmd == "add_network":
        add_network_contact(args.name, args.company, args.role, args.linkedin, args.email, args.status)
    elif args.cmd == "prefill_csv":
        prefill_from_csv(args.csv, args.type)
    elif args.cmd == "run_sync":
        run_sync(args.threads)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
