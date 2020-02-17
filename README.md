# Monitor-Appdaemon-App
Appdaemon App for [Andrew's Monitor Presence Detection System](https://github.com/andrewjfreyer/monitor).

The Monitor Presence Detection system, is a Bash script `monitor.sh` created by [Andrew Freyer](https://github.com/andrewjfreyer), which is designed to run on multiple Linux systems like the Raspberry Pi around the home, to detect if persons are near or not. It is designed to work with 1 or more scripts installed on 1 or more computers (like raspberry) referred to as nodes, to detect presence. The node uses Bluetooth to detect Bluetooth devices (phone/watch/beacon/etc) is near and then reports the state from the device on a person (near or not) to a MQTT Broker. More details about the script, how it functions and setup can be found by following this [link](https://github.com/andrewjfreyer/monitor). This App is designed to maximise the use of the detection system, so that the user can easily have it integrated into their system with as less effort as possible, no matter the number of users or nodes in place.

What this app does is simply to make it easy to integrate the system into Home Assistant (HA) and AppDaemon (AD). This app can be added to an Appdaemon instance, which will help to auto generate entities for presence detection based on the data reported by each node. With this app, all the user has to do, is to add the app to his AD instance, set it up and all entities and devices will be generated in HA, no matter the number of nodes running in that location or Bluetooth devices to be detected.

## Features
- Generates sensors in Home Assistant (HA) and AppDaemon (AD) for the following
    - Sensors of the Confidence levels for each Bluetooth device like phone/watch/beacon etc based on each node in each location. So if you have 3 presence nodes, each known device will have 3 confidence sensors with the names sensor.<monitor_name><device name>_location_conf. in AD it is <monitor_name>.<device name>_location in the `mqtt` namespace
    - Binary Sensors for each device. So no matter the number of location sensors you have, only one is generated and this is a presence       sensor. The sensor entity_id will be binary_sensor.<monitor_name><device name>. So if one has an entry in the known_static_address as       xx:xx:xx:xx:xx:xx odianosen's iphone it will generate `binary_sensor.monitor_odianosens_iphone_s`
    - If wanting to use `device_trackers`, it is possible to config the app to use `device_tracker` instead of `binary_sensors` for each device. The app will update the state as required; that is use `home`/`not_home` instead of `on`/`off`. - contributed by [shbatm](https://github.com/shbatm)
    - Binary sensors for when everyone is in `binary_sensor.everyone_home`, when everyone is out `binary_sensor.everyone_not_home`.     These sensors are set to ON or OFF  depending on declared users in the apps.yaml file users_sensors are in or out. If some are in and some out, both will be OFF, but another sensor `binary_sensor.somebody_is_home` can be used. This is handy for other automation rules.
    - The name of the sensors for `everyone_home`, `everyone_not_home` and `someone_is_home` can be modified to use other names as required. - contributed by [shbatm](https://github.com/shbatm)
- If a device is seen to be below the configured minimum confidence minimum_confidence level across all locations which defaults to 50,   a configurable not_home_timeout is ran before declaring the user device is not home in HA using the binary sensor generated for that     device.
- When one of the declared gateway_sensors in the apps.yaml is opened, based on who is in the house it will send a scan instruction to     the monitor system.
- Before sending the scan instruction, it first checks for if the system is busy scanning. With the new upgrade to monitor by Andrew, this is not really needed. But (though preferred) if the user was to activate `PREF_MQTT_REPORT_SCAN_MESSAGES` to `true` in preferences, it can still use it
- If no gateway sensors are specified, it will send scan instructions every 1 minute. This negates the experience for quick detection, so it is highly recommended to make use of at least a single gateway sensor.
- Ability to define the `known_devices` in a single place within AD, which is then loaded to all monitor nodes on the network. This can be useful, if having multiple nodes, and need to manage all `known_devices` from a single place, instead of having to change it in all nodes individually.
- Generates entities within AD, which has all the data published by the node per device, and can be listened to in other Apps for other automation reasons. For example `rssi` readings based on devices.
- Constantly checks for all installed monitor nodes on the network, to ensure which is online. If any location doesn't respond after a set time `system_timeout`, it sets all entities generated from that location to `0`. This is very useful if for example, a node reported a device confidence of `100`, then it went down. The device will stay at `100` even if the user had left the house, which will lead to wrong state.
- Requests all devices update from the nodes on the network on a system restart
- Determines the closest monitor node in an area with more than one, and adds that to the generated user binary sensor. - contributed by [shbatm](https://github.com/shbatm)
- Supports the use of external MQTT command to instruct the app to executes some tasks like `arrive` scan or hardware reboot. - contributed by [shbatm](https://github.com/shbatm)
- Has the ability to hardware reboot remote monitor nodes, as its known that after a while the Pi script is running (node) on can get locked and the script doesn't work as efficiently anymore. So instead of simply restarting the script, the app can be set to reboot the hardware itself. This can also be done via mqtt by sending an empty payload to `monitor/<location>/reboot`. More explanation below
- Has service calls within AD only, that allows a user to execute its functions from other AD apps
- Use motion sensors to update Received Signal Strength Indication (RSSI) values in the home, so when users move the `nearest_monitor` can be updated
    
To use the app, it is required to setup the system in the home as follows:
--------------------------------------------------------------------------

- Have [Home Assistant](https://www.home-assistant.io/getting-started/) and [Appdaemon](https://appdaemon.readthedocs.io/en/latest/INSTALL.html) >= 4.0 running (of course :roll_eyes:)
- Make use of the Appdaemon MQTT plugin alongside that of HASS. How to setup the MQTT plugin in AD can be seen via this [link](https://appdaemon.readthedocs.io/en/latest/CONFIGURE.html#configuration-of-the-mqtt-plugin). A simple plugin configuration sufficient for this app, in the `appdaemon.yaml` file is seen below.
    ```yaml
    plugins:
        HASS:
          type: hass
          ha_url: <some_url>
          token: <token>
          
        MQTT:
           type: mqtt
           namespace: mqtt
           client_host: Broker IP Address or DNS
           client_user: username
           client_password: password
    ```
- Have at least a single main node, which runs as `monitor.sh -tdr -a -b` in a location that users stay more often in line with @andrewjfreyer example setup. If having more than 1 monitor, have the rest run as `monitor.sh -tad -a -b` so they only scan on trigger for both arrival and departure.
- In the main node, have good spacing between scans, not only to avoid unnecessarily flooding your environment with scans but also allowing the app to take over scans intermittently. I have mine set at 120 secs throughout for now
- Have sensors at the entrances into the home which I termed `gateways`, whether it be doors or garages. Windows also for those that use it :wink:


When developing this app, 4 main things were my target:
-------------------------------------------------------

- Ease of use: The user should only setup the monitor system (collection of nodes), and no matter the number of nodes involved, it should be up and running without virtually any or minimal extra work needed. The idea of editing the configuration.yaml file for sensors, automation and input_boolean as in the example to use this great system was almost a put off for me. And once one’s system grows, it exponentially takes more work to setup and debug :persevere:.
- Scalability: No matter the number of users or gateways or nodes in place, whether its small like mine which is 3, 1 & 2 respectively or you have 30, 10 and 20 respectively (if possible), it should take virtually the same amount of work to be up and running when using this app :smirk:
- Speed: To improve in speed, the app makes use of an internal feature, whereby the app instructs the system to carry out an arrival or departure scans based on if someone enters or leaves the house and if everyone home or not. This made possible without need of forcing the monitor system to scan more frequently and thereby reducing impact on WiFi and other wireless equipment :relieved:
- Lastly and most especially Reliability: It was important false positives/negatives are eliminated in the way the system runs. So the app tries to build in some little time based buffers here and there :grimacing:

### Example Simple Configuration
```yaml
home_presence_app:
  module: home_presence_app
  class: HomePresenceApp
  home_gateway_sensors:
    - binary_sensor.main_door_contact
    
  known_devices:
    - xx:xx:xx:xx:xx:xx Odianosen's iPhone
    - xx:xx:xx:xx:xx:xx Nkiruka's iPad
```

### Example Advanced Configuration
```yaml
home_presence_app:
  module: home_presence_app
  class: HomePresenceApp
  plugin: 
    - HASS
    - MQTT
  #monitor_topic: presence
  #mqtt_event: MQTT
  #user_device_domain: device_tracker
  #everyone_not_home: everyone_not_home
  #everyone_home: everyone_home
  #somebody_is_home: somebody_is_home
  depart_check_time: 30
  minimum_confidence: 60
  not_home_timeout: 15
  system_check: 30
  system_timeout: 60
  home_gateway_sensors:
    - binary_sensor.main_door_contact
    
  home_motion_sensors:
    - binary_sensor.living_room_motion_sensor_occupancy
    - binary_sensor.kitchen_motion_sensor_occupancy
    - binary_sensor.hallway_motion_sensor_occupancy
    
  #log_level: DEBUG
  known_devices:
    - xx:xx:xx:xx:xx:xx Odianosen's iPhone
    - xx:xx:xx:xx:xx:xx Nkiruka's iPad
  
  known_beacons:
    - xx:xx:xx:xx:xx:xx Odianosen's Car Keys
  
  remote_monitors:
    kitchen:
      host: !secret kitchen_monitor_host
      username: !secret kitchen_monitor_username
      password: !secret kitchen_monitor_password
    
    living_room:
      host: 192.168.1.xxx
      username: !secret living_room_monitor_username
      password: !secret living_room_monitor_password
  
```

### App Configuration
key | optional | type | default | description
-- | -- | -- | -- | --
`module` | False | string | home_presence_app | The module name of the app.
`class` | False | string | HomePresenceApp | The name of the Class.
`plugin` | True | list | | The plugins at if restarted, the app should restart.
`monitor_topic` | True | string | `monitor` | The top topic level used by the monitor system. This is also used as the domain for service call
`mqtt_event` | True | string | `MQTT_MESSAGE` | The event name, used by the MQTT plugin to send data to the app.
`user_device_domain` | True | string | `binary_sensor` | The domain to be used for the sensors generated by the app for each device.
`everyone_home` | True | string | `everyone_home` | Binary sensor name to be used, to indicate everyone is home.
`everyone_not_home` | True | string | `everyone_not_home` | Binary sensor name to be used, to indicate everyone is not home.
`someone_is_home` | True | string | `someone_is_home` | Binary sensor name to be used, to indicate someone is home.
`depart_check_time` | True | int | 30 | Delay in seconds, before depart scan is ran. This depends on how long it takes the user to leave the door and not being picked up by a monitor node.
`minimum_confidence` | True | int | 50 | Minimum confidence required across all nodes, for a device to be considered departed.
`not_home_timeout` | True | int | 15 | Time in seconds a device has to be considered away, before registering it deaprted by the app.
`system_check`| True | int | 30 | Time in seconds, for the app to check the availability of each monitor node.
`system_timeout`| True | int | 60 | Time in seconds, for a monitor node not to respond to system check for it to be considered offline. If this happens, and the node's login details is specified under `remote_monitors`, the node will be rebooted
`home_gateway_sensors`| True | list |  | List of gateway sensors, which can be used by the app to instruct the nodes based on their state if to run a arrive/depart scan. If all home, only depart scan is ran. If all away, arrive scan is ran, and if neither both scans are ran.
`home_motion_sensors`| True | list |  | List of motion sensors, which can be used by the app to instruct the nodes based on their state if to run rssi scan.
`known_devices`| True | list |  | List of known devices that are to be loaded into all the nodes on the network
`known_beacons`| True | list |  | List of known beacons that data received from them by the app from the nodes, are to be processed by the app
`remote_monitors`| True | dict |  | Dictionary of the nodes on the network that the app is allowed to reboot. These nodes will be rebooted when it fails the `system_timeout` check, or when the `restart_device` service call is executed. The `host`, `username` and `password` of each node must be specified
`log_level` | True | `'INFO'` &#124; `'DEBUG'` | `'INFO'` | Switches log level.

Service Calls:
--------------
This app supports the use of some service calls, which can be useful if wanting to use execute some commands in the app from other AD apps. An example service call is 

```python
self.call_service("monitor/remove_known_device", device="xx:xx:xx:xx:xx:xx", namespace=mqtt)
```
The domain is determined by the specified `monitor_topic`. Below is listed the supported service calls

### remove_known_device
Used to remove a known device from all the nodes. The device's MAC address should be supplied in the service call

```python
self.call_service("monitor/remove_known_device", device="xx:xx:xx:xx:xx:xx", namespace=mqtt)
```

### run_arrive_scan
Used to instruct the app to execute an arrival scan on all nodes

```python
self.call_service("presence/run_arrive_scan", namespace=mqtt)
```

### run_depart_scan
Used to instruct the app to execute a depart scan on all nodes. If wanting to execute it immediately, pass a parameter `scan_delay=0` in the call. If not, the defined `depart_check_time` will be used as the delay before running the scan

```python
# run depart scan in 10 seconds time
self.call_service("presence/run_arrive_scan", scan_delay=10, namespace=mqtt)
```

### run_rssi_scan
Used to instruct the app to execute an rssi scan on all nodes

```python
self.call_service("monitor/run_rssi_scan", namespace=mqtt)
```

### restart_device
Used to instruct the app to execute a restart of the monitor script on all nodes. If a node has its login detail in `remote_monitors` it will attempt to reboot the hardware itself. To reboot a particular node in a location, specify the `location` parameter. This same location, should be used in defining the node's login details in `remote_monitors`

```python
# restart the monitor scripts in all nodes
self.call_service("monitor/restart_device", namespace=mqtt)

# reboot the node in the living room's hardware
self.call_service("monitor/restart_device", location="living_room", namespace=mqtt)
```

### reload_device_state
Used to instruct the app to have the nodes report the state of their devices

```python
self.call_service("presence/reload_device_state", namespace=mqtt)
```

### load_known_devices
Used to instruct the app to have the nodes setup the known devices as specified in the app's configuration

```python
self.call_service("presence/load_known_devices", namespace=mqtt)
```

### clear_location_entities
Used to instruct the app to set all entities in a predefined location to 0, indicating that no device is seen by that node. The `location` parameter must be specified

```python
self.call_service("monitor/clear_location_entities", location="hallway", namespace=mqtt)
```

MQTT Commands:
--------------
This app supports the ability to send commands to it over MQTT. This can be very useful, if wanting to execute specific functions from an external system like HA or any hub that supports MQTT. Outline below are the supported MQTT topics and the payload commands:

### monitor/run_scan
This topic is listened to by the app, and when a message is received it will execute the required command. Supported commands on this topic are as follows
 - `arrive`: This will run the arrive scan immediately
 - `depart`: This will run the depart scan immediaiely
 - `rssi`: This will run the rssi scan immediately
 
### monitor/location/reboot
 This topic is used by the app to reboot a remote monitor node. The `location` parmeter can be a any of the declared nodes in `remote_monitors`. So if wanting to say reboot only the living room's node, simply send an empty payload to `monitor/living_room/reboot`. if the location is `all`, that is an empty payload is sent to `monitor/all/reboot`, this will reboot all the declared remote_monitor nodes.

RSSI Tracking:
--------------

Within this app, RSSI tracking is also updated regularly on the AppDaemon based entities. I personally use this, for rudimentary home area tracking, aided with the use of motion sensors within the home. To use this feature, it is advised that all monitor systems are setup as `monitor.sh -tad -a -b` and the `PREF_MQTT_REPORT_SCAN_MESSAGES` should be set to `true` in preferences. I also found using this `rssi` scans only based on motion sensors, does help in keeping my systems reported state updated, with as minimal scans as possible; for example no need scanning at night, when all are sleeping. I am not advising the get motion sensors for this, but in my home I already had motion sensors for lights. So felt I may as well integrate it to improve on reliability.

Hardware Rebooting (WARNING):
-----------------------------

This is a feature which allows the app to remotely reboot a node's hardware, and not just the script it is running. It must be noted to make use of this, an external python package in the `requirements.txt` file most be installed. If using `Hass.io`, do add it to your `python_pakages` list in the config. If running on a standalone Linux system and not using the supplied script above, simply run `pip3 install -r requirements.txt` should install it; depending on which user is running AD. Care should be taken when using this feature, as any device with its details specified within the `remote_monitors` can be rebooted by the app. The hardware within which this app is running, should never be added to the list. Below is listed the conditions that can lead to a hardware reboot: 
- When a `restart_device` service call is made, the app will also attempt to reboot the hardware
- When a MQTT message is sent, to the reboot topic
