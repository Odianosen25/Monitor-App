import mqttapi as mqtt
import json
import shelve
import datetime

class HomePresenceApp(mqtt.Mqtt): 
 
    def initialize(self):
        self.set_namespace("mqtt")
        self.hass = self.get_plugin_api('HASS')
        self.presence_topic = self.args.get('monitor_topic', 'presence')
        self.timeout = self.args.get('not_home_timeout', 30) #time interval before declaring not home
        self.minimum_conf = self.args.get('minimum_confidence', 90)
        self.depart_check_time = self.args.get('depart_check_time', 30)
        self.system_timeout = self.args.get('system_timeout', 60) #time interval for system to report back from echo
        system_check = self.args.get('system_check', 30) #time in seconds app queries for system online
        self.all_users_sensors = [] #used to determine if anyone at home or not
        self.not_home_timers = dict()
        self.location_timers = dict()
        self.home_state_entities = dict() #used to store or map different confidence sensors based on location to devices

        self.monitor_entity = '{}.monitor_state'.format(self.presence_topic) #used to check if the network monitor is busy 
        if not self.entity_exists(self.monitor_entity):
            self.set_state(self.monitor_entity, state = 'idle', attributes = {'locations': []}, replace = True) #set it to idle initially

        self.monitor_handlers = dict() #used to store different handlers
        self.monitor_handlers[self.monitor_entity] = None

        everyone_not_home_state = "binary_sensor.everyone_not_home_state"
        everyone_home_state = "binary_sensor.everyone_home_state"
        self.gateway_timer = None #run only a single timer at a time, to avoid sending multiple messages to the monitor

        if not self.hass.entity_exists(everyone_not_home_state): #check if the sensor exist and if not create it
            self.log('Creating Binary Sensor for Everyone Not Home State')
            attributes = {"friendly_name": "Everyone Not Home State", "device_class" : "presence"}
            self.hass.set_state(everyone_not_home_state, state = "off", attributes = attributes) #send to homeassistant to create binary sensor sensor for home state

        if not self.hass.entity_exists(everyone_home_state): #check if the sensor exist and if not create it
            self.log('Creating Binary Sensor for Everyone Home State')
            attributes = {"friendly_name": "Everyone Home State", "device_class" : "presence"}
            self.hass.set_state(everyone_home_state, state = "off", attributes = attributes) #send to homeassistant to create binary sensor sensor for home state

        '''setup home gateway sensors'''
        for gateway_sensor in self.args['home_gateway_sensors']:
            '''it is assumed when the sensor is "on" it is opened and "off" is closed'''
            self.hass.listen_state(self.gateway_opened, gateway_sensor) #when the door is either opened or closed

        time = datetime.time(0, 0, 1)
        #self.run_daily(self.restart_device, time) #restart device at midnight everyday

        if self.system_timeout > system_check:
            time = datetime.datetime.now() + datetime.timedelta(seconds = 1)
            topic = "{}/echo".format(self.presence_topic)
            self.run_every(self.send_mqtt_message, time, system_check, topic=topic, payload="", scan_type="System")
        
        else:
            self.log("Cannot setup System Check due to System Timeout being Loswer than System Check in Seconds", level = "WARNING")

        self.listen_event(self.presence_message, 'MQTT', wildcard = '{}/#'.format(self.presence_topic))
        self.hass.listen_event(self.reload_device_state, 'plugin_restarted')
        self.reload_device_state(None, None, {})
        
    def presence_message(self, event_name, data, kwargs):
        topic = data['topic']
        payload = data['payload']
        self.log("{} payload: {}".format(topic, payload), level = "DEBUG")

        if topic.split('/')[-1] == 'status': #meaning its a message on the presence system
            location = topic.split('/')[1].replace('_',' ').title()
            siteId = location.lower().replace(" ", "_")

            self.log('The Presence System in the {} is {}'.format(location, payload.title()), level = "DEBUG")

            if payload.title() == 'Offline': #run timer so to clear all entities for that location
                if location in self.location_timers:
                    self.cancel_timer(self.location_timers[location])

                self.location_timers[location] = self.run_in(self.clear_location_entities, self.system_timeout, location = location)
            
            elif payload.title() == 'Online' and location in self.location_timers:
                self.cancel_timer(self.location_timers[location])
            
            entity_id = "{}.{}".format(self.presence_topic, siteId)
            attributes = {}

            if not self.entity_exists(entity_id):
                attributes.update({"friendly_name" : location})

            self.set_state(entity_id, state = payload.title(), attributes = attributes)
            return
        
        elif topic.split('/')[-1] == 'restart': #meaning its a message is a restart
            self.log('The Presence System is Restarting')
            return

        elif topic.split('/')[-1].lower() in ["depart", "arrive", "KNOWN DEVICE STATES"]: #meaning its something we not interested in
            return
        
        try:
            if topic.split('/')[-1] == "rssi": #meaning its for rssi
                attributes = {"rssi" : payload}
            else:
                payload = json.loads(payload)
        except:

            return

        if topic.split('/')[-1] == 'start': #meaning a scan is starting
            location = payload['identity']
            #self.log("The system in the {} is scanning".format(location))
            if self.get_state(self.monitor_entity) != 'scanning':
                '''since its idle, just set it to scanning and put in the location of the scan'''
                self.set_state(self.monitor_entity, state = 'scanning', attributes = {'scan_type' : topic.split('/')[2], 'locations': [location], location : 'scanning'}) 
            else: #meaning it was already set to 'scanning' already, so just update the location
                locations_attr = self.get_state(self.monitor_entity, attribute = 'locations')
                if location not in locations_attr: #meaning it hadn't started the scan before
                    locations_attr.append(location)
                    self.set_state(self.monitor_entity, attributes = {'locations': locations_attr, location : 'scanning'}) #update the location in the event of different scan systems in place
            
            return
                
        elif topic.split('/')[-1] == 'end': #meaning a scan in a location just ended
            location = payload['identity']
            locations_attr = self.get_state(self.monitor_entity, attribute = 'locations')
            if location in locations_attr: #meaning it had started the scan before
                locations_attr.remove(location)
            
                if locations_attr == []: #meaning no more locations scanning
                    self.set_state(self.monitor_entity, state = 'idle', attributes = {'scan_type' : topic.split('/')[2], 'locations': [], location : 'idle'}) #set the monitor state to idle 
                else:
                    self.set_state(self.monitor_entity, attributes = {'locations': locations_attr, location : 'idle'}) #update the location in the event of different scan systems in place
            return

        elif topic.split('/')[-1] == 'echo': #meaning it is for echo check
            self.log(payload, level = "DEBUG")

            if payload == "ok":
                location = topic.split('/')[1]
                siteId = location.replace(' ', '_').lower()
                entity_id = "{}.{}".format(self.presence_topic, siteId)
                if location in self.location_timers:
                    self.cancel_timer(self.location_timers[location])

                self.location_timers[location] = self.run_in(self.clear_location_entities, self.system_timeout, location = location)

                if self.get_state(entity_id) == "Offline":
                    self.set_state(entity_id, state = "Online")
            return

        location = topic.split('/')[1].replace('_',' ').title()
        siteId = location.replace(' ', '_').lower()
        device_name = topic.split('/')[2]
        device_local = '{}_{}'.format(device_name, siteId)
        appdaemon_entity = '{}.{}'.format(self.presence_topic, device_local)

        if topic.split('/')[-1] == 'rssi': #meaningits for rssi
            self.set_state(appdaemon_entity, attributes = attributes)
        
        elif isinstance(payload, dict) and payload.get('type', None) in ['KNOWN_MAC', 'GENERIC_BEACON']:
            friendly_name = payload.get('name', None)

            if friendly_name != None:
                del payload["name"]
                payload["friendly_name"] = "{} {}".format(friendly_name, location)

            confidence = int(float(payload['confidence']))
            del payload['confidence']

            conf_sensor = 'sensor.{}'.format(device_local)
            device_state = '{}_home_state'.format(device_name)
            user_device_sensor = 'binary_sensor.{}'.format(device_state)

            if not self.hass.entity_exists(conf_sensor): #meaning it doesn't exist
                self.log('Creating sensor {!r} for Confidence'.format(conf_sensor))
                self.hass.set_state(conf_sensor, state = confidence, attributes = {"friendly_name" : "{} {} Confidence".format(friendly_name, location)}) #create sensor for confidence

                '''create user home state sensor'''
                if not self.hass.entity_exists(user_device_sensor): #meaning it doesn't exist.
                    self.log('Creating sensor {!r} for Home State'.format(user_device_sensor))

                    if confidence >= self.minimum_conf:
                        state = "on"
                    else:
                        state = "off"

                    self.hass.set_state(user_device_sensor, state = state, attributes = {"friendly_name" : "{} Home State".format(friendly_name), "device_class" : "presence"}) #create sensor for confidence

                self.hass.listen_state(self.confidence_updated, conf_sensor, device_state = device_state)

                if device_state not in self.home_state_entities:
                    self.home_state_entities[device_state] = list()

                if conf_sensor not in self.home_state_entities[device_state]: #not really needed, but noting wrong in being extra careful
                    self.home_state_entities[device_state].append(conf_sensor)

            else:
                if device_state not in self.home_state_entities:
                    self.home_state_entities[device_state] = list()

                if conf_sensor not in self.home_state_entities[device_state]:
                    self.home_state_entities[device_state].append(conf_sensor)
                    self.hass.listen_state(self.confidence_updated, conf_sensor, device_state = device_state)
                     
                self.update_sensor(conf_sensor, confidence)

            self.set_state(appdaemon_entity, state = confidence, attributes = payload)
            if user_device_sensor not in self.all_users_sensors:
                self.all_users_sensors.append(user_device_sensor)

            if device_state not in self.not_home_timers:
                self.not_home_timers[device_state] = None

    def confidence_updated(self, entity, attribute, old, new, kwargs):
        device_state = kwargs['device_state']
        user_device_sensor = 'binary_sensor.' + device_state
        user_conf_sensors = self.home_state_entities.get(device_state, None)
    
        if user_conf_sensors != None:
            sensor_res = list(map(lambda x: self.hass.get_state(x), user_conf_sensors))
            sensor_res = [i for i in sensor_res if i != 'unknown'] # remove unknown vales from list
            sensor_res = [i for i in sensor_res if i != None] # remove None values from list
            if  sensor_res != [] and any(list(map(lambda x: int(x) >= self.minimum_conf, sensor_res))): #meaning at least one of them states is greater than the minimum so device definitely home
                if self.not_home_timers[device_state] != None: #cancel timer if running
                    self.cancel_timer(self.not_home_timers[device_state])
                    self.not_home_timers[device_state] = None

                self.update_sensor(user_device_sensor, "on")

                if user_device_sensor in self.all_users_sensors: #check if everyone home
                    self.update_sensor("binary_sensor.everyone_not_home_state", "off")
                    
                    self.run_in(self.check_home_state, 2, check_state = 'is_home')

            else:
                self.log("Device State: {}, User Device Sensor: {}, New: {}, State: {}".format(device_state, user_device_sensor, new, self.hass.get_state(user_device_sensor)), level = "DEBUG")
                if self.not_home_timers[device_state] == None and self.hass.get_state(user_device_sensor) != 'off' and int(new) == 0: #run the timer
                    self.run_arrive_scan() #run so it does another scan before declaring the user away as extra check within the timeout time
                    self.not_home_timers[device_state] = self.run_in(self.not_home_func, self.timeout, device_state = device_state)
                    self.log("Timer Started for {}".format(device_state), level = "DEBUG")

    def not_home_func(self, kwargs):
        device_state = kwargs['device_state']
        user_device_sensor = 'binary_sensor.' + device_state
        user_conf_sensors = self.home_state_entities[device_state]
        sensor_res = list(map(lambda x: self.hass.get_state(x), user_conf_sensors))
        sensor_res = [i for i in sensor_res if i != 'unknown'] # remove unknown vales from list
        self.log("Device State: {}, Sensors: {}".format(device_state, sensor_res), level = "DEBUG")

        if  all(list(map(lambda x: int(x) < self.minimum_conf, sensor_res))): #still confirm for the last time
            self.update_sensor(user_device_sensor, "off")

            if user_device_sensor in self.all_users_sensors: #check if everyone not home
                '''since at least someone not home, set to off the everyone home state'''
                self.update_sensor("binary_sensor.everyone_home_state", "off")

                self.run_in(self.check_home_state, 2, check_state = 'not_home')

        self.not_home_timers[device_state] = None

    def send_mqtt_message(self, kwargs):
        topic = kwargs['topic']
        payload = kwargs['payload']
        if kwargs['scan_type'] == 'Depart':
            count = kwargs['count']
            self.gateway_timer = None #meaning no more gateway based timer is running

            if self.get_state(self.monitor_entity) == 'idle': #meaning its not busy
                self.mqtt_publish(topic, payload) #send to scan for departure of anyone
                if count <= self.args.get('depart_scans', 3): #scan for departure times. 3 as default
                    count = count + 1
                    self.run_depart_scan(count = count)

            else: #meaning it is busy so re-run timer for it to get idle before sending the message to start scan
                self.run_depart_scan(delay = 10, count = count)

        elif kwargs['scan_type'] == 'Arrive':
            self.mqtt_publish(topic, payload) #send to scan for arrival of anyone

        elif kwargs['scan_type'] == 'System':
            self.mqtt_publish(topic, payload) #just send the data

    def update_sensor(self, sensor, data):
        self.log("__function__: Entity_ID: {}, Data: {}".format(sensor, data), level = "DEBUG")
        sensorState = self.hass.get_state(sensor, attribute = "all")
        state = sensorState["state"]
        attributes = sensorState["attributes"]

        if state != data:
            state = data
            self.hass.set_state(sensor, state = state, attributes = attributes)

    def gateway_opened(self, entity, attribute, old, new, kwargs):
        '''one of the gateways was opened and so needs to check what happened'''
        self.log("Gateway Sensor " + new)
        everyone_not_home_state = 'binary_sensor.everyone_not_home_state'
        everyone_home_state = 'binary_sensor.everyone_home_state'

        if self.gateway_timer != None: #meaning a timer is running already
            self.cancel_timer(self.gateway_timer)
            self.gateway_timer = None

        if self.hass.get_state(everyone_not_home_state) == 'on': #meaning no one at home
            self.run_arrive_scan()

        elif self.hass.get_state(everyone_home_state) == 'on': #meaning everyone at home
            self.run_depart_scan()
            #self.run_depart_scan(delay = 90)

        else:
            self.run_arrive_scan()
            self.run_depart_scan()
            #self.run_depart_scan(delay = 90)

    def check_home_state(self, kwargs):
        check_state = kwargs['check_state']
        if check_state == 'is_home':
            ''' now run to check if everyone is home since a user is home'''
            user_res = list(map(lambda x: self.hass.get_state(x), self.all_users_sensors))
            user_res = [i for i in user_res if i != 'unknown'] # remove unknown vales from list
            user_res = [i for i in user_res if i != None] # remove None vales from list

            if all(list(map(lambda x: x == 'on', user_res))): #meaning every one is home
                self.update_sensor("binary_sensor.everyone_home_state", "on")
                
        elif check_state == 'not_home':
            ''' now run to check if everyone is not home since a user is not home'''
            user_res = list(map(lambda x: self.hass.get_state(x), self.all_users_sensors))
            user_res = [i for i in user_res if i != 'unknown'] # remove unknown vales from list
            user_res = [i for i in user_res if i != None] # remove None vales from list

            if all(list(map(lambda x: x == 'off', user_res))): #meaning no one is home
                self.update_sensor("binary_sensor.everyone_not_home_state", "on")
    
    def reload_device_state(self, event_name, data, kwargs):
        topic = "{}/KNOWN DEVICE STATES".format(self.presence_topic) #get latest states
        self.run_in(self.send_mqtt_message, 0, topic=topic, payload="", scan_type="System")

    def monitor_changed_state(self, entity, attribute, old, new, kwargs):
        scan = kwargs['scan']
        topic = kwargs['topic']
        payload = kwargs['payload']
        self.run_in(self.send_mqtt_message, 1, topic = topic, payload = payload, scan_type = 'Arrive') #send to scan for arrival of anyone
        self.cancel_listen_state(self.monitor_handlers[scan])
        self.monitor_handlers[scan] = None

    def run_arrive_scan(self, **kwargs):
        topic = '{}/scan/Arrive'.format(self.presence_topic)
        payload = ''

        '''used to listen for when the monitor is free, and then send the message'''
        if self.get_state(self.monitor_entity) == 'idle': #meaning its not busy
            self.mqtt_publish(topic, payload) #send to scan for arrival of anyone
        else:
            '''meaning it is busy so wait for it to get idle before sending the message'''
            if self.monitor_handlers.get('Arrive Scan', None) == None: #meaning its not listening already
                self.monitor_handlers['Arrive Scan'] = self.listen_state(self.monitor_changed_state, self.monitor_entity, 
                            new = 'idle', old = 'scanning', scan = 'Arrive Scan', topic = topic, payload = payload)
        return

    def run_depart_scan(self, **kwargs):
        delay = kwargs.get('delay', self.depart_check_time)
        count = kwargs.get('count', 1)

        topic ='{}/scan/Depart'.format(self.presence_topic)
        payload = ''

        if self.gateway_timer != None: #meaning a timer running aleady
            self.cancel_timer(self.gateway_timer) #just extra check, shouldn't be needed

        self.gateway_timer = self.run_in(self.send_mqtt_message, delay, topic = topic, 
                        payload = payload, scan_type = 'Depart', count = count) #send to scan for departure of anyone
        return

    def restart_device(self, kwargs):
        topic = '{}/scan/restart'.format(self.presence_topic)
        payload = ''
        self.mqtt_publish(topic, payload) #instruct to restart service

    def clear_location_entities(self, kwargs): 
        '''used to retrieve the different sensors based on system location, and set them to 0
            this will ensure that if a location goes down and the confidence is set to 100, it doesn't
            stay that way, and therefore lead to false info''' 
        location = kwargs['location']
        self.log('Processing System Unavailable for '+ location)
        siteId = location.replace(' ', '_').lower()
        for device_state, entity_list in self.home_state_entities.items():
            for sensor in entity_list: 
                if siteId in sensor: #meaning that sensor belongs to that location
                    self.update_sensor(sensor, 0)
                    device_local = sensor.replace("sensor.", "")
                    appdaemon_entity = '{}.{}'.format(self.presence_topic, device_local)
                    self.set_state(appdaemon_entity, state = 0)

        if location in self.location_timers:
            self.location_timers.pop(location)

        entity_id = "{}.{}".format(self.presence_topic, siteId)
        self.set_state(entity_id, state = "Offline")