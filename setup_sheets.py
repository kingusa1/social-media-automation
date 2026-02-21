"""One-time setup script to populate existing Google Spreadsheet with tabs and headers."""
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TABS = {
    "Projects": [
        "id", "display_name", "description", "brand_voice", "hashtags",
        "rss_feeds", "scoring_weights", "schedule_cron", "twitter_enabled",
        "is_active", "created_at", "updated_at",
    ],
    "Profiles": [
        "id", "project_id", "platform", "account_type", "display_name",
        "access_token", "refresh_token", "token_expires_at", "platform_user_id",
        "extra_config", "is_active", "created_at", "updated_at",
    ],
    "PipelineRuns": [
        "id", "project_id", "trigger_type", "status", "started_at",
        "completed_at", "articles_fetched", "articles_new",
        "selected_article_id", "ai_model_used", "used_fallback",
        "error_message", "log_details",
    ],
    "Articles": [
        "id", "project_id", "url", "original_url", "title", "source_feed",
        "summary", "published_at", "relevance_score", "was_selected",
        "content_text", "fetch_run_id", "created_at",
    ],
    "GeneratedPosts": [
        "id", "pipeline_run_id", "project_id", "platform", "content",
        "article_url", "article_title", "is_fallback", "quality_score",
        "validation_notes", "created_at",
    ],
    "PublishResults": [
        "id", "generated_post_id", "profile_id", "platform", "account_type",
        "status", "platform_post_id", "error_message", "posted_at",
    ],
    "AppSettings": [
        "key", "value", "updated_at",
    ],
}

SERVICE_ACCOUNT_FILE = "service_account.json"
SPREADSHEET_ID = "193wer_dfBFqrsITyUfkYw8i3DR2VABtntGsmeG6rHSI"


def main():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)

    print(f"Opening spreadsheet {SPREADSHEET_ID}...")
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    print(f"Opened: {spreadsheet.title}")

    existing_tabs = [ws.title for ws in spreadsheet.worksheets()]
    print(f"Existing tabs: {existing_tabs}")

    first_tab_name = list(TABS.keys())[0]

    # Rename default "Sheet1" to first tab if it exists
    if "Sheet1" in existing_tabs:
        ws = spreadsheet.worksheet("Sheet1")
        ws.update_title(first_tab_name)
        ws.clear()
        ws.append_row(TABS[first_tab_name])
        print(f"  Renamed Sheet1 -> {first_tab_name} (headers set)")
        existing_tabs = [first_tab_name if t == "Sheet1" else t for t in existing_tabs]
    elif first_tab_name not in existing_tabs:
        ws = spreadsheet.add_worksheet(title=first_tab_name, rows=1000, cols=len(TABS[first_tab_name]))
        ws.append_row(TABS[first_tab_name])
        print(f"  Created tab: {first_tab_name}")

    # Create remaining tabs
    for tab_name, headers in list(TABS.items())[1:]:
        if tab_name in existing_tabs:
            print(f"  Tab {tab_name} already exists, setting headers...")
            ws = spreadsheet.worksheet(tab_name)
            ws.clear()
            ws.append_row(headers)
        else:
            ws = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=len(headers))
            ws.append_row(headers)
            print(f"  Created tab: {tab_name}")

    print(f"\nAll tabs created successfully!")
    print(f"Spreadsheet URL: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit")


if __name__ == "__main__":
    main()
