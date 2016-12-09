import argparse
from collections import deque


class BGPMessagesQueue(deque):
    def __init__(self, time):
        super(BGPMessagesQueue, self).__init__()
        self.time = time

    """
    Remove all the bgp messages in the queue that have expired
    """
    def refresh(self, ts):
        while len(self) > 0 and ts - self[0].time > self.time:
            self.popleft()

    """
    Remove all the bgp messages in the queue that have expired.
    And yields the expired messages.
    """
    def refresh_iter(self, ts):
        while len(self) > 0 and ts - self[0].time > self.time:
            yield self.popleft()

"""
Remove duplicate ASes in case of AS-path prepending.
Check for loops in the as-path.
Return the non-duplicated AS-path or None if there was a loop.
"""
def clean_aspath(as_path):
    prev = None
    as_set = set()
    final_as_path = []

    for asn in as_path:
        if asn != prev:
            if asn in as_set:
                return []
            else:
                as_set.add(asn)
                final_as_path.append(asn)
        prev = asn
    return final_as_path

if __name__ == '__main__':

    parser = argparse.ArgumentParser("This script parses bgp messages.")
    parser.add_argument("infile", type=str, help="Infile")
    args = parser.parse_args()
    infile = args.infile

    with open(infile, 'r') as fd:
        for line in fd.readlines():
            bgp_msg = parse(line)
            print bgp_msg

    print clean_aspath([1,2,3,3,3,4,4,4,4,5])
