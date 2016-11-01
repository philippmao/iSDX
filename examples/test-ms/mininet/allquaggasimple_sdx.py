#!/usr/bin/python

from mininext.topo import Topo
from mininet.net import Mininet
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.node import RemoteController, OVSSwitch, Node
from sdnip import BgpRouter, SdnipHost
import inspect, os, sys, atexit
from mininext.services.quagga import QuaggaService
from mininext.net import MiniNExT as Mininext
import mininext.util
import mininet.util
mininet.util.isShellBuiltin = mininext.util.isShellBuiltin
sys.modules['mininet.util'] = mininet.util
from mininet.util import dumpNodeConnections
from mininet.node import RemoteController
from mininet.node import Node
from mininet.link import Link
from mininet.log import setLogLevel, info
from collections import namedtuple
#from mininet.term import makeTerm, cleanUpScreens
QuaggaHost = namedtuple("QuaggaHost", "name ip mac port")
net = None

ROUTE_SERVER_IP = '172.0.255.254'
ROUTE_SERVER_ASN = 65000


class SDXTopo(Topo):

    def __init__(self, *args, **kwargs):
        Topo.__init__(self, *args, **kwargs)
        # Describe Code
        # Set up data plane switch - this is the emulated router dataplane
        # Note: The controller needs to be configured with the specific driver that
        # will be attached to this switch.

        # IXP fabric
        main_switch = self.addSwitch('s1')
        inbound_switch = self.addSwitch('s2')
        outbound_switch = self.addSwitch('s3')
        arp_switch = self.addSwitch('s4')

        self.addLink(main_switch, inbound_switch, 1, 1)
        self.addLink(main_switch, outbound_switch, 2, 1)
        self.addLink(main_switch, arp_switch, 3, 1)
        self.addLink(outbound_switch, inbound_switch, 2, 2)

        # Add node for central Route Server"
        route_server = self.addHost('x1', ip='172.0.255.254/16', mac='08:00:27:89:3b:ff', inNamespace=False)
        self.addLink(main_switch, route_server, 4)
        
        # Add node for ARP Proxy"
        arp_proxy = self.addHost('x2', ip='172.0.255.253/16', mac='08:00:27:89:33:ff', inNamespace=False)
        self.addLink(arp_switch, arp_proxy, 2)
        
	"Directory where this file / script is located"
        scriptdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))) # script directory

        "Initialize a service helper for Quagga with default options"
        quaggaSvc = QuaggaService(autoStop=False)

        "Path configurations for mounts"
        quaggaBaseConfigPath=scriptdir + '/configs_qugga/'

        "List of Quagga host configs"
        quaggaHosts = []
        quaggaHosts.append(QuaggaHost(name = 'a1', ip = '172.0.0.1/16', mac = '08:00:27:89:3b:9f', port = 5))
        quaggaHosts.append(QuaggaHost(name = 'b1', ip = '172.0.0.11/16', mac ='08:00:27:92:18:1f', port = 6))
        quaggaHosts.append(QuaggaHost(name = 'c1', ip = '172.0.0.21/16', mac = '08:00:27:54:56:ea', port = 7))
	
	"Setup each legacy router, add a link between it and the IXP fabric"
        for host in quaggaHosts:
            "Set Quagga service configuration for this node"
            quaggaSvcConfig = \
            { 'quaggaConfigPath' : '/usr/configs/' + host.name }

            quaggaContainer = self.addHost( name=host.name,
                                            ip=host.ip,
                                            mac=host.mac,
                                            privateLogDir=True,
                                            privateRunDir=True,
                                            inMountNamespace=True,
                                            inPIDNamespace=True)
            self.addNodeService(node=host.name, service=quaggaSvc,
                                nodeConfig=quaggaSvcConfig)
            "Attach the quaggaContainer to the IXP Fabric Switch"
            self.addLink( quaggaContainer, main_switch , host.port)
	    
def addInterfacesForSDXNetwork( net ):
    hosts=net.hosts
    print "Configuring participating ASs\n\n"
    for host in hosts:
        print "Host name: ", host.name
        if host.name=='a1':
            host.cmd('sudo ifconfig lo:1 100.0.0.1 netmask 255.255.255.0 up')
            host.cmd('sudo ifconfig lo:2 100.0.0.2 netmask 255.255.255.0 up')
            host.cmd('sudo ifconfig lo:110 110.0.0.1 netmask 255.255.255.0 up')
        if host.name=='b1':
            host.cmd('sudo ifconfig lo:140 140.0.0.1 netmask 255.255.255.0 up')
            host.cmd('sudo ifconfig lo:150 150.0.0.1 netmask 255.255.255.0 up')
        if host.name=='c1':
            host.cmd('sudo ifconfig lo:140 140.0.0.1 netmask 255.255.255.0 up')
            host.cmd('sudo ifconfig lo:150 150.0.0.1 netmask 255.255.255.0 up')
	if host.name == 'x1':
            host.cmd( 'route add -net 172.0.0.0/16 dev exabgp-eth0')


if __name__ == "__main__":
    setLogLevel('info')
    topo = SDXTopo()

    net = Mininet(topo=topo, controller=RemoteController, switch=OVSSwitch)

    net.start()
    
    info( '**Adding Network Interfaces for SDX Setup\n' )    
    addInterfacesForSDXNetwork(net)

    CLI(net)

    net.stop()

    info("done\n")