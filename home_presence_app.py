"""AppDaemon App For use with Monitor Bluetooth Presence Detection Script.

apps.yaml parameters:
| - not_home_timeout (default 30s): Time interval before declaring not home
| - minimum_confidence (default 90): Minimum Confidence Level to consider home
| - depart_check_time (default 30s): Time to wait before running depart scan
| - system_timeout (default 90s): Time for system to report back from echo
| - system_check (default 30s): Time interval for checking if system is online
| - everyone_not_home: Name to use for the "Everyone Not Home" Sensor
| - everyone_home: Name to use for the "Everyone Home" Sensor
| - somebody_is_home: Name to use for the "Somebody Is Home" Sensor
| - user_device_domain: Use "binary_sensor" or "device_tracker" domains.
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

        self.presence_topic = self.args.get("monitor_topic", "presence")
        self.user_device_domain = self.args.get("user_device_domain", "binary_sensor")
        self.state_true = "on" if self.user_device_domain == "binary_sensor" else "home"
        self.state_false = (
            "off" if self.user_device_domain == "binary_sensor" else "not_home"
        )
        self.topic_level = len(self.presence_topic.split("/"))
        self.timeout = self.args.get("not_home_timeout", 30)
        self.minimum_conf = self.args.get("minimum_confidence", 90)
        self.depart_check_time = self.args.get("depart_check_time", 30)
        self.system_timeout = self.args.get("system_timeout", 60)
        system_check = self.args.get("system_check", 30)

        self.all_users_sensors = []
        self.not_home_timers = dict()
        self.location_timers = dict()
        self.home_state_entities = dict()
        self.system_handle = dict()

        # Create a sensor to keep track of if the monitor is busy or not.
        self.monitor_entity = f"{self.presence_topic}.monitor_state"
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
        for gateway_sensor in self.args.get("home_gateway_sensors", []):
            self.hass.listen_state(self.gateway_opened, gateway_sensor)

        # Setup home motion sensors, used for RSSI tracking
        for motion_sensor in self.args.get("home_motion_sensors", []):
            self.hass.listen_state(self.motion_detected, motion_sensor)

        # Uncomment to restart the monitor systems every night at midnight
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
            self.presence_message, "MQTT_MESSAGE", wildcard=f"{self.presence_topic}/#"
        )

        # Listen for any HASS restarts
        self.hass.listen_event(self.hass_restarted, "plugin_restarted")

        # Load the devices from the config.
        self.adbase.run_in(self.reload_device_state, 5)
        self.adbase.run_in(self.load_known_devices, 0)

    def setup_global_sensors(self):
        """Add all global home/not_home sensors."""
        self.everyone_not_home = "binary_sensor.{}".format(
            self.args.get("everyone_not_home", "everyone_not_home")
        )
        self.everyone_home = "binary_sensor.{}".format(
            self.args.get("everyone_home", "everyone_home")
        )
        self.somebody_is_home = "binary_sensor.{}".format(
            self.args.get("somebody_is_home", "somebody_is_home")
        )

        self.create_global_sensor(self.everyone_not_home)
        self.create_global_sensor(self.everyone_home)
        self.create_global_sensor(self.somebody_is_home)

    def create_global_sensor(self, sensor):
        """Create a global sensor in HASS if it does not exist."""
        if self.hass.entity_exists(sensor):
            return

        self.adbase.log("Creating Binary Sensor for Everyone Home State")
        attributes = {
            "friendly_name": sensor.replace("_", " ").title(),
            "device_class": "presence",
        }
        self.hass.set_state(sensor, state="off", attributes=attributes)

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

        device_name = topic_path[self.topic_level + 1]
        device_local = f"{device_name}_{location}"
        appdaemon_entity = f"{self.presence_topic}.{device_local}"

        # RSSI Value for a Known Device:
        if action == "rssi":
            attributes = {"rssi": payload, "last_reported_by": location}
            self.adbase.log(
                f"Recieved an RSSI of {payload} for {device_name} from {location_friendly}",
                level="INFO",
            )
            self.mqtt.set_state(appdaemon_entity, attributes=attributes)
            # TODO: Set a sensor within HASS for the RSSI value.
            return

        if not payload_json or payload_json.get("type") not in [
            "KNOWN_MAC",
            "GENERIC_BEACON",
        ]:
            return

        friendly_name = payload_json.get("name", device_name).strip().title()
        payload_json["friendly_name"] = f"{friendly_name} {location_friendly}"

        if "name" in payload_json:
            del payload_json["name"]

        confidence = int(float(payload_json["confidence"]))
        del payload_json["confidence"]

        conf_sensor = f"sensor.{device_local}"
        device_state = f"{device_name}_home"
        user_device_sensor = f"{self.user_device_domain}.{device_state}"
        state = self.state_true if confidence >= self.minimum_conf else self.state_false

        if not self.hass.entity_exists(conf_sensor):
            # Entity does not exist in HASS yet.
            self.adbase.log("Creating sensor {!r} for Confidence".format(conf_sensor))
            self.hass.set_state(
                conf_sensor,
                state="unknown",
                attributes={
                    "friendly_name": f"{friendly_name} {location_friendly} Confidence"
                },
            )

        if not self.hass.entity_exists(user_device_sensor):
            # Device Home Presence Sensor Doesn't Exist Yet
            self.adbase.log(
                "Creating sensor {!r} for Home State".format(user_device_sensor),
                level="DEBUG",
            )
            self.hass.set_state(
                user_device_sensor,
                state=state,
                attributes={
                    "friendly_name": f"{friendly_name} Home",
                    "device_class": "presence",
                },
            )

        if device_state not in self.home_state_entities:
            self.home_state_entities[device_state] = list()

        if conf_sensor not in self.home_state_entities[device_state]:
            self.home_state_entities[device_state].append(conf_sensor)
            self.hass.listen_state(
                self.confidence_updated,
                conf_sensor,
                device_state=device_state,
                immediate=True,
            )

        self.update_hass_sensor(conf_sensor, confidence)

        payload_json["location"] = location
        self.mqtt.set_state(appdaemon_entity, state=confidence, attributes=payload_json)

        if user_device_sensor not in self.all_users_sensors:
            self.all_users_sensors.append(user_device_sensor)

        if device_state not in self.not_home_timers:
            self.not_home_timers[device_state] = None

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

        entity_id = f"{self.presence_topic}.{location}"
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
        entity_id = f"{self.presence_topic}.{location}"
        if location in self.location_timers:
            self.adbase.cancel_timer(self.location_timers[location])

        self.location_timers[location] = self.adbase.run_in(
            self.clear_location_entities, self.system_timeout, location=location
        )
        if self.mqtt.get_state(entity_id, copy=False) == "offline":
            self.mqtt.set_state(entity_id, state="online")

    def confidence_updated(self, entity, attribute, old, new, kwargs):
        """Respond to a monitor providing a new confidence value."""
        device_state = kwargs["device_state"]
        user_device_sensor = f"{self.user_device_domain}.{device_state}"
        uds_state = self.hass.get_state(user_device_sensor, copy=False)
        user_conf_sensors = self.home_state_entities.get(device_state)

        if user_conf_sensors is None:
            self.adbase.log(
                f"Got Confidence Value for {device_state} but device"
                " is not set up (no sensors found).",
                level="WARNING",
            )
            return

        sensor_res = list(
            map(lambda x: self.hass.get_state(x, copy=False), user_conf_sensors)
        )
        sensor_res = [i for i in sensor_res if i is not None and i != "unknown"]

        if sensor_res != [] and any(
            list(map(lambda x: int(x) >= self.minimum_conf, sensor_res))
        ):
            # Cancel the running timer.
            if self.not_home_timers[device_state] is not None:
                self.adbase.cancel_timer(self.not_home_timers[device_state])
                self.not_home_timers[device_state] = None

            self.update_hass_sensor(user_device_sensor, self.state_true)
            self.update_hass_sensor(self.somebody_is_home, "on")

            if user_device_sensor in self.all_users_sensors:
                self.update_hass_sensor(self.everyone_not_home, "off")
                self.adbase.run_in(self.check_home_state, 2, check_state="is_home")
            return

        self.adbase.log(
            "Device State: {}, User Device Sensor: {}, New: {}, State: {}".format(
                device_state, user_device_sensor, new, uds_state
            ),
            level="DEBUG",
        )

        if (
            self.not_home_timers[device_state] is None
            and uds_state not in ["off", "not_home"]
            and int(new) == 0
        ):

            # Run another scan before declaring the user away as extra
            # check within the timeout time
            self.run_arrive_scan()

            self.not_home_timers[device_state] = self.adbase.run_in(
                self.not_home_func, self.timeout, device_state=device_state
            )
            self.adbase.log(f"Timer Started for {device_state}", level="DEBUG")

    def not_home_func(self, kwargs):
        """Manage devices that are not home."""
        device_state = kwargs.get("device_state")
        user_device_sensor = f"{self.user_device_domain}.{device_state}"
        user_conf_sensors = self.home_state_entities[device_state]
        sensor_res = list(
            map(lambda x: self.hass.get_state(x, copy=False), user_conf_sensors)
        )

        # Remove unknown vales from list
        sensor_res = [i for i in sensor_res if i is not None and i != "unknown"]

        self.adbase.log(
            f"Device State: {device_state}, Sensors: {sensor_res}", level="DEBUG"
        )

        if all(list(map(lambda x: int(x) < self.minimum_conf, sensor_res))):
            # Confirm for the last time
            self.update_hass_sensor(user_device_sensor, self.state_false)

            if user_device_sensor in self.all_users_sensors:
                # At least someone not home, set Everyone Home to off
                self.update_hass_sensor(self.everyone_home, "off")

                self.adbase.run_in(self.check_home_state, 2, check_state="not_home")

        self.not_home_timers[device_state] = None

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
                    self.run_depart_scan(count=count)
                return
            # Scanner busy, re-run timer for it to get idle before
            # sending the message to start scan
            self.run_depart_scan(delay=10, count=count)
            return

        # Perform Arrival Scan
        if kwargs["scan_type"] in "Arrive":
            self.mqtt.mqtt_publish(topic, payload)
            return

        # System Command, Send the raw payload
        if kwargs["scan_type"] == "System":
            self.mqtt.mqtt_publish(topic, payload)
            return

    def update_hass_sensor(self, sensor, new_state, new_attr=None):
        """Update the hass sensor if it has changed."""
        self.adbase.log(
            f"__function__: Entity_ID: {sensor}, new_state: {new_state}", level="DEBUG"
        )
        sensor_state = self.hass.get_state(sensor, attribute="all")
        state = sensor_state.get("state")
        attributes = sensor_state.get("attributes", {})
        update_needed = state != new_state

        if isinstance(new_attr, dict):
            attributes.update(new_attr)
            update_needed = True

        if update_needed:
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
            self.run_arrive_scan()

        elif self.hass.get_state(self.everyone_home, copy=False) == "on":
            # everyone at home
            self.run_depart_scan()
        else:
            self.run_arrive_scan()
            self.run_depart_scan()

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

        if check_state == "is_home" and all(list(map(lambda x: x == "on", user_res))):
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

    def run_arrive_scan(self, **kwargs):
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

    def run_depart_scan(self, **kwargs):
        """Request a departure scan.

        Will wait for the scanner to be free and then sends the message.
        """
        delay = kwargs.get("delay", self.depart_check_time)
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
        self.mqtt.mqtt_publish(topic, payload)

    def clear_location_entities(self, kwargs):
        """Clear sensors from an offline location.

        This is used to retrieve the different sensors based on system
        location, and set them to 0. This will ensure that if a location goes
        down and the confidence is not 0, it doesn't stay that way,
        and therefore lead to false info.
        """
        location = kwargs.get("location")
        self.adbase.log("Processing System Unavailable for " + location)
        for _, entity_list in self.home_state_entities.items():
            for sensor in entity_list:
                if location in sensor:  # that sensor belongs to that location
                    self.update_hass_sensor(sensor, 0)
                    device_local = sensor.replace("sensor.", "")
                    appdaemon_entity = f"{self.presence_topic}.{device_local}"
                    self.mqtt.set_state(appdaemon_entity, state=0, rssi="-99")

        if location in self.location_timers:
            self.location_timers.pop(location)

        entity_id = f"{self.presence_topic}.{location}"
        self.mqtt.set_state(entity_id, state="Offline")

    def system_state_changed(self, entity, attribute, old, new, kwargs):
        """Respond to a change in the system state."""
        self.adbase.run_in(self.reload_device_state, 0)

    def monitor_scan_now(self, entity, attribute, old, new, kwargs):
        """Request an immediate scan from the monitors."""
        scan_type = self.mqtt.get_state(entity, attribute="scan_type", copy=False)
        locations = self.mqtt.get_state(entity, attribute="locations", copy=False)

        if scan_type == "both":
            self.run_arrive_scan(location=locations)
            self.run_depart_scan(location=locations)

        elif scan_type == "arrival":
            self.run_arrive_scan(location=locations)

        elif scan_type == "depart":
            self.run_depart_scan(location=locations)

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

    def remove_known_device(self, **kwargs):
        """Request all known devices in config to be deleted from monitors."""
        self.adbase.run_in(
            self.send_mqtt_message,
            0,
            topic=f"{self.presence_topic}/setup/DELETE STATIC DEVICE",
            payload=kwargs["device"],
            scan_type="System",
        )

    def hass_restarted(self, event_name, data, kwargs):
        """Respond to a HASS Restart."""
        self.setup_global_sensors()
        self.adbase.run_in(self.reload_device_state, 10)
