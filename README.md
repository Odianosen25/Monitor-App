# Monitor-Appdaemon-App
Appdaemon App for [Andrew's Monitor Presence Detection System](https://github.com/andrewjfreyer/monitor).

The Monitor Presence Detection system, is a Bash script `monitor.sh` created by [Andrew Freyer](https://github.com/andrewjfreyer), which is designed to run on a Linux system like the Raspberry Pi. It is designed to be used as a distributed system, having multiple nodes within the environment it is functioning to ensure total coverage. These nodes/systems are used to detect the presence of Bluetooth devices, using the Bluetooth adapter on the node. It works by reporting the detected devices to an MQTT broker, which can then be integrated into an automation hub like Home-Assistant. More details about the script, how it functions and setup can be found by following the link above. This App is designed to maximise the use of the detection system, so that the user can easily have it interated into their system with as less effort as possible, no matter the number of users or nodes in place.

This app can be added to an Appdaemon system, which will help to auto generate entities for presence detection based on the Monitor script. With this app, all the user has to do, is to add the app to his AD instance, set it up and all entities and devices will be generated in HA, no matter the number of monitor systems running on that location. How to setup the monitor (not presence) system can be seen in the link above, and what this app does is simply to make it easy to integrate it into HA and AD. 

## Features
- Generates sensors in HA and AD for the following
    - Sensors of the Confidence levels for each device based on each location. So if you have 3 presence systems, each known device will       have 3 confidence sensors with the names sensor.<monitor_name><device name>_location_conf. in AD it is <monitor_name>.<device name>_location in the `mqtt` namesapce
    - Binary Sensors for each device. So no matter the number of location sensors you have, only one is generated and this is a presence       sensor. The sensor entity_id will be binary_sensor.<monitor_name><device name>. So if one has an entry in the known_static_address as       xx:xx:xx:xx:xx:xx odianosen's iphone it will generate `binary_sensor.monitor_odianosens_iphone_s`
    - If wanting to use `device_trackers`, it is possible to config the app to use `device_tracker` instead of `binary_sensors` for each device. The app will update the state as required; that is use `home`/`not_home` instead of `on`/`off`. - contributed by [shbatm](https://github.com/shbatm)
    - Binary sensors for when everyone is in `binary_sensor.everyone_home`, when everyone is out `binary_sensor.everyone_not_home`.     These sensors are set to ON or OFF  depending on declared users in the apps.yaml file users_sensors are in or out. If some are in and some out, both will be OFF, but another sensor `binary_sensor.somebody_is_home` can be used. This is handy for other automation rules.
    - The name of the sensors for `everyone_home`, `everyone_not_home` and `someone_is_home` can be modified to use other names as required. - contributed by [shbatm](https://github.com/shbatm)
- If a device is seen to be below the configured minimum confidence minimum_confidence level across all locations which defaults to 50,   a configurable not_home_timeout is ran before declaring the user device is not home in HA using the binary sensor generated for that     device.
- When one of the declared gateway_sensors in the apps.yaml is opened, based on who is in the house it will send a scan instruction to     the monitor system.
- Before sending the scan instruction, it first checks for if the system is busy scanning. With the new upgrade to the script, this is     not really needed. But (though prefered) if the user was to activate `PREF_MQTT_REPORT_SCAN_MESSAGES` to `true` in preferences, it can still use it
- Abiltity to define the `known_devices` in a single place within AD, which is then loaded to all monitor systems on the network. This can be useful, if having multiple monitor systems, and need to manage all `known_devices` from a single place, instead of having to change it in all systems individually.
- Generates entities within AD, which has all the data published by the script per device, and can be listened to in other Apps for other automation reasons. For example `rssi` readings based on devices.
- Constantly checks for all installed scripts on the network, to ensure which is online. If any location doesn't respond after a set time `system_timeout`, it sets all entities generated from that location to `0`. This is very useful if for example, as system reported a device confidence of `100`, then it went down. The device will stay at `100` even if the user had left the house, which will lead to wrong state.
- Requests all devices update from the scripts on the network on a system restart
- Determines the closest monitor system in an area with more than one, and adds that to the generated user binary sensor. - contributed by [shbatm](https://github.com/shbatm)
- Supports the use of external MQTT command to instruct the app to carry out some instructions. - contributed by [shbatm](https://github.com/shbatm)
- Has the ability to hardware reboot remote monitor systems, as its known that after a while the Pi monitor is running on can get locked and the script doesn't work as efficiently. So instead of simply restarting the script, the app can be set to reboot the hardware. This can also be done via mqtt by sending an empty payload to `monitor/<location>/reboot`. 
- Has service calls within AD, that allows a user to execute its functions from other AD apps
- Use motion sensors to update RSSI values in the home, so when users move the `nearest_monitor` can be updated

When developing this app, 4 main things were my target:
-------------------------------------------------------

- Ease of use: The user should only setup the monitor system/s, and no matter the number of locations involved, it should be up and running without virtually any or minimal extra work needed. The idea of editing the configuration.yaml file for sensors, automation and input_boolean as in the example to use this great system was almost a put off for me. And once one’s system grows, it exponentially takes more work to setup and debug :persevere:.
- Scalability: No matter the number of users or gateways or monitor systems in place, whether its small like mine which is 3, 1 & 2 respectively or you have 30, 10 and 20 respectively (if possible), it should take virtually the same amount of work to be up and running when using this app :smirk:
- Speed: To improve in speed, the app makes use of an internal feature, whereby the app instructs the system to carryout an arrival or departure scans based on if someone enters or leaves the house and if everyone home or not. This made possible without need of forcing the monitor system to scan more frequently and thereby reducing impact on WiFi and other wireless equipment :relieved:
- Lastly and most especially Reliability: It was important false positives/negatives are eliminated in the way the system runs. So the app tries to build in some little time based buffers here and there :grimacing:

### Example Configuration
```yaml
home_presence_app:
  module: home_presence_app
  class: HomePresenceApp
  plugin: 
    - HASS
    - MQTT
  #monitor_topic: presence
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
  
  remote_monitors:
    kitchen:
      host: !secret kitchen_monitor_host
      username: !secret kitchen_monitor_username
      password: !secret kitchen_monitor_password
    
    living_room:
      host: 192.168.1.xxx
      username: pi
      password: raspberry
  
```

### App Configuration
key | optional | type | default | description
-- | -- | -- | -- | --
`module` | False | string | home_presence_app | The module name of the app.
`class` | False | string | HomePresenceApp | The name of the Class.
`plugin` | True | list | | The plugins at if restarted, the app should restart.
`monitor_topic` | True | string | `monitor` | The topic level topic used by the monitor nodes.
`user_device_domain` | True | string | `binary_sensor` | The domain to be used for the sensors generated by the app for each device.
`everyone_home` | True | string | `everyone_home` | Binary sensor name to be used, to indicate everyone is home.
`everyone_not_home` | True | string | `everyone_not_home` | Binary sensor name to be used, to indicate everyone is not home.
`someone_is_home` | True | string | `someone_is_home` | Binary sensor name to be used, to indicate someone is home.
`depart_check_time` | True | int | 30 | Delay in seconds, before depart scan is ran. This depends on how long it takes the user to leave the door and not being picked up by a monitor node.
`minimum_confidence` | True | int | 50 | Minimum confidence required across all nodes, for a device to be considered departed.
`not_home_timeout` | True | int | 15 | Time in seconds a device has to be considered away, before registering it deaprted by the app.
`system_check`| True | int | 30 | Time in seconds, for the app to check the availablity of each monitor node.
`system_timeout`| True | int | 60 | Time in seconds, for a monitor node not to respond to system check for it to be considered offline. If this happens, and the node's login details is specified under `remote_monitors`, the node will be rebooted
`home_gateway_sensors`| True | list |  | List of gateway sensors, which can be used by the app to instruct the nodes based on their state if to run a arrive/depart scan. If all home, only depart scan is ran. If all away, arrive scan is ran, and if neither both scans are ran.
`home_motion_sensors`| True | list |  | List of motion sensors, which can be used by the app to instruct the nodes based on their state if to run rssi scan.
`known_devices`| True | list |  | List of known devices that are to be loaded into all the nodes on the network
`remote_monitors`| True | dict |  | Dictionary of the nodes on the network that the app is allowed to reboot. These nodes will be rebooted when it fails the `system_timeout` check, or when the `restart_device` service call is executed. The `host`, `username` and `password` of each node must be specified
`log_level` | True | `'INFO'` &#124; `'DEBUG'` | `'INFO'` | Switches log level.

Service Calls:
--------------
This app supports the use of some service calls, which can be useful if wanting to use execute some commands in the app from other AD apps. An example service call is 

```python
self.call_service("monitor/remove_known_device", device="xx:xx:xx:xx:xx:xx", namespace=mqtt)
```
The domain is determined by the specifed `monitor_topic`. Below is listed the supported service calls

### remove_known_device
Used to remove a known device from all the nodes. The device's MAC address should be supplied in the service call

### run_arrive_scan
Used to instruct the app to execute an arrival scan on all nodes

### run_depart_scan
Used to instruct the app to execute a depart scan on all nodes. If wanting to execute it immediately, pass a parameter `scan_Delay=0` in the call. If not, the defined `depart_check_time` will be used as the delay before running the scan

### run_rssi_scan
Used to instruct the app to execute an rssi scan on all nodes

### restart_device
Used to instruct the app to execute a restart of the script on all nodes. If a node has its login detail in `remote_monitors` it will attempt to reboot the hardware itself

### reload_device_state
Used to instruct the app to have the nodes report the state of their devices

### load_known_devices
Used to instruct the app to have the nodes setup the known devices as specified in the app's configuration

### clear_location_entities
Used to instruct the app to set all entities in a predefined location to 0, indicating that no device is seen by that node

MQTT Commands:
--------------
This app supports the ability to send commands to it over MQTT. This can be very useful, if wanting to execute specific functions from an external system like HA or any hub that supports MQTT. Outline below are the supported MQTT topics and the payload commands:

### monitor/run_scan
This topic is listened to by the app, and when a message is received it will execute the required command. Supported commands on this topic are as follows
 - `arrive`: This will run the arrive scan immediately
 - `depart`: This will run the depart scan immedaiely
 - `rssi`: This will run the rssi scan immediately
 
### monitor/location/reboot
 This topic is used by the app to reboot a remote monitor node. The `location` parmeter can be a any of the declared nodes in `remote_monitors`. So if wanting to say reboot only the living room's node, simply send an empty payload to `monitor/living room/reboot`. if the location is `all`, that is an empty payload is sent to `monitor/all/reboot`, this will reboot all the delared remote_monitor nodes.

To maximise the app, it will be advisable to setup the system in the home as follows:
-------------------------------------------------------------------------------------

- Use Appdaemon >= 4.0 (of course :roll_eyes:)
- Make use of the Appdaemon MQTT plugin. 
- Have a single main sensor, which runs as `monitor.sh -tdr -a -b` in a location that users stay more often in line with @andrewjfreyer example setup. If having more than 1 monitor, have the rest run as `monitor.sh -tad -a -b` so they only scan on trigger for both arrival and departutre.
- In the main sensor, have good spacing between scans, not only to avoid unnecessarily flooding your environment with scans but also allowing the app to take over scans intermittently. I have mine set at 120 secs throughout for now
- Have sensors at the entrances into the home which I termed `gateways`, whether it be doors or garages. Windows also for those that use it :wink:

RSSI Tracking:
--------------

Within this app, RSSI tracking is also updated regurlarly on the AppDaemon based entities. I personally use this, for rudimentary home area tracking, aided with the use of motion sensors within the home. As at the time of last update, the `monitor.sh` script has not way of requesting the RSSI values alone of scanned/available devices. To retrieve this data, the system carries out arrival scans when motion is detected after a set interval. To use this feature, it is advised that all monitor systems are setup as `monitor.sh -tad -a -b` and the `PREF_MQTT_REPORT_SCAN_MESSAGES` should be set to `true` in preferences. I also found using this `arrival` scans only based on motion sensors, does help in keeping my systems reported state updated, with as minimal scans as possible; for example no need scanning at night, when all are sleeping. I am not advising the get motion sensors for this, but in my home I already had motion sensors for lights. So felt I may as well integrate it to imporve on reliability. 
