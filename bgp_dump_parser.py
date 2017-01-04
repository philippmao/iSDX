#!/usr/bin/env python
#  Author:
#  Rudiger Birkner (NSG @ ETH Zurich)

import argparse
import signal
import sys


def main(argv):
    def signal_handler(signalling, frame):
        print('Processed ' + str(num_prefixes) + ' prefixes')
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    seen_prefixes = list()
    num_prefixes = 0

    with open(argv.outfile, 'w') as outfile:
        with open(argv.infile, 'r') as infile:
            for line in infile:
                num_prefixes += 1
                if num_prefixes % 100000 == 0:
                    print('Processed ' + str(num_prefixes) + ' prefixes')

                data = line.split('|')

                prefix, length = data[5].split('/')

                if prefix not in seen_prefixes:
                    seen_prefixes.append(prefix)

                    data[5] = prefix + '/24'
                    output = '|'.join(data)
                    outfile.write(output)

    print 'Processed ' + str(num_prefixes) + ' prefixes and got ' + str(len(seen_prefixes)) + ' unique prefixes'


''' main '''
if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('infile', help='path to input file')
    parser.add_argument('outfile', help='path of output file')

    args = parser.parse_args()

    main(args)