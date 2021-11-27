"""AppDaemon App For use with Monitor Bluetooth Presence Detection Script.

apps.yaml parameters:
| - monitor_topic (default 'monitor'): MQTT Topic monitor.sh script publishes to
| - mqtt_event (default 'MQTT_MESSAGE'): MQTT event name as specified in the plugin setting 
| - not_home_timeout (default 30s): Time interval before declaring not home
| - minimum_confidence (default 50): Minimum Confidence Level to consider home
| - depart_check_time (default 30s): Time to wait before running depart scan
| - system_timeout (default 90s): Time for system to report back from echo
| - system_check (default 30s): Time interval for checking if system is online
| - everyone_not_home: Name to use for the "Everyone Not Home" Sensor
| - everyone_home: Name to use for the "Everyone Home" Sensor
| - somebody_is_home: Name to use for the "Somebody Is Home" Sensor
| - user_device_domain: Use "binary_sensor" or "device_tracker" domains.
| - known_devices: Known devices to be added to each monitor.
| - known_beacons: Known Beacons to monitor.
| - remote_monitors: login details of remote monitors that can be hardware rebooted
"""
import json
import adbase as ad
import copy
from datetime import datetime, timedelta
import traceback
import re


__VERSION__ = "2.4.2"
IGNORED_ACTIONS = [
    "depart",
    "arrive",
    "state",
    "known device states",
    "add static device",
    "delete static device",
]

# pylint: disable=attribute-defined-outside-init,unused-argument
class HomePresenceApp(ad.ADBase):
    """Home Precence App Main Class."""

    def initialize(self):
        """Initialize AppDaemon App."""
        self.adapi = self.get_ad_api()
        self.hass = self.get_plugin_api("HASS")
        self.mqtt = self.get_plugin_api("MQTT")

        self.monitor_topic = self.args.get("monitor_topic", "monitor")
        self.user_device_domain = self.args.get("user_device_domain", "binary_sensor")

        # State string to use depends on which domain is in use.
        self.state_true = "on" if self.user_device_domain == "binary_sensor" else "home"
        self.state_false = (
            "off" if self.user_device_domain == "binary_sensor" else "not_home"
        )

        # Setup dictionary of known beacons in the format { mac_id: name }.
        self.known_beacons = {
            p[0]: p[1].lower()
            for p in (b.split(" ", 1) for b in self.args.get("known_beacons", []))
        }

        # Setup dictionary of known devices in the format { mac_id: name }.
        self.known_devices = {
            p[0]: p[1].lower()
            for p in (b.split(" ", 1) for b in self.args.get("known_devices", []))
        }

        # Support nested presence topics (e.g. "hass/monitor")
        self.topic_level = len(self.monitor_topic.split("/"))
        self.monitor_name = self.monitor_topic.split("/")[-1]

        self.timeout = self.args.get("not_home_timeout", 30)
        self.minimum_conf = self.args.get("minimum_confidence", 50)
        self.depart_check_time = self.args.get("depart_check_time", 30)
        self.system_timeout = self.args.get("system_timeout", 60)
        system_check = self.args.get("system_check", 30)

        self.all_users_sensors = list()
        self.not_home_timers = dict()
        self.location_timers = dict()
        self.confidence_handlers = dict()
        self.home_state_entities = dict()
        self.system_handle = dict()
        self.node_scheduled_reboot = dict()
        self.node_executing = dict()
        self.locations = set()

        # Create a sensor to keep track of if the monitor is busy or not.
        self.monitor_entity = f"{self.monitor_name}.monitor_state"

        self.mqtt.set_state(
            self.monitor_entity,
            state="idle",
            attributes={
                "locations": [],
                "version": __VERSION__,
                "nodes": 0,
                "online_nodes": [],
                "offline_nodes": [],
                "friendly_name": "Monitor System State",
            },
            replace=True,
        )

        # Listen for requests to scan immediately.
        self.mqtt.listen_state(self.monitor_scan_now, self.monitor_entity, new="scan")

        # Listen for all changes to the monitor entity for MQTT forwarding
        self.mqtt.listen_state(
            self.forward_monitor_state,
            self.monitor_entity,
            attribute="all",
            immediate=True,
        )

        self.monitor_handlers = {self.monitor_entity: None}

        # Setup the Everybody Home/Not Home Group Sensors
        self.setup_global_sensors()

        # Initialize our timer variables
        self.gateway_timer = None
        self.motion_timer = None
        self.check_home_timer = None

        # Setup home gateway sensors
        if self.args.get("home_gateway_sensors") is not None:

            for gateway_sensor in self.args["home_gateway_sensors"]:
                (namespace, sensor) = self.parse_sensor(gateway_sensor)
                self.adapi.listen_state(
                    self.gateway_opened, sensor, namespace=namespace
                )
        else:
            # no gateway sensors, do app has to run arrive and depart scans every 2 minutes
            self.adapi.log(
                "No Gateway Sensors specified, Monitor-APP will run Arrive and Depart Scan every 2 minutes. Please specify Gateway Sensors for a better experience",
                level="WARNING",
            )
            self.adapi.run_every(
                self.run_arrive_scan, self.adapi.datetime() + timedelta(seconds=1), 60
            )
            self.adapi.run_every(
                self.run_depart_scan, self.adapi.datetime() + timedelta(seconds=2), 60
            )

        # Setup home motion sensors, used for RSSI tracking
        for motion_sensor in self.args.get("home_motion_sensors", []):
            (namespace, sensor) = self.parse_sensor(motion_sensor)
            self.adapi.listen_state(self.motion_detected, sensor, namespace=namespace)

        if self.args.get("scheduled_restart") is not None:
            kwargs = {}
            if "time" in self.args["scheduled_restart"]:
                time = self.args["scheduled_restart"]["time"]

                if "days" in self.args["scheduled_restart"]:
                    kwargs["constrain_days"] = ",".join(
                        self.args["scheduled_restart"]["days"]
                    )

                if "location" in self.args["scheduled_restart"]:
                    kwargs["location"] = self.args["scheduled_restart"]["location"]

                self.adapi.log("Setting up Monitor auto reboot")
                self.adapi.run_daily(self.restart_device, time, **kwargs)

            else:
                self.adapi.log(
                    "Will not be setting up auto reboot, as no time specified",
                    level="WARNING",
                )

        # Setup the system checks.
        if self.system_timeout > system_check:
            topic = f"{self.monitor_topic}/echo"
            self.adapi.run_every(
                self.send_mqtt_message,
                self.adapi.datetime() + timedelta(seconds=1),
                system_check,
                topic=topic,
                payload="",
                scan_type="System",
            )
        else:
            self.adapi.log(
                "Cannot setup System Check due to System Timeout"
                " being Lower than System Check in Seconds",
                level="WARNING",
            )

        # subscribe to the mqtt topic
        self.mqtt.mqtt_subscribe(f"{self.monitor_topic}/#")

        # Setup primary MQTT Listener for all presence messages.
        self.mqtt.listen_event(
            self.presence_message,
            self.args.get("mqtt_event", "MQTT_MESSAGE"),
            wildcard=f"{self.monitor_topic}/#",
        )
        self.adapi.log(f"Listening on MQTT Topic {self.monitor_topic}", level="DEBUG")

        # Listen for any HASS restarts
        self.hass.listen_event(self.hass_restarted, "plugin_restarted")

        # Load the devices from the config.
        self.adapi.run_in(self.clean_devices, 0)  # clean old devices first
        self.setup_service()  # setup service

        # now this is to be ran, every hour to clean strayed location data
        self.adapi.run_every(
            self.run_location_clean, f"now+{self.system_timeout + 30}", 3600
        )

    def setup_global_sensors(self):
        """Add all global home/not_home sensors."""
        everyone_not_home = self.args.get("everyone_not_home", "everyone_not_home")
        self.everyone_not_home = f"binary_sensor.{everyone_not_home}"

        everyone_home = self.args.get("everyone_home", "everyone_home")
        self.everyone_home = f"binary_sensor.{everyone_home}"

        somebody_is_home = self.args.get("somebody_is_home", "somebody_is_home")
        self.somebody_is_home = f"binary_sensor.{somebody_is_home}"

        self.create_global_sensor(everyone_not_home)
        self.create_global_sensor(everyone_home)
        self.create_global_sensor(somebody_is_home)

    def create_global_sensor(self, sensor):
        """Create a global sensor in HASS if it does not exist."""
        if self.hass.entity_exists(f"binary_sensor.{sensor}"):
            return

        self.adapi.log(f"Creating Binary Sensor for {sensor}", level="DEBUG")
        attributes = {
            "friendly_name": sensor.replace("_", " ").title(),
            "device_class": "presence",
        }

        self.hass.set_state(
            f"binary_sensor.{sensor}", state="off", attributes=attributes
        )

    def presence_message(self, event_name, data, kwargs):
        """Process a message sent on the MQTT Topic."""
        topic = data.get("topic")
        payload = data.get("payload")
        self.adapi.log(f"{topic} payload: {payload}", level="DEBUG")

        topic_path = topic.split("/")
        action = topic_path[-1].lower()

        # Process the payload as JSON if it is JSON
        payload_json = {}
        try:
            payload_json = json.loads(payload)
        except ValueError:
            pass

        # Handle request for immediate scan via MQTT
        # can be arrive/depart/rssi
        if action == "run_scan":
            # add scan_delay=0 to ensure its done immediately
            self.mqtt.call_service(
                f"{self.monitor_topic}/run_{payload.lower()}_scan", scan_delay=0
            )
            return

        # Determine which scanner initiated the message
        location = None
        if isinstance(payload_json, dict) and "identity" in payload_json:
            location = payload_json.get("identity")

        elif len(topic_path) > self.topic_level + 1:
            location = topic_path[self.topic_level]

        if location in (None, "None", ""):
            # got an invalid location

            if action in IGNORED_ACTIONS + [
                "echo"
            ]:  # its echo, so recieved possibly from himself
                pass

            else:
                self.adapi.log(
                    f"Got an invalid location {location}, from topic {topic}",
                    level="WARNING",
                )
            return

        location = location.replace(" ", "_").lower()
        location_friendly = location.replace("_", " ").title()

        # Presence System is Restarting
        if action == "restart":
            self.adapi.log("The Entire Presence System is Restarting")
            return

        # Miscellaneous Actions, Discard
        if action in IGNORED_ACTIONS:
            return

        # Status Message from the Presence System
        if action == "status":
            self.handle_status(location=location, payload=payload.lower())
            return

        if action in ["start", "end"]:
            self.handle_scanning(
                action=action,
                location=location,
                scan_type=topic_path[self.topic_level + 1],
            )
            return

        # Response to Echo Check of Scanner
        if action == "echo":
            self.handle_echo(location=location, payload=payload)
            return

        # Handle request for reboot of hardware
        if action == "reboot":
            self.adapi.run_in(self.restart_device, 1, location=location)
            return

        device_name = topic_path[self.topic_level + 1]
        # Handle Beacon Topics in MAC or iBeacon ID formats and make friendly.
        if device_name in list(self.known_beacons.keys()):
            device_name = self.known_beacons[device_name]
        else:
            device_name = device_name.replace(":", "_").replace("-", "_")

        device_entity_id = f"{self.monitor_name}_{device_name}"
        device_state_sensor = f"{self.user_device_domain}.{device_entity_id}"
        device_entity_prefix = f"{device_entity_id}_{location}"
        device_conf_sensor = f"sensor.{device_entity_prefix}_conf"
        device_local = f"{device_name}_{location}"
        appdaemon_entity = f"{self.monitor_name}.{device_local}"
        friendly_name = device_name.strip().replace("_", " ").title()

        # store the location
        self.locations.add(location)

        # RSSI Value for a Known Device:
        if action == "rssi":
            if topic == f"{self.monitor_topic}/scan/rssi" or payload == "":
                return

            attributes = {
                "rssi": payload,
                "last_reported_by": location.replace("_", " ").title(),
            }
            self.adapi.log(
                f"Recieved an RSSI of {payload} for {device_name} from {location_friendly}",
                level="DEBUG",
            )

            if (
                self.hass.entity_exists(device_conf_sensor)
                and self.hass.get_state(device_state_sensor, copy=False)
                == self.state_true
            ):
                # unless it exists, and the device is home don't update RSSI
                self.mqtt.set_state(appdaemon_entity, attributes=attributes)
                self.update_hass_sensor(device_conf_sensor, new_attr={"rssi": payload})
                self.update_nearest_monitor(device_name)
            return

        # Ignore invalid JSON responses
        if not payload_json:
            return

        # Ignore unknown/bad types and unknown beacons
        if payload_json.get("type") not in [
            "KNOWN_MAC",
            "GENERIC_BEACON",
        ] and payload_json.get("id") not in list(self.known_beacons.keys()):
            self.adapi.log(
                f"Ignoring Beacon {payload_json.get('id')} because it is not in the known_beacons list.",
                level="DEBUG",
            )
            return

        # Clean-up names now that we have proper JSON payload available.
        payload_json["friendly_name"] = f"{friendly_name} {location_friendly}"
        if "name" in payload_json:
            payload_json["name"] = payload_json["name"].strip().title()

        # Get the confidence value from the payload
        confidence = int(float(payload_json.get("confidence", "0")))
        del payload_json["confidence"]

        state = self.state_true if confidence >= self.minimum_conf else self.state_false

        if not self.hass.entity_exists(device_conf_sensor):
            # Entity does not exist in HASS yet.
            self.adapi.log(
                "Creating sensor {!r} for Confidence".format(device_conf_sensor)
            )
            self.hass.set_state(
                device_conf_sensor,
                state=confidence,
                attributes={
                    "friendly_name": f"{friendly_name} {location_friendly} Confidence",
                    "unit_of_measurement": "%",
                },
            )

        if not self.hass.entity_exists(device_state_sensor):
            # Device Home Presence Sensor Doesn't Exist Yet in Hass so create it
            self.adapi.log(
                "Creating sensor {!r} for Home State".format(device_state_sensor),
                level="DEBUG",
            )
            self.hass.set_state(
                device_state_sensor,
                state=state,
                attributes={
                    "friendly_name": f"{friendly_name} Home",
                    "type": payload_json.get("type", "UNKNOWN_TYPE"),
                    "device_class": "presence",
                },
            )

        if not self.mqtt.entity_exists(device_state_sensor):
            # Device Home Presence Sensor Doesn't Exist Yet in default so create it
            self.adapi.log(
                "Creating sensor {!r} for Home State".format(device_state_sensor),
                level="DEBUG",
            )
            self.mqtt.set_state(
                device_state_sensor,
                state=state,
                attributes={
                    "friendly_name": f"{friendly_name} Home",
                    "type": payload_json.get("type", "UNKNOWN_TYPE"),
                    "device_class": "presence",
                },
            )

        if device_entity_id not in self.home_state_entities:
            self.home_state_entities[device_entity_id] = list()

        # Add listeners to the conf sensors to update the main state sensor on change.
        if device_conf_sensor not in self.home_state_entities[device_entity_id]:
            self.home_state_entities[device_entity_id].append(device_conf_sensor)
            self.confidence_handlers[device_conf_sensor] = self.hass.listen_state(
                self.confidence_updated,
                device_conf_sensor,
                device_entity_id=device_entity_id,
                immediate=True,
            )

        # Actually update the confidence sensor.
        payload_json["location"] = location
        self.update_hass_sensor(device_conf_sensor, confidence, new_attr=payload_json)
        self.mqtt.set_state(appdaemon_entity, state=confidence, attributes=payload_json)

        # Set the nearest monitor property if we have a new RSSI.
        if "rssi" in payload_json:
            self.update_nearest_monitor(device_name)

        if device_state_sensor not in self.all_users_sensors:
            self.all_users_sensors.append(device_state_sensor)

            # now listen to this sensor's state changes
            # used to check if the user was not home before, and if home run rssi immediately to determine closest monitor
            self.mqtt.listen_state(
                self.device_state_changed,
                device_state_sensor,
                device_name=device_name,
                immediate=True,
            )

        if device_entity_id not in self.not_home_timers:
            self.not_home_timers[device_entity_id] = None

    def handle_status(self, location, payload):
        """Handle a status message from the presence system."""
        location_friendly = location.replace("_", " ").title()
        self.adapi.log(
            f"The {location_friendly} Presence System is {payload.title()}.",
            level="DEBUG",
        )

        if payload == "offline":
            # Location Offline, Run Timer to Clear All Entities
            if location in self.location_timers and self.adapi.timer_running(
                self.location_timers[location]
            ):
                self.adapi.cancel_timer(self.location_timers[location])

            self.location_timers[location] = self.adapi.run_in(
                self.clear_location_entities, self.system_timeout, location=location
            )

        elif (
            payload == "online"
            and location in self.location_timers
            and self.adapi.timer_running(self.location_timers[location])
        ):
            # Location back online. Cancel any timers.
            self.adapi.cancel_timer(self.location_timers[location])

        self.handle_nodes_state(location, payload)

        entity_id = f"{self.monitor_name}.{location}_state"
        attributes = {}

        if (
            not self.mqtt.entity_exists(entity_id)
            or self.mqtt.get_state(entity_id, attribute="friendly_name", copy=False)
            is None
        ):
            attributes.update(
                {
                    "friendly_name": f"{location_friendly} State",
                    "last_rebooted": "",
                    "location": location_friendly,
                }
            )
            # Load devices for all locations:
            self.adapi.run_in(self.load_known_devices, 30)

        self.mqtt.set_state(entity_id, state=payload, attributes=attributes)

        if self.system_handle.get(entity_id) is None:
            self.system_handle[entity_id] = self.mqtt.listen_state(
                self.node_state_changed, entity_id
            )

            # Listen for all changes to the node's entity for MQTT forwarding
            self.mqtt.listen_state(
                self.forward_monitor_state, entity_id, attribute="all", immediate=True,
            )

    def handle_scanning(self, action, location, scan_type):
        """Handle a Monitor location starting or stopping a scan."""
        old_state = self.mqtt.get_state(self.monitor_entity, copy=False)
        locations_attr = self.mqtt.get_state(self.monitor_entity, attribute="locations")
        new_state = "scanning" if action == "start" else "idle"
        attributes = {
            "scan_type": scan_type,
            "locations": locations_attr,
            location: new_state,
        }

        if action == "start":
            self.adapi.log(
                f"The {location} presence system is scanning...", level="DEBUG"
            )
            if old_state != "scanning":
                # Scanner was IDLE. Set it to SCANNING.
                attributes["locations"] = [location]
            elif location not in locations_attr:
                attributes["locations"].append(location)
        # Scan has just finished.
        elif action == "end" and location in locations_attr:
            attributes["locations"].remove(location)

        last_one = old_state != new_state and not attributes.get("locations")

        self.mqtt.set_state(
            self.monitor_entity,
            state="scanning" if not last_one else "idle",
            attributes=attributes,
        )

    def handle_echo(self, location, payload):
        """Handle an echo response from a scanner."""
        self.adapi.log(f"Echo received from {location}: {payload}", level="DEBUG")
        if payload != "ok":
            return

        entity_id = f"{self.monitor_name}.{location}_state"
        if location in self.location_timers and self.adapi.timer_running(
            self.location_timers[location]
        ):
            self.adapi.cancel_timer(self.location_timers[location])

        self.location_timers[location] = self.adapi.run_in(
            self.clear_location_entities, self.system_timeout, location=location
        )

        if self.mqtt.get_state(entity_id, copy=False) != "online":
            self.mqtt.set_state(entity_id, state="online")

            self.handle_nodes_state(location, "online")

    def handle_nodes_state(self, location, state):
        """Used to handle the state of the nodes for reporting """
        location_friendly = location.replace("_", " ").title()
        state = state.lower()

        attributes = self.mqtt.get_state(self.monitor_entity, attribute="all")[
            "attributes"
        ]

        if state == "online":

            # update the online/offline nodes as needed
            if location_friendly not in attributes["online_nodes"]:
                attributes["online_nodes"].append(location_friendly)

            if location_friendly in attributes["offline_nodes"]:
                attributes["offline_nodes"].remove(location_friendly)

        elif state == "offline":

            # update the online/offline nodes as needed
            if location_friendly not in attributes["offline_nodes"]:
                attributes["offline_nodes"].append(location_friendly)

            if location_friendly in attributes["online_nodes"]:
                attributes["online_nodes"].remove(location_friendly)

        attributes["nodes"] = len(attributes["online_nodes"]) + len(
            attributes["offline_nodes"]
        )

        self.mqtt.set_state(self.monitor_entity, attributes=attributes)

    def update_nearest_monitor(self, device_name):
        """Determine which monitor the device is closest to based on RSSI value."""
        device_entity_id = f"{self.monitor_name}_{device_name}"
        device_conf_sensors = self.home_state_entities.get(device_entity_id)
        device_state_sensor = f"{self.user_device_domain}.{device_entity_id}"

        if device_conf_sensors is None:
            self.adapi.log(
                f"Got Confidence Value for {device_entity_id} but device"
                " is not set up (no sensors found).",
                level="WARNING",
            )
            self.adapi.run_in(self.run_arrive_scan, 0)
            return

        rssi_values = {
            loc.replace(f"sensor.{device_entity_id}_", "").replace(
                "_conf", ""
            ): self.hass.get_state(loc, attribute="rssi")
            for loc in device_conf_sensors
        }

        rssi_values = {
            loc: int(rssi)
            for loc, rssi in rssi_values.items()
            if rssi is not None and rssi != "unknown"
        }

        nearest_monitor = "unknown"
        if rssi_values:
            nearest_monitor = max(rssi_values, key=rssi_values.get)
            self.adapi.log(
                f"{device_entity_id} is closest to {nearest_monitor} based on last reported RSSI values",
                level="DEBUG",
            )

        nearest_monitor = nearest_monitor.replace("_", " ").title()
        self.mqtt.set_state(device_state_sensor, nearest_monitor=nearest_monitor)
        self.update_hass_sensor(
            device_state_sensor, new_attr={"nearest_monitor": nearest_monitor},
        )

    def confidence_updated(self, entity, attribute, old, new, kwargs):
        """Respond to a monitor providing a new confidence value."""
        device_entity_id = kwargs["device_entity_id"]
        device_state_sensor = f"{self.user_device_domain}.{device_entity_id}"
        device_state_sensor_value = self.hass.get_state(device_state_sensor, copy=False)
        device_type = self.hass.get_state(entity, attribute="type", copy=False)
        device_conf_sensors = self.home_state_entities.get(device_entity_id)

        if device_conf_sensors is None:
            self.adapi.log(
                f"Got Confidence Value for {device_entity_id} but device"
                " is not set up (no sensors found).",
                level="WARNING",
            )

            self.adapi.run_in(self.run_arrive_scan, 0)
            return

        if int(new) == 0:  # the confidence is 0, so rssi should be lower
            # unknown used just to ensure it doesn't clash with an active node
            appdaemon_conf_sensor = self.hass_conf_sensor_to_appdaemon_conf(entity)
            self.mqtt.set_state(appdaemon_conf_sensor, rssi="unknown")
            self.update_hass_sensor(entity, new_attr={"rssi": "unknown"})

        sensor_res = list(
            map(lambda x: self.hass.get_state(x, copy=False), device_conf_sensors)
        )
        sensor_res = [i for i in sensor_res if i is not None and i != "unknown"]

        self.adapi.log(
            "Device State: {}, User Device Sensor: {}, Device Type {}, New: {}, State: {}".format(
                device_entity_id,
                device_state_sensor,
                device_type,
                new,
                device_state_sensor_value,
            ),
            level="DEBUG",
        )

        if sensor_res != [] and any(
            list(map(lambda x: int(x) >= self.minimum_conf, sensor_res))
        ):
            # Cancel the running timer.
            if self.not_home_timers.get(
                device_entity_id
            ) is not None and self.adapi.timer_running(
                self.not_home_timers[device_entity_id]
            ):
                self.adapi.cancel_timer(self.not_home_timers[device_entity_id])
                self.not_home_timers[device_entity_id] = None

            # update binary sensors for user
            self.mqtt.set_state(device_state_sensor, state=self.state_true)
            self.update_hass_sensor(device_state_sensor, self.state_true)

            # now check how many ppl are home
            count = self.count_persons_in_home()
            self.update_hass_sensor(
                self.somebody_is_home, "on", new_attr={"count": count}
            )

            if device_state_sensor in self.all_users_sensors:
                self.update_hass_sensor(self.everyone_not_home, "off")
                if self.check_home_timer is not None and self.adapi.timer_running(
                    self.check_home_timer
                ):
                    self.adapi.cancel_timer(self.check_home_timer)

                self.check_home_timer = self.adapi.run_in(
                    self.check_home_state, 2, check_state="is_home"
                )
            return

        if (
            self.not_home_timers.get(device_entity_id) is None
            and device_state_sensor_value not in ["off", "not_home"]
            and int(new) == 0
        ):
            # if "BEACON" not in str(device_type):
            # Run another scan before declaring the user away as extra
            # check within the timeout time if this isn't a beacon
            self.adapi.run_in(self.run_arrive_scan, 0)

            self.not_home_timers[device_entity_id] = self.adapi.run_in(
                self.not_home_func, self.timeout, device_entity_id=device_entity_id
            )
            self.adapi.log(f"Timer Started for {device_entity_id}", level="DEBUG")

    def device_state_changed(self, entity, attribute, old, new, kwargs):
        """Used to run RSSI scan in the event the device Left the house and re-entered"""

        device_name = kwargs["device_name"]
        device_entity_id = f"{self.monitor_name}_{device_name}"
        if new == self.state_true:  # device now home
            self.adapi.run_in(self.run_rssi_scan, 0)

        elif new == self.state_false:  # device is away
            device_conf_sensors = self.home_state_entities[device_entity_id]
            # now set all of their sensor's rssi to unknown to indicate its way
            for sensor in device_conf_sensors:
                location = self.hass.get_state(sensor, attribute="location", copy=False)
                device_local = f"{device_name}_{location}"
                appdaemon_entity = f"{self.monitor_name}.{device_local}"
                self.mqtt.set_state(appdaemon_entity, rssi="unknown")
                self.update_hass_sensor(sensor, new_attr={"rssi": "unknown"})

    def not_home_func(self, kwargs):
        """Manage devices that are not home."""
        device_entity_id = kwargs["device_entity_id"]

        # remove from dictionary
        self.not_home_timers.pop(device_entity_id, None)

        device_state_sensor = f"{self.user_device_domain}.{device_entity_id}"
        device_conf_sensors = self.home_state_entities[device_entity_id]
        sensor_res = list(
            map(lambda x: self.hass.get_state(x, copy=False), device_conf_sensors)
        )

        # Remove unknown values from list
        sensor_res = [i for i in sensor_res if i is not None and i != "unknown"]

        self.adapi.log(
            f"Device Not Home: {device_entity_id}, Sensors: {sensor_res}", level="DEBUG"
        )

        if all(list(map(lambda x: int(x) < self.minimum_conf, sensor_res))):
            # Confirm for the last time
            self.mqtt.set_state(
                device_state_sensor, state=self.state_false, nearest_monitor="unknown"
            )
            self.update_hass_sensor(
                device_state_sensor, self.state_false, {"nearest_monitor": "unknown"}
            )

            if device_state_sensor in self.all_users_sensors:
                # At least someone not home, set Everyone Home to off
                self.update_hass_sensor(self.everyone_home, "off")

                if self.check_home_timer is not None and self.adapi.timer_running(
                    self.check_home_timer
                ):
                    self.adapi.cancel_timer(self.check_home_timer)

                self.check_home_timer = self.adapi.run_in(
                    self.check_home_state, 2, check_state="not_home"
                )

        self.not_home_timers[device_entity_id] = None

    def send_mqtt_message(self, kwargs):
        """Send a MQTT Message."""
        topic = kwargs.get("topic")
        payload = kwargs.get("payload")
        if kwargs["scan_type"] == "Depart":
            count = kwargs.get("count", 0)
            # Last Gateway Based Timer
            self.gateway_timer = None

            if self.mqtt.get_state(self.monitor_entity) == "idle":
                self.mqtt.mqtt_publish(topic, payload)
                # Scan for departure times. 3 as default
                if count <= self.args.get("depart_scans", 3):
                    count = count + 1
                    self.adapi.run_in(self.run_depart_scan, 0, count=count)
                return
            # Scanner busy, re-run timer for it to get idle before
            # sending the message to start scan
            self.adapi.run_in(self.run_depart_scan, 0, scan_delay=10, count=count)
            return

        # Perform Arrival Scan
        if kwargs["scan_type"] == "Arrive":
            self.mqtt.mqtt_publish(topic, payload)
            return

        # System Command, Send the raw payload
        if kwargs["scan_type"] == "System":
            self.mqtt.mqtt_publish(topic, payload)
            return

    def update_hass_sensor(self, sensor, new_state=None, new_attr=None):
        """Update the hass sensor if it has changed."""
        if not self.hass.entity_exists(sensor):
            self.adapi.log(
                f"Entity {sensor} does not exist, running arrival scan.", level="ERROR"
            )
            self.adapi.run_in(self.run_arrive_scan, 0)
            return

        sensor_state = self.hass.get_state(sensor, attribute="all")
        state = sensor_state.get("state")
        attributes = sensor_state.get("attributes", {})
        if new_state is None:
            update_needed = False
            new_state = state
        else:
            update_needed = state != new_state

        if isinstance(new_attr, dict):
            attributes.update(new_attr)
            update_needed = True

        if update_needed:
            self.adapi.log(
                f"__function__: Entity_ID: {sensor}, new_state: {new_state}",
                level="DEBUG",
            )
            self.hass.set_state(sensor, state=new_state, attributes=attributes)

    def motion_detected(self, entity, attribute, old, new, kwargs):
        """Respond to motion detected somewhere in the house.

        This will attempt to check for where users are located.
        """
        self.adapi.log(f"Motion Sensor {entity} now {new}", level="DEBUG")

        if self.motion_timer is not None and self.adapi.timer_running(
            self.motion_timer
        ):  # a timer is running already
            self.adapi.cancel_timer(self.motion_timer)
            self.motion_timer = None
        """ 'duration' parameter could be used in listen_state.
            But need to use a single timer for all motion sensors,
            to avoid running the scan too many times"""
        self.motion_timer = self.adapi.run_in(
            self.run_rssi_scan, self.args.get("rssi_timeout", 60)
        )

    def check_home_state(self, kwargs):
        """Check if a user is home based on multiple locations."""

        self.check_home_timer = None
        check_state = kwargs["check_state"]
        user_res = list(
            map(lambda x: self.hass.get_state(x, copy=False), self.all_users_sensors)
        )
        user_res = [i for i in user_res if i is not None and i != "unknown"]
        somebody_home = "on"

        if check_state == "is_home" and all(
            list(map(lambda x: x in ["on", "home"], user_res))
        ):
            # Someone is home, check if everyone is home.
            self.update_hass_sensor(self.everyone_home, "on")
        elif check_state == "not_home" and all(
            list(map(lambda x: x in ["off", "not_home"], user_res))
        ):
            # Someone is not home, see if anyone is still home.
            self.update_hass_sensor(self.everyone_not_home, "on")
            somebody_home = "off"

        count = self.count_persons_in_home()
        new_attr = {"count": count}
        self.update_hass_sensor(self.somebody_is_home, somebody_home, new_attr=new_attr)

    def reload_device_state(self, kwargs):
        """Get the latest states from the scanners."""
        topic = f"{self.monitor_topic}/KNOWN DEVICE STATES"
        self.adapi.run_in(
            self.send_mqtt_message, 0, topic=topic, payload="", scan_type="System"
        )

    def monitor_changed_state(self, entity, attribute, old, new, kwargs):
        """Respond to a monitor location changing state."""
        scan = kwargs["scan"]
        topic = kwargs["topic"]
        payload = kwargs["payload"]
        self.adapi.run_in(
            self.send_mqtt_message, 1, topic=topic, payload=payload, scan_type="Arrive"
        )  # Send to scan for arrival of anyone
        self.adapi.cancel_listen_state(self.monitor_handlers[scan])
        self.monitor_handlers[scan] = None

    def forward_monitor_state(self, entity, attribute, old, new, kwargs):
        """Respond to any changes in the monitor system or each node"""
        new_state = copy.deepcopy(new)
        data = new_state["attributes"]

        # clean the data
        data.pop("friendly_name")
        last_changed = new_state["last_changed"]
        state = new_state["state"]
        data.update({"last_changed": last_changed, "state": state})

        if "location" not in data:  # it belongs to the overall monitor system
            topic = f"{self.monitor_topic}/state"

        else:  # it belongs to a node
            location = data["location"].lower().replace(" ", "_")
            topic = f"{self.monitor_topic}/{location}/state"

        self.mqtt.mqtt_publish(topic, json.dumps(data))

    def gateway_opened(self, entity, attribute, old, new, kwargs):
        """Respond to a gateway device opening or closing."""
        self.adapi.log(f"Gateway Sensor {entity} now {new}", level="DEBUG")

        self.check_and_run_scans(new)

    def gateway_opened_timer(self, kwargs):
        """Ran at intervals depending on when the user has a gateway opened"""

        self.check_and_run_scans(**kwargs)

    def check_and_run_scans(self, state=None, **kwargs):
        """Check the state of the home and run the required scans"""

        true_states = ("on", "y", "yes", "true", "home", "opened", "unlocked", True)
        false_states = ("off", "n", "no", "false", "away", "closed", "locked", False)

        if state is None:
            # none sent, so its a timer and so need to get the data itself, what a drag

            states = []
            for gateway_sensor in self.args.get("home_gateway_sensors", []):
                (namespace, sensor) = self.parse_sensor(gateway_sensor)
                states.append(self.adapi.get_state(x, copy=False, namespace=namespace))

            # now check if any of them is opened
            for s in states:
                if s in true_states:
                    state = s
                    break

        if state not in (true_states + false_states):
            return

        if self.gateway_timer is not None and self.adapi.timer_running(
            self.gateway_timer
        ):
            # Cancel Existing Timer
            self.adapi.cancel_timer(self.gateway_timer)
            self.gateway_timer = None

        if self.hass.get_state(self.everyone_not_home, copy=False) == "on":
            # No one at home
            self.adapi.run_in(self.run_arrive_scan, 0)

        elif self.hass.get_state(self.everyone_home, copy=False) == "on":
            # everyone at home
            self.adapi.run_in(self.run_depart_scan, 0)

        else:
            self.adapi.run_in(self.run_arrive_scan, 0)
            self.adapi.run_in(self.run_depart_scan, 0)

        # now check if gateway opned and the user had declared a scan interval for gateway opened
        if state in true_states and self.args.get("gateway_scan_interval"):
            timer = int(self.args.get("gateway_scan_interval"))
            first_time = kwargs.get("first_time", True)
            # there is a scan interval so need to be worked on
            # but first check if there is an initial one and it hasn't been ran
            if first_time and self.args.get("gateway_scan_interval_delay"):
                timer = int(self.args.get("gateway_scan_interval_delay"))
                first_time = False

            self.adapi.run_in(self.gateway_opened_timer, timer, first_time=first_time)

    def run_arrive_scan(self, kwargs):
        """Request an arrival scan.

        Will wait for the scanner to be free and then sends the message.
        """
        topic = f"{self.monitor_topic}/scan/arrive"
        payload = ""
        if self.mqtt.get_state(self.monitor_entity, copy=False) == "idle":
            self.mqtt.mqtt_publish(topic, payload)
            return

        # Scanner busy. Wait for it to finish:
        scan_type = self.mqtt.get_state(
            self.monitor_entity, attribute="scan_type", copy=False
        )
        if self.monitor_handlers.get("Arrive Scan") is None and scan_type != "arrival":
            self.monitor_handlers["Arrive Scan"] = self.mqtt.listen_state(
                self.monitor_changed_state,
                self.monitor_entity,
                new="idle",
                old="scanning",
                scan="Arrive Scan",
                topic=topic,
                payload=payload,
            )

    def run_depart_scan(self, kwargs):
        """Request a departure scan.

        Will wait for the scanner to be free and then sends the message.
        """
        delay = kwargs.get("scan_delay", self.depart_check_time)
        count = kwargs.get("count", 1)

        topic = f"{self.monitor_topic}/scan/depart"
        payload = ""

        # Cancel any timers
        if self.gateway_timer is not None and self.adapi.timer_running(
            self.gateway_timer
        ):
            self.adapi.cancel_timer(self.gateway_timer)

        # Scan for departure of anyone
        self.gateway_timer = self.adapi.run_in(
            self.send_mqtt_message,
            delay,
            topic=topic,
            payload=payload,
            scan_type="Depart",
            count=count,
        )

    def run_rssi_scan(self, kwargs):
        """Send a RSSI Scan Request."""
        topic = f"{self.monitor_topic}/scan/rssi"
        payload = ""
        self.mqtt.mqtt_publish(topic, payload)
        self.motion_timer = None

    def restart_device(self, kwargs):
        """Send a restart command to the monitor services."""
        topic = f"{self.monitor_topic}/scan/restart"
        payload = ""

        location = kwargs.get("location")  # meaning it needs a device to reboot

        if location is None:  # no specific location specified
            self.mqtt.mqtt_publish(topic, payload)

        elif (
            self.args.get("remote_monitors") is not None
            and self.args["remote_monitors"].get("disable") is not True
        ):

            if location == "all":  # reboot everything
                # get all locations
                locations = list(self.args.get("remote_monitors", {}).keys())

            elif isinstance(location, str):
                locations = location.split(",")

            elif isinstance(location, list):
                locations = location

            else:
                self.adapi.log(
                    f"Location {location} not supported. So cannot run hardware reboot",
                    level="WARNING",
                )

                return

            for location in locations:
                node = location.lower().strip().replace(" ", "_")
                entity_id = f"{self.monitor_name}.{node}_state"

                if node not in self.args["remote_monitors"]:
                    self.adapi.log(
                        f"Node {node} not defined. So cannot reboot it",
                        level="WARNING",
                    )

                    continue

                if (
                    self.node_scheduled_reboot.get(node) is not None
                    and kwargs.get("auto_rebooting") is True
                ):
                    # it means this is from a scheduled reboot, so reset the handler
                    self.node_scheduled_reboot[node] = None
                    self.mqtt.set_state(entity_id, reboot_scheduled="off")

                try:
                    # use executor here, as sometimes due to being unable to process it
                    # as the node might be busy, could lead to AD hanging

                    node_task = self.node_executing.get(node)
                    if node_task is None or node_task.done() or node_task.cancelled():
                        # meaning its either not running, or had completed or cancelled
                        self.node_executing[node] = self.adapi.submit_to_executor(
                            self.restart_hardware, node
                        )

                    else:
                        self.adapi.log(
                            f"{location}'s node busy executing a command. So cannot execute this now",
                            level="WARNING",
                        )

                except Exception as e:
                    self.adapi.error(
                        f"Could not restart {node}, due to {e}", level="ERROR"
                    )

    def run_node_command(self, kwargs):
        """Execute Command to be ran on the Node."""

        location = kwargs.get("location")
        cmd = kwargs.get("cmd")

        assert cmd is not None, "Command must be provided"

        # first get the required nodes

        if isinstance(location, str):
            node = location.lower().replace(" ", "_")

        else:
            node = location

        if node == "all":
            nodes = list(self.args.get("remote_monitors", {}).keys())

        elif isinstance(node, list):
            nodes = location

        else:
            nodes = [node]

        # now execute the command
        for node in nodes:
            if node not in self.args["remote_monitors"]:
                self.adapi.log(
                    f"Node {node} not defined. So cannot reboot it", level="WARNING",
                )

                continue

            node_task = self.node_executing.get(node)
            if node_task is None or node_task.done() or node_task.cancelled():
                # meaning its either not running, or had completed or cancelled
                self.node_executing[node] = self.adapi.submit_to_executor(
                    self.execute_command, node, cmd
                )

            else:
                self.adapi.log(
                    f"{location}'s node busy executing a command. So cannot execute this now",
                    level="WARNING",
                )

    def restart_hardware(self, node):
        """Used to Restart the Hardware Monitor running in"""

        self.adapi.log(f"Restarting {node}'s Hardware")

        reboot_command = "sudo reboot now"

        if "reboot_command" in self.args["remote_monitors"][node]:
            reboot_command = self.args["remote_monitors"][node]["reboot_command"]

        location = node.replace("_", " ").title()
        try:
            result = self.execute_command(node, reboot_command)
            self.adapi.log(
                f"{node}'s Hardware reset completed with result {result}",
                level="DEBUG",
            )

            entity_id = f"{self.monitor_name}.{node}_state"
            self.mqtt.set_state(
                entity_id,
                last_rebooted=self.adapi.datetime().replace(microsecond=0).isoformat(),
            )

        except Exception:
            self.adapi.error(traceback.format_exc(), leve="ERROR")
            self.adapi.error(
                f"Could not restart {location} Monitor Hardware", level="ERROR",
            )

    def execute_command(self, node, cmd):
        """Used to Run command on a Monitor Node"""

        self.adapi.log(f"Running {cmd} on {node}'s Hardware")
        import paramiko

        # get the node's credentials

        if node not in self.args["remote_monitors"]:
            raise ValueError(f"Given Node {node}, has no specified credentials")

        setting = self.args["remote_monitors"][node]
        host = setting["host"]
        username = setting["username"]
        password = setting["password"]

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            host,
            username=username,
            password=password,
            timeout=float(self.system_timeout),
        )
        stdin, stdout, stderr = ssh.exec_command(cmd)
        completed = stdout.readlines()
        ssh.close()

        self.adapi.log(completed, level="DEBUG")

        # reset node task if completed
        self.node_executing[node] = None
        return completed

    def run_location_clean(self, kwargs):
        """Check for if any location has data that had not been properly cleaned
        and carry out some cleaning"""

        # first get all sensors, and lets start from there
        monitor_sensors = list(self.mqtt.get_state(self.monitor_name).keys())

        # next we go via the location data, and see if any location needs cleaning
        for sensor in monitor_sensors:
            if sensor == self.monitor_entity:
                continue

            sens = list(filter(lambda l: re.search(l, sensor), self.locations))
            if len(sens) == 0:
                # it means this sensor doesn't belong to a valid location
                # so it needs to be removed
                self.adbase.log(f"Removing sensor {sensor}", level="WARNING")
                self.mqtt.remove_entity(sensor)

    def clear_location_entities(self, kwargs):
        """Clear sensors from an offline location.

        This is used to retrieve the different sensors based on system
        location, and set them to 0. This will ensure that if a location goes
        down and the confidence is not 0, it doesn't stay that way,
        and therefore lead to false info.
        """
        location = kwargs["location"]
        self.adapi.log(
            "Processing System Unavailable for " + location.replace("_", " ").title()
        )

        # remove the handler from dict
        self.location_timers.pop(location, None)

        for _, entity_list in self.home_state_entities.items():
            for sensor in entity_list:
                if location in sensor:  # that sensor belongs to that location
                    self.update_hass_sensor(sensor, 0)
                    appdaemon_conf_sensor = self.hass_conf_sensor_to_appdaemon_conf(
                        sensor
                    )
                    # set to "unknown" since it had been cleared
                    self.mqtt.set_state(appdaemon_conf_sensor, state=0, rssi="unknown")
                    self.update_hass_sensor(sensor, new_attr={"rssi": "unknown"})

        if location in self.location_timers:
            self.location_timers.pop(location)

        entity_id = f"{self.monitor_name}.{location}_state"
        self.mqtt.set_state(entity_id, state="offline")

        self.handle_nodes_state(location, "offline")

        if location in self.locations:
            self.locations.remove(location)

    def hass_conf_sensor_to_appdaemon_conf(self, sensor):
        """used to convert HASS confidence sensor to AD's"""

        device_entity_prefix = sensor.replace(
            f"sensor.{self.monitor_name}_", ""
        ).replace("_conf", "")

        appdaemon_conf_sensor = f"{self.monitor_name}.{device_entity_prefix}"

        return appdaemon_conf_sensor

    def node_state_changed(self, entity, attribute, old, new, kwargs):
        """Respond to a change in the Node's state."""

        location = self.mqtt.get_state(entity, attribute="location", copy=False)
        node = location.lower().replace(" ", "_")

        if (
            new == "online"
            and self.node_scheduled_reboot.get(node)
            and self.adapi.timer_running(self.node_scheduled_reboot[node])
        ):
            # means there was a scheduled reboot for this node, so should be cancelled
            self.adapi.log(
                f"Cancelling Scheduled Auto Reboot for Node at {location}, as its now back Online"
            )

            self.adapi.cancel_timer(self.node_scheduled_reboot[node])
            self.node_scheduled_reboot[node] = None
            self.mqtt.set_state(entity, reboot_scheduled="off")

        if old == "offline" and new == "online":
            self.adapi.run_in(self.reload_device_state, 0)

        elif new == "offline" and old == "online":
            self.adapi.log(
                f"Node at {location} is Offline, will need to be checked",
                level="WARNING",
            )

            # now check if to auto reboot the node
            if node in self.args.get("remote_monitors", {}):
                if (
                    self.args["remote_monitors"][node].get("auto_reboot_when_offline")
                    is True
                ):
                    if self.node_scheduled_reboot.get(node) is not None:
                        # a reboot had been scheduled earlier, so must be cancled and started all over
                        # this should technically not need to run, unless there is a bug somewhere

                        if self.adapi.timer_running(self.node_scheduled_reboot[node]):
                            self.adapi.cancel_timer(self.node_scheduled_reboot[node])

                        self.node_scheduled_reboot[node] = None

                    self.adapi.log(
                        f"Scheduling Auto Reboot for Node at {location} as its Offline",
                        level="WARNING",
                    )

                    if self.args["remote_monitors"][node].get("time") is not None:
                        # there is a time it should be rebooted if need be
                        reboot_time = self.args["remote_monitors"][node]["time"]
                        now = self.adapi.datetime()
                        scheduled_time = datetime.combine(
                            self.adapi.date(), self.adapi.parse_time(reboot_time)
                        )
                        if now > scheduled_time:  # the scheduled time is in the past
                            # run the scheduled time the next day
                            scheduled_time = scheduled_time + timedelta(days=1)

                        self.node_scheduled_reboot[node] = self.adapi.run_at(
                            self.restart_device,
                            scheduled_time,
                            location=node,
                            auto_rebooting=True,
                        )
                        reboot_time = scheduled_time.isoformat()

                    else:
                        # use the same system_check time out for auto rebooting, to give it time to
                        # reconnect to the network, in case of a network glich
                        self.node_scheduled_reboot[node] = self.adapi.run_in(
                            self.restart_device,
                            self.system_timeout,
                            location=node,
                            auto_rebooting=True,
                        )

                        reboot_time = (
                            self.adapi.datetime()
                            + timedelta(seconds=self.system_timeout)
                        ).isoformat()

                    self.mqtt.set_state(
                        entity, reboot_scheduled="on", reboot_time=reboot_time
                    )

                else:
                    # send a ping to node and log the output for debugging
                    host = self.args["remote_monitors"][node]["host"]

                    import subprocess

                    status, result = subprocess.getstatusoutput(f"ping -c1 -w2 {host}")

                    if status == 1:  # it is offline
                        self.mqtt.set_state(entity, state="network disconnected")

    def monitor_scan_now(self, entity, attribute, old, new, kwargs):
        """Request an immediate scan from the monitors."""
        scan_type = self.mqtt.get_state(entity, attribute="scan_type", copy=False)
        locations = self.mqtt.get_state(entity, attribute="locations", copy=False)

        if scan_type == "both":
            self.adapi.run_in(self.run_arrive_scan, 0, location=locations)
            self.adapi.run_in(self.run_depart_scan, 0, location=locations)

        elif scan_type == "arrival":
            self.adapi.run_in(self.run_arrive_scan, 0, location=locations)

        elif scan_type == "depart":
            self.adapi.run_in(self.run_depart_scan, 0, location=locations)

        self.mqtt.set_state(entity, state="idle")

    def load_known_devices(self, kwargs):
        """Request all known devices in config to be added to monitors."""
        timer = 0
        if self.args.get("known_devices") is not None:
            for device in self.args["known_devices"]:
                self.adapi.run_in(
                    self.send_mqtt_message,
                    timer,
                    topic=f"{self.monitor_topic}/setup/ADD STATIC DEVICE",
                    payload=device,
                    scan_type="System",
                )
                timer += 3

    def remove_known_device(self, kwargs):
        """Request all known devices in config to be deleted from monitors."""

        device = kwargs["device"]

        self.adapi.log(f"Removing device {device}", level="INFO")

        self.adapi.run_in(
            self.send_mqtt_message,
            0,
            topic=f"{self.monitor_topic}/setup/DELETE STATIC DEVICE",
            payload=device,
            scan_type="System",
        )

        # now remove the device from AD
        entities = list(
            self.mqtt.get_state(f"{self.monitor_name}", copy=False, default={}).keys()
        )
        device_name = None
        for entity in entities:
            if device == self.mqtt.get_state(entity, attribute="id", copy=False):
                location = self.mqtt.get_state(entity, attribute="location")
                if location is None:
                    continue

                node = location.replace(" ", "_").lower()
                self.mqtt.remove_entity(entity)
                if device_name is None:
                    _, domain_device = self.mqtt.split_entity(entity)
                    device_name = domain_device.replace(f"_{node}", "")

        # now remove the device from HA
        entities = list(self.hass.get_state("sensor", copy=False, default={}).keys())
        for entity in entities:
            if device == self.hass.get_state(entity, attribute="id", copy=False):
                # first cancel the handler if it exists
                handler = self.confidence_handlers.get(entity)
                if handler is not None:
                    self.hass.cancel_listen_state(handler)

                self.hass.remove_entity(entity)

        if device_name is not None:
            device_entity_id = f"{self.monitor_name}_{device_name}"
            device_state_sensor = f"{self.user_device_domain}.{device_entity_id}"

            if device_entity_id in self.home_state_entities:
                del self.home_state_entities[device_entity_id]

            if device_state_sensor in self.all_users_sensors:
                self.all_users_sensors.remove(device_state_sensor)

            # now remove for HA
            self.hass.remove_entity(device_state_sensor)

            # now remove for AD
            self.mqtt.remove_entity(device_state_sensor)

    def clean_devices(self, kwargs):
        """Used to check for old devices, and remove them accordingly"""

        # search for them first
        delay = 0
        removed = []
        known_device_names = [n.lower() for n in list(self.known_devices.values())]

        for sensor in self.mqtt.get_state(self.monitor_topic, copy=False, default={}):
            mac_id = self.mqtt.get_state(sensor, attribute="id", copy=False)
            if mac_id is None:
                continue

            sensor_name = self.mqtt.get_state(
                sensor, attribute="name", copy=False, default=""
            ).lower()
            if mac_id not in removed and (
                mac_id not in self.known_devices
                or sensor_name not in known_device_names
            ):
                # it should be removed

                if removed == []:  # means haven't removed one yet
                    self.adapi.log("Cleaning out old Known Devices")

                self.adapi.run_in(self.remove_known_device, delay, device=mac_id)
                removed.append(mac_id)  # indicate it has been removed
                delay += 3  # should process later

        if removed != []:
            delay += 5
            # means some where removed, so needs to re-load the scripts to clean properly
            self.adapi.run_in(self.restart_device, delay)

        # now load up the known devices before state
        delay += 45
        self.adapi.run_in(self.load_known_devices, delay)

        if removed != []:
            delay += 15 + len(known_device_names)
            self.adapi.run_in(self.run_arrive_scan, delay)
            self.adapi.run_in(self.load_known_devices, delay + 120)

        delay += 60
        self.adapi.run_in(self.reload_device_state, delay)

        # for some strange reasons, forces the app to run load_known_devices twice
        # to get updated data on the cleaned out devices

    def count_persons_in_home(self):
        """Used to count the number of persons in the Home"""

        user_devices = list(self.home_state_entities.keys())
        sensors = list(
            map(
                lambda x: self.mqtt.get_state(
                    f"{self.user_device_domain}.{x}", copy=False
                ),
                user_devices,
            )
        )
        sensors = [i for i in sensors if i == self.state_true]

        return len(sensors)

    def hass_restarted(self, event_name, data, kwargs):
        """Respond to a HASS Restart."""
        self.setup_global_sensors()
        # self.adapi.run_in(self.reload_device_state, 10)
        self.adapi.run_in(self.restart_device, 5)

    def setup_service(self):  # rgister services
        """Register services for app"""
        self.mqtt.register_service(
            f"{self.monitor_name}/remove_known_device", self.presense_services
        )
        self.mqtt.register_service(
            f"{self.monitor_name}/run_arrive_scan", self.presense_services
        )
        self.mqtt.register_service(
            f"{self.monitor_name}/run_depart_scan", self.presense_services
        )
        self.mqtt.register_service(
            f"{self.monitor_name}/run_rssi_scan", self.presense_services
        )
        self.mqtt.register_service(
            f"{self.monitor_name}/run_node_command", self.presense_services
        )
        self.mqtt.register_service(
            f"{self.monitor_name}/restart_device", self.presense_services
        )
        self.mqtt.register_service(
            f"{self.monitor_name}/reload_device_state", self.presense_services
        )
        self.mqtt.register_service(
            f"{self.monitor_name}/load_known_devices", self.presense_services
        )
        self.mqtt.register_service(
            f"{self.monitor_name}/clear_location_entities", self.presense_services
        )
        self.mqtt.register_service(
            f"{self.monitor_name}/clean_devices", self.presense_services
        )

    def presense_services(self, namespace, domain, service, kwargs):
        """Callback for executing service call"""
        self.adapi.log(
            f"presence_services() {namespace} {domain} {service} {kwargs}",
            level="DEBUG",
        )

        func = getattr(self, service)  # get the function first

        if func is None:
            raise ValueError(f"Unsupported service call {service}")

        if service == "remove_known_device" and "device" not in kwargs:
            self.adapi.log(
                "Could not Remove Known Device as no Device provided", level="WARNING"
            )
            return

        elif service == "clear_location_entities" and "location" not in kwargs:
            self.adapi.log(
                "Could not Clear Location Entities as no Location provided",
                level="WARNING",
            )
            return

        if "location" in kwargs:
            kwargs["location"] = kwargs["location"].replace(" ", "_").lower()

        if "delay" in kwargs:
            scan_delay = kwargs.pop("delay")
            kwargs["scan_delay"] = scan_delay

        self.adapi.run_in(func, 0, **kwargs)

    def parse_sensor(self, sensor) -> tuple:
        """Used to parse the sensor to for namespace """

        if sensor.count(".") > 1:  # means there is namespace given in the entity
            (namespace, domain, device) = sensor.split(".")
            sen = f"{domain}.{device}"

        else:
            namespace = self.hass.get_namespace()  # default is hass
            sen = sensor

        return (namespace, sen)

    def terminate(self):
        for node in self.node_executing:
            if self.node_executing[node] is not None:
                if (
                    not self.node_executing[node].done()
                    and not self.node_executing[node].cancelled()
                ):
                    # this means its still running, so cancel the task
                    self.node_executing[node].cancel()
