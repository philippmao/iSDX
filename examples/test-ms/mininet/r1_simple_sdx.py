#!/usr/bin/python

import os
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.node import RemoteController, OVSSwitch, Node
from r1_sdnip import BgpRouter, SdnipHost


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
        
        # Add Participants to the IXP
        # Each participant consists of 1 quagga router PLUS
        # 1 host per network advertised behind quagga
        a1 = self.addParticipant(fabric=main_switch,
                                 name='a1',
                                 port=5,
                                 mac='08:00:27:89:3b:9f',
                                 ip='172.0.0.01/16',
                                 networks=['100.0.0.0/24', '110.0.0.0/24'],
                                 asn=100)

        b1 = self.addParticipant(fabric=main_switch,
                                 name='b1',
                                 port=6,
                                 mac='08:00:27:92:18:1f',
                                 ip='172.0.0.11/16',
                                 networks=['140.0.0.0/24', '150.0.0.0/24'],
                                 asn=200)

        c1 = self.addParticipant(fabric=main_switch,
                                 name='c1',
                                 port=7,
                                 mac='08:00:27:54:56:ea',
                                 ip='172.0.0.21/16',
                                 networks=['140.0.0.0/24', '150.0.0.0/24'],
                                 asn=300)

        # Add new router connected to C and B that will be used to inject routes
        r1 = self.addDumpRouter(name='r1',
                           ip='173.0.0.31/16',
                           asn=400,
                           b1=b1,
                           c1=c1)

        dump_host = self.addHost('x3', ip='173.0.255.252/16', mac='08:00:27:89:3c:ff', inNamespace=False)
        self.addLink(r1, dump_host, 2)

    def addDumpRouter(self, name, ip, asn, b1, c1):
        peerb1 = {'mac': '08:00:27:54:56:23', 'ipAddrs': ['1.0.0.2/16']}
        peerc1 = {'mac': '08:00:27:54:56:24', 'ipAddrs': ['2.0.0.2/16']}
        peerx3 = {'mac': '08:00:27:54:56:27', 'ipAddrs': [ip]}
        intfs = {
            'r1-eth0': peerb1,
            'r1-eth1': peerc1,
            'r1-eth2': peerx3
        }

        neighbors = [
            {'address': '1.0.0.1', 'as': 200},
            {'address': '2.0.0.1', 'as': 300},
            {'address': '173.0.255.252', 'as': 64000}
        ]

        networks = ['180.0.0.0/24']
        peer = self.addHost(name, intfDict=intfs, asNum=asn, neighbors=neighbors, routes=networks, cls=BgpRouter)
        self.addLink(peer, b1, 0, 1)
        self.addLink(peer, c1, 1, 1)

        return peer

    def addParticipant(self, fabric, name, port, mac, ip, networks, asn):

        # Adds the interface to connect the router to the Route server
        peereth0 = {'mac': mac, 'ipAddrs': [ip]}
        intfs = {name + '-eth0': peereth0}

        if name == 'b1':
            eth = {'mac': '08:00:27:54:56:25', 'ipAddrs': ['1.0.0.1/16']}
            intfs['b1-eth1'] = eth

        if name == 'c1':
            eth = {'mac': '08:00:27:54:56:26', 'ipAddrs': ['2.0.0.1/16']}
            intfs['c1-eth1'] = eth

        num_interfaces = len(intfs)

        # Adds 1 gateway interface for each network connected to the router
        for net in networks:
            eth = {'ipAddrs': [replace_ip(net, '254')]}  # ex.: 100.0.0.254
            i = len(intfs)
            intfs[name+'-eth'+str(i)] = eth

        print str(intfs)

        # Set up the peer router
        neighbors = [{'address': ROUTE_SERVER_IP, 'as': ROUTE_SERVER_ASN}]
        if name == 'b1':
            neighbors.append({'address': '1.0.0.2', 'as': 400})

        if name == 'c1':
            neighbors.append({'address': '2.0.0.2', 'as': 400})

        peer = self.addHost(name,
                            intfDict=intfs,
                            asNum=asn,
                            neighbors=neighbors,
                            routes=networks,
                            cls=BgpRouter)

        self.addLink(fabric, peer, port, 0)
        
        # Adds a host connected to the router via the gateway interface
        i = 0
        for net in networks:
            i += 1
            ips = [replace_ip(net, '1')]  # ex.: 100.0.0.1/24
            hostname = 'h' + str(i) + '_' + name  # ex.: h1_a1
            host = self.addHost(hostname,
                                cls=SdnipHost,
                                ips=ips,
                                gateway = replace_ip( net, '254').split('/')[0])  #ex.: 100.0.0.254
            # Set up data plane connectivity
            self.addLink(peer, host, num_interfaces + i - 1, 0)

        return peer


def replace_ip(network, ip):
    net, subnet = network.split('/')
    gw = net.split('.')
    gw[3] = ip
    gw = '.'.join(gw)
    gw = '/'.join([gw,subnet])
    return gw

if __name__ == "__main__":
    setLogLevel('info')
    topo = SDXTopo()

    net = Mininet(topo=topo, controller=RemoteController, switch=OVSSwitch)

    net.start()

    CLI(net)

    net.stop()

    info("done\n")