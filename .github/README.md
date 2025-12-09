# Notion Job Search Automation (Beginner-Friendly)

This repository keeps your Notion job-search system updated automatically.

## 🚀 What This Does
- Adds new job applications
- Updates statuses
- Adds interviews + follow-ups
- Runs automatically every 15 minutes on GitHub Actions

## 🧩 Setup Steps (No Coding Needed)

1. Create a Notion integration at https://www.notion.com/my-integrations
2. Share each Notion database with the integration
3. Upload this folder to a new GitHub repo
4. Add your NOTION_TOKEN under GitHub Settings → Secrets → Actions
5. GitHub Actions will start running automatically.

## 🧰 How to use commands locally (optional)
Set the token in your environment and run commands locally to test:
```bash
export NOTION_TOKEN="secret_xxx"
python notion_sync.py add_application --company "ACME" --role "Product Manager"
python notion_sync.py prefill_csv --csv job_applications.csv --type applications
python notion_sync.py run_sync --threads project_threads.json
```

## ✅ Troubleshooting
- If you get permission errors: confirm the integration is shared with the DB.
- If network errors: check internet connection and NOTION_TOKEN value.
- Logs are saved to `notion_sync.log` in the repo root.
