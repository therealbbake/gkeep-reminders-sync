import os
import logging
import time
import threading
from typing import Dict, List

import gkeepapi
import schedule
from flask import Flask, jsonify, request

def env(name: str, default: str | None = None) -> str | None:
    val = os.getenv(name)
    return val if val is not None and val != "" else default

def parse_sync_list_names(raw: str | None) -> List[str]:
    if not raw:
        return []
    return [name.strip() for name in raw.split(",") if name.strip()]

def setup_logging() -> None:
    level = env("LOG_LEVEL", "INFO") or "INFO"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

def login_keep(email: str, password: str | None) -> gkeepapi.Keep | None:
    keep = gkeepapi.Keep()
    master_token = env("GKEEP_MASTER_TOKEN")

    try:
        if master_token:
            keep.authenticate(email, master_token)
        else:
            if not password:
                logging.error("GKEEP_PASSWORD or GKEEP_MASTER_TOKEN must be provided.")
                return None
            keep.authenticate(email, password)

        keep.sync()
        return keep
    except Exception as e:
        logging.exception(f"Failed to authenticate with Google Keep: {e}")
        return None

def fetch_all_keep_lists(keep: gkeepapi.Keep) -> Dict[str, List[str]]:
    lists_data = {}
    try:
        for n in keep.all():
            if isinstance(n, gkeepapi.node.List):
                title = (n.title or "").strip()
                if title:
                    items = []
                    for item in n.items:
                        if getattr(item, "text", None) and not getattr(item, "checked", False):
                            items.append(item.text.strip())
                    lists_data[title] = items
    except Exception as e:
        logging.exception(f"Error while fetching Google Keep lists: {e}")
    return lists_data

def clear_keep_lists(keep: gkeepapi.Keep, sync_list_names: List[str]) -> None:
    """Delete all items from the specified Google Keep lists."""
    for list_name in sync_list_names:
        try:
            # Find the list
            target_list = None
            for n in keep.all():
                if isinstance(n, gkeepapi.node.List) and (n.title or "").strip().lower() == list_name.lower():
                    target_list = n
                    break

            if target_list:
                # Delete all items
                items_deleted = 0
                items_to_delete = list(target_list.items)  # Create a copy to avoid modification during iteration
                for item in items_to_delete:
                    item.delete()
                    items_deleted += 1

                if items_deleted > 0:
                    logging.info(f"Deleted {items_deleted} items from Google Keep list '{list_name}'.")
                else:
                    logging.info(f"No items found in Google Keep list '{list_name}'.")
            else:
                logging.warning(f"Google Keep list '{list_name}' not found.")
        except Exception as e:
            logging.exception(f"Error clearing items in Google Keep list '{list_name}': {e}")

def refresh_lists_job() -> None:
    global keep, keep_lists
    try:
        keep.sync()
        new_lists = fetch_all_keep_lists(keep)
        keep_lists = new_lists
        logging.info(f"Refreshed {len(keep_lists)} lists from Google Keep.")
    except Exception as e:
        logging.exception(f"Error refreshing Google Keep lists: {e}")

app = Flask(__name__)

@app.route('/lists', methods=['GET'])
def get_lists():
    return jsonify(keep_lists)

@app.route('/list/<list_name>', methods=['GET'])
def get_list(list_name):
    if list_name in keep_lists:
        return jsonify({list_name: keep_lists[list_name]})
    else:
        return jsonify({"error": "List not found"}), 404

@app.route('/clear', methods=['POST'])
def clear_lists():
    global keep, keep_lists
    try:
        sync_list_names = parse_sync_list_names(env("SYNC_LIST_NAMES"))
        if not sync_list_names:
            return jsonify({"error": "No lists defined in SYNC_LIST_NAMES environment variable"}), 400

        clear_keep_lists(keep, sync_list_names)
        keep.sync()

        # Refresh in-memory lists
        keep_lists = fetch_all_keep_lists(keep)

        logging.info("Cleared all items in SYNC_LIST_NAMES from Google Keep.")
        return jsonify({"message": f"Cleared all items in lists: {', '.join(sync_list_names)}"})
    except Exception as e:
        logging.exception("Error clearing Google Keep lists: {e}")
        return jsonify({"error": "Failed to clear lists"}), 500

@app.route('/list/<list_name>/item', methods=['POST'])
def add_item(list_name):
    global keep, keep_lists
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({"error": "Missing 'text' field in request body"}), 400

    item_text = data['text'].strip()
    if not item_text:
        return jsonify({"error": "Item text cannot be empty"}), 400

    try:
        # Find the list
        target_list = None
        for n in keep.all():
            if isinstance(n, gkeepapi.node.List) and (n.title or "").strip().lower() == list_name.lower():
                target_list = n
                break

        if not target_list:
            return jsonify({"error": f"List '{list_name}' not found"}), 404

        # Add the item
        target_list.add(item_text, False)  # False means unchecked
        keep.sync()

        # Refresh in-memory lists
        keep_lists = fetch_all_keep_lists(keep)

        logging.info(f"Added item '{item_text}' to list '{list_name}'.")
        return jsonify({"message": f"Added item '{item_text}' to list '{list_name}'"})
    except Exception as e:
        logging.exception(f"Error adding item to list '{list_name}': {e}")
        return jsonify({"error": "Failed to add item"}), 500

@app.route('/list/<list_name>/item/<item_text>/check', methods=['PUT'])
def check_item(list_name, item_text):
    global keep, keep_lists
    try:
        # Find the list
        target_list = None
        for n in keep.all():
            if isinstance(n, gkeepapi.node.List) and (n.title or "").strip().lower() == list_name.lower():
                target_list = n
                break

        if not target_list:
            return jsonify({"error": f"List '{list_name}' not found"}), 404

        # Find and check the item
        item_found = False
        for item in target_list.items:
            if item.text and item.text.strip().lower() == item_text.lower():
                item.checked = True
                item_found = True
                break

        if not item_found:
            return jsonify({"error": f"Item '{item_text}' not found in list '{list_name}'"}), 404

        keep.sync()

        # Refresh in-memory lists
        keep_lists = fetch_all_keep_lists(keep)

        logging.info(f"Marked item '{item_text}' as checked in list '{list_name}'.")
        return jsonify({"message": f"Marked item '{item_text}' as checked in list '{list_name}'"})
    except Exception as e:
        logging.exception(f"Error checking item in list '{list_name}': {e}")
        return jsonify({"error": "Failed to check item"}), 500

def scheduler_thread():
    while True:
        schedule.run_pending()
        time.sleep(1)

def main() -> None:
    global keep, keep_lists
    setup_logging()

    gkeep_email = env("GKEEP_EMAIL")
    gkeep_password = env("GKEEP_PASSWORD")

    if not gkeep_email:
        logging.error("Missing GKEEP_EMAIL.")
        return
    if not (gkeep_password or env("GKEEP_MASTER_TOKEN")):
        logging.error("Missing GKEEP_PASSWORD or GKEEP_MASTER_TOKEN.")
        return

    keep = login_keep(gkeep_email, gkeep_password)
    if keep is None:
        logging.error("Could not authenticate to Google Keep.")
        return

    keep_lists = fetch_all_keep_lists(keep)
    logging.info(f"Loaded {len(keep_lists)} lists from Google Keep.")

    # Schedule refresh every 3 minutes
    schedule.every(3).minutes.do(refresh_lists_job)
    logging.info("Scheduled list refresh every 3 minutes.")

    # Start scheduler in background thread
    scheduler = threading.Thread(target=scheduler_thread, daemon=True)
    scheduler.start()

    port = int(env("SERVER_PORT", "5000") or "5000")
    app.run(host='0.0.0.0', port=port, debug=True)

if __name__ == "__main__":
    main()