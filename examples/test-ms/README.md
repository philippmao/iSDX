
# Example: MultiSwitch

## Topology

![Experimental Setup]
(https://creately.com/diagram/ix0o4t3p/eRUcTBqB71plGQ720c7JxcWNoAw%3D)

The setup consists of 3 participants (participating ASes) A, B and C. These participants have the following routers:

`Router A1, Router B1, Router C1

These routers are running the zebra and bgpd daemons, part of the `Quagga` routing engine. We've used the `MiniNext` emulation tool to create this topology. In this example we have three switches representing SDX switch: (1) Main Switch, (2) Outbound Switch, and (3) Inbound Switch. 

## Configuring the Setup

The experiment needs two types of configurations: the control plane (SDX controller and Swift), and the data plane (Mininet topology). 

* **Control Plane Configurations**

The control plane configuration involves defining participant's policies, configuring `bgp.conf` for SDX's route server (based on ExaBGP), configuring 'sdx_global.cfg' to provide each participant's information to the SDX controller and to provide the Swift parameters including vmac partitioning. 

In this example, participant `A` has outbound policies defined in `/examples/test-ms/policies/participant_1.py`. Participant `C` and Participant `B` have no policy.


* **Data Plane Configurations**

In our experimental setup, we need edge routers running a routing engine to exchange BGP paths. 
We also need X3 to inject routes into r1 which then get advertised to B1 C1 and ultimately A1. 
For our example, the MiniNext script is described in `/examples/test-ms/mininext/r1_simple_sdx.py`.

The SDX route server (which is based on ExaBGP) runs in the root namespace. We created an interface in the root namespace itself and connected it with the SDX switch. 

## Running the setup
The test-ms scenario has been wrapped in a launch.sh shell script.

### Log Server

$ cd ~/iSDX
$ rm -f SDXLog.log
$ python logServer.py SDXLog.log
```

### Mininet
```bash
$ cd iSDX/examples/test-ms/mininet
$ sudo python r1_simple_sdx.py
```


### Run everything else
```bash
$ cd ~
$ ./iSDX/launch.sh test-ms 3
```

This will start the following parts (and if `--stats` is specificed, it will also start the gauge.py Ryu app):

#### RefMon (Fabric Manager)
```bash
$ cd ~/iSDX/flanc
$ ryu-manager refmon.py --refmon-config ~/iSDX/examples/test-ms/config/sdx_global.cfg &
$ sleep 1
```

The RefMon module is based on Ryu. It listens for forwarding table modification instructions from the participant controllers and the IXP controller and installs the changes in the switch fabric. It abstracts the details of the underlying switch hardware and OpenFlow messages from the participants and the IXP controllers and also ensures isolation between the participants.

#### xctrl (IXP Controller)
```bash
$ cd ~/iSDX/xctrl
$ python xctrl.py ~/iSDX/examples/test-ms/config/sdx_global.cfg
```

The IXP controller initializes the sdx fabric and installs all static default forwarding rules. It also handles ARP queries and replies in the fabric and ensures that these messages are forwarded to the respective participantsâ€™ controllers via ARP relay.

#### arpproxy (ARP Relay)
```bash
$ cd ~/iSDX/arproxy
$ sudo python arproxy.py test-ms &
$ sleep 1
```

This module receives ARP requests from the IXP fabric and it relays them to the corresponding participant's controller. It also receives ARP replies from the participant controllers which it relays to the IXP fabric. 

#### xrs (BGP Relay)
```bash
$ cd ~/iSDX/xrs
$ sudo python route_server.py test-ms &
$ sleep 1
```

The BGP relay is based on ExaBGP and is similar to a BGP route server in terms of establishing peering sessions with the border routers. Unlike a route server, it does not perform any route selection. Instead, it multiplexes all BGP routes to the participant controllers. 
It also starts swift processes for the participants

#### pctrl (Participant SDN Controller)
```bash
$ cd ~/iSDX/pctrl
$ sudo python participant_controller.py test-ms 1 &
$ sudo python participant_controller.py test-ms 2 &
$ sudo python participant_controller.py test-ms 3 &
$ sleep 1
```

Each participant SDN controller computes a compressed set of forwarding table entries, which are installed into the inbound and outbound switches via the fabric manager, and continuously updates the entries in response to the changes in SDN policies and BGP updates. The participant controller receives BGP updates from the BGP relay. It processes the incoming BGP updates by selecting the best route and updating the RIBs. The participant controller also generates BGP announcements destined to the border routers of this participant, which are sent to the routers via the BGP relay.

#### ExaBGP
```bash
$ cd ~/iSDX
$ exabgp examples/test-ms/config/bgp.conf
```

It is part of the `xrs` module itself and it handles the BGP sessions with all the border routers of the SDX participants.

#### Bgpsimple
```bash
sudo /home/vagrant/iSDX/Bgpdump/bgp_simple.pl -myas 64000 -myip 173.0.255.252 -peerip 173.0.0.31 -peeras 400 -holdtime 180 - keepalive 60 -p /home/vagrant/iSDX/Bgpdump/myroutes -m “number of prefixes” -n
```

Bgpsimple will advertise a certain amount of prefixes ("number of prefixes") to r1. It takes these routes from the myroutes file. To advertise all 300000 prefixes in myroutes remove -m "number of prefixes" from the command.


## Testing the setup

Check if the route server has correctly advertised the routes  

    mininext> a1 route -n  
    Kernel IP routing table  
    Destination     Gateway         Genmask         Flags Metric Ref    Use Iface  
    140.0.0.0       172.0.1.3       255.255.255.0   UG    0      0        0 a1-eth0  
    150.0.0.0       172.0.1.4       255.255.255.0   UG    0      0        0 a1-eth0  
    172.0.0.0       0.0.0.0         255.255.0.0     U     0      0        0 a1-eth0  

Run the `clean` script:
```bash
$ sh ~/iSDX/pctrl/clean.sh
```

### Note
Always check with ```route``` whether ```a1``` sees ```140.0.0.0/24``` and ```150.0.0.0/24```, ```b1```/```c1```/```c2``` see ```100.0.0.0/24``` and ```110.0.0.0/24```
