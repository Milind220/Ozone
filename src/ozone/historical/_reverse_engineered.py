import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
import js2py
import pandas
from sseclient import SSEClient as SSE

# NOTE(lahdjirayhan):
# The following variable is a long string, a source JS code that
# is excerpted from one of aqicn.org frontend's scripts.
# See relevant_funcs.js for more information.
_JS_FUNCS = Path(__file__).parent.joinpath("relevant_funcs.js").read_text()

# Make js context where js code can be executed
_context = js2py.EvalJs()
_context.execute(_JS_FUNCS)


def get_results_from_backend(city_id: int) -> List[Dict[str, Any]]:
    event_data_url = f"https://api.waqi.info/api/attsse/{city_id}/yd.json"

    events = SSE(event_data_url)
    result = []

    for event in events:
        if event.event == "done":
            break

        try:
            if "msg" in event.data:
                result.append(json.loads(event.data))
        except json.JSONDecodeError:
            pass

    return result


def parse_incoming_result(json_object: dict) -> pandas.DataFrame:
    # Run JS code
    # Function is defined within JS code above
    # Convert result to Python dict afterwards
    OUTPUT = _context.gatekeep_convert_date_object_to_unix_seconds(
        json_object["msg"]
    ).to_dict()

    # Change unix timestamp back to datetime
    RESULT = OUTPUT
    for i, spec in enumerate(OUTPUT["species"]):
        for j, val in enumerate(spec["values"]):
            RESULT["species"][i]["values"][j]["t"]["datetime"] = datetime.fromtimestamp(
                OUTPUT["species"][i]["values"][j]["t"]["d"]
            )

    result_dict = {}
    for spec in OUTPUT["species"]:
        pollutant_name: str = spec["pol"]

        dates, values = [], []
        for step in spec["values"]:
            # Change unix timestamp back to datetime
            date = datetime.fromtimestamp(step["t"]["d"])
            value: int = step["v"]

            dates.append(date)
            values.append(value)

        series = pandas.Series(values, index=dates)
        result_dict[pollutant_name] = series

    FRAME = pandas.DataFrame(result_dict)
    return FRAME


def get_data_from_id(city_id: int) -> pandas.DataFrame:
    backend_data = get_results_from_backend(city_id)
    result = pandas.concat([parse_incoming_result(data) for data in backend_data])

    # Arrange to make most recent appear on top of DataFrame
    result = result.sort_index(ascending=False, na_position="last")

    # Deduplicate because sometimes the backend sends duplicates
    result = result[~result.index.duplicated()]

    # Reindex to make missing dates appear with value nan
    # Conditional is necessary to avoid error when trying to
    # reindex empty dataframe i.e. just in case the returned
    #  response AQI data was empty.
    if len(result) > 1:
        complete_days = pandas.date_range(
            result.index.min(), result.index.max(), freq="D"
        )
        result = result.reindex(complete_days, fill_value=None)

    return result