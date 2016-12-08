import sys
import os
import select
import logging
import logging.handlers
import signal
import cPickle as pickle
from bgproute import BGPRoute
from rib_global import RIBGlobal
import atexit
import time
from vnh import VirtualNextHops, FlowsQueue

class RIBPeer:
    def __init__(self):
        self.rib = {}

    """
    Update (or create) the AS path for a prefix and returns the previous AS path used
    """
    def update(self, prefix, as_path):
        if prefix in self.rib:
            as_path = self.rib[prefix]
        else:
            as_path = []
        self.rib[prefix] = as_path

        return as_path

    """
    Delete this prefix, and returns the last AS path known for this prefix
    """
    def withdraw(self, prefix):
        if prefix in self.rib:
            as_path = self.rib[prefix]
            del self.rib[prefix]
            return as_path
        else:
            return []

    def __len__(self):
        return len(self.rib)

    def __str__(self):
        res = ''
        for i in self.rib:
            res += str(i)+'\t'+str(self.rib[i])+'\n'
        return res

# Define the logger
LOG_DIRNAME = 'log'
rib_logger = logging.getLogger('RibLogger')
rib_logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s :: %(levelname)s :: %(message)s')
handler = logging.handlers.RotatingFileHandler(LOG_DIRNAME+'/rib', maxBytes=200000000000000, backupCount=5)
handler.setFormatter(formatter)
rib_logger.addHandler(handler)

rib_logger.info('RIB launched!')


