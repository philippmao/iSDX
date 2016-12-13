#!/usr/bin/env python
#  Author:
#  Muhammad Shahbaz (muhammad.shahbaz@gatech.edu)
#  Rudiger Birkner (Networked Systems Group ETH Zurich)
#  Arpit Gupta (Princeton)


from threading import RLock

import os
import sys
np = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if np not in sys.path:
    sys.path.append(np)
import util.log

from rib import LocalRIB
from bgp_route import BGPRoute


class BGPPeer(object):
    def __init__(self, id, asn, ports, peers_in, peers_out):
        self.id = id
        self.asn = asn
        self.ports = ports
        self.lock_items = {}
        self.logger = util.log.getLogger('P'+str(self.id)+'-peer')

        tables = [
            {'name': 'input', 'primary_keys': ('prefix', 'neighbor'), 'mappings': [(), ('prefix',), ('neighbor',)]},
            {'name': 'local', 'primary_keys': ('prefix',), 'mappings': [()]},
            {'name': 'output', 'primary_keys': ('prefix',), 'mappings': [()]}
        ]

        self.rib = LocalRIB(self.asn, tables)

        # peers that a participant accepts traffic from and sends advertisements to
        self.peers_in = peers_in
        # peers that the participant can send its traffic to and gets advertisements from
        self.peers_out = peers_out

    def update(self, route):

        # Extract out neighbor information in the given BGP update
        if 'announce' in route:
            announce = route['announce']
            self.add_route('input', announce)

        if 'withdraw' in route:
            withdraw = route['withdraw']
            neighbor = withdraw.neighbor
            deleted_route = self.get_routes('input', False, prefix=withdraw.prefix, neighbor=neighbor)
            if deleted_route:
                self.delete_route('input', prefix=withdraw.prefix, neighbor=neighbor)

    def decision_process(self, update):
        'Update the local rib with new best path'
        if 'announce' in update:

            # NOTES:
            # Currently the logic is that we push the new update in input rib and then
            # make the best path decision. This is very efficient. This is how it should be
            # done:
            # (1) For announcement: We need to compare between the entry for that
            # prefix in the local rib and new announcement. There is not need to scan
            # the entire input rib. The compare the new path with output rib and make
            # deicision whether to announce a new path or not.
            # (2) For withdraw: Check if withdraw withdrawn route is same as
            # best path in local, if yes, then delete it and run the best path
            # selection over entire input rib, else just ignore this withdraw
            # message.

            new_best_route = None

            announced_route = update['announce']
            prefix = announced_route.prefix

            current_best_route = self.get_routes('local', False, prefix=prefix)

            # decision process if there is an existing best route
            if current_best_route:
                # new route is better than existing
                if announced_route > current_best_route:
                    new_best_route = announced_route
                #Replace routes without as-path with
                if current_best_route.as_path_vmac is None:
                    if announced_route.as_path_vmac is not None:
                        new_best_route = announced_route
                # if the new route is an update of the current best route and makes it worse, we have to rerun the
                # entire decision process
                elif announced_route < current_best_route \
                        and announced_route.neighbor == current_best_route.neighbor:
                    routes = self.get_routes('input', True, prefix=announced_route.prefix)
                    # TODO check if it is necessary to append the route as we it should already be in the RIB
                    routes.append(announced_route)
                    routes.sort(reverse=True)

                    new_best_route = routes[0]
            else:
                # This is the first time for this prefix
                new_best_route = announced_route

            if new_best_route:
                self.update_route('local', new_best_route)

        elif 'withdraw' in update:
            deleted_route = update['withdraw']
            prefix = deleted_route.prefix

            if deleted_route is not None:
                # Check if the withdrawn route is the current_best_route and update best route
                current_best_route = self.get_routes('local', False, prefix=prefix)
                if current_best_route:
                    if deleted_route.neighbor == current_best_route.neighbor:
                        self.delete_route('local', prefix=prefix)
                        routes = self.get_routes('input', True, prefix=prefix)
                        if routes:
                            routes.sort(reverse=True)
                            best_route = routes[0]
                            self.update_route('local', best_route)
                    else:
                        self.logger.debug("BGP withdraw for prefix "+str(prefix)+" has no impact on best path")
                else:
                    self.logger.error("Withdraw received for a prefix which wasn't even in the local table")

    def bgp_update_peer(self, update, prefix_2_VNH_nrfp, prefix_2_FEC, prefix_2_BEC ,BECid_FECid_2_VNH , VNH_2_vmac, ports):
        announcements = []
        new_VNHs = []

        if 'announce' in update:
            prefix = update['announce'].prefix
        else:
            prefix = update['withdraw'].prefix

        prev_route = self.get_routes('output', False, prefix=prefix)

        best_route = self.get_routes('local', False, prefix=prefix)

        if 'announce' in update:
            # Check if best path has changed for this prefix
            # store announcement in output rib
            BEC_id = prefix_2_BEC[prefix]['id']
            FEC_id = prefix_2_FEC[prefix]['id']
            vnh = BECid_FECid_2_VNH[(BEC_id, FEC_id)]

            if prev_route:
                if prev_route.as_path_vmac is None:
                    self.delete_route("output", prefix = prefix)
                    new_VNHs.append(vnh)

            self.update_route("output", best_route)
            BEC_id = prefix_2_BEC[prefix]['id']
            FEC_id = prefix_2_FEC[prefix]['id']
            vnh = BECid_FECid_2_VNH[(BEC_id, FEC_id)]
            if vnh not in VNH_2_vmac:
                new_VNHs.append(vnh)
            if best_route:
                # announce the route to each router of the participant
                for port in ports:
                    # TODO: Create a sender queue and import the announce_route function
                    announcements.append(announce_route(port["IP"],
                                                            prefix,
                                                            vnh,
                                                            best_route.as_path))
            else:
                self.logger.error("Race condition problem for prefix: "+str(prefix))
                return new_VNHs, announcements

        elif 'withdraw' in update:
            # A new announcement is only needed if the best path has changed
            if best_route:
                # store announcement in output rib
                self.update_route("output", best_route)
                BEC_id = prefix_2_BEC[prefix]['id']
                FEC_id = prefix_2_FEC[prefix]['id']
                vnh = BECid_FECid_2_VNH[(BEC_id, FEC_id)]
                if vnh not in VNH_2_vmac:
                    new_VNHs.append(vnh)
                for port in ports:
                    announcements.append(announce_route(port["IP"],
                                                            prefix,
                                                            vnh,
                                                            best_route.as_path))

            else:
                "Currently there is no best route to this prefix"
                if prev_route:
                    # Clear this entry from the output rib
                    self.delete_route("output", prefix=prefix)
                    for port in self.ports:
                        # TODO: Create a sender queue and import the announce_route function
                        announcements.append(withdraw_route(port["IP"],
                                                                prefix,
                                                                prefix_2_VNH_nrfp[prefix]))

        return new_VNHs, announcements

    def get_lock(self, lock):
        if lock not in self.lock_items:
            self.lock_items[lock] = RLock()
        return self.lock_items[lock]

    def process_notification(self, route):
        if 'shutdown' == route['notification']:
            self.delete_all_routes('input')
            self.delete_all_routes('local')
            self.delete_all_routes('output')

    def add_route(self, table_name, bgp_route): # updated
        with self.get_lock(bgp_route.prefix):
            self.rib.add(table_name, bgp_route)
            self.rib.commit()

    def get_routes(self, table_name, all_entries, **kwargs):
        key_items = kwargs
        lock = key_items['prefix'] if 'prefix' in key_items else 'global'
        with self.get_lock(lock):
            return self.rib.get(table_name, key_items, all_entries)

    def update_route(self, table_name, bgp_route):
        with self.get_lock(bgp_route.prefix):
            self.rib.add(table_name, bgp_route)

    def delete_route(self, table_name, **kwargs):
        key_items = kwargs
        lock = key_items['prefix'] if 'prefix' in key_items else 'global'
        with self.get_lock(lock):
            self.rib.delete(table_name, key_items)
            self.rib.commit()

    def delete_all_routes(self, table_name, **kwargs):
        key_items = kwargs
        self.rib.delete(table_name, key_items)
        self.rib.commit()


def announce_route(neighbor, prefix, next_hop, as_path):
    msg = "neighbor " + neighbor + " announce route " + prefix + " next-hop " + str(next_hop)
    msg += " as-path [ ( " + ' '.join(str(ap) for ap in as_path) + " ) ]"
    return msg


def withdraw_route(neighbor, prefix, next_hop):
    msg = "neighbor " + neighbor + " withdraw route " + prefix + " next-hop " + str(next_hop)
    return msg


def fake_exabgp_routes(msg_type, neighbor, next_hop, prefix, as_path):
    route = {
        'neighbor': {
            'ip': neighbor,
            'state': 'up or down',
            'message': {
                'update': {
                    'attribute': {
                        'origin': 'igp',
                        'as-path': as_path,
                        'med': 0,
                        'community': [],
                    },
                }
            }
        }
    }

    if msg_type == 'announce':
        route['neighbor']['message']['update']['announce'] = {
            'ipv4 unicast': {
                next_hop: {prefix: ''},
            },
        }

    elif msg_type == 'withdraw':
        route['neighbor']['message']['update']['withdraw'] = {
            'ipv4 unicast': {
                prefix: [],
            }
        }

    return route


def pretty_print(rib_entry):
    print "|prefix\t\t|neighbor\t|next hop\t|as path\t|"
    if isinstance(rib_entry, list):
        for entry in rib_entry:
            print str(entry)
    else:
        print str(rib_entry)


''' main '''
if __name__ == '__main__':
    bgp_peer = BGPPeer(1, 111, None, None, None)

    routes = [
        {
            'msg_type': 'announce',
            'neighbor': '100.0.0.1',
            'next_hop': '100.0.0.1',
            'prefix': '10.0.0.0/8',
            'as_path': [300, 400, 500]
        },
        {
            'msg_type': 'announce',
            'neighbor': '100.0.0.2',
            'next_hop': '100.0.0.2',
            'prefix': '10.0.0.0/8',
            'as_path': [100, 500]
        },
    ]

    for route in routes:
        update = bgp_peer.update(fake_exabgp_routes(route['msg_type'], route['neighbor'], route['next_hop'], route['prefix'], route['as_path']))
        bgp_peer.decision_process(update[0])

    print 'Test 1 - Best Path with AS Path [100, 500]'
    bgp_route = bgp_peer.get_routes('local', True, prefix='10.0.0.0/8')
    pretty_print(bgp_route)

    routes = [
        {
            'msg_type': 'announce',
            'neighbor': '100.0.0.1',
            'next_hop': '100.0.0.1',
            'prefix': '20.0.0.0/8',
            'as_path': [300, 500]
        },
        {
            'msg_type': 'announce',
            'neighbor': '100.0.0.2',
            'next_hop': '100.0.0.2',
            'prefix': '20.0.0.0/8',
            'as_path': [100, 500]
        },
    ]

    for route in routes:
        update = bgp_peer.update(fake_exabgp_routes(route['msg_type'], route['neighbor'], route['next_hop'], route['prefix'], route['as_path']))
        bgp_peer.decision_process(update[0])

    print 'Test 2 - Best Path with Neighbor 100.0.0.1'
    bgp_route = bgp_peer.get_routes('local', False, prefix='20.0.0.0/8')
    pretty_print(bgp_route)

    print 'Test 3 - All entries input - 4 entries'
    bgp_route = bgp_peer.get_routes('input', True)
    pretty_print(bgp_route)

    routes = [
        {
            'msg_type': 'withdraw',
            'neighbor': '100.0.0.1',
            'next_hop': '100.0.0.1',
            'prefix': '20.0.0.0/8',
            'as_path': [300, 500]
        },
    ]

    for route in routes:
        update = bgp_peer.update(fake_exabgp_routes(route['msg_type'], route['neighbor'], route['next_hop'], route['prefix'], route['as_path']))
        bgp_peer.decision_process(update[0])

    print 'Test 4 - All entries after withdraw of 20/8 from 100.0.0.1 in input - 3 entries'
    bgp_route = bgp_peer.get_routes('input', True)
    pretty_print(bgp_route)

    print 'Test 5 - All entries local - 5 entries'
    bgp_route = bgp_peer.get_routes('local', True)
    pretty_print(bgp_route)
