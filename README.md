# Monitor-Appdaemon-App
Appdaemon App for [Andrew's Monitor Presence Detection System](https://github.com/andrewjfreyer/monitor).

The Monitor Presence Detection system, is a Bash script `monitor.sh` created by [Andrew Freyer](https://github.com/andrewjfreyer), which is designed to run on a Linux system like the Raspberry Pi. It is designed to be used as a distributed system, having multiple nodes within the environment it is functioning to ensure total coverage. These nodes/systems are used to detect the presence of Bluetooth devices, using the Bluetooth adapter on the node. It works by reporting the detected devices to an MQTT broker, which can then be integrated into an automation hub like Home-Assistant. More details about the script, how it functions and setup can be found by following the link above. This App is designed to maximise the use of the detection system, so that the user can easily have it interated into their system with as less effort as possible, no matter the number of users or nodes in place.

This app can be added to an Appdaemon system, which will help to auto generate entities for presence detection based on the Monitor script. With this app, all the user has to do, is to add the app to his AD instance, set it up and all entities and devices will be generated in HA, no matter the number of monitor systems running on that location. How to setup the monitor (not presence) system can be seen in the link above, and what this app does is simply to make it easy to integrate it into HA and AD. 

## Features
- Generates sensors in HA and AD for the following
    - Sensors of the Confidence levels for each device based on each location. So if you have 3 presence systems, each known device will       have 3 confidence sensors with the names sensor.<monitor_name><device name>_location_conf. in AD it is <monitor_name>.<device name>_location in the `mqtt` namesapce
    - Binary Sensors for each device. So no matter the number of location sensors you have, only one is generated and this is a presence       sensor. The sensor entity_id will be binary_sensor.<monitor_name><device name>. So if one has an entry in the known_static_address as       xx:xx:xx:xx:xx:xx odianosen's iphone it will generate `binary_sensor.monitor_odianosens_iphone_s`
    - Binary sensors for when everyone is in `binary_sensor.everyone_home`, when everyone is out `binary_sensor.everyone_not_home`.     These sensors are set to ON or OFF  depending on declared users in the apps.yaml file users_sensors are in or out. If some are in and some out, both will be OFF, but another sensor `binary_sensor.somebody_is_home` can be used. This is handy for other automation rules.
- If a device is seen to be below the configured minimum confidence minimum_confidence level across all locations which defaults to 50,   a configurable not_home_timeout is ran before declaring the user device is not home in HA using the binary sensor generated for that     device.
- When one of the declared gateway_sensors in the apps.yaml is opened, based on who is in the house it will send a scan instruction to     the monitor system.
- Before sending the scan instruction, it first checks for if the system is busy scanning. With the new upgrade to the script, this is     not really needed. But (though prefered) if the user was to activate `PREF_MQTT_REPORT_SCAN_MESSAGES` to `true` in preferences, it can still use it
- Abiltity to define the `known_devices` in a single place within AD, which is then loaded to all monitor systems on the network. This can be useful, if having multiple monitor systems, and need to manage all `known_devices` from a single place, instead of having to change it in all systems individually.
- Generates entities within AD, which has all the data published by the script per device, and can be listened to in other Apps for other automation reasons. For example `rssi` readings based on devices.
- Constantly checks for all installed scripts on the network, to ensure which is online. If any location doesn't respond after a set time `system_timeout`, it sets all entities generated from that location to `0`. This is very useful if for example, as system reported a device confidence of `100`, then it went down. The device will stay at `100` even if the user had left the house, which will lead to wrong state.
- Requests all devices update from the scripts on the network on a system restart
- Determines the closest monitor system in an area with more than one, and adds that to the generated user binary sensor. - contributed by `shbatm <https://github.com/shbatm>`__ 
- Supports the use of external MQTT command to instruct the app to carry out some instructions. - contributed by `shbatm <https://github.com/shbatm>`__ 
- Has the ability to hardware reboot remote monitor systems, as its known that after a while the Pi monitor is running on can get locked and the script doesn't work as efficiently. So instead of simply restarting the script, the app can be set to reboot the hardware. This can also be done via mqtt by sending an empty payload to `monitor/<location>/reboot`. 
- Has service calls within AD, that allows a user to execute its functions from other AD apps
- Use motion sensors to update RSSI values in the home, so when users move the `nearest_monitor` can be updated

When developing this app, 4 main things were my target:
-------------------------------------------------------

- Ease of use: The user should only setup the monitor system/s, and no matter the number of locations involved, it should be up and running without virtually any or minimal extra work needed. The idea of editing the configuration.yaml file for sensors, automation and input_boolean as in the example to use this great system was almost a put off for me. And once one’s system grows, it exponentially takes more work to setup and debug :persevere:.
- Scalability: No matter the number of users or gateways or monitor systems in place, whether its small like mine which is 3, 1 & 2 respectively or you have 30, 10 and 20 respectively (if possible), it should take virtually the same amount of work to be up and running when using this app :smirk:
- Speed: To improve in speed, the app makes use of an internal feature, whereby the app instructs the system to carryout an arrival or departure scans based on if someone enters or leaves the house and if everyone home or not. This made possible without need of forcing the monitor system to scan more frequently and thereby reducing impact on WiFi and other wireless equipment :relieved:
- Lastly and most especially Reliability: It was important false positives/negatives are eliminated in the way the system runs. So the app tries to build in some little time based buffers here and there :grimacing:

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
