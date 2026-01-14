import os
import time
import logging
from typing import List, Set, Tuple, Any

import schedule
import gkeepapi

# Prefer pyicloud; fall back to pyicloud-ipd if available
try:
    from pyicloud import PyiCloudService  # type: ignore
except Exception:  # pragma: no cover
    try:
        from pyicloud_ipd import PyiCloudService  # type: ignore
    except Exception:
        PyiCloudService = None  # type: ignore


def env(name: str, default: str | None = None) -> str | None:
    val = os.getenv(name)
    return val if val is not None and val != "" else default


def normalize(text: str) -> str:
    return " ".join(text.lower().split())


def setup_logging() -> None:
    level = env("LOG_LEVEL", "INFO") or "INFO"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

def parse_sync_list_names(raw: str | None) -> List[str]:
    if not raw:
        return []
    return [name.strip() for name in raw.split(",") if name.strip()]

def login_keep(email: str, password: str | None) -> gkeepapi.Keep | None:
    keep = gkeepapi.Keep()
    master_token = env("GKEEP_MASTER_TOKEN")
    try:
        if master_token:
            keep.resume(email, master_token)
        else:
            if not password:
                logging.error("GKEEP_PASSWORD or GKEEP_MASTER_TOKEN must be provided.")
                return None
            keep.login(email, password)
        keep.sync()
        return keep
    except Exception as e:
        logging.exception(f"Failed to authenticate with Google Keep: {e}")
        return None

def fetch_gkeep_unchecked_items_from_keep(keep: gkeepapi.Keep, list_title: str) -> List[str]:
    """
    Return unchecked items from the specified Google Keep list using an existing session.
    """
    # Find the list note by title (case-insensitive)
    note = None
    try:
        for n in keep.all():
            # list notes are of type gkeepapi.node.List
            if isinstance(n, gkeepapi.node.List) and (n.title or "").strip().lower() == list_title.strip().lower():
                note = n
                break
    except Exception as e:
        logging.exception(f"Error while iterating Google Keep notes: {e}")
        return []

    if not note:
        logging.warning(f"Google Keep list '{list_title}' not found.")
        return []

    items: List[str] = []
    try:
        for item in note.items:
            # Each item has .text and .checked
            if getattr(item, "text", None) and not getattr(item, "checked", False):
                items.append(item.text.strip())
    except Exception as e:
        logging.exception(f"Error while processing items from Keep list '{list_title}': {e}")
        return []

    logging.info(f"Fetched {len(items)} unchecked item(s) from Google Keep list '{list_title}'.")
    return items


def fetch_gkeep_unchecked_items(email: str, password: str | None, list_title: str) -> List[str]:
    """
    Login to Google Keep and return unchecked items from the specified list.
    Supports login via password or master token (GKEEP_MASTER_TOKEN).
    """
    keep = gkeepapi.Keep()

    master_token = env("GKEEP_MASTER_TOKEN")
    try:
        if master_token:
            keep.resume(email, master_token)
        else:
            if not password:
                logging.error("GKEEP_PASSWORD or GKEEP_MASTER_TOKEN must be provided.")
                return []
            keep.login(email, password)
        keep.sync()
    except Exception as e:
        logging.exception(f"Failed to authenticate with Google Keep: {e}")
        return []

    # Find the list note by title (case-insensitive)
    note = None
    try:
        for n in keep.all():
            # list notes are of type gkeepapi.node.List
            if isinstance(n, gkeepapi.node.List) and (n.title or "").strip().lower() == list_title.strip().lower():
                note = n
                break
    except Exception as e:
        logging.exception(f"Error while iterating Google Keep notes: {e}")
        return []

    if not note:
        logging.warning(f"Google Keep list '{list_title}' not found.")
        return []

    items: List[str] = []
    try:
        for item in note.items:
            # Each item has .text and .checked
            if getattr(item, "text", None) and not getattr(item, "checked", False):
                items.append(item.text.strip())
    except Exception as e:
        logging.exception(f"Error while processing items from Keep list '{list_title}': {e}")
        return []

    logging.info(f"Fetched {len(items)} unchecked item(s) from Google Keep list '{list_title}'.")
    return items


def icloud_connect(apple_id: str, apple_password: str, cookie_dir: str) -> Any | None:
    """
    Create a PyiCloudService session (persisting cookies in cookie_dir).
    Handles 2FA if APPLE_2FA_CODE is provided at first run.
    """
    if PyiCloudService is None:
        logging.error("pyicloud is not installed. Ensure 'pyicloud' (or 'pyicloud-ipd') is available.")
        return None

    os.makedirs(cookie_dir, exist_ok=True)
    try:
        api = PyiCloudService(apple_id, apple_password, cookie_directory=cookie_dir)
    except Exception as e:
        logging.exception(f"Failed to initialize PyiCloudService: {e}")
        return None

    # Handle potential 2FA/2SA
    requires_2fa = getattr(api, "requires_2fa", False) or getattr(api, "requires_2sa", False)
    if requires_2fa:
        code = env("APPLE_2FA_CODE")
        if not code:
            logging.error(
                "Apple iCloud requires two-factor authentication. "
                "Set APPLE_2FA_CODE environment variable with the code sent to your device and restart."
            )
            return None
        try:
            valid = api.validate_2fa_code(code) if hasattr(api, "validate_2fa_code") else api.validate_2sa_code(code)
            if not valid:
                logging.error("Invalid Apple 2FA/2SA code.")
                return None
            # Try to trust the session so you don't need to re-enter code
            try:
                if hasattr(api, "trust_session"):
                    api.trust_session()
            except Exception:
                pass
            logging.info("Two-factor authentication validated and session trusted.")
        except Exception as e:
            logging.exception(f"2FA validation failed: {e}")
            return None

    return api


def find_reminders_list(reminders_service: Any, list_name: str) -> Any | None:
    """
    Attempt to locate a Reminders list by name across various pyicloud versions.
    Returns the list object/dict if found, None otherwise.
    """
    lists = getattr(reminders_service, "lists", None)
    if not lists:
        logging.warning("Could not access iCloud Reminders lists; 'lists' attribute not available.")
        return None

    iterable = lists.values() if isinstance(lists, dict) else lists
    for lst in iterable:
        title = None
        if isinstance(lst, dict):
            title = lst.get("title") or lst.get("name")
        else:
            title = getattr(lst, "title", None) or getattr(lst, "name", None)

        if title and title.strip().lower() == list_name.strip().lower():
            return lst

    return None


def list_identifier(reminders_list: Any) -> str | None:
    """
    Extract a usable list identifier from a reminders list object/dict.
    """
    if reminders_list is None:
        return None

    if isinstance(reminders_list, dict):
        return (
            reminders_list.get("id")
            or reminders_list.get("guid")
            or reminders_list.get("pGuid")
            or reminders_list.get("list_id")
        )
    # Object-like
    return getattr(reminders_list, "id", None) or getattr(reminders_list, "guid", None) or getattr(reminders_list, "pGuid", None)


def get_existing_uncompleted_titles(reminders_service: Any, target_list: Any) -> Set[str]:
    """
    Collect normalized titles of uncompleted reminders in the target list.
    Tries multiple access patterns depending on pyicloud version.
    """
    titles: Set[str] = set()

    # Prefer tasks directly on the target list if available
    tasks = None
    for attr in ("tasks", "open", "uncompleted"):
        try:
            if hasattr(target_list, attr):
                tasks = getattr(target_list, attr)
                if callable(tasks):
                    tasks = tasks()
                break
            if isinstance(target_list, dict) and attr in target_list:
                tasks = target_list.get(attr)
                break
        except Exception:
            tasks = None

    # Fall back to top-level uncompleted if list-scoped tasks not available
    if tasks is None and hasattr(reminders_service, "uncompleted"):
        try:
            tasks = reminders_service.uncompleted()
        except Exception:
            tasks = None

    if not tasks:
        logging.warning("Could not retrieve tasks for the Reminders list.")
        return titles

    # Filter to only tasks belonging to the target list if task carries parent/list identifiers
    target_lid = list_identifier(target_list)

    try:
        for t in tasks:
            if isinstance(t, dict):
                completed = t.get("completed", False) or t.get("isCompleted", False)
                title = t.get("title") or t.get("name")
                t_lid = t.get("list_id") or t.get("pGuid") or t.get("parentGuid") or t.get("listId")
            else:
                completed = getattr(t, "completed", False) or getattr(t, "isCompleted", False)
                title = getattr(t, "title", None) or getattr(t, "name", None)
                t_lid = getattr(t, "list_id", None) or getattr(t, "pGuid", None) or getattr(t, "parentGuid", None) or getattr(t, "listId", None)

            if title and not completed:
                if target_lid and t_lid and str(t_lid) != str(target_lid):
                    # Task belongs to a different list
                    continue
                titles.add(normalize(title))
    except Exception as e:
        logging.exception(f"Error while enumerating existing reminders: {e}")

    return titles


def add_reminder(reminders_service: Any, target_list: Any, title: str) -> bool:
    """
    Add a reminder item to the target list, trying different pyicloud APIs.
    """
    try:
        # 1) If an 'add' helper exists
        if hasattr(reminders_service, "add"):
            try:
                lid = list_identifier(target_list)
                # Try with list_id kw
                return bool(reminders_service.add(title=title, list_id=lid))
            except TypeError:
                # Some versions may expect 'list' or 'calendar' kw by name
                try:
                    list_name = (getattr(target_list, "title", None) or getattr(target_list, "name", None))
                    if isinstance(target_list, dict) and not list_name:
                        list_name = target_list.get("title") or target_list.get("name")
                    return bool(reminders_service.add(title=title, list=list_name))
                except Exception:
                    pass

        # 2) Fallback to a generic POST interface
        if hasattr(reminders_service, "post"):
            payload = {"title": title}
            lid = list_identifier(target_list)
            if lid:
                # Common key name observed in various implementations
                payload["list_id"] = lid
            reminders_service.post("tasks", data=payload)
            return True

    except Exception as e:
        logging.exception(f"Failed adding reminder '{title}': {e}")

    logging.error("Unable to add reminder with the available pyicloud API.")
    return False


def sync_job() -> None:
    gkeep_email = env("GKEEP_EMAIL")
    gkeep_password = env("GKEEP_PASSWORD")  # optional if using GKEEP_MASTER_TOKEN
    sync_names = parse_sync_list_names(env("SYNC_LIST_NAMES"))

    # Fallback (single list mode) if SYNC_LIST_NAMES is not provided
    single_keep_list = env("GKEEP_LIST_TITLE", "Groceries") or "Groceries"
    single_reminders_list = env("REMINDERS_LIST_NAME", "Groceries") or "Groceries"

    apple_id = env("APPLE_ID")
    apple_password = env("APPLE_PASSWORD")
    icloud_cookie_dir = env("ICLOUD_COOKIE_DIR", "/data/icloud") or "/data/icloud"

    if not gkeep_email:
        logging.error("Missing GKEEP_EMAIL.")
        return
    if not (gkeep_password or env("GKEEP_MASTER_TOKEN")):
        logging.error("Missing GKEEP_PASSWORD or GKEEP_MASTER_TOKEN.")
        return
    if not apple_id or not apple_password:
        logging.error("Missing APPLE_ID or APPLE_PASSWORD.")
        return

    # Login to Google Keep once
    keep = login_keep(gkeep_email, gkeep_password)
    if keep is None:
        logging.error("Could not authenticate to Google Keep; skipping this run.")
        return

    # Connect to iCloud once
    api = icloud_connect(apple_id, apple_password, icloud_cookie_dir)
    if api is None:
        logging.error("Could not connect to iCloud; skipping this run.")
        return

    reminders_service = getattr(api, "reminders", None)
    if reminders_service is None:
        logging.error("This iCloud account does not expose Reminders via pyicloud.")
        return

    # Determine which lists to sync
    if sync_names:
        pairs = [(name, name) for name in sync_names]
    else:
        pairs = [(single_keep_list, single_reminders_list)]

    total_added = 0
    for keep_list_name, reminders_list_name in pairs:
        # Fetch unchecked items from Keep for this list
        keep_items = fetch_gkeep_unchecked_items_from_keep(keep, keep_list_name)
        if not keep_items:
            logging.info(f"No unchecked items from Google Keep list '{keep_list_name}' to sync.")
            continue

        # Locate the matching Reminders list
        target_list = find_reminders_list(reminders_service, reminders_list_name)
        if target_list is None:
            logging.error(f"Reminders list '{reminders_list_name}' not found. Create it in Apple Reminders first.")
            continue

        existing = get_existing_uncompleted_titles(reminders_service, target_list)
        added = 0
        for item in keep_items:
            if normalize(item) not in existing:
                if add_reminder(reminders_service, target_list, item):
                    added += 1
                    # Update local existing set to prevent duplicates within the same run
                    existing.add(normalize(item))
                else:
                    logging.error(f"Failed to add reminder: {item}")

        total_added += added
        logging.info(f"List '{keep_list_name}' -> '{reminders_list_name}' sync complete. Added {added} new reminder(s).")

    logging.info(f"All lists sync complete. Added {total_added} new reminder(s) across all lists.")


def main() -> None:
    setup_logging()

    interval = int(env("SCHEDULE_INTERVAL_MINUTES", "5") or "5")
    if interval < 1:
        interval = 5

    # Run once at startup, then schedule
    logging.info("Starting initial sync...")
    sync_job()

    logging.info(f"Scheduling sync every {interval} minute(s).")
    schedule.every(interval).minutes.do(sync_job)
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
