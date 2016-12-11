#  Author:
#  Arpit Gupta (Princeton)
#  Robert MacDavid (Princeton)


import argparse
import atexit
import json
import os
from signal import signal, SIGTERM
from sys import exit
from threading import RLock, Thread
import time

import sys
np = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if np not in sys.path:
    sys.path.append(np)
import util.log
from xctrl.flowmodmsg import FlowModMsgBuilder

from lib import PConfig
from ss_lib import vmac_part_port_match,  vmac_next_hop_match_iSDXmac, vmac_next_hop_mask_iSDXmac ,vmac_next_hop_match_iSDXmac_bitsring, vmac_next_hop_mask_iSDXmac_bitstring
from ss_rule_scheme import update_outbound_rules, init_inbound_rules, init_outbound_rules, msg_clear_all_outbound, ss_process_policy_change
from supersets import SuperSets
from FEC import FEC
from BEC import BEC

TIMING = True


class ParticipantController(object):
    def __init__(self, id, config_file, policy_file, logger):
        # participant id
        self.id = id
        self.logger = logger

        # used to signal termination
        self.run = True
        self.prefix_lock = {}

        # Initialize participant params
        self.cfg = PConfig(config_file, self.id)

        # load policies
        self.policies = self.load_policies(policy_file)

        # The port 0 MAC is used for tagging outbound rules as belonging to us
        self.port0_mac = self.cfg.port0_mac

        self.nexthop_2_part = self.cfg.get_nexthop_2_part()

        # VNHs related params
        self.num_VNHs_in_use = 0
        self.VNH_2_vmac = {}
        self.vmac_2_VNH = {}
        self.FEC_list = {}
        self.prefix_2_FEC = {}
        self.prefix_2_VNH_nrfp = {}
        #SWIFT Backup equivalence class
        self.BEC_list = {((-1, -1, -1), (-1, -1, -1)): {'id': 1, 'as_path': None, 'backup_nbs': None, 'as_path_vmac': None}}
        self.prefix_2_BEC = {}
        self.BECid_FECid_2_VNH = {}
        self.prefix_2_BEC_nrfp = {}
        self.max_depth = self.cfg.Swift_vmac["max_depth"]
        self.nexthops_nb_bits = self.cfg.Swift_vmac["nexthops_nb_bits"]
        self.Swift_hit_priority = self.cfg.Swift_vmac["Swift flowrule priority"]
        self.vnh_2_BFEC = {}
        #swift tag dic mapping ip to mac
        self.tag_dict = {}
        self.prefix_2_FEC_nrfp = {}
        self.prefix_2_BEC_nrfp = {}

        # Superset related params
        if self.cfg.isSupersetsMode():
            self.supersets = SuperSets(self, self.cfg.vmac_options)

        # Keep track of flow rules pushed
        self.dp_pushed = []
        # Keep track of flow rules which are scheduled to be pushed
        self.dp_queued = []

    def xstart(self):
        # Start all clients/listeners/whatevs
        self.logger.info("Starting controller for participant")

        # ExaBGP Peering Instance
        self.bgp_instance = self.cfg.get_bgp_instance()
        self.FEC = FEC(self)
        self.BEC = BEC(self)

        # Route server client, Reference monitor client, Arp Proxy client
        self.xrs_client = self.cfg.get_xrs_client(self.logger)
        self.xrs_client.send({'msgType': 'hello', 'id': self.cfg.id, 'peers_in': self.cfg.peers_in, 'peers_out': self.cfg.peers_out, 'ports': self.cfg.get_ports()})

        self.arp_client = self.cfg.get_arp_client(self.logger)
        self.arp_client.send({'msgType': 'hello', 'macs': self.cfg.get_macs()})

        # Participant Server for dynamic route updates
        self.participant_server = self.cfg.get_participant_server(self.id, self.logger)
        if self.participant_server is not None:
            self.participant_server.start(self)

        self.refmon_client = self.cfg.get_refmon_client(self.logger)

        # Send flow rules for initial policies to the SDX's Reference Monitor
        self.initialize_dataplane()
        self.push_dp()

        # Start the event handlers
        ps_thread_arp = Thread(target=self.start_eh_arp)
        ps_thread_arp.daemon = True
        ps_thread_arp.start()

        ps_thread_xrs = Thread(target=self.start_eh_xrs)
        ps_thread_xrs.daemon = True
        ps_thread_xrs.start()

        ps_thread_arp.join()
        ps_thread_xrs.join()
        self.logger.debug("Return from ps_thread.join()")

    def sanitize_policies(self, policies):

        port_count = len(self.cfg.ports)

        # sanitize the inbound policies
        if 'inbound' in policies:
            for policy in policies['inbound']:
                if 'action' not in policy:
                    continue
                if 'fwd' in policy['action'] and int(policy['action']['fwd']) >= port_count:
                    policy['action']['fwd'] = 0
                    self.logger.warn('Port count in inbound policy is too big.  Setting it to 0.')

        # sanitize the outbound policies
        if 'outbound' in policies:
            for policy in policies['outbound']:
                # If no cookie field, give it cookie 0. (Should be OK for multiple flows with same cookie,
                # though they can't be individually removed.)
                if 'cookie' not in policy:
                    policy['cookie'] = 0
                    self.logger.warn('Cookie not specified in new policy.  Defaulting to 0.')

        return policies

    def load_policies(self, policy_file):
        # Load policies from file

        with open(policy_file, 'r') as f:
            policies = json.load(f)

        return self.sanitize_policies(policies)

    def initialize_dataplane(self):
        "Read the config file and update the queued policy variable"

        self.logger.info("Initializing inbound rules")

        final_switch = "main-in"
        if self.cfg.isMultiTableMode():
            final_switch = "main-out"

        self.FEC.init_FEC_assignment()
        self.BEC.init_BEC_assignment()
        self.init_vnh_assignment()

        rule_msgs = init_inbound_rules(self.id, self.policies,
                                        self.supersets, final_switch)
        self.logger.debug("Rule Messages INBOUND:: "+json.dumps(rule_msgs))

        rule_msgs2 = init_outbound_rules(self, self.id, self.policies,
                                        self.supersets, final_switch)
        self.logger.debug("Rule Messages OUTBOUND:: "+json.dumps(rule_msgs2))

        if 'changes' in rule_msgs2:
            if 'changes' not in rule_msgs:
                rule_msgs['changes'] = []
            rule_msgs['changes'] += rule_msgs2['changes']

        #TODO: Initialize Outbound Policies from RIB
        self.logger.debug("Rule Messages:: "+json.dumps(rule_msgs))
        if 'changes' in rule_msgs:
            self.dp_queued.extend(rule_msgs["changes"])

    def push_dp(self):
        '''
        (1) Check if there are any policies queued to be pushed
        (2) Send the queued policies to reference monitor
        '''

        self.logger.debug("Pushing current flow mod queue:")

        # it is crucial that dp_queued is traversed chronologically
        fm_builder = FlowModMsgBuilder(self.id, self.refmon_client.key)
        for flowmod in self.dp_queued:
            self.logger.debug("MOD: "+str(flowmod))
            if (flowmod['mod_type'] == 'remove'):
                fm_builder.delete_flow_mod(flowmod['mod_type'], flowmod['rule_type'], flowmod['cookie'][0], flowmod['cookie'][1])
            elif (flowmod['mod_type'] == 'insert'):
                fm_builder.add_flow_mod(**flowmod)
            else:
                self.logger.error("Unhandled flow type: " + flowmod['mod_type'])
                continue
            self.dp_pushed.append(flowmod)

        self.dp_queued = []
        self.refmon_client.send(json.dumps(fm_builder.get_msg()))

    def stop(self):
        "Stop the Participants' SDN Controller"

        self.logger.info("Stopping Controller.")

        # Signal Termination and close blocking listener
        self.run = False

    def start_eh_arp(self):
        self.logger.info("ARP Event Handler started.")

        while self.run:
            # need to poll since recv() will not detect close from this end
            # and need some way to shutdown gracefully.
            if not self.arp_client.poll(1):
                continue
            try:
                tmp = self.arp_client.recv()
            except EOFError:
                break

            data = json.loads(tmp)
            self.logger.debug("ARP Event received: %s", data)

            # Starting a thread for independently processing each incoming network event
            event_processor_thread = Thread(target=self.process_event, args=(data,))
            event_processor_thread.daemon = True
            event_processor_thread.start()

        self.arp_client.close()
        self.logger.debug("Exiting start_eh_arp")

    def start_eh_xrs(self):
        self.logger.info("XRS Event Handler started.")

        while self.run:
            # need to poll since recv() will not detect close from this end
            # and need some way to shutdown gracefully.
            if not self.xrs_client.poll(1):
                continue
            try:
                tmp = self.xrs_client.recv()
            except EOFError:
                break

            data = tmp
            self.logger.debug("XRS Event received: %s", data)

            self.process_event(data)

        self.xrs_client.close()
        self.logger.debug("Exiting start_eh_xrs")

    def process_event(self, data):
        "Locally process each incoming network event"

        #@TODO: when receiving swift FR push backup rules
        if 'FR' in data:
            print "FR in participant controller received"
            self.logger.debug("Event Received: FR request")
            FR_parameters = data['FR']
            self.process_FR(FR_parameters)

        if 'down' in data:
            print "processing down participant"
            down_ip = data['down']
            self.deal_with_local_failure(down_ip)
        if 'bgp' in data :
            self.logger.debug("Event Received: BGP Update.")
            update = data['bgp']
            # Process the incoming BGP updates from XRS
            #self.logger.debug("BGP Route received: "+str(route)+" "+str(type(route)))
            self.process_bgp_route(update)

        elif 'policy' in data:
            # Process the event requesting change of participants' policies
            self.logger.debug("Event Received: Policy change.")
            change_info = data['policy']
            self.process_policy_changes(change_info)

        elif 'arp' in data:
            (requester_srcmac, requested_vnh) = tuple(data['arp'])
            self.logger.debug("Event Received: ARP request for IP "+str(requested_vnh))
            self.process_arp_request(requester_srcmac, requested_vnh)

        else:
            self.logger.warn("UNKNOWN EVENT TYPE RECEIVED: "+str(data))

    #@TODO: Make sure the message type sent from route-server matches
    def process_FR(self, FR_parameters):
        peer_id = FR_parameters['peer_id']
        as_path_vmac = FR_parameters['as_path_vmac']
        as_path_bitmask = FR_parameters['as_path_bitmask']
        depth = FR_parameters['depth']
        rules = []
        print "FR with parameters as_path_vmac", as_path_vmac, as_path_bitmask ,depth
        if depth > self.max_depth:
            return
        for backup_ip in self.tag_dict.keys():
            print "backup_ip", backup_ip
            print "self.tag_dict:", self.tag_dict
            backup_part = self.nexthop_2_part[backup_ip]
            if backup_part != self.id:
                backup_vmac = ''
                backup_bitmask = ''
                for i in range(1, self.max_depth+1):
                    if i == depth:
                        backup_tag = self.tag_dict[backup_ip]
                        backup_vmac += bin(backup_tag)[2:].zfill(self.nexthops_nb_bits)
                        backup_bitmask += '1' * self.nexthops_nb_bits

                    else:
                        backup_vmac += '0' * self.nexthops_nb_bits
                        backup_bitmask += '0' * self.nexthops_nb_bits


                next_hop_match = vmac_next_hop_match_iSDXmac_bitsring(peer_id, self.supersets,only_isdx_vmac=True)
                next_hop_mask = vmac_next_hop_mask_iSDXmac_bitstring(self.supersets, only_isdx_vmac=True)

                vmac = next_hop_match + backup_vmac + as_path_vmac
                print "vmac", vmac, "next_hop_match:", next_hop_match, "backup_vamc", backup_vmac, "as_path_vmac", as_path_vmac
                vmac_bitmask = next_hop_mask + backup_bitmask + as_path_bitmask
                vmac = '{num:0{width}x}'.format(num=int(vmac, 2), width=48 / 4)
                vmac= ':'.join([vmac[i] + vmac[i + 1] for i in range(0, 48 / 4, 2)])
                vmac_bitmask = '{num:0{width}x}'.format(num=int(vmac_bitmask, 2), width=48 / 4)
                vmac_bitmask = ':'.join([vmac_bitmask[i] + vmac_bitmask[i + 1] for i in range(0, 48 / 4, 2)])

                match_args = {}
                match_args["eth_dst"] = (vmac, vmac_bitmask)

                print "FR match vmac:", vmac, vmac_bitmask
                #set dst mac to mac with best next hop
                dst_mac = vmac_next_hop_match_iSDXmac(backup_part, self.supersets)
                print "FR set dst_mac", dst_mac
                actions = {"set_eth_dst": dst_mac, "fwd": 'main-in'}
                rule = {"rule_type": "main-in", "priority": self.Swift_hit_priority,
                            "match": match_args, "action": actions, "mod_type": "insert",
                            }
                rules.append(rule)

        self.dp_queued.extend(rules)

        self.push_dp()


    def update_policies(self, new_policies, in_out):
        if in_out != 'inbound' and in_out != 'outbound':
            self.logger.exception("Illegal argument to update_policies: " + in_out)
            raise
        if in_out not in new_policies:
            return
        if in_out not in self.policies:
            self.policies[in_out] = []
        new_cookies = {x['cookie'] for x in new_policies[in_out] if 'cookie' in x}
        self.logger.debug('new_cookies: ' + str(new_cookies))

        # remove any items with same cookie (TODO: verify that this is the behavior we want)
        self.policies[in_out] = [x for x in self.policies[in_out] if x['cookie'] not in new_cookies]
        self.logger.debug('new_policies[io]: ' + str(new_policies[in_out]))
        self.policies[in_out].extend(new_policies[in_out])

    # Remove polices that match the cookies and return the list of cookies for removed policies
    def remove_policies_by_cookies(self, cookies, in_out):
        if in_out != 'inbound' and in_out != 'outbound':
            self.logger.exception("Illegal argument to update_policies: " + in_out)
            raise
        if in_out in self.policies:
            to_remove = [x['cookie'] for x in self.policies[in_out] if x['cookie'] in cookies]
            self.policies[in_out] = [x for x in self.policies[in_out] if x['cookie'] not in cookies]
            self.logger.debug('removed cookies: ' + str(to_remove) + ' from: ' + in_out)
            return to_remove
        return []

    def queue_flow_removals(self, cookies, in_out):
        removal_msgs = []
        for cookie in cookies:
            mod =  {"rule_type":in_out,
                    "cookie":(cookie,2**16-1), "mod_type":"remove"}
            removal_msgs.append(mod)
        self.logger.debug('queue_flow_removals: ' + str(removal_msgs))
        self.dp_queued.extend(removal_msgs)

    def process_policy_changes(self, change_info):
        if not self.cfg.isSupersetsMode():
            self.logger.warn('Dynamic policy updates only supported in SuperSet mode')
            return

        # First step towards a less brute force approach: Handle removals without having to remove everything
        if 'removal_cookies' in change_info:
            cookies = change_info['removal_cookies']
            removed_in_cookies = self.remove_policies_by_cookies(cookies, 'inbound')
            self.queue_flow_removals(removed_in_cookies, 'inbound')
            removed_out_cookies = self.remove_policies_by_cookies(cookies, 'outbound')
            self.queue_flow_removals(removed_out_cookies, 'outbound')
            if not 'new_policies' in change_info:
                self.push_dp()
                return

        # Remainder of this method is brute force approach: wipe everything and re-do it
        # This should be replaced by a more fine grained approach
        self.logger.debug("Wiping outbound rules.")
        wipe_msgs = msg_clear_all_outbound(self.policies, self.port0_mac)
        self.dp_queued.extend(wipe_msgs)

        self.logger.debug("pre-updated policies: " + json.dumps(self.policies))
        if 'removal_cookies' in change_info:
            cookies = change_info['removal_cookies']
            self.remove_policies_by_cookies(cookies, 'inbound')
            self.remove_policies_by_cookies(cookies, 'outbound')

        if 'new_policies' in change_info:
            new_policies = change_info['new_policies']
            self.sanitize_policies(new_policies)
            self.update_policies(new_policies, 'inbound')
            self.update_policies(new_policies, 'outbound')

        self.logger.debug("updated policies: " + json.dumps(self.policies))
        self.logger.debug("pre-recomputed supersets: " + json.dumps(self.supersets.supersets))

        self.initialize_dataplane()
        self.push_dp()

        # Send gratuitous ARP responses for all
        garp_required_FECs = self.prefix_2_FEC.values()['vnh']
        #garp_required_vnhs = self.VNH_2_prefix.keys()
        for FEC in garp_required_FECs:
            self.process_arp_request(None, FEC)
            
        return

        # Original code below...
        
        "Process the changes in participants' policies"
        # TODO: Implement the logic of dynamically changing participants' outbound and inbound policy
        '''
            change_info =
            {
                'removal_cookies' : [cookie1, ...], # Cookies of deleted policies
                'new_policies' :
                {
                    <policy file format>
                }

            }
        '''
        # remove flow rules for the old policies
        removal_msgs = []

        '''
        for cookie in change_info['removal_cookies']:
            mod =  {"rule_type":"outbound", "priority":0,
                    "match":match_args , "action":{},
                    "cookie":cookie, "mod_type":"remove"}
            removal_msgs.append(mod)
        '''

        self.dp_queued.extend(removal_msgs)


        # add flow rules for the new policies
        if self.cfg.isSupersetsMode():
            dp_msgs = ss_process_policy_change(self.supersets, add_policies, remove_policies, policies,
                                                self.port_count, self.port0_mac)
        else:
            dp_msgs = []

        self.dp_queued.extend(dp_msgs)

        self.push_dp()

        return 0




    def process_arp_request(self, part_mac, vnh):
        vmac = ""
        #if self.cfg.isSupersetsMode():
            #vmac = self.supersets.get_vmac(self, FEC)

        arp_responses = list()

        # if this is gratuitous, send a reply to the part's ID
        if part_mac is None:
            gratuitous = True
            # set fields appropriately for gratuitous arps
            vmac = self.supersets.get_vmac(self, vnh)
            i = 0
            self.VNH_2_vmac[vnh] = vmac
            self.vmac_2_VNH[vmac] = vnh
            for port in self.cfg.ports:
                eth_dst = vmac_part_port_match(self.id, i, self.supersets, False)
                arp_responses.append({'SPA': vnh, 'TPA': vnh,
                                   'SHA': vmac, 'THA': vmac,
                                   'eth_src': vmac, 'eth_dst': eth_dst})
                i += 1

        else: # if it wasn't gratuitous
            gratuitous = False
            # dig up the IP of the target participant
            if vnh not in self.VNH_2_vmac:
                return
            vmac = self.VNH_2_vmac[vnh]
            for port in self.cfg.ports:
                if part_mac == port["MAC"]:
                    part_ip = port["IP"]
                    break

            # set field appropriately for arp responses
            arp_responses.append({'SPA': vnh, 'TPA': part_ip,
                        'SHA': vmac, 'THA': part_mac,
                        'eth_src': vmac, 'eth_dst': part_mac})

        if gratuitous:
            self.logger.debug("Sending Gratuitious ARP: ")
        else:
            self.logger.debug("Sending ARP Response: ")

        for arp_response in arp_responses:
            arp_response['msgType'] = 'garp'
            self.arp_client.send(arp_response)


    def getlock(self, prefixes):
        prefixes.sort()
        hsh = "-".join(prefixes)
        if hsh not in self.prefix_lock:
            #self.logger.debug("First Lock:: "+str(hsh))
            self.prefix_lock[hsh] = RLock()
        #else:
            #self.logger.debug("Repeat :: "+str(hsh))
        return self.prefix_lock[hsh]

    def process_bgp_route(self, update):

        "Process each incoming BGP advertisement"
        tstart = time.time()

        #Check for local failure, push fast reroute rules if local failure
        #self.deal_with_local_failure(routes)

        # Map to update for each prefix in the route advertisement.
        self.bgp_instance.update(update)
        self.logger.debug("process_bgp_route:: "+str(update))
        # TODO: This step should be parallelized
        # TODO: The decision process for these prefixes is going to be same, we
        # should think about getting rid of such redundant computations.
        self.bgp_instance.decision_process(update)
        #assign FEC to prefix
        self.FEC.assignment(update)
        #assign BEC to prefix
        self.BEC.assignment(update)
        #assign VNH to FEC, BEC pair of prefix
        self.vnh_assignment(update)

        if TIMING:
            elapsed = time.time() - tstart
            self.logger.info("Time taken for decision process: " + str(elapsed))
            self.logger.debug("Time taken for decision process: " + str(elapsed))
            tstart = time.time()


        if self.cfg.isSupersetsMode():
            ################## SUPERSET RESPONSE TO BGP ##################
            # update supersets
            "Map the set of BGP updates to a list of superset expansions."
            ss_changes, ss_changed_prefs = self.supersets.update_supersets(self, update)

            if TIMING:
                elapsed = time.time() - tstart
                self.logger.debug("Time taken to update supersets: "+str(elapsed))
                tstart = time.time()

            # ss_changed_prefs are prefixes for which the VMAC bits have changed
            # these prefixes must have gratuitous arps sent
            garp_required_VNHs = []
            for prefix in ss_changed_prefs:
                BEC_id = self.prefix_2_BEC[prefix]['id']
                FEC_id = self.prefix_2_FEC[prefix]['id']
                garp_required_VNHs.append(self.BECid_FECid_2_VNH[(BEC_id,FEC_id)])

            "If a recomputation event was needed, wipe out the flow rules."
            if ss_changes["type"] == "new":
                self.logger.debug("Wiping outbound rules.")
                wipe_msgs = msg_clear_all_outbound(self.policies, self.port0_mac)
                self.dp_queued.extend(wipe_msgs)

                #if a recomputation was needed, all VMACs must be reARPed
                # TODO: confirm reARPed is a word
                #garp_required_vnhs = self.VNH_2_prefix.keys()
                garp_required_VNHs =[]
                for VNH in self.BECid_FECid_2_VNH.values():
                    garp_required_VNHs.append(VNH)
                #garp_required_vnhs = self.prefix_2_FEC.values()['vnh']

            if len(ss_changes['changes']) > 0:

                self.logger.debug("Supersets have changed: "+str(ss_changes))

                "Map the superset changes to a list of new flow rules."
                flow_msgs = update_outbound_rules(ss_changes, self.policies,
                        self.supersets, self.port0_mac)

                self.logger.debug("Flow msgs: "+str(flow_msgs))
                "Dump the new rules into the dataplane queue."
                self.dp_queued.extend(flow_msgs)

            if TIMING:
                elapsed = time.time() - tstart
                self.logger.debug("Time taken to deal with ss_changes: "+str(elapsed))
                tstart = time.time()

        ################## END SUPERSET RESPONSE ##################

        else:
            # TODO: similar logic for MDS
            self.logger.debug("Creating ctrlr messages for MDS scheme")

        self.push_dp()

        if TIMING:
            elapsed = time.time() - tstart
            self.logger.debug("Time taken to push dp msgs: "+str(elapsed))
            tstart = time.time()

        new_VNHs, announcements = self.bgp_instance.bgp_update_peer(update,self.prefix_2_VNH_nrfp,
                self.prefix_2_FEC, self.prefix_2_BEC, self.BECid_FECid_2_VNH, self.VNH_2_vmac, self.cfg.ports)

        """ Combine the VNHs which have changed BGP default routes with the
            VNHs which have changed supersets.
        """

        #new_FECs = set(new_FECs)

        new_VNHs = new_VNHs + garp_required_VNHs

        #remove duplicates
        new_VNHs = list(set(new_VNHs))

        #print self.id, "tag_dict", self.tag_dict
        #print self.id, "VNH_2_vmac", self.VNH_2_vmac
        #print "new_vnh_next_hops", new_VNHs

        # Send gratuitous ARP responses for all them
        for VNH in new_VNHs:
            self.process_arp_request(None, VNH)

        # Tell Route Server that it needs to announce these routes
        for announcement in announcements:
            # TODO: Complete the logic for this function
            self.send_announcement(announcement)

        if TIMING:
            elapsed = time.time() - tstart
            self.logger.info("Time taken to send garps/announcements: "+str(elapsed))
            self.logger.debug("Time taken to send garps/announcements: " + str(elapsed))
            tstart = time.time()

    def send_announcement(self, announcement):
        "Send the announcements to XRS"
        #self.logger.debug("Sending announcements to XRS: %s", announcement)
        self.xrs_client.send({'msgType': 'bgp', 'announcement': announcement})

    def vnh_assignment(self,update):
        if self.cfg.isSupersetsMode():
            if 'announce' in update:
                prefix = update['announce'].prefix
            if 'withdraw' in update:
                prefix = update['withdraw'].prefix
            if prefix:
                route = self.bgp_instance.get_routes('local', False, prefix = prefix)
                if route:
                    FEC_id = self.prefix_2_FEC[prefix]['id']
                    BEC_id = self.prefix_2_BEC[prefix]['id']
                    if (BEC_id, FEC_id) not in self.BECid_FECid_2_VNH:
                        self.num_VNHs_in_use += 1
                        vnh = str(self.cfg.VNHs[self.num_VNHs_in_use])
                        self.BECid_FECid_2_VNH[(BEC_id, FEC_id)] = vnh
                        self.vnh_2_BFEC[vnh] = [self.prefix_2_BEC[prefix], self.prefix_2_FEC[prefix]]
                    else:
                        vnh = self.BECid_FECid_2_VNH[(BEC_id, FEC_id)]
                        self.vnh_2_BFEC[vnh] = [self.prefix_2_BEC[prefix], self.prefix_2_FEC[prefix]]
                else:
                    BEC_id = self.prefix_2_BEC_nrfp[prefix]['id']
                    FEC_id = self.prefix_2_FEC_nrfp[prefix]['id']
                    self.prefix_2_VNH_nrfp[prefix] = self.BECid_FECid_2_VNH[(BEC_id,FEC_id)]





    def init_vnh_assignment(self):
        if self.cfg.isSupersetsMode():
            bgp_routes = self.bgp_instance.get_routes('local', True)
            for bgp_route in bgp_routes:
                prefix = bgp_route.prefix
                FEC_id = self.prefix_2_FEC[prefix]['id']
                BEC_id = self.prefix_2_BEC[prefix]['id']
                if (BEC_id, FEC_id) not in self.BECid_FECid_2_VNH:
                    self.num_VNHs_in_use += 1
                    vnh = str(self.cfg.VNHs[self.num_VNHs_in_use])
                    self.BECid_FECid_2_VNH[(BEC_id, FEC_id)] = vnh
                    self.vnh_2_BFEC[vnh] = [self.prefix_2_BEC[prefix], self.prefix_2_FEC[prefix]]

    def deal_with_local_failure(self,down_ip):
        route_list = []

        #@TODO: PUSH BACKUP RULES IF NECESSARY

        routes = self.bgp_instance.get_routes('input', True, neighbor=down_ip)
        for route_item in routes:
            route_list.append({'withdraw': route_item})

        self.bgp_instance.delete_all_routes('input', neighbor=down_ip)

        for route in route_list:
            self.process_bgp_route(route)

            #rules = []
            #for backup_ip in self.tag_dict:
                #backup_part = self.cfg.get_nexthop_2_part(backup_ip)
                #if backup_part != self.id:
                 #   backup_vmac = ''
                  #  backup_bitmask = ''
                   # for i in range(1, self.max_depth + 1):
                    #    if i == 1:
                     #       backup_tag = self.tag_dict[backup_ip]
                      #      backup_vmac += bin(backup_tag)[2:].zfill(self.nexthops_nb_bits)
#
 #                           backup_bitmask += '1' * self.nexthops_nb_bits
#
 #                       else:
  #                          backup_vmac += '0' * self.nexthops_nb_bits
   #                         backup_bitmask += '0' * self.nexthops_nb_bits
#
 #                   best_next_hop_vmac = vmac_next_hop_match_iSDXmac(self.cfg.get_nexthop_2_part(neighbor), self.supersets)
  #                  best_next_hop_mask = vmac_next_hop_mask_iSDXmac(self.cfg.get_nexthop_2_part(neighbor), self.supersets)



#                    vmac = backup_vmac + best_next_hop_vmac
 #                   vmac_bitmask = backup_bitmask +best_next_hop_mask
  #                  vmac = '{num:0{width}x}'.format(num=int(vmac, 2), width=48 / 4)
   #                 vmac = ':'.join([vmac[i] + vmac[i + 1] for i in range(0, 48 / 4, 2)])
    #                vmac_bitmask = '{num:0{width}x}'.format(num=int(vmac_bitmask, 2), width=48 / 4)
     #               vmac_bitmask = ':'.join([vmac_bitmask[i] + vmac_bitmask[i + 1] for i in range(0, 48 / 4, 2)])

#                    match_args = {}
 #                   match_args["eth_dst"] = (vmac, vmac_bitmask)
                    # set dst mac to mac with best next hop
  #                  dst_mac = vmac_next_hop_match_iSDXmac(backup_part, self.supersets)
   #                 actions = {"set_eth_dst": dst_mac, "fwd": 'main-in'}
    #                rule = {"rule_type": "swift", "priority": SWIFT_HIT_PRIORITY,
     #                       "match": match_args, "action": actions, "mod_type": "insert",
      #                      }
       #             rules.append(rule)

#            self.dp_queued.extend(rules)

 #           self.push_dp()


def get_prefixes_from_announcements(route):
    prefixes = []
    if 'update' in route['neighbor']['message']:
        if 'announce' in route['neighbor']['message']['update']:
            announce = route['neighbor']['message']['update']['announce']
            if 'ipv4 unicast' in announce:
                for next_hop in announce['ipv4 unicast'].keys():
                    for prefix in announce['ipv4 unicast'][next_hop].keys():
                        prefixes.append(prefix)

        elif 'withdraw' in route['neighbor']['message']['update']:
            withdraw = route['neighbor']['message']['update']['withdraw']
            if 'ipv4 unicast' in withdraw:
                for prefix in withdraw['ipv4 unicast'].keys():
                    prefixes.append(prefix)
    return prefixes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('dir', help='the directory of the example')
    parser.add_argument('id', type=int,
                   help='participant id (integer)')
    args = parser.parse_args()

    # locate config file
    # TODO: Separate the config files for each participant
    base_path = os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "..","examples",args.dir,"config"))
    config_file = os.path.join(base_path, "sdx_global.cfg")

    # locate the participant's policy file as well
    policy_filenames_file = os.path.join(base_path, "sdx_policies.cfg")
    with open(policy_filenames_file, 'r') as f:
        policy_filenames = json.load(f)
    policy_filename = policy_filenames[str(args.id)]

    policy_path = os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                            "..","examples",args.dir,"policies"))

    policy_file = os.path.join(policy_path, policy_filename)

    logger = util.log.getLogger("P_" + str(args.id))

    logger.info("Starting controller with config file: "+str(config_file))
    logger.info("and policy file: "+str(policy_file))

    # start controller
    ctrlr = ParticipantController(args.id, config_file, policy_file, logger)
    ctrlr_thread = Thread(target=ctrlr.xstart)
    ctrlr_thread.daemon = True
    ctrlr_thread.start()
    
    atexit.register(ctrlr.stop)
    signal(SIGTERM, lambda signum, stack_frame: exit(1))

    while ctrlr_thread.is_alive():
        try:
            ctrlr_thread.join(1)
        except KeyboardInterrupt:
            ctrlr.stop()

    logger.info("Pctrl exiting")


if __name__ == '__main__':
    main()
