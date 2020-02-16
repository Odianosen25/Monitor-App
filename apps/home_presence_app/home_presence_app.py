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
import datetime
import adbase as ad


# pylint: disable=attribute-defined-outside-init,unused-argument
class HomePresenceApp(ad.ADBase):
    """Home Precence App Main Class."""

    def initialize(self):
        """Initialize AppDaemon App."""
        self.adbase = self.get_ad_api()
        self.hass = self.get_plugin_api("HASS")
        self.mqtt = self.get_plugin_api("MQTT")

        self.presence_topic = self.args.get("monitor_topic", "monitor")
        self.user_device_domain = self.args.get("user_device_domain", "binary_sensor")

        # State string to use depends on which domain is in use.
        self.state_true = "on" if self.user_device_domain == "binary_sensor" else "home"
        self.state_false = (
            "off" if self.user_device_domain == "binary_sensor" else "not_home"
        )

        # Setup dictionary of known beacons in the format { name: mac_id }.
        self.known_beacons = {
            p[0]: p[1].lower()
            for p in (b.split(" ", 1) for b in self.args.get("known_beacons", []))
        }

        # Support nested presence topics (e.g. "hass/monitor")
        self.topic_level = len(self.presence_topic.split("/"))
        self.presence_name = self.presence_topic.split("/")[-1]

        self.timeout = self.args.get("not_home_timeout", 30)
        self.minimum_conf = self.args.get("minimum_confidence", 50)
        self.depart_check_time = self.args.get("depart_check_time", 30)
        self.system_timeout = self.args.get("system_timeout", 60)
        system_check = self.args.get("system_check", 30)

        self.all_users_sensors = []
        self.not_home_timers = dict()
        self.location_timers = dict()
        self.home_state_entities = dict()
        self.system_handle = dict()

        # Create a sensor to keep track of if the monitor is busy or not.
        self.monitor_entity = f"{self.presence_name}.monitor_state"
        if not self.mqtt.entity_exists(self.monitor_entity):
            self.mqtt.set_state(
                self.monitor_entity,
                state="idle",
                attributes={"locations": []},
                replace=True,
            )

        # Listen for requests to scan immediately.
        self.mqtt.listen_state(self.monitor_scan_now, self.monitor_entity, new="scan")
        self.monitor_handlers = {self.monitor_entity: None}

        # Setup the Everybody Home/Not Home Group Sensors
        self.setup_global_sensors()

        # Initialize our timer variables
        self.gateway_timer = None
        self.motion_timer = None

        # Setup home gateway sensors
        if self.args.get("home_gateway_sensors") is not None:

            for gateway_sensor in self.args["home_gateway_sensors"]:
                self.hass.listen_state(self.gateway_opened, gateway_sensor)
        else:
            # no gateway sensors, do app has to run arrive and depart scans every 2 minutes
            self.adbase.log(
                "No Gateway Sensors specified, Monitor-APP will run Arrive and Depart Scan every 2 minutes. Please specify Gateway Sensors for a better experience",
                Level="WARNING",
            )
            self.adbase.run_every(self.run_arrive_scan, "now", 60)
            self.adbase.run_every(self.run_depart_scan, "now+1", 60)

        # Setup home motion sensors, used for RSSI tracking
        for motion_sensor in self.args.get("home_motion_sensors", []):
            self.hass.listen_state(self.motion_detected, motion_sensor)

        # Uncomment to restart the monitor systems every night at midnight
        # if "remote_monitors" specifed, it will lead to the hardward also being rebooted
        # time = "00:00:01"
        # self.adbase.run_daily(self.restart_device, time)

        # Setup the system checks.
        if self.system_timeout > system_check:
            time = datetime.datetime.now() + datetime.timedelta(seconds=1)
            topic = f"{self.presence_topic}/echo"
            self.adbase.run_every(
                self.send_mqtt_message,
                time,
                system_check,
                topic=topic,
                payload="",
                scan_type="System",
            )
        else:
            self.adbase.log(
                "Cannot setup System Check due to System Timeout"
                " being Lower than System Check in Seconds",
                level="WARNING",
            )

        # Setup primary MQTT Listener for all presence messages.
        self.mqtt.listen_event(
            self.presence_message,
            self.args.get("mqtt_event", "MQTT_MESSAGE"),
            wildcard=f"{self.presence_topic}/#",
        )
        self.adbase.log(f"Listening on MQTT Topic {self.presence_topic}", level="DEBUG")

        # Listen for any HASS restarts
        self.hass.listen_event(self.hass_restarted, "plugin_restarted")

        # Load the devices from the config.
        self.adbase.run_in(self.reload_device_state, 5)
        self.adbase.run_in(self.load_known_devices, 0)
        self.setup_service()  # setup service

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

        self.adbase.log(f"Creating Binary Sensor for {sensor}", level="DEBUG")
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
        self.adbase.log(f"{topic} payload: {payload}", level="DEBUG")

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
                f"{self.presence_topic}/run_{payload.lower()}_scan", scan_delay=0
            )
            return

        # Determine which scanner initiated the message
        location = "unknown"
        if isinstance(payload_json, dict) and "identity" in payload_json:
            location = payload_json.get("identity", "unknown")

        elif len(topic_path) > self.topic_level + 1:
            location = topic_path[self.topic_level]

        location = location.replace(" ", "_").lower()
        location_friendly = location.replace("_", " ").title()

        # Presence System is Restarting
        if action == "restart":
            self.adbase.log("The Entire Presence System is Restarting", level="INFO")
            return

        # Miscellaneous Actions, Discard
        if action in [
            "depart",
            "arrive",
            "known device states",
            "add static device",
            "delete static device",
        ]:
            return

        # Status Message from the Presence System
        if action == "status":
            self.handle_status(location=location, payload=payload)
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
            self.adbase.run_in(self.restart_device, 1, location=location)
            return

        device_name = topic_path[self.topic_level + 1]
        # Handle Beacon Topics in MAC or iBeacon ID formats and make friendly.
        if device_name in list(self.known_beacons.keys()):
            device_name = self.known_beacons[device_name]
        else:
            device_name = device_name.replace(":", "_").replace("-", "_")

        device_entity_id = f"{self.presence_name}_{device_name}"
        device_entity_prefix = f"{device_entity_id}_{location}"
        device_conf_sensor = f"sensor.{device_entity_prefix}_conf"
        device_local = f"{device_name}_{location}"
        appdaemon_entity = f"{self.presence_name}.{device_local}"
        friendly_name = device_name.strip().replace("_", " ").title()

        # RSSI Value for a Known Device:
        if action == "rssi":
            if topic == f"{self.presence_topic}/scan/rssi":
                return

            attributes = {
                "rssi": payload,
                "last_reported_by": location.replace("_", " ").title(),
            }
            self.adbase.log(
                f"Recieved an RSSI of {payload} for {device_name} from {location_friendly}",
                level="DEBUG",
            )
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
            self.adbase.log(
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

        device_state_sensor = f"{self.user_device_domain}.{device_entity_id}"
        state = self.state_true if confidence >= self.minimum_conf else self.state_false

        if not self.hass.entity_exists(device_conf_sensor):
            # Entity does not exist in HASS yet.
            self.adbase.log(
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
            # Device Home Presence Sensor Doesn't Exist Yet
            self.adbase.log(
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

        if device_entity_id not in self.home_state_entities:
            self.home_state_entities[device_entity_id] = list()

        # Add listeners to the conf sensors to update the main state sensor on change.
        if device_conf_sensor not in self.home_state_entities[device_entity_id]:
            self.home_state_entities[device_entity_id].append(device_conf_sensor)
            self.hass.listen_state(
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

        if device_entity_id not in self.not_home_timers:
            self.not_home_timers[device_entity_id] = None

    def handle_status(self, location, payload):
        """Handle a status message from the presence system."""
        location_friendly = location.replace("_", " ").title()
        self.adbase.log(
            f"The {location_friendly} Presence System is {payload.title()}.",
            level="DEBUG",
        )

        if payload == "offline":
            # Location Offline, Run Timer to Clear All Entities
            if location in self.location_timers:
                self.adbase.cancel_timer(self.location_timers[location])

            self.location_timers[location] = self.adbase.run_in(
                self.clear_location_entities, self.system_timeout, location=location
            )
        elif payload == "online" and location in self.location_timers:
            # Location back online. Cancel any timers.
            self.adbase.cancel_timer(self.location_timers[location])

        entity_id = f"{self.presence_name}.{location}"
        attributes = {}

        if not self.mqtt.entity_exists(entity_id):
            attributes.update({"friendly_name": location_friendly})
            # Load devices for all locations:
            self.adbase.run_in(self.load_known_devices, 30)

        self.mqtt.set_state(entity_id, state=payload, attributes=attributes)

        if self.system_handle.get(entity_id) is None:
            self.system_handle[entity_id] = self.mqtt.listen_state(
                self.system_state_changed, entity_id, old="offline", new="online"
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
            self.adbase.log(
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
        self.adbase.log(f"Echo received from {location}: {payload}", level="DEBUG")
        if payload != "ok":
            return
        entity_id = f"{self.presence_name}.{location}"
        if location in self.location_timers:
            self.adbase.cancel_timer(self.location_timers[location])

        self.location_timers[location] = self.adbase.run_in(
            self.clear_location_entities, self.system_timeout, location=location
        )
        if self.mqtt.get_state(entity_id, copy=False) == "offline":
            self.mqtt.set_state(entity_id, state="online")

    def update_nearest_monitor(self, device_name):
        """Determine which monitor the device is closest to based on RSSI value."""
        device_entity_id = f"{self.presence_name}_{device_name}"
        device_conf_sensors = self.home_state_entities.get(device_entity_id)

        if device_conf_sensors is None:
            self.adbase.log(
                f"Got Confidence Value for {device_entity_id} but device"
                " is not set up (no sensors found).",
                level="WARNING",
            )
            self.adbase.run_in(self.run_arrive_scan, 0)
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
            if rssi is not None and str(rssi) != "-99"
        }

        nearest_monitor = "unknown"
        if rssi_values:
            nearest_monitor = max(rssi_values, key=rssi_values.get)
            self.adbase.log(
                f"{device_entity_id} is closest to {nearest_monitor} based on last reported RSSI values",
                level="DEBUG",
            )

        self.update_hass_sensor(
            f"{self.user_device_domain}.{device_entity_id}",
            new_attr={"nearest_monitor": nearest_monitor.replace("_", " ").title()},
        )

    def confidence_updated(self, entity, attribute, old, new, kwargs):
        """Respond to a monitor providing a new confidence value."""
        device_entity_id = kwargs["device_entity_id"]
        device_state_sensor = f"{self.user_device_domain}.{device_entity_id}"
        device_state_sensor_value = self.hass.get_state(device_state_sensor, copy=False)
        device_type = self.hass.get_state(entity, attribute="type", copy=False)
        device_conf_sensors = self.home_state_entities.get(device_entity_id)

        if device_conf_sensors is None:
            self.adbase.log(
                f"Got Confidence Value for {device_entity_id} but device"
                " is not set up (no sensors found).",
                level="WARNING",
            )

            self.adbase.run_in(self.run_arrive_scan, 0)
            return

        sensor_res = list(
            map(lambda x: self.hass.get_state(x, copy=False), device_conf_sensors)
        )
        sensor_res = [i for i in sensor_res if i is not None and i != "unknown"]

        self.adbase.log(
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
            if self.not_home_timers[device_entity_id] is not None:
                self.adbase.cancel_timer(self.not_home_timers[device_entity_id])
                self.not_home_timers[device_entity_id] = None

            self.update_hass_sensor(device_state_sensor, self.state_true)
            self.update_hass_sensor(self.somebody_is_home, "on")

            if device_state_sensor in self.all_users_sensors:
                self.update_hass_sensor(self.everyone_not_home, "off")
                self.adbase.run_in(self.check_home_state, 2, check_state="is_home")
            return

        if (
            self.not_home_timers[device_entity_id] is None
            and device_state_sensor_value not in ["off", "not_home"]
            and int(new) == 0
        ):
            if "BEACON" not in str(device_type):
                # Run another scan before declaring the user away as extra
                # check within the timeout time if this isn't a beacon
                self.adbase.run_in(self.run_arrive_scan, 0)

            self.not_home_timers[device_entity_id] = self.adbase.run_in(
                self.not_home_func, self.timeout, device_entity_id=device_entity_id
            )
            self.adbase.log(f"Timer Started for {device_entity_id}", level="DEBUG")

    def not_home_func(self, kwargs):
        """Manage devices that are not home."""
        device_entity_id = kwargs.get("device_entity_id")
        device_state_sensor = f"{self.user_device_domain}.{device_entity_id}"
        device_conf_sensors = self.home_state_entities[device_entity_id]
        sensor_res = list(
            map(lambda x: self.hass.get_state(x, copy=False), device_conf_sensors)
        )

        # Remove unknown values from list
        sensor_res = [i for i in sensor_res if i is not None and i != "unknown"]

        self.adbase.log(
            f"Device Not Home: {device_entity_id}, Sensors: {sensor_res}", level="DEBUG"
        )

        if all(list(map(lambda x: int(x) < self.minimum_conf, sensor_res))):
            # Confirm for the last time
            self.update_hass_sensor(device_state_sensor, self.state_false)

            if device_state_sensor in self.all_users_sensors:
                # At least someone not home, set Everyone Home to off
                self.update_hass_sensor(self.everyone_home, "off")
                self.adbase.run_in(self.check_home_state, 2, check_state="not_home")

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
                    self.adbase.run_in(self.run_depart_scan, 0, count=count)
                return
            # Scanner busy, re-run timer for it to get idle before
            # sending the message to start scan
            self.adbase.run_in(self.run_depart_scan, 0, scan_delay=10, count=count)
            return

        # Perform Arrival Scan
        if kwargs["scan_type"] in "Arrive":
            self.mqtt.mqtt_publish(topic, payload)
            return

        # System Command, Send the raw payload
        if kwargs["scan_type"] == "System":
            self.mqtt.mqtt_publish(topic, payload)
            return

    def update_hass_sensor(self, sensor, new_state=None, new_attr=None):
        """Update the hass sensor if it has changed."""
        if not self.hass.entity_exists(sensor):
            self.adbase.log(f"Entity {sensor} does not exist.", level="ERROR")

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
            self.adbase.log(
                f"__function__: Entity_ID: {sensor}, new_state: {new_state}",
                level="DEBUG",
            )
            self.hass.set_state(sensor, state=new_state, attributes=attributes)

    def gateway_opened(self, entity, attribute, old, new, kwargs):
        """Respond to a gateway device opening or closing."""
        self.adbase.log(f"Gateway Sensor {entity} now {new}", level="DEBUG")

        if self.gateway_timer is not None:
            # Cancel Existing Timer
            self.adbase.cancel_timer(self.gateway_timer)
            self.gateway_timer = None

        if self.hass.get_state(self.everyone_not_home, copy=False) == "on":
            # No one at home
            self.adbase.run_in(self.run_arrive_scan, 0)

        elif self.hass.get_state(self.everyone_home, copy=False) == "on":
            # everyone at home
            self.adbase.run_in(self.run_depart_scan, 0)
        else:
            self.adbase.run_in(self.run_arrive_scan, 0)
            self.adbase.run_in(self.run_depart_scan, 0)

    def motion_detected(self, entity, attribute, old, new, kwargs):
        """Respond to motion detected somewhere in the house.

        This will attempt to check for where users are located.
        """
        self.adbase.log(f"Motion Sensor {entity} now {new}", level="DEBUG")

        if self.motion_timer is not None:  # a timer is running already
            self.adbase.cancel_timer(self.motion_timer)
            self.motion_timer = None
        """ 'duration' parameter could be used in listen_state.
            But need to use a single timer for all motion sensors,
            to avoid running the scan too many times"""
        self.motion_timer = self.adbase.run_in(
            self.run_rssi_scan, self.args.get("rssi_timeout", 60)
        )

    def check_home_state(self, kwargs):
        """Check if a user is home based on multiple locations."""
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

        self.update_hass_sensor(self.somebody_is_home, somebody_home)

    def reload_device_state(self, kwargs):
        """Get the latest states from the scanners."""
        topic = f"{self.presence_topic}/KNOWN DEVICE STATES"
        self.adbase.run_in(
            self.send_mqtt_message, 0, topic=topic, payload="", scan_type="System"
        )

    def monitor_changed_state(self, entity, attribute, old, new, kwargs):
        """Respond to a monitor location changing state."""
        scan = kwargs["scan"]
        topic = kwargs["topic"]
        payload = kwargs["payload"]
        self.adbase.run_in(
            self.send_mqtt_message, 1, topic=topic, payload=payload, scan_type="Arrive"
        )  # Send to scan for arrival of anyone
        self.adbase.cancel_listen_state(self.monitor_handlers[scan])
        self.monitor_handlers[scan] = None

    def run_arrive_scan(self, kwargs):
        """Request an arrival scan.

        Will wait for the scanner to be free and then sends the message.
        """
        topic = f"{self.presence_topic}/scan/arrive"
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

        topic = f"{self.presence_topic}/scan/depart"
        payload = ""

        # Cancel any timers
        if self.gateway_timer is not None:
            self.adbase.cancel_timer(self.gateway_timer)

        # Scan for departure of anyone
        self.gateway_timer = self.adbase.run_in(
            self.send_mqtt_message,
            delay,
            topic=topic,
            payload=payload,
            scan_type="Depart",
            count=count,
        )

    def run_rssi_scan(self, kwargs):
        """Send a RSSI Scan Request."""
        topic = f"{self.presence_topic}/scan/rssi"
        payload = ""
        self.mqtt.mqtt_publish(topic, payload)
        self.motion_timer = None

    def restart_device(self, kwargs):
        """Send a restart command to the monitor services."""
        topic = f"{self.presence_topic}/scan/restart"
        payload = ""

        location = kwargs.get("location")  # meaning it needs a device to reboot

        if location is None:  # no specific location specified
            self.mqtt.mqtt_publish(topic, payload)

        else:
            location = location.lower().replace(" ", "_")
            if location == "all":  # reboot everything
                location = None

            elif location not in self.args.get("remote_monitors", {}):
                self.adbase.log(
                    f"Location {location} not defined. So cannot restart it",
                    level="WARNING",
                )

                return

        if self.args.get("remote_monitors") is not None:
            for remote_device, setting in self.args["remote_monitors"].items():

                if location is not None and remote_device != location:
                    continue

                try:
                    host = setting["host"]
                    username = setting["username"]
                    password = setting["password"]
                    self.restart_hardware(remote_device, host, username, password)
                except Exception as e:
                    self.adbase.error(
                        f"Could not restart {remote_device}, due to {e}", level="ERROR"
                    )

    def restart_hardware(self, device, host, username, password):
        """Used to Restart the Hardware Monitor running in"""
        self.adbase.log(f"Restarting {device}'s Hardware")
        import paramiko

        try:
            cmd = "sudo reboot now"
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(host, username=username, password=password)
            stdin, stdout, stderr = ssh.exec_command(cmd)
            completed = stdout.readlines()
            ssh.close()
            self.adbase.log(
                f"{device} Hardware reset completed with result {completed}",
                level="DEBUG",
            )

        except Exception as e:
            self.adbase.error(
                f"Could not restart {device} Monitor Hardware due to {e}", level="ERROR"
            )

    def clear_location_entities(self, kwargs):
        """Clear sensors from an offline location.

        This is used to retrieve the different sensors based on system
        location, and set them to 0. This will ensure that if a location goes
        down and the confidence is not 0, it doesn't stay that way,
        and therefore lead to false info.
        """
        location = kwargs.get("location")
        self.adbase.log(
            "Processing System Unavailable for " + location.replace("_", " ").title()
        )

        for _, entity_list in self.home_state_entities.items():
            for sensor in entity_list:
                if location in sensor:  # that sensor belongs to that location
                    self.update_hass_sensor(sensor, 0)
                    device_entity_prefix = sensor.replace(
                        f"sensor.{self.presence_topic}_", ""
                    ).replace("_conf", "")

                    appdaemon_entity = f"{self.presence_name}.{device_entity_prefix}"
                    self.mqtt.set_state(appdaemon_entity, state=0, rssi="-99")
                    self.update_hass_sensor(sensor, new_attr={"rssi": "-99"})

        if location in self.location_timers:
            self.location_timers.pop(location)

        entity_id = f"{self.presence_name}.{location}"
        self.mqtt.set_state(entity_id, state="offline")

    def system_state_changed(self, entity, attribute, old, new, kwargs):
        """Respond to a change in the system state."""
        self.adbase.run_in(self.reload_device_state, 0)

    def monitor_scan_now(self, entity, attribute, old, new, kwargs):
        """Request an immediate scan from the monitors."""
        scan_type = self.mqtt.get_state(entity, attribute="scan_type", copy=False)
        locations = self.mqtt.get_state(entity, attribute="locations", copy=False)

        if scan_type == "both":
            self.adbase.run_in(self.run_arrive_scan, 0, location=location)
            self.adbase.run_in(self.run_depart_scan, 0, location=locations)

        elif scan_type == "arrival":
            self.adbase.run_in(self.run_arrive_scan, 0, location=location)

        elif scan_type == "depart":
            self.adbase.run_in(self.run_depart_scan, 0, location=locations)

        self.mqtt.set_state(entity, state="idle")

    def load_known_devices(self, kwargs):
        """Request all known devices in config to be added to monitors."""
        timer = 0
        for device in self.args["known_devices"]:
            self.adbase.run_in(
                self.send_mqtt_message,
                timer,
                topic=f"{self.presence_topic}/setup/ADD STATIC DEVICE",
                payload=device,
                scan_type="System",
            )
            timer += 15

    def remove_known_device(self, kwargs):
        """Request all known devices in config to be deleted from monitors."""
        device = kwargs["device"]
        self.adbase.run_in(
            self.send_mqtt_message,
            0,
            topic=f"{self.presence_topic}/setup/DELETE STATIC DEVICE",
            payload=device,
            scan_type="System",
        )

        # now remove the device from AD
        for entity in self.mqtt.get_state(f"{self.presence_topic}", copy=False):
            if device == self.mqtt.get_state(entity, attribute="id", copy=False):
                self.mqtt.remove_entity(entity)

    def hass_restarted(self, event_name, data, kwargs):
        """Respond to a HASS Restart."""
        self.setup_global_sensors()
        # self.adbase.run_in(self.reload_device_state, 10)
        self.adbase.run_in(self.restart_device, 5)

    def setup_service(self):  # rgister services
        """Register services for app"""
        self.mqtt.register_service(
            f"{self.presence_topic}/remove_known_device", self.presense_services
        )
        self.mqtt.register_service(
            f"{self.presence_topic}/run_arrive_scan", self.presense_services
        )
        self.mqtt.register_service(
            f"{self.presence_topic}/run_depart_scan", self.presense_services
        )
        self.mqtt.register_service(
            f"{self.presence_topic}/run_rssi_scan", self.presense_services
        )
        self.mqtt.register_service(
            f"{self.presence_topic}/restart_device", self.presense_services
        )
        self.mqtt.register_service(
            f"{self.presence_topic}/reload_device_state", self.presense_services
        )
        self.mqtt.register_service(
            f"{self.presence_topic}/load_known_devices", self.presense_services
        )
        self.mqtt.register_service(
            f"{self.presence_topic}/clear_location_entities", self.presense_services
        )

    def presense_services(self, namespace, domain, service, kwargs):
        """Callback for executing service call"""
        self.adbase.log(
            f"presence_services() {namespace} {domain} {service} {kwargs}",
            level="DEBUG",
        )

        func = getattr(self, service)  # get the function first

        if func is None:
            raise ValueError(f"Unsupported service call {service}")

        if service == "remove_known_device" and "device" not in kwargs:
            self.adbase.log(
                "Could not Remove Known Device as no Device provided", level="WARNING"
            )
            return

        elif service == "clear_location_entities" and "location" not in kwargs:
            self.adbase.log(
                "Could not Clear Location Entities as no Location provided",
                level="WARNING",
            )
            return

        if location in kwargs:
            kwargs["location"] = kwargs["location"].replace(" ", "_").lower()

        self.adbase.run_in(func, 0, **kwargs)
