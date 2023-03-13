import os
import csv
import requests
import json
import argparse
import shutil
import re
import pytz
from prompt_toolkit import prompt
from prompt_toolkit.completion import FuzzyWordCompleter
from protobuf_to_dict import protobuf_to_dict
from google.transit import gtfs_realtime_pb2
from datetime import datetime, timedelta
from tabulate import tabulate


API_KEY = ""


def main():
    if not os.path.isfile("new stations.csv"):
        make_new_stations_csv()

    SAVE_JSON, RESET, SERVICE = cli_args()

    # Delete config.ini if CLI arg entered by user
    if RESET:
        if os.path.isfile("config.json"):
            os.remove("config.json")
            print("Defaults removed!")
        else:
            print(f"Defaults could not be reset: config.json missing!")

    # Loads default settings if file exists
    if os.path.isfile("config.json"):
        with open("config.json", "r") as f:
            config_data = json.load(f)

        # Assign values of the keys in the 'config.json' file to variables
        id_lines_feed_dict = config_data["id_lines_feed_dict"]
        stop_name_dict = config_data["stop_name_dict"]
        train_line_list = config_data["train_line_list"]

    else:
        # Gets info. on desired station (but not arr. times yet)
        id_lines_feed_dict, stop_name_dict, train_line_list = get_info()

        # Asks if the user wants to save the station as their default setting
        make_default(id_lines_feed_dict, stop_name_dict, train_line_list)

    # Get train line real time status feed & service alert feed
    stop_name_feed_dict, filename_set, service_alert = get_feed(
        stop_name_dict, id_lines_feed_dict
    )

    # Get arr. times & service status (if any) for ea. line at station
    for stop, values in stop_name_feed_dict.items():
        name = values["name"]
        feed = values["feed"]

        for line in train_line_list:
            if line in id_lines_feed_dict[stop]["train_lines"]:
                station_arrival(
                    stop,
                    name,
                    line,
                    feed,
                    service_alert,
                )
                if SERVICE:  # Prints the full service alert msg. if arg
                    service_info(service_alert, line, stop, name)

    # Deletes JSON feeds if CLI arg not entered by user
    if not SAVE_JSON:
        for filename in filename_set:
            os.remove(filename)
        os.remove("Subway Service Alerts.json")


def cli_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        default=False,
        help="Keeps JSON(s) for train line feed(s)",
    )
    parser.add_argument(
        "-r",
        "--reset",
        action="store_true",
        default=False,
        help="Reset default settings",
    )
    parser.add_argument(
        "-s",
        "--service",
        action="store_true",
        default=False,
        help="Show service alert messages for station",
    )

    args = parser.parse_args()

    return (
        args.json,
        args.reset,
        args.service,
    )


def make_new_stations_csv():
    """Almost all subseq. func. in this prog. rely on this new, conglom. csv file"""

    # Checks for MTA static files (i.e. non real time data)
    if (
        not os.path.isfile("transfers.txt")
        or not os.path.isfile("stops.txt")
        or not os.path.isfile("service.csv")
    ):
        print(
            f"Error: Missing files from working directory!\n\nPlease make sure the "
            f"following are in the same folder as the python source code:"
            f"\n\t• stops.txt\n\t• transfers.txt\n\t• stations.csv\n\n"
            f"These static files can be found at:"
            f"\n\t• (all static files) http://web.mta.info/developers/developer-data-terms.html#data"
            f"\n\t• (zip of txt files) http://web.mta.info/developers/data/nyct/subway/google_transit.zip"
            f"\n\t• (stations.csv) https://atisdata.s3.amazonaws.com/Station/Stations.csv"
        )
        quit()

    # Correct MTA inconsist. by changing stop_id 140 (inop.) to 142
    transfers_dict = {}
    with open("transfers.txt", "r+") as f:
        content = f.read()
        modified_content = content.replace("140", "142")
        f.seek(0)
        f.write(modified_content)
        f.seek(0)

        # Pop. dict. w/ salient info.
        lines = csv.reader(f)
        next(lines)  # Skip headers
        for line in lines:
            from_id = line[0].strip().upper()
            to_id = line[1].strip().upper()
            if from_id != to_id:
                transfers_dict[from_id] = to_id

    with open("stations.csv", "r") as f_in, open(
        "new stations.csv", "w", newline=""
    ) as f_out:
        reader = csv.reader(f_in)
        writer = csv.writer(f_out)

        # New csv headers
        writer.writerow(
            [
                "Station ID",
                "Complex ID",
                "GTFS Stop ID",
                "Division",
                "Line",
                "Stop Name",
                "Borough",
                "Daytime Routes",
                "Structure",
                "GTFS Latitude",
                "GTFS Longitude",
                "North Direction Label",
                "South Direction Label",
                "ADA",
                "ADA Direction Notes",
                "ADA NB",
                "ADA SB",
                "Capital Outage NB",  # Currently unused but kept just in case
                "Capital Outage SB",  # Currently unused but kept just in case
                "Transfer From",
                "Transfer To",
            ]
        )

        next(reader)
        rows = list(reader)

        for row in rows:
            csv_stop_id = row[2].strip().upper()
            if csv_stop_id in transfers_dict:
                row.append(csv_stop_id)
                row.append(transfers_dict[csv_stop_id])

            # Append row to new file
            writer.writerow(row)

    return


def get_info():
    """
    Collects stop IDs to resemble real life stations; passes to mta_stop_id func.;
    retrieves list of stop IDs from user input (from the above func.);
    returns station name (for timetables), realtime feeds, IDs, & train lines
    """
    with open("test new stations.csv", "r") as f:
        next(f)  # Skip header
        reader = csv.reader(f)

        stops_dict = {}
        id_lines_feed_dict = {}
        for row in reader:
            stop_id = row[2].strip()
            stop_name = row[5].strip().strip(".").upper()  # Extra strip() is for Sq/Sq.
            row_train_lines = row[7].split()

            # Reformats certain lines to make later searching easier
            if stop_id in ["901", "902"]:
                row_train_lines += ["GS"]  # Midtown Shuttle
            elif stop_id in ["S01", "S03", "S04", "D26"]:
                row_train_lines += ["FS"]  # Franklin Av Shuttle
            elif stop_id in ["H12", "H13", "H14", "H15"]:
                row_train_lines += ["RS"]  # Rockaway Pk Shuttle

            # Express serv. of these lines not in static files
            if any(value in row_train_lines for value in ("6", "7", "F")):
                if "6" in row_train_lines and stop_id not in [""]:
                    row_train_lines += [f"<6>"]
                elif "7" in row_train_lines:
                    row_train_lines += [f"<7>"]
                if "F" in row_train_lines:
                    row_train_lines += [f"<F>"]

            if (
                "S" in row_train_lines
                and [
                    "GS",
                    "FS",
                    "RS",
                    "SI",
                    "SIR",
                ]
                not in row_train_lines
            ):
                row_train_lines.remove("S")  # remove "S" if it exists

            train_lines_set = set(row_train_lines)

            stop_feed_url = set()
            for line in train_lines_set:
                stop_feed_url.add(api_endpoint_urls(line))

            # Later used to prevent stupid combo. like G -> Mhttn. when iter.;
            # also for downloading service feed per stop ID instead of all lines
            id_lines_feed_dict[stop_id] = {
                "train_lines": train_lines_set,
                "api_endpoint": stop_feed_url,
            }

            # Checks for transfer info. & adds if found
            if len(row) >= 20:
                transfer_from = row[19].strip()
                transfer_to = row[20].strip()
            else:
                transfer_from, transfer_to = None, None

            # Makes a dict of key: dict. pairs
            if stop_id not in stops_dict:
                stops_dict[stop_id] = {
                    "station_names": set(),
                    "train_lines": set(),
                    "transfer_from": transfer_from,
                    "transfer_to": transfer_to,
                }

            # Combines all transfers; i.e. a station as understood by people
            stops_dict[stop_id]["station_names"].add(stop_name)
            stops_dict[stop_id]["train_lines"].update(train_lines_set)

            # Loop over stops_dict to update names & lines via transfer info.
            for stop_id, stop_data in stops_dict.items():
                transfer_from = stop_data.get("transfer_from")
                transfer_to = stop_data.get("transfer_to")

                if transfer_from and transfer_to:
                    transfer_data = stops_dict.get(transfer_to)
                    if transfer_data:
                        # Adds names and lines by finding transfer station names & lines
                        stop_data["station_names"].update(
                            transfer_data["station_names"]
                        )
                        stop_data["train_lines"].update(transfer_data["train_lines"])
                        transfer_data["station_names"].update(
                            stop_data["station_names"]
                        )
                        transfer_data["train_lines"].update(stop_data["train_lines"])

    # Retrieves list of stop ID(s)
    parameter_stop_id_list = mta_stop_id(stops_dict)

    # Iter. thru. list immed. above & assigns info. specific to user input
    train_lines_set = set()
    stop_name_dict = {}

    for a_stop_id in parameter_stop_id_list:
        stop_id_name = stops_dict.get(a_stop_id, {}).get("station_names", set())
        train_lines_set.update(stops_dict.get(a_stop_id, {}).get("train_lines", set()))

        stop_name_dict[a_stop_id] = stop_id_name

    # Cleans up info. so trains are grouped tgtr. in order (e.g. N Q R W)
    train_lines_list = sorted(train_lines_set, key=lambda x: str(x))

    return id_lines_feed_dict, stop_name_dict, train_lines_list


def mta_stop_id(stops_dict):
    """Gets the GTFS feed stop ID via user input prompt; returns stop ID(s)"""
    name_id_dict = {}
    names_set = set()

    # Reformat & reorg. dict. to be e.g. "STATION (ROUTE)" : "STOP ID"
    for a_stop_id, some_stop_data in stops_dict.items():
        station_names = some_stop_data.get("station_names")
        train_lines = some_stop_data.get("train_lines")

        if station_names and train_lines:
            station_names_str = ", ".join(sorted(station_names))
            train_lines_str = " ".join(sorted(train_lines))

            name_id_str = f"{station_names_str} ({train_lines_str})"

            if name_id_str not in names_set:
                names_set.add(name_id_str)
                name_id_dict[name_id_str] = [a_stop_id]
            else:
                name_id_dict[name_id_str].append(a_stop_id)

    # Autocomplete wordbank (to def. against incorr./unknown names)
    word_completer = FuzzyWordCompleter(name_id_dict.keys())

    # Get stop ID from CLI user input
    while True:
        user_input = prompt(f"Enter station name:\n", completer=word_completer)
        if user_input in name_id_dict.keys():
            return name_id_dict[user_input]
        else:
            print(f"{user_input} not found.")


def get_feed(stop_name_dict, id_lines_feed_dict):
    """
    Gets GTFS feed for realtime train info. & also service alerts JSON;
    makes JSON(s) of GTFS feed

    returns dict. of stop ID(s) paired to station name & GTFS feed (ea. a nested dict.),
    filename(s) set (for JSON(s)), &
    service alert feed
    """
    filename_set = set()  # For JSON filename
    stop_name_feed_dict = {}  # Combines stop_name_dict w/ GTFS feed

    for stop, name in stop_name_dict.items():
        if name:
            _ = name.pop()  # .pop() extracts str from set
            name = _.title()  # Using .title() & .pop() simul. prod. a mem. address

        # For feed filenaming purposes
        if len(stop_name_dict.keys()) > 1:
            filename = f"{stop} {name} Feed.json"
            filename_set.add(filename)
        else:
            filename = f"{name} Feed.json"

        # Checks that the stop has found an endpoint url
        if id_lines_feed_dict.get(stop, {}):
            url = (id_lines_feed_dict[stop]["api_endpoint"]).pop()
            if not url:
                break

        # Gets GTFS (i.e. real time) train data
        HEADER = {"x-api-key": API_KEY}
        response = requests.get(url, headers=HEADER)

        # Decodes GTFS bin. into readable text
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)
        feed_dict = protobuf_to_dict(feed)

        if not feed_dict:
            print(f"The feed for {filename} could not be retrieved.")
            break

        # Creates fresh dict. to be nested in the returned dict.
        stop_dict = {}
        stop_dict["name"] = name
        stop_dict["feed"] = feed

        # Adds above dict. to stop_name_feed_dict
        stop_name_feed_dict[stop] = stop_dict

        # Create a readable JSON of GTFS
        with open(filename, "w") as f:
            f.write(json.dumps(feed_dict, indent=4))

    # Gets JSON of subway service alerts
    service_response = requests.get(
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fsubway-alerts.json",
        headers=HEADER,
    )
    service_alert = json.loads(service_response.text)

    if not service_alert:
        print(f"The service alerts feed could not be retrieved.")

    # Write to local JSON
    with open("Subway Service Alerts.json", "w") as f:
        f.write(json.dumps(service_alert, indent=4))

    return stop_name_feed_dict, filename_set, service_alert


def check_route_id(line):
    """
    The MTA has its own, internal ideas re stop IDs, lines, etc.--& these don't always
    match the name used by the gen. pub. (or even stay consistent w/n even their own
    org.--e.g. why the S train runs on stop IDs 901 & 902, & route ID GS instead of just
    having them all be S is a mystery); in any case, the returned values below should
    match the route_id in the GTFS feed, which will ult. return the arr. times shown in
    the feed for the desired train line.
    """
    line = line.upper()
    if "<" in line and ">" in line:
        actual_route_id = f"{line[1]}X"
    elif line in ["SIRR", "SIR", "SS", "SI"]:
        actual_route_id = "SI"
    elif line in ["ROCKAWAY PK SHUTTLE", "ROCKAWAY SHUTTLE", "RS", "SR"]:
        actual_route_id = "A"
    elif line in ["SF", "FS", "FRANKLIN AV SHUTTLE"]:
        actual_route_id = "FS"
    elif line in [
        "GS",
        "SG",
        "S",
        "42ND ST SHUTTLE",
        "GRAND CENTRAL/TIMES SQ SHUTTLE",
    ]:
        actual_route_id = "GS"
    else:
        actual_route_id = line
    return actual_route_id


def make_default(id_lines_feed_dict, stop_name_dict, train_line_list):
    while True:
        user_input = (
            input("Would you like to save this station as your default? (y/n) ")
            .strip()
            .lower()
        )
        if user_input == "y":
            # Extract sets and convert them to lists; sets cannot be serialised in JSONs
            for key, value in id_lines_feed_dict.items():
                if "train_lines" in value:
                    id_lines_feed_dict[key]["train_lines"] = list(value["train_lines"])
                if "api_endpoint" in value:
                    id_lines_feed_dict[key]["api_endpoint"] = list(
                        value["api_endpoint"]
                    )

            for key, value in stop_name_dict.items():
                stop_name_dict[key] = list(value)

            # Combine dicts. & list into one dict.
            data = {
                "stop_name_dict": stop_name_dict,
                "train_line_list": train_line_list,
                "id_lines_feed_dict": id_lines_feed_dict,
            }

            # Write the above dict. to a JSON
            with open("config.json", "w") as f:
                json.dump(data, f, indent=4)

            print("Default settings JSON created!")

            return
        elif user_input == "n":
            return
        else:
            print("Invalid entry, please enter y or n.")


def station_arrival(stop, name, line, feed, service_alert):
    """
    Gets arr. times & tabulates 3 nearest trains in both direct.;
    Also calls check_ada() to check for ADA access to station in both direct.;
    Eventually calls tabulate_times() to display timetable(s) in CLI
    """
    north_data = []
    south_data = []
    north_bound_train = None
    south_bound_train = None

    # Fixes train line name to MTA's official route name
    actual_route_id = check_route_id(line)

    # Gets train arrival times for both directions at the station
    for direction in ["N", "S"]:
        stop = stop[:3] + direction
        nearest_trains = {}

        # Find & add key-value pairs to dict., i.e. train no. & sta. arr. time
        for entity in feed.entity:
            if entity.HasField("trip_update"):  # HasField() v. handy, but GTFS only
                if entity.trip_update.trip.route_id == actual_route_id:
                    for update in entity.trip_update.stop_time_update:
                        if update.stop_id == stop:
                            # If not checked for pos. times, it'll append trains
                            # that have already passed, no times at all, or times
                            # that're so far away they're useless (i.e. > 2 hrs.)
                            _ = datetime.fromtimestamp(update.arrival.time)
                            delta = _ - datetime.now()  # Broken up for readability
                            total_seconds = int(delta.total_seconds())
                            if total_seconds > 0:
                                nearest_trains[
                                    entity.trip_update.trip.trip_id
                                ] = update.arrival.time

        # Dict. compr. usage: OUTPUT for ITERATION in ITERABLE
        # sorted(thing to be sorted, key=FUNCTION or key=lambda INPUT: OUTPUT)
        # key=lambda item: item[1], means sorting will be based on the second element,
        # (i.e., the value) of each (key, value) pair, in ascend. order
        nearest_trains = {
            k: v for k, v in sorted(nearest_trains.items(), key=lambda item: item[1])
        }

        # Sorted 10 (arbitrary no.) nearest trains & put into list (of dict.)
        nearest_trains = list(nearest_trains.items())[:10]

        # Gets 3 nearest trains (also an arbitrary no.) & formats arr. times
        for train_id, arrival_time in nearest_trains:
            arrival_datetime = datetime.fromtimestamp(arrival_time)
            train_number, ext = train_id.split("_")  # For testing purposes

            # Get formatted time 'til arr.
            delta = arrival_datetime - datetime.now()
            total_seconds = int(delta.total_seconds())
            duration_str = time_calc(delta)

            # Append info to be tabulated
            if direction == "N" and len(north_data) < 3:
                north_data.append(duration_str)
            if direction == "S" and len(south_data) < 3:
                south_data.append(duration_str)

            if len(north_data) == 3 and len(south_data) == 3:
                break

        # Check for ADA access to station &, if applicable, its direction
        ada = check_ada(stop)

        # Get a specific label for train direction, if applicable/not both
        if direction == "N":
            if ada == "North":
                north_bound_train = (
                    f"{line_direction(line, stop)} \N{WHEELCHAIR SYMBOL}"
                )
            else:
                north_bound_train = f"{line_direction(line, stop)}"
        else:
            if ada == "South":
                south_bound_train = (
                    f"{line_direction(line, stop)} \N{WHEELCHAIR SYMBOL}"
                )
            else:
                south_bound_train = f"{line_direction(line, stop)}"

    # Checks for any line/station alerts
    alert_type_dict = check_service(service_alert, stop, actual_route_id, name)

    tabulate_times(
        alert_type_dict,
        name,
        line,
        ada,
        north_data,
        south_data,
        south_bound_train,
        north_bound_train,
    )

    return


def tabulate_times(
    alert_type_dict,
    name,
    line,
    ada,
    north_data,
    south_data,
    south_bound_train,
    north_bound_train,
):
    """
    Tabulates data from station_arrival(): shows station name, train line, & an alert
    icon (if there's service disrupt.) in CLI timetable(s);

    Also checks for service alerts (but only to display as an icon/notice; printing the
    whole alert comes after printing the table, & only if CLI arg provided)
    """

    # Checks whether there are service alerts for the station; doesn't retrieve msgs.
    status_icons_list = []
    if alert_type_dict:
        status_icons_list = "(!)"
        status_icons_str = "".join(status_icons_list)
        # status_icons_list = (" ".join(list(alert_type_dict.keys()))).rstrip()
    else:
        status_icons_str = ""

    # If one direction list is empty of arr. times, zipping a new list fails
    if north_data and not south_data:
        south_data = [" ", " ", " "]
    if not north_data and south_data:
        north_data = [" ", " ", " "]
    data = list(zip(north_data, south_data))

    # Don't show empty tables
    if not data:
        print(f"\n{name} - No {line} Trains!\n")
        return

    if north_data and south_data:
        table = tabulate(
            data,
            headers=[
                f"{north_bound_train}",
                f"{south_bound_train}",
            ],
            tablefmt="outline",
            colalign=("left", "right"),
        )
    else:
        table = tabulate(
            data,
            headers=[
                f"{north_bound_train}",
                f"{south_bound_train}",
            ],
            tablefmt="outline",
        )
    # Print formatting
    line_length = len(table.split("\n")[0])  # Above table's horiz. length
    left = f"\n{name} "

    if ada == "1":
        left = f"\n{name} \N{WHEELCHAIR SYMBOL}"
        print(f"{left:<{line_length - len(status_icons_list)}}{status_icons_str:>1}")
    else:
        print(
            f"{left:<{line_length - len(status_icons_list) + 1}}{status_icons_str:>1}"
        )

    print(table)

    if alert_type_dict:
        # Turn dict_values output into list, then a str., w/ newlines after ea. comma
        print(", ".join(list(alert_type_dict.values())).replace(",", ",\n"))
    print("")
    return


def check_service(service_alert, stop, line, name):
    """Checks if alerts exist for the line & station (but not alert full text(s))"""

    stop = stop[:3]  # Drops the stop direct.
    alert_type_dict = {}

    if service_alert.get("entity", {}):
        # For ea. alert (dict.) in the JSON
        for entity_alert in service_alert["entity"]:
            line_match = None
            stop_match = None
            line_disruption = None
            alert_type = None
            description_text = None

            alert = entity_alert["alert"]
            informed_entity_list = alert.get("informed_entity", [])
            transit_realtime_dict = alert.get("transit_realtime.mercury_alert", {})
            active_period = alert.get("active_period", [])
            description_text = alert.get("description_text", {})

            if informed_entity_list:
                # Why did they have to seperate route & stop IDs, ffs.
                for informed_entity in informed_entity_list:
                    if informed_entity.get("route_id") == line:
                        line_match = True
                    if informed_entity.get("stop_id") == stop:
                        stop_match = True

            if description_text:
                actual_description_text = description_text.get("translation")[0]["text"]
                if name in actual_description_text:
                    stop_match = True

            # Sometimes the whole friggin' line's affected but there's no mention of your specific stop
            if line_match and len(informed_entity_list) > 2:
                informed_entity_line_range_list = []
                for informed_entity in informed_entity_list:
                    a_stop_id = informed_entity.get("stop_id")
                    if a_stop_id:
                        informed_entity_line_range_list.append(a_stop_id)
                if informed_entity_line_range_list:
                    range_list_first = informed_entity_line_range_list[0]
                    range_list_last = informed_entity_line_range_list[-1]
                    # Logic to order range start & end due to inconsist. MTA input
                    if range_list_first[1:] < range_list_last[1:]:
                        range_start = range_list_first
                        range_end = range_list_last
                    else:
                        range_start = range_list_last
                        range_end = range_list_first

                    if int(stop[1:]) in range(
                        int(range_start[1:]),
                        int(range_end[1:]) + 1,  # incl. end of range
                    ):
                        line_disruption = True

            if (line_match and stop_match) or line_disruption:
                # Printout header & body info.: alert created/update, duration, plan no., & type
                if transit_realtime_dict:
                    alert_type = transit_realtime_dict.get("alert_type")
                # Detailed explanation & suggestions

                if active_period:
                    now = time_zone(int(datetime.now().timestamp()))
                    for element in active_period:
                        # could be many start & end; could be no end
                        start_time = time_zone(element["start"])
                        end_time = (
                            time_zone(element["end"]) if element.get("end") else None
                        )
                        if start_time <= now:
                            active = "(now)"
                            if end_time:
                                active = (
                                    f"(now 'til {end_time.strftime('%m/%d %H:%M')})"
                                )
                        elif now < start_time:
                            time_diff = start_time - now
                            if time_diff > timedelta(days=15):
                                active = f"(much later at '{start_time.strftime('%y %m/%d %H:%M')})"
                            else:
                                active = (
                                    f"(later at {start_time.strftime('%m/%d %H:%M')})"
                                )
                        else:
                            active = ""

            if alert_type:
                if re.match(r".*station notice.*", alert_type, re.IGNORECASE):
                    alert_type_dict["(!)"] = f"Station Notice {active}"
                if re.match(r".*skipped.*", alert_type, re.IGNORECASE):
                    alert_type_dict["{!}"] = f"Station Skipped {active}"
                if re.match(r".*suspended.*", alert_type, re.IGNORECASE):
                    alert_type_dict["X!X"] = f"Part Suspended {active}"
                if re.match(r".*multiple changes.*", alert_type, re.IGNORECASE):
                    alert_type_dict["!!!"] = f"Multiple Changes {active}"
                if re.match(r".*delays.*", alert_type, re.IGNORECASE) or re.match(
                    r".*reduced service.*", alert_type, re.IGNORECASE
                ):
                    alert_type_dict["<!>"] = f"Line Disruption {active}"
                if re.match(r".*reroute.*", alert_type, re.IGNORECASE):
                    alert_type_dict["R!R"] = f"Reroute {active}"
                if re.match(r".*special schedule.*", alert_type, re.IGNORECASE):
                    alert_type_dict["S!S"] = f"Special Schedule {active}"
                if re.match(r".*boarding change.*", alert_type, re.IGNORECASE):
                    alert_type_dict["B!C"] = f"Boarding Change {active}"
                if re.match(r".*extra service.*", alert_type, re.IGNORECASE):
                    alert_type_dict["E!S"] = f"Extra Service {active}"
                if re.match(r".*no midday.*", alert_type, re.IGNORECASE):
                    alert_type_dict["Mid"] = f"No Midday Servic {active}"
                if re.match(r".*no weekend.*", alert_type, re.IGNORECASE):
                    alert_type_dict["Wkd"] = f"No Weekend Service {active}"
                if re.match(r".*no overnight.*", alert_type, re.IGNORECASE):
                    alert_type_dict["Ngt"] = f"No Overnight Service {active}"
                if re.match(r".*local to express.*", alert_type, re.IGNORECASE):
                    alert_type_dict["L-E"] = f"Local to Express {active}"
                if re.match(r".*express to local.*", alert_type, re.IGNORECASE):
                    alert_type_dict["E-L"] = f"Express to Local {active}"

    return alert_type_dict


def check_ada(stop):
    stop = stop[:3]

    with open("new stations.csv", "r") as f:
        reader = csv.reader(f)
        for line in reader:
            if line[13] == "1" and line[2] == stop:
                return "1"  # ADA access both sides
            if line[13] == "2" and line[2] == stop:
                if line[15] == "1" and line[2] == stop:
                    return "North"  # Only NB ADA access
                elif line[16] == "1" and line[2] == stop:
                    return "South"  # Only SB ADA access

    return "0"  # Unfort. the vast maj. of stations


def service_info(service_alert, line, stop, name):
    terminal_width, _ = shutil.get_terminal_size()  # Printed table formatting

    if service_alert.get("entity", {}):
        # For ea. alert (dict.) in the JSON
        for entity_alert in service_alert["entity"]:
            line_match = None
            stop_match = None
            line_disruption = None

            alert_type = None
            duration = None
            terse_desc_text = None
            actual_description_text = None
            plan_duration_list = None

            created_datetime = None
            updated_datetime = None
            created = None
            updated = None
            header_text = None
            description_text = None

            alert = entity_alert["alert"]

            informed_entity_list = alert.get("informed_entity", [])
            transit_realtime_dict = alert.get("transit_realtime.mercury_alert", {})
            header_text = alert.get("header_text", {})
            description_text = alert.get("description_text", {})

            if informed_entity_list:
                # Why did they have to seperate nest lvls. for route & stop IDs, ffs.
                for informed_entity in informed_entity_list:
                    if informed_entity.get("route_id") == line:
                        line_match = True
                    if informed_entity.get("stop_id") == stop:
                        stop_match = True
            # Kinda hackish, but checks text for station name just in case other filters fail
            if description_text:
                actual_description_text = description_text.get("translation")[0]["text"]
                if name in actual_description_text:
                    stop_match = True

            # Sometimes the whole friggin' line's affected but no mention of your specific stop
            if line_match and len(informed_entity_list) > 2:
                informed_entity_line_range_list = []
                for informed_entity in informed_entity_list:
                    a_stop_id = informed_entity.get("stop_id")
                    if a_stop_id:
                        informed_entity_line_range_list.append(a_stop_id)
                if informed_entity_line_range_list:
                    # Unsure if this is good logic to just use the v. first & last element in list
                    range_list_first = informed_entity_line_range_list[0]
                    range_list_last = informed_entity_line_range_list[-1]

                    # Logic to order stop ID range start & end due to inconsist. order
                    if range_list_first[1:] < range_list_last[1:]:
                        range_start = range_list_first
                        range_end = range_list_last
                    else:
                        range_start = range_list_last
                        range_end = range_list_first

                    if int(stop[1:]) in range(
                        int(range_start[1:]),
                        int(range_end[1:]) + 1,  # + 1 incl. end of range
                    ):
                        line_disruption = True

            if (line_match and stop_match) or line_disruption:
                # Printout header & body info.: alert created/update, duration, plan no., & type
                if transit_realtime_dict:
                    alert_type = transit_realtime_dict.get("alert_type")
                    created_datetime = transit_realtime_dict.get("created_at")
                    updated_datetime = transit_realtime_dict.get("updated_at")

                    active_period = transit_realtime_dict.get(
                        "human_readable_active_period"
                    )
                    service_plan_id_list = transit_realtime_dict.get(
                        "service_plan_number", []
                    )  # For testing purposes

                    if active_period:
                        duration = active_period.get("translation")[0]["text"]
                    else:
                        epoch_time_active_period = alert.get("active_period", [])
                        plan_duration_list = []
                        if epoch_time_active_period:
                            for duration_list_element in epoch_time_active_period:
                                start = time_zone(duration_list_element["start"])
                                end = time_zone(duration_list_element["end"])

                                # If the mo. of the start & end time is the same, just print once
                                if start.strftime("%b") == end.strftime("%b"):
                                    date_str = f"{start.strftime('%b %d')} - {end.strftime('%d')}"

                                # If mo. is the same & the date is the same, just print ea. once
                                if start.strftime("%b") == end.strftime(
                                    "%b"
                                ) and start.strftime("%d") == end.strftime("%d"):
                                    date_str = f"{start.strftime('%b %d')}"
                                    day_str = f"{start.strftime('%a')}"

                                else:
                                    date_str = f"{start.strftime('%b %d')} - {end.strftime('%b %d')}"
                                    day_str = (
                                        f"{start.strftime('%a')} - {end.strftime('%a')}"
                                    )
                                time_str = f"{start.strftime('%I:%M')} to {end.strftime('%I:%M')}"

                                plan_duration_list.append(
                                    f"{date_str}\n{day_str}\n{time_str}"
                                )
                        else:
                            duration_list = "DURATION TIME UNKNOWN"

                    # Alt. station suggestions/info, if any
                    if transit_realtime_dict.get("station_alternative", []):
                        station_alternative = transit_realtime_dict[
                            "station_alternative"
                        ]
                        for station_alternative_section in station_alternative:
                            affected_entity = station_alternative_section.get(
                                "affected_entity", {}
                            )
                            notes = station_alternative_section.get("notes", {})
                            if affected_entity:
                                affected_entity_stop_id = affected_entity["stop_id"]
                            if notes:
                                station_alternative_text = notes.get("translation")[0][
                                    "text"
                                ]

                # Summary/title of alert
                if header_text:
                    actual_header_text = header_text.get("translation")[0]["text"]

                # Detailed explanation & suggestions
                if description_text:
                    actual_description_text = description_text.get("translation")[0][
                        "text"
                    ]
                    # Removes useless text (I believe it's used for printing tho.)
                    if "shuttle bus icon" in actual_description_text:
                        actual_description_text = actual_description_text.replace(
                            "shuttle bus icon", ""
                        )
                    if "accessibility icon" in actual_description_text:
                        actual_description_text = actual_description_text.replace(
                            "accessibility icon", ""
                        )

                    # Not import. info. imo.; only useful if only using paper print outs
                    if "Key transfer" in actual_description_text:
                        terse_desc_text = actual_description_text.split("Key transfer")
                    if "Transfer Stations:" in actual_description_text:
                        if terse_desc_text:
                            terse_desc_text = terse_desc_text.split("Key transfer")[0]
                        else:
                            terse_desc_text = actual_description_text.partition(
                                "Transfer Stations:"
                            )[0]
                    if "What's happening?" in actual_description_text:
                        if terse_desc_text:
                            terse_desc_text = terse_desc_text.split("What's happening?")
                        else:
                            terse_desc_text = actual_description_text.partition(
                                f"What's happening?"
                            )[0]
                            if len(terse_desc_text) == 1:
                                terse_desc_text = None

                if alert_type:
                    formatted_alert_type = (
                        f"\n\033[4m[{line}] {alert_type}\033[0m"  # Underlined text
                    )
                    print(f"\n+{'-'*(terminal_width-2)}+\n{formatted_alert_type}")

                if duration:
                    formatted_duration = duration.split(", ")
                    if len(formatted_duration) > 1:
                        print("")
                        for i in range(len(formatted_duration)):
                            print(f"{formatted_duration[i]}")
                    else:
                        print(f"{duration}")
                    print("")
                elif plan_duration_list:
                    print(f"{''.join(plan_duration_list)}\n")

                if created_datetime and updated_datetime:
                    created = (datetime.fromtimestamp(created_datetime)).strftime(
                        f"'%y %b %d %H:%M"
                    )
                    delta = datetime.now() - datetime.fromtimestamp(updated_datetime)
                    updated = time_calc(delta)
                    print(f"Alert created: {created},\nLast updated: {updated} ago\n")

                if duration or created or updated:
                    print(f"{'='*terminal_width}")

                if header_text:
                    print(f"\033[1m\n{actual_header_text}\033[0m\n")  # Bold text

                if description_text:
                    if terse_desc_text:
                        print(f"{'='*terminal_width}\n{''.join(terse_desc_text)}")

                print(f"+{'-'*(terminal_width-2)}+")
                if (
                    not alert_type
                    and not duration
                    and not plan_duration_list
                    and not created_datetime
                    and not updated_datetime
                    and not header_text
                    and not description_text
                ):
                    print(f"\nNO ALERTS FOUND\n")
    return


def time_calc(delta):
    total_seconds = int(delta.total_seconds())

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days > 0:
        duration_str = f"{days}d {hours:02d}h {minutes:02d}m {seconds:02d}s"
    elif hours > 0:
        duration_str = f"{hours:02d}h {minutes:02d}m {seconds:02d}s"
    elif minutes > 0:
        duration_str = f"{minutes:02d}m {seconds:02d}s"
    else:
        duration_str = f"{seconds:02d}s"
    return duration_str


def time_zone(epoch_time):
    """Makes sure service times/dates are in ET/NYC time"""
    # Convert epoch time to Eastern Time
    et_tz = pytz.timezone("America/New_York")
    nyc_time = datetime.fromtimestamp(epoch_time, tz=pytz.utc).astimezone(et_tz)
    return nyc_time


def line_direction(line, stop):
    """
    Granular line dir. info.; the info.'s somewhat in stations.csv, but I didn't care
    for it, so divvied it up my own; might change in the future (if there are perm.
    service changes) to just rely on stations.csv & not manual formatting since the
    rest of this prog. is self-generating &, therefore, more robust
    """
    actual_route_id = check_route_id(line)

    # Don't Dead
    # Open Inside
    if stop.endswith("N"):
        if stop in [
            "107N",
            "108N",
            "109N",
            "110N",
            "111N",
            "112N",
            "113N",
            "114N",
            "115N",
            "116N",
            "117N",
            "118N",
            "119N",
            "120N",
            "121N",
            "122N",
            "123N",
            "124N",
            "125N",
            "126N",
            "127N",
            "128N",
            "129N",
            "130N",
            "131N",
            "132N",
            "133N",
            "134N",
            "135N",
            "136N",
            "137N",
            "138N",
            "139N",
            "140N",
            "142N",
            "120N",
            "121N",
            "122N",
            "123N",
            "124N",
            "125N",
            "126N",
            "127N",
            "128N",
            "129N",
            "130N",
            "131N",
            "132N",
            "133N",
            "134N",
            "135N",
            "136N",
            "137N",
            "138N",
            "139N",
            "140N",
            "142N",
            "225N",
            "226N",
            "227N",
            "228N",
            "229N",
            "301N",
            "302N",
            "418N",
            "419N",
            "622N",
            "623N",
            "624N",
            "625N",
            "626N",
            "627N",
            "628N",
            "629N",
            "630N",
            "631N",
            "632N",
            "633N",
            "634N",
            "635N",
            "636N",
            "637N",
            "638N",
            "639N",
            "640N",
            "A02N",
            "A03N",
            "A05N",
            "A06N",
            "A07N",
            "A09N",
            "A10N",
            "A11N",
            "A12N",
            "A14N",
            "A15N",
            "A16N",
            "A17N",
            "A18N",
            "A19N",
            "A20N",
            "A21N",
            "A22N",
            "A24N",
            "A25N",
            "A27N",
            "A28N",
            "A30N",
            "A31N",
            "A32N",
            "A33N",
            "A34N",
            "A36N",
            "B08N",
            "B10N",
            "D12N",
            "D13N",
            "D14N",
            "D15N",
            "D16N",
            "D17N",
            "D18N",
            "D19N",
            "D20N",
            "D21N",
            "E01N",
            "F12N",
            "F14N",
            "F15N",
            "M18N",
            "M19N",
            "M20N",
            "M21N",
            "M22N",
            "M23N",
            "Q01N",
            "Q03N",
            "Q04N",
            "Q05N",
            "R13N",
            "R14N",
            "R15N",
            "R16N",
            "R17N",
            "R18N",
            "R19N",
            "R20N",
            "R21N",
            "R22N",
            "R23N",
            "R24N",
            "R25N",
            "R26N",
            "230N",
            "420N",
            "A38N",
            "D22N",
            "F16N",
            "M18N",
            "R27N",
        ]:
            north_bound = "Uptown"
        elif stop in [
            "H01N",
            "H02N",
            "H03N",
            "H04N",
            "H06N",
            "H07N",
            "H08N",
            "H09N",
            "H10N",
            "H11N",
            "H12N",
            "H13N",
            "H14N",
            "H15N",
            "H19N",
            "231N",
            "232N",
            "233N",
            "234N",
            "235N",
            "236N",
            "237N",
            "238N",
            "239N",
            "241N",
            "242N",
            "243N",
            "244N",
            "245N",
            "246N",
            "247N",
            "248N",
            "249N",
            "250N",
            "251N",
            "252N",
            "253N",
            "254N",
            "255N",
            "256N",
            "257N",
            "423N",
            "A40N",
            "A41N",
            "A42N",
            "A43N",
            "A44N",
            "A45N",
            "A46N",
            "A47N",
            "A48N",
            "A49N",
            "A50N",
            "A51N",
            "A52N",
            "A53N",
            "A54N",
            "A55N",
            "A57N",
            "A59N",
            "A60N",
            "A61N",
            "A63N",
            "A64N",
            "A65N",
            "B12N",
            "B13N",
            "B14N",
            "B15N",
            "B16N",
            "B17N",
            "B18N",
            "B19N",
            "B20N",
            "B21N",
            "B22N",
            "B23N",
            "D24N",
            "D25N",
            "D26N",
            "D27N",
            "D28N",
            "D29N",
            "D30N",
            "D31N",
            "D32N",
            "D33N",
            "D34N",
            "D35N",
            "D37N",
            "D38N",
            "D39N",
            "D40N",
            "D41N",
            "D42N",
            "D43N",
            "F18N",
            "F20N",
            "F21N",
            "F22N",
            "F23N",
            "F24N",
            "F25N",
            "F26N",
            "F27N",
            "F29N",
            "F30N",
            "F31N",
            "F32N",
            "F33N",
            "F34N",
            "F35N",
            "F36N",
            "F38N",
            "F39N",
            "J19N",
            "J20N",
            "J21N",
            "J22N",
            "J23N",
            "J24N",
            "J27N",
            "J28N",
            "J29N",
            "J30N",
            "J31N",
            "L08N",
            "L10N",
            "L11N",
            "L12N",
            "L13N",
            "L14N",
            "L15N",
            "L16N",
            "L17N",
            "L19N",
            "L20N",
            "L21N",
            "L22N",
            "L24N",
            "L25N",
            "L26N",
            "L27N",
            "L28N",
            "L29N",
            "M09N",
            "M10N",
            "M11N",
            "M12N",
            "M13N",
            "M14N",
            "M16N",
            "N02N",
            "N03N",
            "N04N",
            "N05N",
            "N06N",
            "N07N",
            "N08N",
            "N09N",
            "N10N",
            "N12N",
            "R28N",
            "R29N",
            "R30N",
            "R31N",
            "R32N",
            "R33N",
            "R34N",
            "R35N",
            "R36N",
            "R39N",
            "R40N",
            "R41N",
            "R42N",
            "R43N",
            "R44N",
            "R45N",
            "701N",
            "702N",
            "705N",
            "706N",
            "707N",
            "708N",
            "709N",
            "710N",
            "711N",
            "712N",
            "713N",
            "714N",
            "715N",
            "716N",
            "718N",
            "719N",
            "720N",
            "721N",
            "B04N",
            "F01N",
            "F02N",
            "F03N",
            "F04N",
            "F05N",
            "F06N",
            "F07N",
            "F09N",
            "G05N",
            "G06N",
            "G07N",
            "G08N",
            "G09N",
            "G10N",
            "G11N",
            "G12N",
            "G13N",
            "G14N",
            "G15N",
            "G16N",
            "G18N",
            "G19N",
            "G20N",
            "G21N",
            "G22N",
            "R01N",
            "R03N",
            "R04N",
            "R05N",
            "R06N",
            "R08N",
            "R09N",
            "M08N",
        ]:
            north_bound = "Mhttn."
        elif stop in [
            "101N",
            "103N",
            "104N",
            "201N",
            "204N",
            "205N",
            "206N",
            "207N",
            "208N",
            "209N",
            "210N",
            "211N",
            "212N",
            "213N",
            "214N",
            "215N",
            "216N",
            "217N",
            "218N",
            "219N",
            "220N",
            "221N",
            "222N",
            "401N",
            "402N",
            "405N",
            "406N",
            "407N",
            "408N",
            "409N",
            "410N",
            "411N",
            "412N",
            "413N",
            "414N",
            "415N",
            "416N",
            "501N",
            "502N",
            "503N",
            "504N",
            "505N",
            "601N",
            "602N",
            "603N",
            "604N",
            "606N",
            "607N",
            "608N",
            "609N",
            "610N",
            "611N",
            "612N",
            "613N",
            "614N",
            "615N",
            "616N",
            "617N",
            "618N",
            "619N",
            "D01N",
            "D03N",
            "D04N",
            "D05N",
            "D06N",
            "D07N",
            "D08N",
            "D09N",
            "D10N",
            "D11N",
            "106N",
            "224N",
            "621N",
        ]:
            north_bound = "Bronx"
        elif stop in [
            "B06N",
            "F11N",
            "R11N",
            "G22N",
            "G24N",
            "G26N",
            "G28N",
            "G29N",
            "G30N",
            "G31N",
            "G32N",
            "G33N",
            "G34N",
            "G35N",
            "G36N",
        ]:
            north_bound = "Queens"
        elif stop in [
            "S09N",
            "S11N",
            "S13N",
            "S14N",
            "S15N",
            "S16N",
            "S17N",
            "S18N",
            "S19N",
            "S20N",
            "S21N",
            "S22N",
            "S23N",
            "S24N",
            "S25N",
            "S26N",
            "S27N",
            "S28N",
            "S29N",
            "S30N",
            "S31N",
        ]:
            north_bound = "N. Sh."
        elif actual_route_id in ["S01N", "S03N", "S04N"] or (
            stop == "D26N" and actual_route_id == "A"
        ):
            north_bound = "F. Av."
        elif stop in [
            "L06N",
            "723N",
            "724N",
            "725N",
            "726N",
            "901N",
            "902N",
            "L01N",
            "L02N",
            "L03N",
            "L05N",
        ]:
            north_bound = "W'side"
        elif stop in [
            "M01N",
            "M04N",
            "M05N",
            "M06N",
            "J12N",
            "J13N",
            "J14N",
            "J15N",
            "J16N",
            "J17N",
        ]:
            north_bound = "Bklyn."
        else:
            north_bound = "???"
        direction = f"{line} -> {north_bound}"

    else:
        if stop in [
            "106S",
            "224S",
            "621S",
            "107S",
            "108S",
            "109S",
            "110S",
            "111S",
            "112S",
            "113S",
            "114S",
            "115S",
            "116S",
            "117S",
            "118S",
            "119S",
            "120S",
            "121S",
            "122S",
            "123S",
            "124S",
            "125S",
            "126S",
            "127S",
            "128S",
            "129S",
            "130S",
            "131S",
            "132S",
            "133S",
            "134S",
            "135S",
            "136S",
            "137S",
            "138S",
            "139S",
            "140S",
            "142S",
            "120S",
            "121S",
            "122S",
            "123S",
            "124S",
            "125S",
            "126S",
            "127S",
            "128S",
            "129S",
            "130S",
            "131S",
            "132S",
            "133S",
            "134S",
            "135S",
            "136S",
            "137S",
            "138S",
            "139S",
            "140S",
            "142S",
            "225S",
            "226S",
            "227S",
            "228S",
            "229S",
            "301S",
            "302S",
            "418S",
            "419S",
            "622S",
            "623S",
            "624S",
            "625S",
            "626S",
            "627S",
            "628S",
            "629S",
            "630S",
            "631S",
            "632S",
            "633S",
            "634S",
            "635S",
            "636S",
            "637S",
            "638S",
            "639S",
            "640S",
            "A02S",
            "A03S",
            "A05S",
            "A06S",
            "A07S",
            "A09S",
            "A10S",
            "A11S",
            "A12S",
            "A14S",
            "A15S",
            "A16S",
            "A17S",
            "A18S",
            "A19S",
            "A20S",
            "A21S",
            "A22S",
            "A24S",
            "A25S",
            "A27S",
            "A28S",
            "A30S",
            "A31S",
            "A32S",
            "A33S",
            "A34S",
            "A36S",
            "B08S",
            "B10S",
            "D12S",
            "D13S",
            "D14S",
            "D15S",
            "D16S",
            "D17S",
            "D18S",
            "D19S",
            "D20S",
            "D21S",
            "E01S",
            "F12S",
            "F14S",
            "F15S",
            "M19S",
            "M20S",
            "M21S",
            "M22S",
            "M23S",
            "Q01S",
            "Q03S",
            "Q04S",
            "Q05S",
            "R13S",
            "R14S",
            "R15S",
            "R16S",
            "R17S",
            "R18S",
            "R19S",
            "R20S",
            "R21S",
            "R22S",
            "R23S",
            "R24S",
            "R25S",
            "R26S",
            "B06S",
            "F11S",
            "R11S",
        ]:
            south_bound = "Dntwn."
        elif stop in [
            "230S",
            "420S",
            "A38S",
            "D22S",
            "F16S",
            "R27S",
            "231S",
            "232S",
            "233S",
            "234S",
            "235S",
            "236S",
            "237S",
            "238S",
            "239S",
            "241S",
            "242S",
            "243S",
            "244S",
            "245S",
            "246S",
            "247S",
            "248S",
            "249S",
            "250S",
            "251S",
            "252S",
            "253S",
            "254S",
            "255S",
            "256S",
            "257S",
            "423S",
            "A40S",
            "A41S",
            "A42S",
            "A43S",
            "A44S",
            "A45S",
            "A46S",
            "A47S",
            "A48S",
            "A49S",
            "A50S",
            "A51S",
            "A52S",
            "A53S",
            "A54S",
            "A55S",
            "A57S",
            "A59S",
            "A60S",
            "A61S",
            "A63S",
            "A64S",
            "A65S",
            "B12S",
            "B13S",
            "B14S",
            "B15S",
            "B16S",
            "B17S",
            "B18S",
            "B19S",
            "B20S",
            "B21S",
            "B22S",
            "B23S",
            "D24S",
            "D25S",
            "D26S",
            "D27S",
            "D28S",
            "D29S",
            "D30S",
            "D31S",
            "D32S",
            "D33S",
            "D34S",
            "D35S",
            "D37S",
            "D38S",
            "D39S",
            "D40S",
            "D41S",
            "D42S",
            "D43S",
            "F18S",
            "F20S",
            "F21S",
            "F22S",
            "F23S",
            "F24S",
            "F25S",
            "F26S",
            "F27S",
            "F29S",
            "F30S",
            "F31S",
            "F32S",
            "F33S",
            "F34S",
            "F35S",
            "F36S",
            "F38S",
            "F39S",
            "J19S",
            "J20S",
            "J21S",
            "J22S",
            "J23S",
            "J24S",
            "J27S",
            "J28S",
            "J29S",
            "J30S",
            "J31S",
            "L08S",
            "L10S",
            "L11S",
            "L12S",
            "L13S",
            "L14S",
            "L15S",
            "L16S",
            "L17S",
            "L19S",
            "L20S",
            "L21S",
            "L22S",
            "L24S",
            "L25S",
            "L26S",
            "L27S",
            "L28S",
            "L29S",
            "M09S",
            "M10S",
            "M11S",
            "M12S",
            "M13S",
            "M14S",
            "M16S",
            "N02S",
            "N03S",
            "N04S",
            "N05S",
            "N06S",
            "N07S",
            "N08S",
            "N09S",
            "N10S",
            "N12S",
            "R28S",
            "R29S",
            "R30S",
            "R31S",
            "R32S",
            "R33S",
            "R34S",
            "R35S",
            "R36S",
            "R39S",
            "R40S",
            "R41S",
            "R42S",
            "R43S",
            "R44S",
            "R45S",
            "L06S",
            "G22S",
            "G24S",
            "G26S",
            "G28S",
            "G29S",
            "G30S",
            "G31S",
            "G32S",
            "G33S",
            "G34S",
            "G35S",
            "G36S",
        ] or (stop == "M18S" and actual_route_id in ["J", "M", "Z"]):
            south_bound = "Bklyn."
        elif stop in [
            "701S",
            "702S",
            "705S",
            "706S",
            "707S",
            "708S",
            "709S",
            "710S",
            "711S",
            "712S",
            "713S",
            "714S",
            "715S",
            "716S",
            "718S",
            "719S",
            "720S",
            "721S",
            "B04S",
            "F01S",
            "F02S",
            "F03S",
            "F04S",
            "F05S",
            "F06S",
            "F07S",
            "F09S",
            "G05S",
            "G06S",
            "G07S",
            "G08S",
            "G09S",
            "G10S",
            "G11S",
            "G12S",
            "G13S",
            "G14S",
            "G15S",
            "G16S",
            "G18S",
            "G19S",
            "G20S",
            "G21S",
            "R01S",
            "R03S",
            "R04S",
            "R05S",
            "R06S",
            "R08S",
            "R09S",
            "723S",
            "M01S",
            "M04S",
            "M05S",
            "M06S",
            "J12S",
            "J13S",
            "J14S",
            "J15S",
            "J16S",
            "J17S",
            "M08S",
        ] or (stop == "G22S" and actual_route_id in ["E", "M", "7"]):
            south_bound = "Queens"
        elif stop in [
            "101S",
            "103S",
            "104S",
            "201S",
            "204S",
            "205S",
            "206S",
            "207S",
            "208S",
            "209S",
            "210S",
            "211S",
            "212S",
            "213S",
            "214S",
            "215S",
            "216S",
            "217S",
            "218S",
            "219S",
            "220S",
            "221S",
            "222S",
            "401S",
            "402S",
            "405S",
            "406S",
            "407S",
            "408S",
            "409S",
            "410S",
            "411S",
            "412S",
            "413S",
            "414S",
            "415S",
            "416S",
            "501S",
            "502S",
            "503S",
            "504S",
            "505S",
            "601S",
            "602S",
            "603S",
            "604S",
            "606S",
            "607S",
            "608S",
            "609S",
            "610S",
            "611S",
            "612S",
            "613S",
            "614S",
            "615S",
            "616S",
            "617S",
            "618S",
            "619S",
            "D01S",
            "D03S",
            "D04S",
            "D05S",
            "D06S",
            "D07S",
            "D08S",
            "D09S",
            "D10S",
            "D11S",
        ]:
            south_bound = "Mhttn."
        elif stop in [
            "S09S",
            "S11S",
            "S13S",
            "S14S",
            "S15S",
            "S16S",
            "S17S",
            "S18S",
            "S19S",
            "S20S",
            "S21S",
            "S22S",
            "S23S",
            "S24S",
            "S25S",
            "S26S",
            "S27S",
            "S28S",
            "S29S",
            "S30S",
            "S31S",
        ]:
            south_bound = "S. Sh."
        elif stop in [
            "S01S",
            "S03S",
            "S04S",
        ] or (stop == "D26S" and actual_route_id == "SF"):
            south_bound = "P. Pk."
        elif stop in [
            "724S",
            "725S",
            "726S",
            "901S",
            "902S",
            "L01S",
            "L02S",
            "L03S",
            "L05S",
        ]:
            south_bound = "E'side"
        elif stop in [
            "H01S",
            "H02S",
            "H03S",
            "H04S",
            "H06S",
            "H07S",
            "H08S",
            "H09S",
            "H10S",
            "H11S",
            "H12S",
            "H13S",
            "H14S",
            "H15S",
            "H19S",
        ]:
            south_bound = "Beach"
        else:
            south_bound = "???"
        direction = f"{line} -> {south_bound}"
    return direction


def api_endpoint_urls(line):
    """Endpoint URLs for subway API feeds"""

    LINES = {
        "1": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
        "2": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
        "3": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
        "4": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
        "5": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
        "6": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
        "<6>": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
        "7": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
        "<7>": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
        "GS": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
        "FS": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",
        "RS": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",
        "A": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",
        "C": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",
        "E": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",
        "B": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",
        "D": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",
        "F": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",
        "<F>": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",
        "M": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",
        "G": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g",
        "L": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l",
        "J": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz",
        "Z": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz",
        "N": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw",
        "Q": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw",
        "R": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw",
        "W": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw",
        "SIR": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si",
    }

    if line == 0:  # For testing purposes
        return list(LINES.keys())
    elif line in LINES:
        url = LINES.get(line)
        return url
    elif line not in LINES:
        print(f"Error: {line} not found")
        return None


if __name__ == "__main__":
    main()
