# kickflip

Datadog debug log enabler.

This repository contains a Tkinter based tool for temporarily allowing
debug logs into Datadog for specific `car_id` values. The tool adds and
later removes negative filters in a Datadog logs pipeline. A ServiceNow
INC number is required to ensure the request is tracked and that the
incident is still open when the filter is created.

## Requirements

* Python 3
* `requests` library (`pip install requests`)
* Tkinter (ships with standard Python installs)

The script expects the following environment variables to be set:

* `DD_API_KEY` – your Datadog API key
* `DD_APP_KEY` – your Datadog application key
* `DD_PIPELINE_ID` – the ID of the logs pipeline to update
* `SN_INSTANCE` – ServiceNow instance hostname
* `SN_USER` – ServiceNow API username
* `SN_PASS` – ServiceNow API password

## Usage

Run the script and enter a `car_id` along with the ServiceNow incident
number authorizing the request. If the INC is open the tool adds a
temporary negative filter allowing debug logs for that car ID. Filters
are automatically removed after 60 minutes but can also be reverted
manually using the "Disable" button.

```bash
python debug_log_enabler.py
```

Each invocation of the "Enable" button starts its own 60 minute timer so
multiple car IDs can be active simultaneously. A car ID can only have one
active filter at a time; attempting to enable it again will result in an
error.
