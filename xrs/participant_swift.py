import sys
import os
import time
import argparse
import select
import cPickle as pickle
import atexit
from copy import deepcopy
import logging.handlers
import multiprocessing
import string
import Queue



from bgp_messages import BGPMessagesQueue
from rib import RIBPeer
from as_topology import ASTopology
from bpa import find_best_fmscore_forward, find_best_fmscore_backward, find_best_fmscore_naive, find_best_fmscore_single
from burst import Burst
from encoding import Encoding

if not os.path.exists('log'):
    os.makedirs('log')

if not os.path.exists('bursts'):
    os.makedirs('bursts')

 #Define the logger
LOG_DIRNAME = 'log'
peer_logger = logging.getLogger('PeerLogger')
peer_logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s :: %(levelname)s :: %(message)s')
handler = logging.handlers.RotatingFileHandler(LOG_DIRNAME+'/peers', maxBytes=200000000000000, backupCount=5)
handler.setFormatter(formatter)
peer_logger.addHandler(handler)

peer_logger.info('Peer launched!')

"""
This function runs the prefixes prediction. To do the prediction, BPA (single or mulitple)
can be used, with different weights on the precision and recall, or the naive
approach can be used. The failed links found, and their prefixes, are then
recorded in the burst object, and written in a file if silent is not enabled.
current_burst   The current burst
G               The graph of AS paths still available, weighted based on the number of prefixes traversing them
G_W             The graph of AS paths that have been withdrawn, weighted based on the number of withdrawn paths
W_queue         The queue of withdrawals.
p_w, r_w        The precision and recall weights
bpa_algo        The type of algoruthm to use (bpa-single, bpa-multiple, naive)
"""

def burst_prediction(current_burst, G, G_W, W_queue, p_w, r_w, bpa_algo, peer_as_set):
    current_burst.prediction_done = True

    try:
        if bpa_algo == 'bpa-multiple':
            best_edge_set_forward, best_fm_score_forward, best_TP_forward, best_FP_forward, best_FN_forward = \
            find_best_fmscore_forward(G, G_W, len(W_queue)+len(current_burst.deleted_from_W_queue), p_w, r_w)
            best_edge_set_backward, best_fm_score_backward, best_TP_backward, best_FP_backward, best_FN_backward = \
            find_best_fmscore_backward(G, G_W, len(W_queue)+len(current_burst.deleted_from_W_queue), p_w, r_w)

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
            else: # backward and forward mode returns the same fm score
                best_edge_set = best_edge_set_forward.union(best_edge_set_backward)
                best_TP = -1
                best_FP = -1
                best_FN = -1
                best_fm_score = best_fm_score_forward

        elif bpa_algo == 'bpa-single':
            best_edge_set, best_fm_score, best_TP, best_FP, best_FN = find_best_fmscore_single(G, G_W, len(W_queue)+len(current_burst.deleted_from_W_queue), p_w, r_w)
        else:
            best_edge_set = set()
            best_TP = 0
            best_FP = 0
            best_FN = 0
            for peer_as in peer_as_set:
                best_edge_set_tmp, best_fm_score, best_TP_tmp, best_FP_tmp, best_FN_tmp = find_best_fmscore_naive(G, G_W, len(W_queue)+len(current_burst.deleted_from_W_queue), peer_as, p_w, r_w)
                best_edge_set = best_edge_set.union(best_edge_set_tmp)
                best_TP += best_TP_tmp
                best_FP += best_FP_tmp
                best_FN += best_FN_tmp

    except:
        #peer_logger.critical('BPA has failed.')
        print "Failed"

    return best_edge_set, best_fm_score, int(best_TP), int(best_FP), int(best_FN)


def burst_add_edge(current_burst, rib, encoding, last_msg_time, best_edge_set, G, G_W, silent):
    for new_edge in current_burst.add_edges_iter(last_msg_time, best_edge_set, G_W):
        for p in G.get_prefixes_edge(new_edge):
            aspath = rib.rib[p]
            is_encoded, depth = encoding.prefix_is_encoded(p, aspath, new_edge[0], new_edge[1])
            current_burst.add_predicted_prefix(last_msg_time, p, is_encoded, depth)

def add_as_path_encoding_to_route(bgp_msg , rib, encoding):
    # if it is an advertisement
    if rib is not None:
        # Make the second part of the v_mac (the part where the as-path is encoded)
        v_mac = ''
        deep = 1
        as_path = [65000] + bgp_msg.as_path
        for asn in as_path:
            if deep in encoding.mapping:
                depth_value = encoding.mapping[deep].get_mapping_string(asn)
                v_mac += ''+depth_value
            deep += 1

        v_mac = string.ljust(v_mac, encoding.max_bytes, '0')

        bgp_msg.as_path_vmac = v_mac

    return bgp_msg




"""
The main function executed when launching a new peer.
queue           is the shared queue between the main process and the peer processes
win_size        is the window_size
nb_withdrawals_burst_start     the number of withdrawals we need to receive in last 5ec to start the burst
nb_withdrawals_burst_end        the number of withdrawals we need to receive in last 5ec to end the burst
min_bpa_burst_size  Minimum burst size before starting to run BPA
burst_outdir    where to store information about the bursts (silent needs to False)
nb_withdraws_per_cycle After how many new withdrawals BPA needs to run_peer
silent          print output in files to get information. To speed-up the algo, set to True.
naive           Use the naive approach if True
"""
def run_peer(queue_server_peer, queue_peer_server, FR_queue, win_size, peer_id, nb_withdrawals_burst_start, \
nb_withdrawals_burst_end, min_bpa_burst_size, burst_outdir, max_depth, \
nb_withdraws_per_cycle=100, p_w=1, r_w=1, bpa_algo='bpa-multiple', nb_bits_aspath=12, \
run_encoding_threshold=1000000, silent=False):

    import socket

    try:
        os.nice(-20)
    except OSError:
        #peer_logger.info('Cannot change the nice.')
        print "nochangenice"

    # Create the topologies for this peer
    G = ASTopology(1, silent) # Main topology
    G_W = ASTopology(nb_withdrawals_burst_start, silent) # Subset of the topology with the withdraws in the queue

    # Current burst (if any)
    current_burst = None

    # Last time the peer wrote the rib and queue size in the log file
    last_log_write = 0

    # Socket connected to the global RIB
    #socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    # Exit properly when receiving SIGINT
    #def signal_handler(signal, frame):
        #if current_burst is not None:
            #current_burst.stop(bgp_msg.time)

        #socket.close()

        #peer_logger.info('Received SIGTERM. Exiting.')

        #sys.exit(0)

    #signal.signal(signal.SIGTERM, signal_handler)

    peer_id = peer_id
    peer_as = None
    peer_as_set = None

    # Create the RIB for this peer
    rib = RIBPeer()

    encoding = None
    # This function create and initialize the encoding
    def init_encoding():
        encoding = Encoding(peer_id, G, 'encoding', nb_bits_aspath, 5, max_depth, output=True)
        encoding.compute_encoding()
        peer_logger.info(str(int(bgp_msg['time']))+'\t'+str(len(rib))+'\t'+str(len(W_queue))+'\t'+'Encoding computed!')

        return encoding

    #A_queue = BGPMessagesQueue(win_size) # Queue of Updates
    W_queue = BGPMessagesQueue(win_size) # Queue of Withdraws

    last_ts = 0

    routes_without_as_path_encoding = []

    peer_handler = logging.handlers.RotatingFileHandler(LOG_DIRNAME + '/peer_' + str(peer_id), maxBytes=200000000000000,
                                                        backupCount=5)
    peer_handler.setFormatter(formatter)
    peer_logger.removeHandler(handler)
    peer_logger.addHandler(peer_handler)

    peer_logger.info('Peer_' + str(peer_id) + '_(AS' + str(str(peer_as)) + ')_started.')

    while True:

        while True:
            bgp_msg = queue_server_peer.get()

            if bgp_msg is not None:

                if 'announce' in bgp_msg:

                    prefix = bgp_msg['announce'].prefix
                    as_path = bgp_msg['announce'].as_path

                    as_path = [65000] + as_path

                    # Update the set set of peer_as (useful when doing the naive solution)
                    #if len(as_path) > 0:
                        #peer_as_set.add(as_path[0])

                    # Update the RIB for this peer
                    old_as_path = rib.update(prefix, as_path)

                    # Remove the old as-path in the main graph for this prefix
                    G.remove(old_as_path, prefix)

                    # Add the new as-path in both the main graph and the graph of advertisments
                    G.add(as_path, prefix)

                    if encoding is not None:
                        encoding.advertisement(old_as_path, as_path)
                        bgp_msg['announce'] = add_as_path_encoding_to_route(bgp_msg['announce'], rib, encoding)
                    elif len(rib.rib) > run_encoding_threshold:
                        encoding = init_encoding()
                        bgp_msg['announce'] = add_as_path_encoding_to_route(bgp_msg['announce'], rib, encoding)
                    else:
                        routes_without_as_path_encoding.append(bgp_msg)

                    queue_peer_server.put(bgp_msg)

                if 'withdraw' in bgp_msg:

                    prefix = bgp_msg['withdraw'].prefix

                    #Withdraws get sent directly to the route server
                    queue_peer_server.put(bgp_msg)

                    # Create the encoding if not done yet
                    if encoding is None:
                        encoding = init_encoding()

                    # Update the RIB for this peer
                    as_path = rib.withdraw(prefix)

                    # Remove the old as-path in the main graph for this prefix
                    G.remove(as_path, prefix)

                    # Add the withdrawn as-path in the graph of withdraws
                    G_W.add(as_path)

                    # Update the queue of withdraws
                    if as_path != []:
                        bgp_msg['withdraw'].as_path = as_path
                        W_queue.append(bgp_msg)

                    # Update the encoding
                    encoding.withdraw(as_path)

                #elif'state' in bgp_msg['neighbor'] and bgp_msg['neighbor']['state'] == 'down':

                    #queue_peer_server.put(bgp_msg)

                    # CLOSE this peer. Clear all the topologies, ribs, queues, bursts, etc
                    #if current_burst is not None:
                       # best_edge_set, best_fm_score, best_TP, best_FP, best_FN = burst_prediction(current_burst, G, G_W, W_queue, p_w, r_w, bpa_algo, peer_as_set)
                        #current_burst.fd_predicted.write('PREDICTION_END_CLOSE|'+bpa_algo+'|'+str(len(current_burst))+'|'+str(best_fm_score)+'|'+str(best_TP)+'|'+str(best_FN)+'|'+str(best_FP)+'\n')
                        #current_burst.fd_predicted.write('PREDICTION_END_EDGE|')
                        #res = ''
                        #depth = 9999999999
                        #for e in best_edge_set:
                            #depth = min(G_W.get_depth(e[0], e[1]), depth)
                            #res += str(e[0])+'-'+str(e[1])+','

                        #current_burst.fd_predicted.write(res[:len(res)-1]+'|'+str(depth)+'\n')

                        #G_W.draw_graph(peer_as)

                        #current_burst.stop(bgp_msg['time'])
                        #current_burst = None

                    # Withdraw all the routes advertised by this peer

                    #peer_logger.info('Received CLOSE. CLEANING the peer.')

                    # Stop this peer
                    #os.kill(os.getpid(), signal.SIGTERM)
                #else:
                    #peer_logger.info(bgp_msg)

                #Ceck for routes without encoding, check for encdoding, send modified routes to route_server
                if len(routes_without_as_path_encoding)> 0:
                    if encoding is not None:
                        for unsent_bgp_msg in routes_without_as_path_encoding:
                            if 'withdraw' in bgp_msg:
                                if unsent_bgp_msg['announce'].prefix == bgp_msg['withdraw'].prefix:
                                    routes_without_as_path_encoding.pop(unsent_bgp_msg)
                                    continue
                            unsent_bgp_msg['announce'] = add_as_path_encoding_to_route(unsent_bgp_msg['announce'], rib, encoding)
                            queue_peer_server.put(unsent_bgp_msg)

                        routes_without_as_path_encoding = []

                # Make sure to compute start en end time of burst with a second granularity (only if ther is a burst)
                if current_burst is not None:
                    while (last_ts != bgp_msg['time']):
                        last_ts += 1

                        # Update the graph of withdraws
                        for w in W_queue.refresh_iter(last_ts):
                            current_burst.deleted_from_W_queue.append(w)

                        # Remove the current burst (if any) if it the size of the withdraws is lower than w_threshold (meaning it has finished)
                        if len(W_queue) < nb_withdrawals_burst_end: #current_burst.is_expired(bgp_msg.time):
                            # Execute BPA at the end of the burst if the burst is large enough
                            print "burst is over"
                            best_edge_set, best_fm_score, best_TP, best_FN, best_FP = burst_prediction(current_burst, G, G_W, W_queue, p_w, r_w, bpa_algo, peer_as_set)
                            current_burst.fd_predicted.write('PREDICTION_END|'+bpa_algo+'|'+str(len(current_burst))+'|'+str(best_fm_score)+'|'+str(best_TP)+'|'+str(best_FN)+'|'+str(best_FP)+'\n')
                            current_burst.fd_predicted.write('PREDICTION_END_EDGE|')

                            # Print some information about the prediction on the prediction file
                            res = ''
                            depth = 9999999999
                            for e in best_edge_set:
                                res += str(e[0])+'-'+str(e[1])+','
                                depth = min(G_W.get_depth(e[0], e[1]), depth)
                            current_burst.fd_predicted.write(res[:len(res)-1]+'|'+str(depth)+'\n')

                            #G_W.draw_graph(peer_as, G, current_burst, outfile='as_graph_'+str(current_burst.start_time)+'.dot', threshold=500)

                            # Update the graph of withdrawals
                            for w in current_burst.deleted_from_W_queue:
                                G_W.remove(w['withdraw'].as_path)

                            current_burst.stop(bgp_msg['time'])
                            current_burst = None
                            break
                        else:
                            current_burst.last_ts = last_ts

                # Update the graph of withdraws.)
                if current_burst is None:
                    for w in W_queue.refresh_iter(bgp_msg['time']):
                        G_W.remove(w['withdraw'].as_path)

                # Update the last timestamp seen
                last_ts = bgp_msg['time']

                # Add the updates in the real prefixes set of the burst, if any
                if current_burst is not None: #and not silent:
                    if 'announce' in bgp_msg:
                        current_burst.add_real_prefix(bgp_msg['time'], bgp_msg['announce'].prefix, 'A', bgp_msg['announce'].as_path)
                    if 'withdraw' in bgp_msg:
                        current_burst.add_real_prefix(bgp_msg['time'], bgp_msg['withdraw'].prefix, 'W', bgp_msg['withdraw'].as_path)

                # If we are not in the burst yet, we create the burst
                if current_burst is None and len(W_queue) >= nb_withdrawals_burst_start:
                    print "SWIFT STARTING BURST!!!"
                    burst_start_time = W_queue[100]['time'] if len(W_queue) > 100 else W_queue[0]['time']
                    current_burst = Burst(peer_id, bgp_msg['time'], win_size, burst_outdir, encoding, burst_start_time, silent)
                    next_bpa_execution = min_bpa_burst_size

                # Print some log ...
                if (bgp_msg['time'] > last_log_write) or bgp_msg['time']-last_log_write >= 3600:
                    peer_logger.info(str(int(bgp_msg['time']))+'\t'+str(len(rib))+'\t'+str(len(W_queue)))
                    last_log_write = bgp_msg['time']

                # Execute BPA if there is a burst and
                # i) the current burst is greater than the minimum required
                # ii) we have wait the number of withdrawals required per cycle or the queue is empty
                if current_burst is not None:
                    total_current_burst_size = len(current_burst)+nb_withdrawals_burst_start
                    if total_current_burst_size >= min_bpa_burst_size and total_current_burst_size > next_bpa_execution:
                        if nb_withdraws_per_cycle > 0 and total_current_burst_size < 12505:
                            next_bpa_execution += nb_withdraws_per_cycle
                        else:
                            next_bpa_execution = 999999999999
                        break

        #print ('Queue size: '+str(len(rib))+'\t'+str(len(W_queue))+'\t'+str(len(current_burst)+nb_withdrawals_burst_start))

        if current_burst is not None:

            # Compute the set of edges with the highest FM score
            best_edge_set, best_fm_score, best_TP, best_FP, best_FN = burst_prediction(current_burst, G, G_W, W_queue, p_w, r_w, bpa_algo, peer_as_set)
            # Load that set in the burst
            if not silent: burst_add_edge(current_burst, rib, encoding, bgp_msg['time'], best_edge_set, G, G_W, silent)

            # Inform the global RIB about the set of failed links
            for e in best_edge_set:
                depth_set = set()
                if G_W.has_edge(e[0], e[1]):
                    depth_set = depth_set.union(G_W[e[0]][e[1]]['depth'].keys())
                if G.has_edge(e[0], e[1]):
                    depth_set = depth_set.union(G[e[0]][e[1]]['depth'].keys())

                for d in depth_set:
                    if encoding.is_encoded(d, e[0], e[1]):


                            vmac_partial = ''
                            bitmask_partial = ''

                            for i in range(2, encoding.max_depth+2):
                                if i == d:
                                    vmac_partial += encoding.mapping[i].get_mapping_string(e[0])
                                    bitmask_partial += '1' * encoding.mapping[i].nb_bytes
                                elif i == d+1:
                                    vmac_partial += encoding.mapping[i].get_mapping_string(e[1])
                                    bitmask_partial += '1' * encoding.mapping[i].nb_bytes
                                else:
                                    if i in encoding.mapping:
                                        vmac_partial += '0' * encoding.mapping[i].nb_bytes
                                        bitmask_partial += '0' * encoding.mapping[i].nb_bytes

                            FR_message = {'FR': {'peer_id': peer_id, 'as_path_vmac': vmac_partial, 'as_path_bitmask': bitmask_partial, 'depth': d}}
                            FR_queue.put(FR_message)

                            print "FR_message:", FR_message, "best_edge", e

            # Print information about the perdiction in the predicted file
            current_burst.fd_predicted.write('PREDICTION|'+bpa_algo+'|'+str(len(current_burst))+'|'+str(best_fm_score)+'|'+str(best_TP)+'|'+str(best_FP)+'|'+str(best_FN)+'\n')
            current_burst.fd_predicted.write('PREDICTION_EDGE|')
            res = ''
            depth = 9999999999
            for e in best_edge_set:
                depth = min(G_W.get_depth(e[0], e[1]), depth)
                res += str(e[0])+'-'+str(e[1])+','
            current_burst.fd_predicted.write(res[:len(res)-1]+'|'+str(depth)+'\n')
