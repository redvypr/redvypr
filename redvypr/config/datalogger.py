# A test configuration file
hostname: heatflowsensor

devices:
- deviceconfig:
    name: udpbroadcast
    config:
       address: <broadcast>
       port: 28719
       protocol: udp
       direction: receive
       serialize: str
  devicemodulename: network_device
- deviceconfig:
    name: datalogger
    loglevel: debug
  devicemodulename: datalogger


connections:
- publish: udpbroadcast
  receive: datalogger

start:
- udpbroadcast
- datalogger

