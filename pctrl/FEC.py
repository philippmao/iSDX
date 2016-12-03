#  Author:
#  Philipp Mao


class FEC(object):
    def __init__(self, pctrl):
        self.FEC_list = pctrl.FEC_list
        self.prefix_2_FEC = pctrl.prefix_2_FEC
        self.cfg = pctrl.cfg
        self.nexthop_2_part = self.cfg.get_nexthop_2_part()
        self.bgp_instance = pctrl.bgp_instance
        self.id = pctrl.id
        self.pctrl = pctrl
        self.prefix_2_VNH_nrfp = pctrl.prefix_2_VNH_nrfp
        self.logger = pctrl.logger

    def assignment(self, update):
        "Assign VNHs for the advertised prefixes"
        if self.cfg.isSupersetsMode():
            " Superset"
            if 'announce' in update:
                prefix = update['announce'].prefix
                route = self.bgp_instance.get_routes('local', False, prefix=prefix)
                if route:
                    next_hop = route.next_hop
                    next_hop_part = self.nexthop_2_part[next_hop]
                    part_set = get_all_participants_advertising(self.pctrl, prefix)
                    part_set_tuple = tuple(part_set)
                    if (next_hop_part, part_set_tuple) in self.FEC_list:
                        #self.logger.debug(str(prefix) + "integrated in existing FEC:" + str(self.FEC_list[(next_hop_part, part_set_tuple)]))
                        self.prefix_2_FEC[prefix] = self.FEC_list[(next_hop_part, part_set_tuple)]
                        return
                    else:
                        new_FEC = {}
                        new_FEC['id'] = len(self.FEC_list) + 1
                        new_FEC['next_hop_part'] = next_hop_part
                        new_FEC['part_advertising'] = part_set
                        self.prefix_2_FEC[prefix] = new_FEC
                        self.FEC_list[(next_hop_part, part_set_tuple)] = new_FEC
                        return

            if 'withdraw' in update:
                prefix = update['withdraw'].prefix
                route = self.bgp_instance.get_routes('local', False, prefix=prefix)
                if route:
                    next_hop = route.next_hop
                    next_hop_part = self.nexthop_2_part[next_hop]
                    part_set = get_all_participants_advertising(self, prefix)
                    part_set_tuple = tuple(part_set)
                    if (next_hop_part, part_set_tuple) in self.FEC_list:
                        #self.logger.debug(str(prefix) + "integrated in existing FEC:" + str(self.FEC_list[(next_hop_part, part_set_tuple)]))
                        self.prefix_2_FEC[prefix] = self.FEC_list[(next_hop_part, part_set_tuple)]
                        return
                    else:
                        new_FEC = {}
                        new_FEC['id'] = len(self.FEC_list) + 1
                        new_FEC['next_hop_part'] = next_hop_part
                        new_FEC['part_advertising'] = part_set
                        self.prefix_2_FEC[prefix] = new_FEC
                        self.FEC_list[(next_hop_part, part_set_tuple)] = new_FEC
                        return
                else :
                    if prefix in self.prefix_2_FEC:
                        self.prefix_2_FEC_nrfp[prefix] = self.prefix_2_FEC[prefix]
                        self.prefix_2_FEC.pop(prefix)
                    return
        else:
            "Disjoint"
            # TODO: @Robert: Place your logic here for VNH assignment for MDS scheme
            #self.logger.debug("VNH assignment called for disjoint vmac_mode")

    def init_FEC_assignment(self):
        "Assign VNHs for the advertised prefixes"
        if self.cfg.isSupersetsMode():
            " Superset"
            bgp_routes = self.bgp_instance.get_routes('local', True)
            for bgp_route in bgp_routes:
                prefix = bgp_route.prefix
                route = self.bgp_instance.get_routes('local', False, prefix=prefix)
                if route is not None:
                    next_hop = route.next_hop
                    next_hop_part = self.nexthop_2_part[next_hop]
                    part_set = get_all_participants_advertising(self, prefix)
                    part_set_tuple = tuple(part_set)
                    if (next_hop_part, part_set_tuple) in self.FEC_list:
                        self.prefix_2_FEC[prefix] = self.FEC_list[(next_hop_part, part_set_tuple)]
                    else:
                        new_FEC = {}
                        new_FEC['id'] = len(self.FEC_list) + 1
                        new_FEC['next_hop_part'] = next_hop_part
                        new_FEC['part_advertising'] = part_set
                        self.prefix_2_FEC[prefix] = new_FEC
                        self.FEC_list[(next_hop_part, part_set_tuple)] = new_FEC


def get_all_participants_advertising(pctrl, prefix):
    bgp_instance = pctrl.bgp_instance
    nexthop_2_part = pctrl.nexthop_2_part

    routes = bgp_instance.get_routes('input', True, prefix=prefix)

    parts = set([])

    for route in routes:
        next_hop = route.next_hop

        if next_hop in nexthop_2_part:
            parts.add(nexthop_2_part[next_hop])
        #else:
            #pctrl.logger.debug("In subcall of prefix2part: Next hop "+str(next_hop)+" NOT in nexthop_2_part")

    return parts