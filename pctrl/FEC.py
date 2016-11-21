#  Author:
#  Philipp Mao


class FEC(object):
    def __init__(self, pctrl):
        self.FEC_list  = pctrl.FEC_list
        self.prefix_2_FEC = pctrl.prefix_2_FEC
        self.cfg = pctrl.cfg
        self.num_VNHs_in_use = pctrl.num_VNHs_in_use
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
            if ('announce' in update):
                prefix = update['announce'].prefix
                route = self.bgp_instance.get_route('local', prefix)
                if route is not None:
                    next_hop = route.next_hop
                    next_hop_part = self.nexthop_2_part[next_hop]
                    part_set = get_all_participants_advertising(self.pctrl, prefix)
                    part_set_tuple = tuple(part_set)
                    if (next_hop_part, part_set_tuple) in self.FEC_list:
                        #self.logger.debug(str(prefix) + "integrated in existing FEC:" + str(self.FEC_list[(next_hop_part, part_set_tuple)]))
                        self.prefix_2_FEC[prefix] = self.FEC_list[(next_hop_part, part_set_tuple)]
                        return
                    else:
                        self.num_VNHs_in_use += 1
                        vnh = str(self.cfg.VNHs[self.num_VNHs_in_use])
                        if vnh in self.nexthop_2_part:
                            self.num_VNHs_in_use += 1
                            vnh = vnh = str(self.cfg.VNHs[self.num_VNHs_in_use])
                        new_FEC = {}
                        new_FEC['id'] = len(self.FEC_list) + 1
                        new_FEC['vnh'] = vnh
                        new_FEC['next_hop_part'] = next_hop_part
                        new_FEC['part_advertising'] = part_set
                        self.prefix_2_FEC[prefix] = new_FEC
                        self.FEC_list[(next_hop_part, part_set_tuple)] = new_FEC
                        return

            if ('withdraw' in update):
                prefix = update['withdraw'].prefix
                route = self.bgp_instance.get_route('local', prefix)
                if route is not None:
                    next_hop = route.next_hop
                    next_hop_part = self.nexthop_2_part[next_hop]
                    part_set = get_all_participants_advertising(self, prefix)
                    part_set_tuple = tuple(part_set)
                    if (next_hop_part, part_set_tuple) in self.FEC_list:
                        #self.logger.debug(str(prefix) + "integrated in existing FEC:" + str(self.FEC_list[(next_hop_part, part_set_tuple)]))
                        self.prefix_2_FEC[prefix] = self.FEC_list[(next_hop_part, part_set_tuple)]
                        return
                    else:
                        self.num_VNHs_in_use += 1
                        vnh = str(self.cfg.VNHs[self.num_VNHs_in_use])
                        new_FEC = {}
                        new_FEC['id'] = len(self.FEC_list) + 1
                        new_FEC['vnh'] = vnh
                        new_FEC['next_hop_part'] = next_hop_part
                        new_FEC['part_advertising'] = part_set
                        self.prefix_2_FEC[prefix] = new_FEC
                        self.FEC_list[(next_hop_part, part_set_tuple)] = new_FEC
                        return
                else :
                    if prefix in self.prefix_2_FEC:
                        self.prefix_2_VNH_nrfp[prefix] = self.prefix_2_FEC[prefix]['vnh']
                        self.prefix_2_FEC.pop(prefix)
                    return
        else:
            "Disjoint"
            # TODO: @Robert: Place your logic here for VNH assignment for MDS scheme
            #self.logger.debug("VNH assignment called for disjoint vmac_mode")

    def init_vnh_assignment(self):
        "Assign VNHs for the advertised prefixes"
        if self.cfg.isSupersetsMode():
            " Superset"
            #self.bgp_instance.rib["local"].dump()
            prefixes = self.bgp_instance.rib["local"].get_prefixes()
            for prefix in prefixes:
                    route = self.bgp_instance.get_route('local', prefix)
                    if route is not None:
                        next_hop = route.next_hop
                        next_hop_part = self.nexthop_2_part[next_hop]
                        part_set = get_all_participants_advertising(self, prefix)
                        part_set_tuple = tuple(part_set)
                        if (next_hop_part, part_set_tuple) in self.FEC_list:
                            self.prefix_2_FEC[prefix] = self.FEC_list[(next_hop_part, part_set_tuple)]
                        else:
                            self.num_VNHs_in_use += 1
                            vnh = str(self.cfg.VNHs[self.num_VNHs_in_use])
                            new_FEC = {}
                            new_FEC['id'] = len(self.FEC_list) + 1
                            new_FEC['vnh'] = vnh
                            new_FEC['next_hop_part'] = next_hop_part
                            new_FEC['part_advertising'] = part_set
                            self.prefix_2_FEC[prefix] = new_FEC
                            self.FEC_list[(next_hop_part, part_set_tuple)] = new_FEC


def get_all_participants_advertising(pctrl, prefix):
    bgp_instance = pctrl.bgp_instance
    nexthop_2_part = pctrl.nexthop_2_part

    routes = bgp_instance.get_routes('input',prefix)
    #pctrl.logger.debug("Supersets all routes:: "+ str(routes))

    parts = set([])

    for route in routes:
        next_hop = route.next_hop

        if next_hop in nexthop_2_part:
            parts.add(nexthop_2_part[next_hop])
        else:
            pctrl.logger.debug("In subcall of prefix2part: Next hop "+str(next_hop)+" NOT in nexthop_2_part")

    return parts