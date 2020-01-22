import adbase as ad
import json
import datetime


class HomePresenceApp(ad.ADBase):
 
    def initialize(self):
        self.adbase = self.get_ad_api()
        self.hass = self.get_plugin_api("HASS") #get hass api
        self.mqtt = self.get_plugin_api("MQTT") #get mqtt api

        self.presence_topic = self.args.get("monitor_topic", "presence")
        self.timeout = self.args.get("not_home_timeout", 30) #time interval before declaring not home
        self.minimum_conf = self.args.get("minimum_confidence", 90)
        self.depart_check_time = self.args.get("depart_check_time", 30)
        self.system_timeout = self.args.get("system_timeout", 60) #time interval for system to report back from echo
        system_check = self.args.get("system_check", 30) #time in seconds app queries for system online
        self.all_users_sensors = [] #used to determine if anyone at home or not
        self.not_home_timers = {}
        self.location_timers = {}
        self.home_state_entities = {} #used to store or map different confidence sensors based on location to devices
        self.system_handle = {}

        self.monitor_entity = "{}.monitor_state".format(self.presence_topic) #used to check if the network monitor is busy 
        if not self.mqtt.entity_exists(self.monitor_entity):
            self.mqtt.set_state(self.monitor_entity, state = "idle", attributes = {"locations": []}, replace = True) #set it to idle initially
        
        self.mqtt.listen_state(self.monitor_scan_now, self.monitor_entity, new = "scan")

        self.monitor_handlers = {} #used to store different handlers
        self.monitor_handlers[self.monitor_entity] = None

        self.everyone_not_home = "binary_sensor.everyone_not_home"
        self.everyone_home = "binary_sensor.everyone_home"
        self.somebody_is_home = "binary_sensor.somebody_is_home"

        self.setup_global_sensors() #setup the gbove sensors

        self.gateway_timer = None #run only a single timer at a time, to avoid sending multiple messages to the monitor
        self.motion_timer = None #run only a single timer at a time, to avoid sending multiple messages to the monitor

        """setup home gateway sensors"""
        for gateway_sensor in self.args.get("home_gateway_sensors", []):
            """it is assumed when the sensor is "on" it is opened and "off" is closed"""
            self.hass.listen_state(self.gateway_opened, gateway_sensor) #when the door is either opened or closed

        """setup home motion sensors, used for RSSI"""
        for motion_sensor in self.args.get("home_motion_sensors", []):
            """it is assumed when the sensor is "on" motion detected and "off" motion not detected after timeout"""
            self.hass.listen_state(self.motion_detected, motion_sensor) #if any motion is detected

        time = "00:00:01"
        self.adbase.run_daily(self.restart_device, time, constrain_days="sun,mon,tue,wed,thu,fri,sat") #restart device at midnight on sunday

        if self.system_timeout > system_check:
            time = datetime.datetime.now() + datetime.timedelta(seconds = 1)
            topic = "{}/echo".format(self.presence_topic)
            self.adbase.run_every(self.send_mqtt_message, time, system_check, topic=topic, payload="", scan_type="System")
        
        else:
            self.adbase.log("Cannot setup System Check due to System Timeout being Lower than System Check in Seconds", level = "WARNING")

        self.mqtt.listen_event(self.presence_message, "MQTT", wildcard = "{}/#".format(self.presence_topic))
        self.hass.listen_event(self.hass_restarted, "plugin_restarted")
        self.adbase.run_in(self.reload_device_state, 5) #reload systems
        self.adbase.run_in(self.load_known_devices, 0) #load up devices for all locations
        self.adbase.run_in(self.setup_service, 0) #setup service
        
    def presence_message(self, event_name, data, kwargs):
        topic = data["topic"]
        payload = data["payload"]
        self.adbase.log("{} payload: {}".format(topic, payload), level = "DEBUG")

        if topic.split("/")[-1] == "status": #meaning its a message on the presence system
            location = topic.split("/")[1].replace("_"," ").title()
            siteId = location.lower().replace(" ", "_")

            self.adbase.log("The Presence System in the {} is {}".format(location, payload.title()), level = "DEBUG")

            if payload.title() == "Offline": #run timer so to clear all entities for that location
                if location in self.location_timers:
                    self.adbase.cancel_timer(self.location_timers[location])

                self.location_timers[location] = self.adbase.run_in(self.clear_location_entities, self.system_timeout, location = location)
            
            elif payload.title() == "Online" and location in self.location_timers:
                self.adbase.cancel_timer(self.location_timers[location])
            
            entity_id = "{}.{}".format(self.presence_topic, siteId)
            attributes = {}

            if not self.mqtt.entity_exists(entity_id): 
                attributes.update({"friendly_name" : location})
                self.adbase.run_in(self.load_known_devices, 30) #load up devices for all locations

            self.mqtt.set_state(entity_id, state = payload.title(), attributes = attributes)

            if self.system_handle.get(entity_id, None) == None:
                self.system_handle[entity_id] = self.mqtt.listen_state(self.system_state_changed, entity_id, old = "Offline", new = "Online")

            return
        
        elif topic.split("/")[-1] == "restart": #meaning its a message is a restart
            self.adbase.log("The Presence System is Restarting") 
            return

        elif topic.split("/")[-1].lower() in ["depart", "arrive", "known device states", "add static device", "delete static device"]: #meaning its something we not interested in
            return
        
        try:
            if topic.split("/")[-1] == "rssi": #meaning its for rssi
                attributes = {"rssi" : payload}
            else:
                payload = json.loads(payload)
        except:

            return

        if topic.split("/")[-1] == "start": #meaning a scan is starting
            location = payload["identity"]
            #self.adbase.log("The system in the {} is scanning".format(location))
            if self.mqtt.get_state(self.monitor_entity, copy=False) != "scanning":
                """since its idle, just set it to scanning and put in the location of the scan"""
                self.mqtt.set_state(self.monitor_entity, state = "scanning", attributes = {"scan_type" : topic.split("/")[2], "locations": [location], location : "scanning"}) 
            else: #meaning it was already set to "scanning" already, so just update the location
                locations_attr = self.mqtt.get_state(self.monitor_entity, attribute = "locations")
                if location not in locations_attr: #meaning it hadn't started the scan before
                    locations_attr.append(location)
                    self.mqtt.set_state(self.monitor_entity, attributes = {"locations": locations_attr, location : "scanning"}) #update the location in the event of different scan systems in place
            
            return
                
        elif topic.split("/")[-1] == "end": #meaning a scan in a location just ended
            location = payload["identity"]
            locations_attr = self.mqtt.get_state(self.monitor_entity, attribute = "locations")
            if location in locations_attr: #meaning it had started the scan before
                locations_attr.remove(location)
            
                if locations_attr == []: #meaning no more locations scanning
                    self.mqtt.set_state(self.monitor_entity, state = "idle", attributes = {"scan_type" : topic.split("/")[2], "locations": [], location : "idle"}) #set the monitor state to idle 
                else:
                    self.mqtt.set_state(self.monitor_entity, attributes = {"locations": locations_attr, location : "idle"}) #update the location in the event of different scan systems in place
            return

        elif topic.split("/")[-1] == "echo": #meaning it is for echo check
            self.adbase.log(payload, level = "DEBUG")

            if payload == "ok":
                location = topic.split("/")[1]
                siteId = location.replace(" ", "_").lower()
                entity_id = "{}.{}".format(self.presence_topic, siteId)
                if location in self.location_timers:
                    self.adbase.cancel_timer(self.location_timers[location])

                self.location_timers[location] = self.adbase.run_in(self.clear_location_entities, self.system_timeout, location = location)

                if self.mqtt.get_state(entity_id, copy=False) == "Offline":
                    self.mqtt.set_state(entity_id, state = "Online")
            return

        location = topic.split("/")[1].replace("_"," ").title()
        siteId = location.replace(" ", "_").lower()
        device_name = topic.split("/")[2]
        device_local = "{}_{}".format(device_name, siteId)
        appdaemon_entity = "{}.{}".format(self.presence_topic, device_local)

        if topic.split("/")[-1] == "rssi": #meaning its for rssi

            if topic.split("/")[-2] != "scan": #meaning its not for rssi scan
                self.mqtt.set_state(appdaemon_entity, attributes = attributes)
        
        elif isinstance(payload, dict) and payload.get("type", None) in ["KNOWN_MAC", "GENERIC_BEACON"]:
            friendly_name = payload.get("name", None)

            if friendly_name != None:
                del payload["name"]
                payload["friendly_name"] = "{} {}".format(friendly_name, location)

            confidence = int(float(payload["confidence"]))
            del payload["confidence"]

            conf_sensor = "sensor.{}".format(device_local)
            device_state = "{}_home".format(device_name)
            user_device_sensor = "binary_sensor.{}".format(device_state)

            if confidence >= self.minimum_conf:
                state = "on"
            else:
                state = "off"

            if not self.hass.entity_exists(conf_sensor): #meaning it doesn't exist
                self.adbase.log("Creating sensor {!r} for Confidence".format(conf_sensor))
                self.hass.set_state(conf_sensor, state = confidence, attributes = {"friendly_name" : "{} {} Confidence".format(friendly_name, location)}) #create sensor for confidence

                """create user home state sensor"""
                if not self.hass.entity_exists(user_device_sensor): #meaning it doesn't exist.
                    self.adbase.log("Creating sensor {!r} for Home State".format(user_device_sensor))

                    self.hass.set_state(user_device_sensor, state = state, attributes = {"friendly_name" : "{} Home".format(friendly_name), "device_class" : "presence"}) #create device sensor

                    if state == "on" and self.hass.get_state(self.somebody_is_home, copy=False) == "off": #at least someone is home
                        self.update_hass_sensor(self.somebody_is_home, "on")

                self.hass.listen_state(self.confidence_updated, conf_sensor, device_state = device_state, immediate = True) #process the change immedaitely

                if device_state not in self.home_state_entities:
                    self.home_state_entities[device_state] = list()

                if conf_sensor not in self.home_state_entities[device_state]: #not really needed, but noting wrong in being extra careful
                    self.home_state_entities[device_state].append(conf_sensor)

            else:
                if device_state not in self.home_state_entities:
                    self.home_state_entities[device_state] = list()

                if conf_sensor not in self.home_state_entities[device_state]:
                    self.home_state_entities[device_state].append(conf_sensor)
                    self.hass.listen_state(self.confidence_updated, conf_sensor, device_state = device_state, immediate = True)
                     
                self.update_hass_sensor(conf_sensor, confidence)

            #add location to payload, so its available in the AD entity's data
            payload["location"] = location #good when writing app to triagulate location
            self.mqtt.set_state(appdaemon_entity, state = confidence, attributes = payload)

            if user_device_sensor not in self.all_users_sensors:
                self.all_users_sensors.append(user_device_sensor)

            if device_state not in self.not_home_timers:
                self.not_home_timers[device_state] = None

    def confidence_updated(self, entity, attribute, old, new, kwargs):
        device_state = kwargs["device_state"]
        user_device_sensor = "binary_sensor." + device_state
        user_conf_sensors = self.home_state_entities.get(device_state, None)
    
        if user_conf_sensors != None:
            sensor_res = list(map(lambda x: self.hass.get_state(x, copy=False), user_conf_sensors))
            sensor_res = [i for i in sensor_res if i != "unknown"] # remove unknown vales from list
            sensor_res = [i for i in sensor_res if i != None] # remove None values from list
            if  sensor_res != [] and any(list(map(lambda x: int(x) >= self.minimum_conf, sensor_res))): #meaning at least one of them states is greater than the minimum so device definitely home
                if self.not_home_timers[device_state] != None: #cancel timer if running
                    self.adbase.cancel_timer(self.not_home_timers[device_state])
                    self.not_home_timers[device_state] = None

                self.update_hass_sensor(user_device_sensor, "on")

                if self.hass.get_state(self.somebody_is_home, copy=False) == "off":
                    self.update_hass_sensor(self.somebody_is_home, "on") #somebody is home

                if user_device_sensor in self.all_users_sensors: #check if everyone home
                    if self.hass.get_state(self.everyone_not_home, copy=False) == "on":
                        self.update_hass_sensor(self.everyone_not_home, "off")
                    
                    self.adbase.run_in(self.check_home_state, 2, check_state = "is_home")

            else:
                self.adbase.log("Device State: {}, User Device Sensor: {}, New: {}, State: {}".format(device_state, user_device_sensor, new, self.hass.get_state(user_device_sensor, copy=False)), level = "DEBUG")
                if self.not_home_timers[device_state] == None and self.hass.get_state(user_device_sensor, copy=False) != "off" and int(new) == 0: #run the timer
                    self.run_arrive_scan() #run so it does another scan before declaring the user away as extra check within the timeout time
                    self.not_home_timers[device_state] = self.adbase.run_in(self.not_home_func, self.timeout, device_state = device_state)
                    self.adbase.log("Timer Started for {}".format(device_state), level = "DEBUG")

    def not_home_func(self, kwargs):
        device_state = kwargs["device_state"]
        user_device_sensor = "binary_sensor." + device_state
        user_conf_sensors = self.home_state_entities[device_state]
        sensor_res = list(map(lambda x: self.hass.get_state(x, copy=False), user_conf_sensors))
        sensor_res = [i for i in sensor_res if i != "unknown"] # remove unknown vales from list
        self.adbase.log("Device State: {}, Sensors: {}".format(device_state, sensor_res), level = "DEBUG")

        if  all(list(map(lambda x: int(x) < self.minimum_conf, sensor_res))): #still confirm for the last time
            self.update_hass_sensor(user_device_sensor, "off")

            if user_device_sensor in self.all_users_sensors: #check if everyone not home
                """since at least someone not home, set to off the everyone home state"""
                self.update_hass_sensor(self.everyone_home, "off")

                self.adbase.run_in(self.check_home_state, 2, check_state = "not_home")

        self.not_home_timers[device_state] = None

    def send_mqtt_message(self, kwargs):
        topic = kwargs["topic"]
        payload = kwargs["payload"]
        if kwargs["scan_type"] == "Depart":
            count = kwargs["count"]
            self.gateway_timer = None #meaning no more gateway based timer is running

            if self.mqtt.get_state(self.monitor_entity) == "idle": #meaning its not busy
                self.mqtt.mqtt_publish(topic, payload) #send to scan for departure of anyone
                if count <= self.args.get("depart_scans", 3): #scan for departure times. 3 as default
                    count = count + 1
                    self.run_depart_scan(count = count)

            else: #meaning it is busy so re-run timer for it to get idle before sending the message to start scan
                self.run_depart_scan(delay = 10, count = count)

        elif kwargs["scan_type"] == "Arrive":
            self.mqtt.mqtt_publish(topic, payload) #send to scan for arrival of anyone

        elif kwargs["scan_type"] == "System":
            self.mqtt.mqtt_publish(topic, payload) #just send the data

    def update_hass_sensor(self, sensor, data):
        self.adbase.log("__function__: Entity_ID: {}, Data: {}".format(sensor, data), level = "DEBUG")
        sensorState = self.hass.get_state(sensor, attribute = "all")
        state = sensorState["state"]
        attributes = sensorState["attributes"]

        if state != data:
            state = data
            self.hass.set_state(sensor, state = state, attributes = attributes)

    def gateway_opened(self, entity, attribute, old, new, kwargs):
        """one of the gateways was opened or closed and so needs to check what happened"""
        self.adbase.log("Gateway Sensor {} now {}".format(entity, new), level="DEBUG")

        if self.gateway_timer != None: #meaning a timer is running already
            self.adbase.cancel_timer(self.gateway_timer)
            self.gateway_timer = None

        if self.hass.get_state(self.everyone_not_home, copy=False) == "on": #meaning no one at home
            self.run_arrive_scan()

        elif self.hass.get_state(self.everyone_home, copy=False) == "on": #meaning everyone at home
            self.run_depart_scan()
            #self.run_depart_scan(delay = 90)

        else:
            self.run_arrive_scan()
            self.run_depart_scan()
            #self.run_depart_scan(delay = 90)

    def motion_detected(self, entity, attribute, old, new, kwargs):
        """motion detected somewhere in the house, so needs to check for where users are"""
        self.adbase.log("Motion Sensor {} now {}".format(entity, new), level="DEBUG")

        if self.motion_timer != None: #meaning a timer is running already
            self.adbase.cancel_timer(self.motion_timer)
            self.motion_timer = None

        """ "duraction" parameter could be used in listen_state. 
            But need to use a single timer for all motion sensors, 
            to avoid running the scan too many times"""
        self.motion_timer = self.adbase.run_in(self.run_rssi_scan, self.args.get("rssi_timeout", 60))

    def check_home_state(self, kwargs):
        check_state = kwargs["check_state"]
        if check_state == "is_home":
            """ now run to check if everyone is home since a user is home"""
            user_res = list(map(lambda x: self.hass.get_state(x, copy=False), self.all_users_sensors))
            user_res = [i for i in user_res if i != "unknown"] # remove unknown vales from list
            user_res = [i for i in user_res if i != None] # remove None vales from list

            if all(list(map(lambda x: x == "on", user_res))): #meaning every one is home
                self.update_hass_sensor(self.everyone_home, "on")
            
            elif any(list(map(lambda x: x == "on", user_res))): #meaning at least someone is home
                if self.hass.get_state(self.somebody_is_home, copy=False) == "off":
                    self.update_hass_sensor(self.somebody_is_home, "on") #somebody is home
                
        elif check_state == "not_home":
            """ now run to check if everyone is not home since a user is not home"""
            user_res = list(map(lambda x: self.hass.get_state(x, copy=False), self.all_users_sensors))
            user_res = [i for i in user_res if i != "unknown"] # remove unknown vales from list
            user_res = [i for i in user_res if i != None] # remove None vales from list

            if all(list(map(lambda x: x == "off", user_res))): #meaning no one is home
                self.update_hass_sensor(self.everyone_not_home, "on")

                if self.hass.get_state(self.somebody_is_home, copy=False) == "on":
                    self.update_hass_sensor(self.somebody_is_home, "off") #somebody is home
            else:
                if self.hass.get_state(self.somebody_is_home, copy=False) == "off":
                    self.update_hass_sensor(self.somebody_is_home, "on") #somebody is home
    
    def reload_device_state(self, kwargs):
        topic = "{}/KNOWN DEVICE STATES".format(self.presence_topic) #get latest states
        self.adbase.run_in(self.send_mqtt_message, 0, topic=topic, payload="", scan_type="System")

    def monitor_changed_state(self, entity, attribute, old, new, kwargs):
        scan = kwargs["scan"]
        topic = kwargs["topic"]
        payload = kwargs["payload"]
        self.adbase.run_in(self.send_mqtt_message, 1, topic = topic, payload = payload, scan_type = "Arrive") #send to scan for arrival of anyone
        self.adbase.cancel_listen_state(self.monitor_handlers[scan])
        self.monitor_handlers[scan] = None

    def run_arrive_scan(self, **kwargs):
        topic = "{}/scan/arrive".format(self.presence_topic)
        payload = ""

        """used to listen for when the monitor is free, and then send the message"""
        if self.mqtt.get_state(self.monitor_entity, copy=False) == "idle": #meaning its not busy
            self.mqtt.mqtt_publish(topic, payload) #send to scan for arrival of anyone
        else:
            """meaning it is busy so wait for it to get idle before sending the message"""
            scan_type = self.mqtt.get_state(self.monitor_entity, attribute="scan_type", copy=False)
            if self.monitor_handlers.get("Arrive Scan", None) == None and scan_type != "arrival": #meaning its not listening already, and arrival not running now
                self.monitor_handlers["Arrive Scan"] = self.mqtt.listen_state(self.monitor_changed_state, self.monitor_entity, 
                            new = "idle", old = "scanning", scan = "Arrive Scan", topic = topic, payload = payload)

    def run_depart_scan(self, **kwargs):
        delay = kwargs.get("delay", self.depart_check_time)
        count = kwargs.get("count", 1)

        topic ="{}/scan/depart".format(self.presence_topic)
        payload = ""

        if self.gateway_timer != None: #meaning a timer running aleady
            self.adbase.cancel_timer(self.gateway_timer) #just extra check, shouldn't be needed

        self.gateway_timer = self.adbase.run_in(self.send_mqtt_message, delay, topic = topic, 
                        payload = payload, scan_type = "Depart", count = count) #send to scan for departure of anyone

    def run_rssi_scan(self, kwargs):
        topic = "{}/scan/rssi".format(self.presence_topic)
        self.adbase.run_in(self.send_mqtt_message, 0, topic=topic, payload="", scan_type="System")
        self.motion_timer = None

    def restart_device(self, kwargs):
        topic = "{}/scan/restart".format(self.presence_topic)
        payload = ""
        self.mqtt.mqtt_publish(topic, payload) #instruct to restart service

    def clear_location_entities(self, kwargs): 
        """used to retrieve the different sensors based on system location, and set them to 0
            this will ensure that if a location goes down and the confidence is set to 100, it doesn"t
            stay that way, and therefore lead to false info""" 
        location = kwargs["location"]
        self.adbase.log("Processing System Unavailable for "+ location)
        siteId = location.replace(" ", "_").lower()
        for device_state, entity_list in self.home_state_entities.items():
            for sensor in entity_list: 
                if siteId in sensor: #meaning that sensor belongs to that location
                    self.update_hass_sensor(sensor, 0)
                    device_local = sensor.replace("sensor.", "")
                    appdaemon_entity = "{}.{}".format(self.presence_topic, device_local)
                    self.mqtt.set_state(appdaemon_entity, state = 0, rssi = "-99")

        if location in self.location_timers:
            self.location_timers.pop(location)

        entity_id = "{}.{}".format(self.presence_topic, siteId)
        self.mqtt.set_state(entity_id, state = "Offline")

        self.run_arrive_scan()

    def system_state_changed(self, entity, attribute, old, new, kwargs):
        self.adbase.run_in(self.reload_device_state, 0)
    
    def monitor_scan_now(self, entity, attribute, old, new, kwargs):
        scan_type = self.mqtt.get_state(entity, attribute="scan_type", copy=False)
        locations = self.mqtt.get_state(entity, attribute="locations", copy=False)

        if scan_type == "both":
            self.run_arrive_scan(location=locations)
            self.run_depart_scan(location=locations)
        
        elif scan_type == "arrival":
            self.run_arrive_scan(location=locations)
        
        elif scan_type == "depart":
            self.run_depart_scan(location=locations)

        self.mqtt.set_state(entity, state = "idle")

    def load_known_devices(self, kwargs):
        topic = "{}/setup/ADD STATIC DEVICE".format(self.presence_topic)
        timer = 0
        for device in self.args["known_devices"]:
            payload = device
            self.adbase.run_in(self.send_mqtt_message, timer, topic=topic, payload=payload, scan_type="System")
            timer += 15

    def remove_known_device(self, kwargs):
        device = kwargs["device"]
        topic = "{}/setup/DELETE STATIC DEVICE".format(self.presence_topic)
        self.adbase.run_in(self.send_mqtt_message, 0, topic=topic, payload=device, scan_type="System")

        # now remove the device from AD
        for entity in self.mqtt.get_state(f"{self.presence_topic}", copy=False):
            if device == self.mqtt.get_state(entity, attribute="id", copy=False):
                self.mqtt.remove_entity(entity)

    def hass_restarted(self, event, data, kwargs):
        self.setup_global_sensors()
        self.adbase.run_in(self.reload_device_state, 10)

    def setup_global_sensors(self):
        if not self.hass.entity_exists(self.everyone_not_home): #check if the sensor exist and if not create it
            self.adbase.log("Creating Binary Sensor for Everyone Not Home State")
            attributes = {"friendly_name": "Everyone Not Home", "device_class" : "presence"}
            self.hass.set_state(self.everyone_not_home, state = "off", attributes = attributes) #send to homeassistant to create binary sensor sensor for home state

        if not self.hass.entity_exists(self.everyone_home): #check if the sensor exist and if not create it
            self.adbase.log("Creating Binary Sensor for Everyone Home State")
            attributes = {"friendly_name": "Everyone Home", "device_class" : "presence"}
            self.hass.set_state(self.everyone_home, state = "off", attributes = attributes) #send to homeassistant to create binary sensor sensor for home state

        if not self.hass.entity_exists(self.somebody_is_home): #check if the sensor exist and if not create it
            self.adbase.log("Creating Binary Sensor for Somebody is Home")
            attributes = {"friendly_name": "Somebody is Home State", "device_class" : "presence"}
            self.hass.set_state(self.somebody_is_home, state = "off", attributes = attributes) #send to homeassistant to create binary sensor sensor for home state
    
    def setup_service(self, kwargs): # rgister services
        self.mqtt.register_service(f"{self.presence_topic}/remove_known_device", self.presense_services)
    
    def presense_services(self, namespace, domain, service, kwargs):
        self.adbase.log(f"presence_services() {namespace} {domain} {service} {kwargs}", level="DEBUG")

        if service == "remove_known_device":
            device = kwargs.get("device")
            if device == None:
                self.adbase.log("Could not process the service as no device provided")
                return

            self.adbase.run_in(self.remove_known_device, 0, device=device)
