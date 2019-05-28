# Monitor-App
Appdaemon App for [Andrew's Monitor Presence Detection System](https://github.com/andrewjfreyer/monitor).

This app can be added to an Appdaemon system, which will help to auto generate entities for presence detection based on the Monitor script. With this app, all the user has to do, is to add the app to his AD instance, set it up and all entnties and devices will be generated in HA, no matter the number of monitor systems running on that location.

How to setup the monitor (not presence) system can be seen in the link above, and what this app does is simply to make it easy to integrate it into HA and AD. This is based of Appdaemon 4.0 and above, so it will only profit those that use it. This app does the following:

- Generates sensors for the following
    - Sensors of the Confidence levels for each device based on each location. So if you have 3 presence systems, each known device will       have 3 confidence sensors with the names sensor.<device name>_location in both HA and AD.
    - Binary Sensors for each device. So no matter the number of location sensors you have, only one is generated and this is a presence       sensor. The sensor entity_id will be binary_sensor.<device name>_home_state. So if one has an entry in the known_static_address as       xx:xx:xx:xx:xx:xx odianosen's iphone it will generate `binary_sensor.odianosens_iphone_s_home_state`
    - Binary sensors for when everyone is in binary_sensor.everyone_home and when everyone is out binary_sensor.everyone_not_home. These       sensors are set to ON or OFF when all declared users in the apps.yaml file users_sensors are in or out. If some are in and some         out, both will be OFF. This is handy for other automation rules.
- If a device is seen to be below the configured minimum confidence minimum_confidence level across all locations which defaults to 90,   a configurable not_home_timeout is ran before declaring the user device is not home in HA using the binary sensor generated for that     device.
- When one of the declared gateway_sensors in the apps.yaml is opened, based on who is in the house it will send a scan instruction to     the monitor system.
- Before sending the scan instruction, it first checks for if the system is busy scanning. With the new upgrade to the script, this is     not really needed. But if the user was to activate `PREF_MQTT_REPORT_SCAN_MESSAGES` to `true` in prefs, it can still use it

When developing this app, 4 main things were my target:

- Ease of use: The user should only setup the monitor system/s, and no matter the number of locations involved, it should be up and running without virtually any or minimal extra work needed. The idea of editing the configuration.yaml file for sensors, automation and input_boolean as in the example to use this great system was almost a put off for me. And once one’s system grows, it exponentially takes more work to setup and debug :persevere:.
- Scalability: No matter the number of users or gateways or monitor systems in place, whether its small like mine which is 3, 1 & 2 respectively or you have 30, 10 and 20 respectively (if possible), it should take virtually the same amount of work to be up and running when using this app :smirk:
- Speed: To improve in speed, the app makes use of an internal feature, whereby the app instructs the system to carryout an arrival or departure scans based on if someone enters or leaves the house and if everyone home or not. This made possible without need of forcing the monitor system to scan more frequently and thereby reducing impact on WiFi and other wireless equipment :relieved:
- Lastly and most especially Reliability: It was important false positives/negatives are eliminated in the way the system runs. So the app tries to build in some little time based buffers here and there :grimacing:

To maximise the app, it will be advisable to setup the system in the home as follows:
- Use Appdaemon >= 4.0 (of course :roll_eyes:)
- Try make use of the Appdaemon MQTT plugin. 
- Have a single main sensor, which runs as monitor.sh in a location that users stay more often as in @andrewjfreyer example setup. If having more than 1 sensor, have the rest run as monitor.sh -t so they only scan on trigger. The main one triggers the rest and and the app does that also when need be
- In the main sensor, have good spacing between scans, not only to avoid unnecessarily flooding your environment with scans but also allowing the app to take over scans intermittently. I have mine set at 120 secs throughout for now

Have sensors at the entrances into the home which I termed gateways, whether it be doors or garages. Windows also for those that use it :wink:
