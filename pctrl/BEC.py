#  Author:
#  Philipp Mao

class BEC(object):
    def __init__(self, pctrl):
        self.BEC_list = pctrl.BEC_list
        self.prefix_2_BEC = pctrl.prefix_2_BEC
        self.cfg = pctrl.cfg
        self.nexthop_2_part = self.cfg.get_nexthop_2_part()
        self.bgp_instance = pctrl.bgp_instance
        self.id = pctrl.id
        self.pctrl = pctrl
        self.logger = pctrl.logger
        self.max_depth = pctrl.max_depth
        self.FEC_list = pctrl.FEC_list
        self.prefix_2_FEC = pctrl.prefix_2_FEC
        self.prefix_2_BEC_nrfp = pctrl.prefix_2_BEC_nrfp

    def assignment(self, update):
        "Assign VNHs for the advertised prefixes"
        if self.cfg.isSupersetsMode():
            " Superset"
            if 'announce' in update:
                prefix = update['announce'].prefix
                route = self.bgp_instance.get_routes('local', False, prefix=prefix)
                as_path = route.as_path
                as_path_vmac = route.as_path_vmac
                if route:
                    #If no encoding yet, use default BEC
                    if route.as_path_vmac is None:
                        self.prefix_2_BEC[prefix] = self.BEC_list[((-1, -1, -1), (-1, -1, -1))]
                    else:
                        backup_nbs = []
                        for d in range(0 ,min(len(as_path)-1, self.max_depth)):
                            backup_nb = self.get_backup_avoiding_as_link(self.prefix_2_FEC[prefix]['next_hop_part'], prefix, (as_path[d], as_path[d+1]))
                            if backup_nb is not None:
                                backup_nbs.append(backup_nb)
                            else:
                                backup_nbs.append(-1)
                        as_path = tuple(as_path)
                        backup_nbs = tuple(backup_nbs)
                        if (backup_nbs, as_path) in self.BEC_list:
                            self.logger.debug(str(prefix) + "integrated in existing BEC:" + str(self.BEC_list[(backup_nbs, as_path)]))
                            self.prefix_2_BEC[prefix] = self.BEC_list[(backup_nbs, as_path)]
                            return
                        else:
                            new_BEC = {}
                            new_BEC['id'] = len(self.BEC_list) + 1
                            new_BEC['as-path'] = as_path
                            new_BEC['backup_nbs'] = backup_nbs
                            new_BEC['as_path_vmac'] = as_path_vmac
                            self.prefix_2_BEC[prefix] = new_BEC
                            self.BEC_list[(backup_nbs, as_path)] = new_BEC
                            return

            if 'withdraw' in update:
                prefix = update['withdraw'].prefix
                route = self.bgp_instance.get_routes('local', False, prefix=prefix)
                if route:
                    as_path = route.as_path
                    as_path_vmac = route.as_path_vmac
                    backup_nbs = []
                    for d in range(0, min(len(as_path)-1, self.max_depth)):

                        backup_nb = self.get_backup_avoiding_as_link(self.prefix_2_FEC[prefix]['next_hop_part'], prefix,
                                                                     (as_path[d], as_path[d + 1]))
                        if backup_nb is not None:
                            backup_nbs.append(backup_nb)
                        else:
                            backup_nbs.append(-1)

                    as_path = tuple(as_path)
                    backup_nbs = tuple(backup_nbs)
                    if (backup_nbs, as_path) in self.BEC_list:
                        if self.BEC_list[(backup_nbs, as_path)]['as_path_vmac'] is None:
                            self.BEC_list[(backup_nbs, as_path)]['as_path_vmac'] = route.as_path_vmac
                        self.logger.debug(
                            str(prefix) + "integrated in existing BEC:" + str(self.BEC_list[(backup_nbs, as_path)]))
                        self.prefix_2_BEC[prefix] = self.BEC_list[(backup_nbs, as_path)]
                        return
                    else:
                        new_BEC = {}
                        new_BEC['id'] = len(self.BEC_list) + 1
                        new_BEC['as-path'] = as_path
                        new_BEC['backup_nbs'] = backup_nbs
                        new_BEC['as_path_vmac'] = as_path_vmac
                        #new_BEC['as_path_vmac '] = route.partial_vmac
                        self.prefix_2_BEC[prefix] = new_BEC
                        self.FEC_list[(backup_nbs, as_path)] = new_BEC
                        return

                else:
                    if prefix in self.prefix_2_BEC:
                        self.prefix_2_BEC_nrfp[prefix] = self.prefix_2_BEC[prefix]
                        self.prefix_2_BEC.pop(prefix)
        else:
            "Disjoint"
            # TODO: @Robert: Place your logic here for VNH assignment for MDS scheme
            #self.logger.debug("VNH assignment called for disjoint vmac_mode")

    def init_BEC_assignment(self):
        "Assign VNHs for the advertised prefixes"
        if self.cfg.isSupersetsMode():
            " Superset"
            bgp_routes = self.bgp_instance.get_routes('local', True)
            for bgp_route in bgp_routes:
                prefix = bgp_route.prefix
                route = self.bgp_instance.get_routes('local', False, prefix=prefix)
                as_path = route.as_path
                if route :
                    backup_nbs = []
                    for d in range(0, min(len(as_path)-1, self.max_depth)):
                        backup_nb = self.get_backup_avoiding_as_link(self.prefix_2_FEC[prefix]['next_hop_part'], prefix,
                                                                     (as_path[d], as_path[d + 1]))
                        if backup_nb is not None:
                            backup_nbs.append(backup_nb)
                        else:
                            backup_nbs.append(-1)
                    as_path = tuple(as_path)
                    backup_nbs = tuple(backup_nbs)
                    if (backup_nbs, as_path) in self.BEC_list:
                        if self.BEC_list[(backup_nbs, as_path)]['as_path_vmac'] is None:
                            self.BEC_list[(backup_nbs, as_path)]['as_path_vmac'] = route.as_path_vmac
                        self.logger.debug(
                            str(prefix) + "integrated in existing BEC:" + str(self.BEC_list[(backup_nbs, as_path)]))
                        self.prefix_2_BEC[prefix] = self.BEC_list[(backup_nbs, as_path)]

                    else:
                        new_BEC = {}
                        new_BEC['id'] = len(self.BEC_list) + 1
                        new_BEC['as-path'] = as_path
                        new_BEC['backup_nbs'] = backup_nbs
                        new_BEC['as_path_vmac '] = route.as_path_vmac
                        #new_BEC['as_path_vmac '] = route.partial_vmac
                        self.prefix_2_BEC[prefix] = new_BEC
                        self.FEC_list[(backup_nbs, as_path)] = new_BEC

    def get_backup_avoiding_as_link(self, best_next_hop , prefix, as_link):
        selected_backup = None
        best_aspath_backup = None
        bgp_routes = self.bgp_instance.get_routes('input', True, prefix= prefix)


        i = 0
        for i in range(0, len(bgp_routes)):

            bgproute = bgp_routes[i]
            next_hop_part = self.nexthop_2_part[bgproute.next_hop]
            if next_hop_part != best_next_hop:
                if best_aspath_backup is None:
                    best_aspath_backup = bgproute.next_hop

                good_aspath = True

                for i in range(0, len(bgproute.as_path) - 1):
                    if (bgproute.as_path[i], bgproute.as_path[i + 1]) == as_link or \
                                    (bgproute.as_path[i + 1], bgproute.as_path[i]) == as_link:
                        good_aspath = False
                        break

                if good_aspath:
                    selected_backup = bgproute.next_hop
                    break

        #if all routes traverse affected link return as_path with shortest as-path
        if selected_backup is None:
            return best_aspath_backup
        else:
            return selected_backup
