#!/usr/bin/env python
#  Author:
#  Muhammad Shahbaz (muhammad.shahbaz@gatech.edu)
#  Rudiger Birkner (Networked Systems Group ETH Zurich)
#  Arpit Gupta (Princeton)


import argparse
from collections import namedtuple
import json
import logging.handlers
from multiprocessing.connection import Listener, Client
import os
import Queue
import sys
from threading import Thread, Lock
import time
from participant_swift import  run_peer
from bgp_route import BGPRoute



np = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if np not in sys.path:
    sys.path.append(np)
import util.log

from server import server as Server


logger = util.log.getLogger('XRS')

Config = namedtuple('Config', 'ah_socket')

bgpListener = None
config = None

participantsLock = Lock()
participants = dict()
portip2participant = dict()

clientPoolLock = Lock()
clientActivePool = dict()
clientDeadPool = set()


class PctrlClient(object):
    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr

        self.id = None
        self.peers_in = []
        self.peers_out = []

    def start(self):
        logger.info('BGP PctrlClient started for client ip %s.', self.addr)
        while True:
            try:
                rv = self.conn.recv()
            except EOFError as ee:
                break

            #logger.debug('Trace: Got rv: %s', rv)
            if not (rv and self.process_message(**json.loads(rv))):
                break

        self.conn.close()

        # remove self
        with clientPoolLock:
            logger.debug('Trace: PctrlClient.start: clientActivePool before: %s', clientActivePool)
            logger.debug('Trace: PctrlClient.start: clientDeadPool before: %s', clientDeadPool)
            t = clientActivePool[self]
            del clientActivePool[self]
            clientDeadPool.add(t)
            logger.debug('Trace: PctrlClient.start: clientActivePool after: %s', clientActivePool)
            logger.debug('Trace: PctrlClient.start: clientDeadPool after: %s', clientDeadPool)

        with participantsLock:
            logger.debug('Trace: PctrlClient.start: portip2participant before: %s', portip2participant)
            logger.debug('Trace: PctrlClient.start: participants before: %s', participants)
            found = [k for k,v in portip2participant.items() if v == self.id]
            for k in found:
                del portip2participant[k]

            found = [k for k,v in participants.items() if v == self]
            for k in found:
                del participants[k]
            logger.debug('Trace: PctrlClient.start: portip2participant after: %s', portip2participant)
            logger.debug('Trace: PctrlClient.start: participants after: %s', participants)


    def process_message(self, msgType=None, **data):
        if msgType == 'hello':
            rv = self.process_hello_message(**data)
        elif msgType == 'bgp':
            rv = self.process_bgp_message(**data)
        else:
            logger.warn("Unrecognized or absent msgType: %s. Message ignored.", msgType)
            rv = True

        return rv


    def process_hello_message(self, id=None, peers_in=None, peers_out=None, ports=None, **data):
        if not (id is not None and isinstance(ports, list) and
                isinstance(peers_in, list) and isinstance(peers_out, list)):
            logger.warn("hello message from %s is missing something: id: %s, ports: %s, peers_in: %s, peers_out: %s. Closing connection.", self.addr, id, ports, peers_in, peers_out)
            return False

        self.id = id = int(id)
        self.peers_in = set(peers_in)
        self.peers_out = set(peers_out)

        with participantsLock:
            logger.debug('Trace: PctrlClient.hello: portip2participant before: %s', portip2participant)
            logger.debug('Trace: PctrlClient.hello: participants before: %s', participants)
            for port in ports:
                portip2participant[port] = id
            participants[id] = self
            logger.debug('Trace: PctrlClient.hello: portip2participant after: %s', portip2participant)
            logger.debug('Trace: PctrlClient.hello: participants after: %s', participants)

        return True


    def process_bgp_message(self, announcement=None, **data):
        if announcement:
            bgpListener.send(announcement)
        return True


    def send(self, route):
        logger.debug('Sending a route update to participant %d', self.id)
        self.conn.send({'bgp': route})

    def sendFR(self, route):
        self.conn.send(route)

class PctrlListener(object):
    def __init__(self):
        logger.info("Initializing the BGP PctrlListener")
        self.listener = Listener(config.ah_socket, authkey=None, backlog=100)
        self.run = True


    def start(self):
        logger.info("Starting the BGP PctrlListener")

        while self.run:
            conn = self.listener.accept()

            pc = PctrlClient(conn, self.listener.last_accepted)
            t = Thread(target=pc.start)

            with clientPoolLock:
                logger.debug('Trace: PctrlListener.start: clientActivePool before: %s', clientActivePool)
                logger.debug('Trace: PctrlListener.start: clientDeadPool before: %s', clientDeadPool)
                clientActivePool[pc] = t

                # while here, join dead threads.
                while clientDeadPool:
                    clientDeadPool.pop().join()
                logger.debug('Trace: PctrlListener.start: clientActivePool after: %s', clientActivePool)
                logger.debug('Trace: PctrlListener.start: clientDeadPool after: %s', clientDeadPool)

            t.start()


    def stop(self):
        logger.info("Stopping PctrlListener.")
        self.run = False


class BGPListener(object):
    def __init__(self):
        logger.info('Initializing the BGPListener')

        # Initialize XRS Server
        self.server = Server(logger)
        self.run = True


    def start(self):
        logger.info("Starting the Server to handle incoming BGP Updates.")
        self.server.start()

        self.peer_swift_dict = {}

        self.peer_queue_dict = {}

        self.peer_queue = Queue.Queue()

        self.waiting = 0

        route_server_listener_thread = Thread(target= self.Route_server_listener)

        route_server_sender_thread = Thread(target= self.Route_server_sender)

        route_server_sender_thread.start()
        route_server_listener_thread.start()

    def send(self, announcement):
        self.server.sender_queue.put(announcement)


    def stop(self):
        logger.info("Stopping BGPListener.")
        self.run = False

    def Route_server_listener(self):

        while self.run:
            try:
                route = self.server.receiver_queue.get(True, 1)
            except Queue.Empty:
                if self.waiting == 0:
                    logger.debug("Waiting for BGP update...")
                self.waiting = (self.waiting+1) % 30
                continue

            self.waiting = 0

            route = json.loads(route)

            logger.info("Got route from ExaBGP: %s", route)
            logger.debug("Got route from ExaBGP: %s", route)

            # Received BGP route advertisement from ExaBGP
            try:
                advertise_ip = route['neighbor']['ip']
            except KeyError:
                print "KEYERROR", route
                logger.debug("KEYERROR" + str(route))
                continue

            with participantsLock:
                try:
                    advertise_id = portip2participant[advertise_ip]
                except KeyError:
                    continue

            route_list = self.route_2_bgp_updates(route)

            if advertise_id not in self.peer_queue_dict:
                print "launching swift for peer_id:", advertise_id
                self.peer_queue_dict[advertise_id] = Queue.Queue()
                win_size = 10
                nb_withdrawals_burst_start = 10
                nb_withdrawals_burst_end = 5
                min_bpa_burst_size = 20
                fm_freq = 20
                p_w = 1
                r_w = 1
                bpa_algo = 'bpa-multiple'
                nb_bits_aspath = 12
                run_encoding_threshold = 10
                silent = True
                with participantsLock:
                    self.peer_swift_dict[advertise_id] = Thread(target=run_peer, \
                                    args=(self.peer_queue_dict[advertise_id], self.peer_queue, win_size,advertise_id, nb_withdrawals_burst_start, \
                                    nb_withdrawals_burst_end, min_bpa_burst_size, "bursts", fm_freq, p_w, \
                                    r_w, bpa_algo, nb_bits_aspath, run_encoding_threshold, \
                                    False, silent))

                self.peer_swift_dict[advertise_id].start()

            for route in route_list:
                self.peer_queue_dict[advertise_id].put(route)

        for thread in self.peer_swift_dict.items():
            thread.stop()

    def Route_server_sender(self):
        while self.run:
            try:
                route = self.peer_queue.get()
            except Queue.Empty:
                if self.waiting == 0:
                    logger.debug("Waiting for FR message or modified Bgp update...")
                self.waiting = (self.waiting+1) % 30
                continue

            if 'FR' in route:
                peer_id = route['FR']['peer_id']
                found = []
                with participantsLock:
                    try:
                        peers_out = participants[peer_id].peers_out
                    except KeyError:
                        continue

                    for id, peer in participants.iteritems():
                        # Apply the filtering logic
                        if id in peers_out and peer_id in peer.peers_in:
                            found.append(peer)

                for peer in found:
                    # Now send this route to participant `id`'s controller'
                    peer.sendFR(route)

            else:
                if 'announce' in route:
                    try:
                        advertise_ip = route['announce'].neighbor
                    except KeyError:
                        print "KEYERROR", route
                        logger.debug("KEYERROR" + str(route))
                        continue
                if 'withdraw' in route:
                    try:
                        advertise_ip = route['withdraw'].neighbor
                    except KeyError:
                        print "KEYERROR", route
                        logger.debug("KEYERROR" + str(route))
                        continue

                found = []
                with participantsLock:
                    try:
                        advertise_id = portip2participant[advertise_ip]
                        peers_out = participants[advertise_id].peers_out
                    except KeyError:
                        continue

                    for id, peer in participants.iteritems():
                        # Apply the filtering logic
                        if id in peers_out and advertise_id in peer.peers_in:
                            found.append(peer)

                for peer in found:
                    # Now send this route to participant `id`'s controller'
                    peer.send(route)

    def route_2_bgp_updates(self, route):
        origin = None
        as_path = None
        as_path_vmac = None
        med = None
        atomic_aggregate = None
        communities = None

        route_list = []

        if 'state' in route['neighbor'] and route['neighbor']['state'] == 'down':
            route_list.append(route)
            return route_list

        # Extract out neighbor information in the given BGP update
        neighbor = route["neighbor"]["ip"]
        if 'message' in route['neighbor']:
            if 'update' in route['neighbor']['message']:
                time = route['time']
                if 'attribute' in route['neighbor']['message']['update']:
                    attribute = route['neighbor']['message']['update']['attribute']

                    origin = attribute['origin'] if 'origin' in attribute else ''

                    as_path = attribute['as-path'] if 'as-path' in attribute else []

                    as_path_vmac = attribute['as_path_vmac'] if 'as_path_vmac' in attribute else None

                    med = attribute['med'] if 'med' in attribute else ''

                    community = attribute['community'] if 'community' in attribute else ''
                    communities = ''
                    for c in community:
                        communities += ':'.join(map(str,c)) + " "

                    atomic_aggregate = attribute['atomic-aggregate'] if 'atomic-aggregate' in attribute else ''

                if 'announce' in route['neighbor']['message']['update']:
                    announce = route['neighbor']['message']['update']['announce']
                    if 'ipv4 unicast' in announce:
                        for next_hop in announce['ipv4 unicast'].keys():
                            for prefix in announce['ipv4 unicast'][next_hop].keys():
                                announced_route = BGPRoute(prefix,
                                                           neighbor,
                                                           next_hop,
                                                           origin,
                                                           as_path,
                                                           as_path_vmac,
                                                           communities,
                                                           med,
                                                           atomic_aggregate
                                                           )

                                route_list.append({'announce': announced_route ,'time': time})

                elif 'withdraw' in route['neighbor']['message']['update']:
                    withdraw = route['neighbor']['message']['update']['withdraw']
                    if 'ipv4 unicast' in withdraw:
                        next_hop = None
                        for prefix in withdraw['ipv4 unicast'].keys():
                            withdrawn_route = BGPRoute(prefix,
                                                           neighbor,
                                                           next_hop,
                                                           origin,
                                                           as_path,
                                                           as_path_vmac,
                                                           communities,
                                                           med,
                                                           atomic_aggregate,
                                                           )
                            route_list.append({'withdraw': withdrawn_route, 'time': time})

        return route_list




def parse_config(config_file):
    "Parse the config file"

    # loading config file
    logger.debug("Begin parsing config...")

    with open(config_file, 'r') as f:
        config = json.load(f)

    ah_socket = tuple(config["Route Server"]["AH_SOCKET"])

    logger.debug("Done parsing config")
    return Config(ah_socket)


def main():
    global bgpListener, pctrlListener, config

    parser = argparse.ArgumentParser()
    parser.add_argument('dir', help='the directory of the example')
    args = parser.parse_args()

    # locate config file
    config_file = os.path.join(os.path.dirname(os.path.realpath(__file__)),"..","examples",args.dir,"config","sdx_global.cfg")

    logger.info("Reading config file %s", config_file)
    config = parse_config(config_file)

    #swift log directories
    if not os.path.exists('log'):
        os.makedirs('log')

    if not os.path.exists('bursts'):
        os.makedirs('bursts')

    LOG_DIRNAME = 'log'
    main_logger = logging.getLogger('MainLogger')
    main_logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s :: %(levelname)s :: %(message)s')
    handler = logging.handlers.RotatingFileHandler(LOG_DIRNAME + '/main', maxBytes=200000000000, backupCount=5)
    handler.setFormatter(formatter)
    main_logger.addHandler(handler)

    bgpListener = BGPListener()
    bp_thread = Thread(target=bgpListener.start)
    bp_thread.start()

    pctrlListener = PctrlListener()
    pp_thread = Thread(target=pctrlListener.start)
    pp_thread.start()

    while bp_thread.is_alive():
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            bgpListener.stop()

    bp_thread.join()
    pctrlListener.stop()
    pp_thread.join()


if __name__ == '__main__':
    main()
