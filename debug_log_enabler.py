import os
import json
import requests
import threading
import tkinter as tk
from tkinter import messagebox

ACTIVE_FILTERS: dict[str, threading.Timer] = {}
BASE_QUERY = ""


def _dd_config() -> tuple[str, str, str]:
    api_key = os.environ.get("DD_API_KEY")
    app_key = os.environ.get("DD_APP_KEY")
    pipeline_id = os.environ.get("DD_PIPELINE_ID")
    if not all([api_key, app_key, pipeline_id]):
        raise RuntimeError(
            "DD_API_KEY, DD_APP_KEY and DD_PIPELINE_ID must be set"
        )
    base_url = (
        "https://api.datadoghq.com/api/v2/logs/config/pipelines/" + pipeline_id
    )
    return api_key, app_key, base_url


def _dd_headers(api_key: str, app_key: str) -> dict[str, str]:
    return {
        "DD-API-KEY": api_key,
        "DD-APPLICATION-KEY": app_key,
        "Content-Type": "application/json",
    }


def _get_pipeline(headers: dict[str, str], base_url: str) -> dict:
    resp = requests.get(base_url, headers=headers)
    resp.raise_for_status()
    return resp.json().get("data", {})


def _apply_filters(car_ids: list[str]) -> None:
    api_key, app_key, base_url = _dd_config()
    headers = _dd_headers(api_key, app_key)
    pipeline = _get_pipeline(headers, base_url)

    global BASE_QUERY
    if not BASE_QUERY:
        BASE_QUERY = (
            pipeline.get("attributes", {})
            .get("filter", {})
            .get("query", "")
            .strip()
        )

    negative_filters = " ".join(
        f"!(@status:debug && @car_id:{cid})" for cid in car_ids
    )
    new_query = f"{BASE_QUERY} {negative_filters}".strip()

    pipeline["attributes"]["filter"] = {"query": new_query}
    payload = {"data": pipeline}

    r = requests.patch(base_url, headers=headers, data=json.dumps(payload))
    r.raise_for_status()


def _inc_open(inc_number: str) -> bool:
    instance = os.environ.get("SN_INSTANCE")
    user = os.environ.get("SN_USER")
    password = os.environ.get("SN_PASS")
    if not all([instance, user, password]):
        raise RuntimeError("SN_INSTANCE, SN_USER and SN_PASS must be set")

    url = f"https://{instance}/api/now/table/incident?sysparm_query=number={inc_number}"
    resp = requests.get(url, auth=(user, password))
    resp.raise_for_status()
    result = resp.json().get("result", [])
    if not result:
        return False
    state = str(result[0].get("state", "")).lower()
    return state not in {"closed", "resolved", "7", "8"}


def enable_debug_logs(car_id: str, inc_number: str) -> None:
    """Enable debug logs for a car_id if the INC is open."""
    if not _inc_open(inc_number):
        raise RuntimeError("INC is not open")

    if car_id in ACTIVE_FILTERS:
        ACTIVE_FILTERS[car_id].cancel()

    ACTIVE_FILTERS[car_id] = threading.Timer(60 * 60, lambda: disable_debug_logs(car_id))
    ACTIVE_FILTERS[car_id].start()

    _apply_filters(list(ACTIVE_FILTERS.keys()))


def disable_debug_logs(car_id: str) -> None:
    timer = ACTIVE_FILTERS.pop(car_id, None)
    if timer:
        timer.cancel()
    if ACTIVE_FILTERS:
        _apply_filters(list(ACTIVE_FILTERS.keys()))
    else:
        _apply_filters([])


def main() -> None:
    root = tk.Tk()
    root.title("Datadog Debug Log Enabler")

    tk.Label(root, text="Car ID:").grid(row=0, column=0, padx=5, pady=5)
    car_entry = tk.Entry(root)
    car_entry.grid(row=0, column=1, padx=5, pady=5)

    tk.Label(root, text="INC #:").grid(row=1, column=0, padx=5, pady=5)
    inc_entry = tk.Entry(root)
    inc_entry.grid(row=1, column=1, padx=5, pady=5)

    def on_enable():
        car_id = car_entry.get().strip()
        inc = inc_entry.get().strip()
        if not car_id or not inc:
            messagebox.showerror("Error", "Car ID and INC are required")
            return
        try:
            enable_debug_logs(car_id, inc)
            messagebox.showinfo("Success", f"Debug logs enabled for {car_id}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def on_disable():
        car_id = car_entry.get().strip()
        if not car_id:
            messagebox.showerror("Error", "Car ID is required")
            return
        if car_id not in ACTIVE_FILTERS:
            messagebox.showerror("Error", "No active filter for that car ID")
            return
        disable_debug_logs(car_id)
        messagebox.showinfo("Reverted", f"Filter for {car_id} removed")

    tk.Button(root, text="Enable Debug Logs", command=on_enable).grid(
        row=2, column=0, columnspan=2, pady=5
    )
    tk.Button(root, text="Disable", command=on_disable).grid(
        row=3, column=0, columnspan=2, pady=5
    )

    root.mainloop()


if __name__ == "__main__":
    main()
