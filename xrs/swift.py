#swift module, embedded into route-server

from as_topology import ASTopology
from bgp_messages import BGPMessagesQueue
from encoding import Encoding
from rib import RIBPeer
from bpa import find_best_fmscore_forward, find_best_fmscore_backward, find_best_fmscore_naive, find_best_fmscore_single
from burst import Burst
import string


class Swift:
    # parse SWIFT parameters from a swift cfg file
    def __init__(self):
        self.win_size = 10
        self.silent = False
        self.nb_withdrawals_burst_start = 1500
        self.nb_withdrawals_burst_end = 9
        self.min_bpa_burst_size = 2500
        self.burst_outdir =
        self.nb_withdraws_per_cycle = 100
        self.p_w = 1
        self.r_w = 3
        self.nb_bits_aspath = 12
        self.run_encoding_threshold = 1000000
        self.G = ASTopology(1, self.silent)  # Main topology
        self.G_W = ASTopology(self.nb_withdrawals_burst_start, self.silent)
        self.bpa_algo ='bpa-multiple'
        self.peer_as_set = ()
        self.peer_id = 1

        self.unsent_routes = []

        self.current_burst = None

        self.rib = RIBPeer()

        self.W_queue = BGPMessagesQueue(self.win_size)

        self.last_ts = 0

    def init_encoding(self):
        self.encoding = Encoding(1, self.G, 'encoding', self.nb_bits_aspath, 5, output=True)
        self.encoding.compute_encoding()



    def burst_prediction(current_burst, G, G_W, W_queue, p_w, r_w, bpa_algo, peer_as_set):
        current_burst.prediction_done = True


        try:
            if bpa_algo == 'bpa-multiple':
                best_edge_set_forward, best_fm_score_forward, best_TP_forward, best_FP_forward, best_FN_forward = \
                    find_best_fmscore_forward(G, G_W, len(W_queue) + len(current_burst.deleted_from_W_queue), p_w, r_w)
                best_edge_set_backward, best_fm_score_backward, best_TP_backward, best_FP_backward, best_FN_backward = \
                    find_best_fmscore_backward(G, G_W, len(W_queue) + len(current_burst.deleted_from_W_queue), p_w, r_w)

                if best_fm_score_forward > best_fm_score_backward:
                    best_edge_set = best_edge_set_forward
                    best_TP = best_TP_forward
                    best_FP = best_FP_forward
                    best_FN = best_FN_forward
                    best_fm_score = best_fm_score_forward
                elif best_fm_score_backward > best_fm_score_forward:
                    best_edge_set = best_edge_set_backward
                    best_TP = best_TP_backward
                    best_FP = best_FP_backward
                    best_FN = best_FN_backward
                    best_fm_score = best_fm_score_backward
                else:  # backward and forward mode returns the same fm score
                    best_edge_set = best_edge_set_forward.union(best_edge_set_backward)
                    best_TP = -1
                    best_FP = -1
                    best_FN = -1
                    best_fm_score = best_fm_score_forward

            elif bpa_algo == 'bpa-single':
                best_edge_set, best_fm_score, best_TP, best_FP, best_FN = find_best_fmscore_single(G, G_W,
                                                                                                   len(W_queue) + len(
                                                                                                       current_burst.deleted_from_W_queue),
                                                                                                   p_w, r_w)
            else:
                best_edge_set = set()
                best_TP = 0
                best_FP = 0
                best_FN = 0
                for peer_as in peer_as_set:
                    best_edge_set_tmp, best_fm_score, best_TP_tmp, best_FP_tmp, best_FN_tmp = find_best_fmscore_naive(G,
                                                                                                                      G_W,
                                                                                                                      len(
                                                                                                                          W_queue) + len(
                                                                                                                          current_burst.deleted_from_W_queue),
                                                                                                                      peer_as,
                                                                                                                      p_w,
                                                                                                                      r_w)
                    best_edge_set = best_edge_set.union(best_edge_set_tmp)
                    best_TP += best_TP_tmp
                    best_FP += best_FP_tmp
                    best_FN += best_FN_tmp

        except:
            print "BPA failed"

        return best_edge_set, best_fm_score, int(best_TP), int(best_FP), int(best_FN)



    # updates G, checks for burst, updates burst, in case of burst predict failed links
    def process_updates(self, route):

        routes = []
        FR_messages = []

        #parse exabgp bgp update
        if 'announce' in route['neighbor']['message']['update']:
            announce = route['neighbor']['message']['update']['announce']

            as_path = []

            if 'attribute' in route['neighbor']['message']['update']:
                attribute = route['neighbor']['message']['update']['attribute']
                as_path = attribute['as-path'] if 'as-path' in attribute else []

            if 'ipv4 unicast' in announce:
                for next_hop in announce['ipv4 unicast'].keys():
                    for prefix in announce['ipv4 unicast'][next_hop].keys():

                        old_as_path = self.rib.update(prefix, as_path)

                        self.G.remove(old_as_path, prefix)

                        self.G.add(as_path, prefix)

                        if self.encoding is not None:
                            self.encoding.advertisement(old_as_path, as_path)
                            routes = self.add_as_path_encoding(prefix, 'announce', route)
                        elif len(self.rib.rib) > self.run_encoding_threshold:
                            self.init_encoding()
                            routes = []
                            for routes in self.unsent_routes:
                                if 'announce' in route['neighbor']['message']['update']:
                                    routes.append(self.add_as_path_encoding(prefix, 'announce', route))

                                else:
                                    routes.append(route)
                        else:
                            self.unsent_routes.append(route)


        if 'withdraw' in route['neighbor']['message']['update']:

            if self.encoding is None:
                self.init_encoding()

            withdraw = route['neighbor']['message']['update']['withdraw']
            if 'ipv4 unicast' in withdraw:
                for prefix in withdraw['ipv4 unicast'].keys():

                    as_path = self.rib.withdraw(prefix)

                    self.G.remove(as_path, prefix)

                    self.G_W.add(as_path)

                    if as_path != []:
                        self.W_queue.append(as_path)

                    self.encoding.withdraw(as_path)

                    #@TODO: send withdraws

        #MAYBE CHECK IF NEIGHBOR IS DOWN ?

        self.msg_time = route['time']

        if self.current_burst is not None:
            while (self.last_ts != self.msg_time):
                self.last_ts += 1

                # Update the graph of withdraws
                for w in self.W_queue.refresh_iter(self.last_ts):
                    self.current_burst.deleted_from_W_queue.append(w)

                # Remove the current burst (if any) if it the size of the withdraws is lower than w_threshold (meaning it has finished)
                if len(self.W_queue) < self.nb_withdrawals_burst_end:  # current_burst.is_expired(bgp_msg.time):
                    # Execute BPA at the end of the burst if the burst is large enough
                    best_edge_set, best_fm_score, best_TP, best_FN, best_FP = self.burst_prediction(self.current_burst, self.G, self.G_W,
                                                                                               self.W_queue, self.p_w, self.r_w,
                                                                                               self.bpa_algo, self.peer_as_set)
                    #current_burst.fd_predicted.write(
                        #'PREDICTION_END|' + bpa_algo + '|' + str(len(current_burst)) + '|' + str(
                            #best_fm_score) + '|' + str(best_TP) + '|' + str(best_FN) + '|' + str(best_FP) + '\n')
                    #current_burst.fd_predicted.write('PREDICTION_END_EDGE|')

                    # Print some information about the prediction on the prediction file
                    res = ''
                    depth = 9999999999
                    for e in best_edge_set:
                        res += str(e[0]) + '-' + str(e[1]) + ','
                        depth = min(self.G_W.get_depth(e[0], e[1]), depth)
                    #current_burst.fd_predicted.write(res[:len(res) - 1] + '|' + str(depth) + '\n')

                    # G_W.draw_graph(peer_as, G, current_burst, outfile='as_graph_'+str(current_burst.start_time)+'.dot', threshold=500)

                    # Update the graph of withdrawals
                    for w in self.current_burst.deleted_from_W_queue:
                        self.G_W.remove(w.as_path)

                    self.current_burst.stop(self.msg_time)
                    self.current_burst = None
                    FR_messages = self.compute_FR_message()
                    return FR_messages, route
                else:
                    self.current_burst.last_ts = self.last_ts

        if self.current_burst is None:
            for as_path in self.W_queue.refresh_iter(self.msg_time):
                self.G_W.remove(as_path)

        self.last_ts = self.msg_time

        if self.current_burst is not None:
            if 'announce' in route['neighbor']['message']['update']:
                announce = route['neighbor']['message']['update']['announce']

                as_path = []

                if 'attribute' in route['neighbor']['message']['update']:
                    attribute = route['neighbor']['message']['update']['attribute']
                    as_path = attribute['as-path'] if 'as-path' in attribute else []

                old_as_path = as_path
                if 'ipv4 unicast' in announce:
                    for next_hop in announce['ipv4 unicast'].keys():
                        for prefix in announce['ipv4 unicast'][next_hop].keys():
                            self.current_burst.add_real_prefix(self.msg_time, prefix, 'A',
                                                               old_as_path)

            if 'withdraw' in route['neighbor']['message']['update']:
                withdraw = route['neighbor']['message']['update']['withdraw']

                as_path = []
                if 'attribute' in route['neighbor']['message']['update']:
                    attribute = route['neighbor']['message']['update']['attribute']
                    as_path = attribute['as-path'] if 'as-path' in attribute else []
                if 'ipv4 unicast' in withdraw:
                    for prefix in withdraw['ipv4 unicast'].keys():
                        self.current_burst.add_real_prefix(self.msg_time, prefix, 'W', as_path)

        # If we are not in the burst yet, we create the burst
        if self.current_burst is None and len(self.W_queue) >= self.nb_withdrawals_burst_start:
            burst_start_time = self.W_queue[100].time if len(self.W_queue) > 100 else self.W_queue[0].time
            self.current_burst = Burst(self.peer_id, self.msg_time, self.win_size, self.burst_outdir, self.encoding, burst_start_time, self.silent)
            self.next_bpa_execution = self.min_bpa_burst_size

        # Execute BPA if there is a burst and
        # i) the current burst is greater than the minimum require
        #  ii) we have wait the number of withdrawals required per cycle or the queue is empty
        if self.current_burst is not None:
            total_current_burst_size = len(self.current_burst)+self.nb_withdrawals_burst_start
            if total_current_burst_size >= self.min_bpa_burst_size and total_current_burst_size > self.next_bpa_execution:#\
                if self.nb_withdraws_per_cycle > 0 and total_current_burst_size < 12505:
                    self.next_bpa_execution += self.nb_withdraws_per_cycle
                else:
                    self.next_bpa_execution = 999999999999
                    #@TODO: GO TO SWIFT Line: 383
                    FR_messages = self.compute_FR_message()



        return FR_messages, routes


    def compute_FR_message(self):
        if self.current_burst is not None:

            FR_messages = []

            # Compute the set of edges with the highest FM score
            best_edge_set, best_fm_score, best_TP, best_FP, best_FN = self.burst_prediction(self.current_burst, self.G, self.G_W, self.W_queue, self.p_w, self.r_w, self.bpa_algo, self.peer_as_set)
            # Load that set in the burst
            if not self.silent: self.burst_add_edge(self.current_burst, self.rib, self.encoding, self.msg_time, best_edge_set, self.G, self.G_W, self.silent)

            # Inform the global RIB about the set of failed links
            for e in best_edge_set:
                depth_set = set()
                if self.G_W.has_edge(e[0], e[1]):
                    depth_set = depth_set.union(self.G_W[e[0]][e[1]]['depth'].keys())
                if self.G.has_edge(e[0], e[1]):
                    depth_set = depth_set.union(self.G[e[0]][e[1]]['depth'].keys())

                for d in depth_set:
                    if self.encoding.is_encoded(d, e[0], e[1]):

                            vmac_partial = ''
                            bitmask_partial = ''

                            for i in range(2, self.encoding.max_depth+2):
                                if i == d:
                                    vmac_partial += self.encoding.mapping[i].get_mapping_string(e[0])
                                    bitmask_partial += '1' * self.encoding.mapping[i].nb_bytes
                                elif i == d+1:
                                    vmac_partial += self.encoding.mapping[i].get_mapping_string(e[1])
                                    bitmask_partial += '1' * self.encoding.mapping[i].nb_bytes
                                else:
                                    if i in self.encoding.mapping:
                                        vmac_partial += '0' * self.encoding.mapping[i].nb_bytes
                                        bitmask_partial += '0' * self.encoding.mapping[i].nb_bytes

                            FR_message = {'FR': {'as_path_vmac': vmac_partial, 'as_path_bitmask': bitmask_partial, 'depth': d}}
                            FR_messages.append(FR_message)

            # Print information about the perdiction in the predicted file
            self.current_burst.fd_predicted.write('PREDICTION|'+self.bpa_algo+'|'+str(len(self.current_burst))+'|'+str(best_fm_score)+'|'+str(best_TP)+'|'+str(best_FP)+'|'+str(best_FN)+'\n')
            self.current_burst.fd_predicted.write('PREDICTION_EDGE|')
            res = ''
            depth = 9999999999
            for e in best_edge_set:
                depth = min(self.G_W.get_depth(e[0], e[1]), depth)
                res += str(e[0])+'-'+str(e[1])+','
            self.current_burst.fd_predicted.write(res[:len(res)-1]+'|'+str(depth)+'\n')

            return FR_messages

    def burst_add_edge(self, current_burst, rib, encoding, last_msg_time, best_edge_set, G, G_W, silent):
        for new_edge in current_burst.add_edges_iter(last_msg_time, best_edge_set, G_W):
            for p in G.get_prefixes_edge(new_edge):
                aspath = rib.rib[p]
                is_encoded, depth = encoding.prefix_is_encoded(p, aspath, new_edge[0], new_edge[1])
                self.current_burst.add_predicted_prefix(last_msg_time, p, is_encoded, depth)


    def add_as_path_encoding(self, prefix, messagetype ,route):
        v_mac = ''
        deep = 1
        aspath = ''
        for asn in self.rib.rib[prefix]:
            if deep in self.encoding.mapping:
                depth_value = self.encoding.mapping[deep].get_mapping_string(asn)
                v_mac += '' + depth_value
            deep += 1
            aspath += str(asn) + ' '
        aspath = aspath[:-1]

        v_mac = string.ljust(v_mac, self.encoding.max_bytes, '0')

        route['neighbor']['message']['update'][messagetype]['ipv4 unicast']['prefix']['as_path_vmac'] = v_mac

        return route







