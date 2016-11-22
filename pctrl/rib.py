#!/usr/bin/env python
#  Author:
#  Rudiger Birkner (NSG @ ETHZ)

from collections import defaultdict, namedtuple

from bgp_route import BGPRoute


class LocalRIB(object):
    def __init__(self, participant_id, tables):
        self.participant_id = participant_id
        self.tables = dict()
        for table in tables:
            self.tables[table['name']] = Table(table['name'], table['primary_keys'], table['mappings'])

    def add(self, name, rib_entry):
        self.tables[name].add(rib_entry)

    def get(self, name, key_items, all_entries):
        return self.tables[name].get(key_items, all_entries)

    def delete(self, name, key_items):
        self.tables[name].delete(key_items)

    def commit(self):
        pass

    def rollback(self):
        pass


class Table(object):
    def __init__(self, name, primary_keys, mappings):
        self.name = name
        self.primary_keys = primary_keys
        self.num_entries = 0
        self.entries = dict()
        self.mappings = dict()

        self.mappings[primary_keys] = dict()
        for mapping in mappings:
            keys = tuple(mapping)
            self.mappings[keys] = defaultdict(set)

    def add(self, entry):
        # first check if the entry already exists
        tmp_entry = dict()
        for p_key in self.primary_keys:
            if 'prefix' == p_key:
                tmp_entry['prefix'] = entry.prefix
            elif 'neighbor' == p_key:
                tmp_entry['neighbor'] = entry.neighbor
            elif 'next_hop' == p_key:
                tmp_entry['next_hop'] = entry.next_hop
            elif 'origin' == p_key:
                tmp_entry['origin'] = entry.origin
            elif 'as_path' == p_key:
                tmp_entry['as_path'] = entry.as_path
            elif 'communities' == p_key:
                tmp_entry['communities'] = entry.communities
            elif 'med' == p_key:
                tmp_entry['med'] = entry.med
            elif 'atomic_aggregate' == p_key:
                tmp_entry['atomic_aggregate'] = entry.atomic_aggregate
        entry_keys = tuple(tmp_entry.values())

        if entry_keys in self.mappings[self.primary_keys]:
            self.delete(tmp_entry)

        # insert entry into main db
        self.entries[self.num_entries] = entry

        # add reference to entry for all required mappings
        for m_keys in self.mappings.keys():
            new_keys = list()

            for key in m_keys:
                if 'prefix' == key:
                    new_keys.append(entry.prefix)
                elif 'neighbor' == key:
                    new_keys.append(entry.neighbor)
                elif 'next_hop' == key:
                    new_keys.append(entry.next_hop)
                elif 'origin' == key:
                    new_keys.append(entry.origin)
                elif 'as_path' == key:
                    new_keys.append(entry.as_path)
                elif 'communities' == key:
                    new_keys.append(entry.communities)
                elif 'med' == key:
                    new_keys.append(entry.med)
                elif 'atomic_aggregate' == key:
                    new_keys.append(entry.atomic_aggregate)

            new_keys = tuple(new_keys)

            mapping = self.mappings[m_keys]
            if m_keys == self.primary_keys:
                mapping[new_keys] = self.num_entries
            else:
                mapping[new_keys].add(self.num_entries)

        self.num_entries += 1

    def get(self, key_items, all_entries):
        keys = list()
        values = list()
        for key in key_items.keys():
            if 'prefix' == key:
                keys.append('prefix')
                values.append(key_items['prefix'])
            elif 'neighbor' == key:
                keys.append('neighbor')
                values.append(key_items['neighbor'])
            elif 'next_hop' == key:
                keys.append('next_hop')
                values.append(key_items['next_hop'])
            elif 'origin' == key:
                keys.append('origin')
                values.append(key_items['origin'])
            elif 'as_path' == key:
                keys.append('as_path')
                values.append(key_items['as_path'])
            elif 'communities' == key:
                keys.append('communities')
                values.append(key_items['communities'])
            elif 'med' == key:
                keys.append('med')
                values.append(key_items['med'])
            elif 'atomic_aggregate' == key:
                keys.append('atomic_aggregate')
                values.append(key_items['atomic_aggregate'])

        keys = tuple(keys)
        values = tuple(values)

        results = list()
        if values in self.mappings[keys]:
            tmp_item = self.mappings[keys][values]
            if isinstance(tmp_item, set):
                entry_ids = list(tmp_item)
            else:
                entry_ids = [tmp_item]

            if all_entries:
                results = list()
                for entry_id in entry_ids:
                    if entry_id in self.entries:
                        results.append(self.entries[entry_id])
            else:
                for entry_id in entry_ids:
                    if entry_id in self.entries:
                        results = self.entries[entry_id]
                        break
        return results

    def delete(self, key_items):
        keys = list()
        values = list()
        for key in key_items.keys():
            if 'prefix' == key:
                keys.append('prefix')
                values.append(key_items['prefix'])
            elif 'neighbor' == key:
                keys.append('neighbor')
                values.append(key_items['neighbor'])
            elif 'next_hop' == key:
                keys.append('next_hop')
                values.append(key_items['next_hop'])
            elif 'origin' == key:
                keys.append('origin')
                values.append(key_items['origin'])
            elif 'as_path' == key:
                keys.append('as_path')
                values.append(key_items['as_path'])
            elif 'communities' == key:
                keys.append('communities')
                values.append(key_items['communities'])
            elif 'med' == key:
                keys.append('med')
                values.append(key_items['med'])
            elif 'atomic_aggregate' == key:
                keys.append('atomic_aggregate')
                values.append(key_items['atomic_aggregate'])

        keys = tuple(keys)
        values = tuple(values)

        tmp_item = self.mappings[keys][values]
        if isinstance(tmp_item, set):
            entry_ids = list(tmp_item)
        else:
            entry_ids = [tmp_item]

        for entry_id in entry_ids:
            entry = self.entries[entry_id]

            for keys, mapping in self.mappings.iteritems():
                del_key = list()
                for key in keys:
                    if 'prefix' == key:
                        del_key.append(entry.prefix)
                    elif 'neighbor' == key:
                        del_key.append(entry.neighbor)
                    elif 'next_hop' == key:
                        del_key.append(entry.next_hop)
                    elif 'origin' == key:
                        del_key.append(entry.origin)
                    elif 'as_path' == key:
                        del_key.append(entry.as_path)
                    elif 'communities' == key:
                        del_key.append(entry.communities)
                    elif 'med' == key:
                        del_key.append(entry.med)
                    elif 'atomic_aggregate' == key:
                        del_key.append(entry.atomic_aggregate)

                del_key = tuple(del_key)

                if keys == self.primary_keys:
                    del mapping[del_key]
                else:
                    mapping[del_key].remove(entry_id)

            del self.entries[entry_id]


def pretty_print(rib_entry):
    print "|prefix\t\t|neighbor\t|next hop\t|as path\t|"
    if isinstance(rib_entry, list):
        for entry in rib_entry:
            print str(entry)
    else:
        print str(rib_entry)

''' main '''
if __name__ == '__main__':
    tables = [
        {'name': 'input', 'primary_keys': ('prefix', 'neighbor'), 'mappings': [('prefix',), ('prefix', 'next_hop'), ('prefix', 'next_hop', 'neighbor')]},
    ]
    myrib = LocalRIB(1, tables)
    routes = [
        {
            'table': 'input',
            'prefix': '70.0.0.0/8',
            'neighbor': '172.0.0.1',
            'next_hop': '172.0.0.1',
            'origin': 'igp',
            'as_path': '7000,7100',
            'communities': '',
            'med': '',
            'atomic_aggregate': ''
        },
        {
            'table': 'input',
            'prefix': '90.0.0.0/8',
            'neighbor': '172.0.0.1',
            'next_hop': '172.0.0.1',
            'origin': 'igp',
            'as_path': '7000,7100',
            'communities': '',
            'med': '',
            'atomic_aggregate': ''
        },
        {
            'table': 'input',
            'prefix': '100.0.0.0/8',
            'neighbor': '172.0.0.1',
            'next_hop': '172.0.0.1',
            'origin': 'igp',
            'as_path': '7000,7100',
            'communities': '',
            'med': '',
            'atomic_aggregate': ''
        },
        {
            'table': 'input',
            'prefix': '100.0.0.0/8',
            'neighbor': '172.0.0.1',
            'next_hop': '172.0.0.1',
            'origin': 'igp',
            'as_path': '5000,8100',
            'communities': '',
            'med': '',
            'atomic_aggregate': ''
        },
        {
            'table': 'input',
            'prefix': '110.0.0.0/8',
            'neighbor': '172.0.0.1',
            'next_hop': '172.0.0.1',
            'origin': 'igp',
            'as_path': '7000,7100',
            'communities': '',
            'med': '',
            'atomic_aggregate': ''
        },
        {
            'table': 'input',
            'prefix': '80.0.0.0/8',
            'neighbor': '172.0.0.3',
            'next_hop': '172.0.0.3',
            'origin': 'igp',
            'as_path': '7000,7100',
            'communities': '',
            'med': '',
            'atomic_aggregate': ''
        },
        {
            'table': 'input',
            'prefix': '100.0.0.0/8',
            'neighbor': '172.0.0.3',
            'next_hop': '172.0.0.3',
            'origin': 'igp',
            'as_path': '7000,7100',
            'communities': '',
            'med': '',
            'atomic_aggregate': ''
        },
    ]

    for route in routes:
        myrib.add(route['table'], BGPRoute(route['prefix'], route['neighbor'],
                                           route['next_hop'], route['origin'],
                                           route['as_path'], route['communities'], route['med'],
                                           route['atomic_aggregate']))

    print 'Test - Single Get prefix'
    results = myrib.get('input', {'prefix': '100.0.0.0/8'}, False)
    pretty_print(results)

    print "+++++++++++++++++++++++++++++++++"

    print 'Test - All Get prefix - Expected 2 Entries'
    results = myrib.get('input', {'prefix': '100.0.0.0/8'}, True)
    pretty_print(results)

    print "+++++++++++++++++++++++++++++++++"

    print 'Test - All Get prefix + neighbor - Expected 1 Entry'
    results = myrib.get('input', {'prefix': '100.0.0.0/8', 'neighbor': '172.0.0.3'}, True)
    pretty_print(results)

    print "+++++++++++++++++++++++++++++++++"

    print 'Test - Key prefix next_hop - Expected 1 Entry'
    results = myrib.get('input', {'prefix': '100.0.0.0/8', 'next_hop': '172.0.0.3'}, True)
    pretty_print(results)

    print "+++++++++++++++++++++++++++++++++"

    print 'Test - Key prefix next_hop neighbor - Expected 1 Entry'
    results = myrib.get('input', {'prefix': '90.0.0.0/8', 'neighbor': '172.0.0.1', 'next_hop': '172.0.0.1'}, True)
    pretty_print(results)

    print "+++++++++++++++++++++++++++++++++"

    print 'Test - Delete key prefix neighbor - Expected 0 Entry'
    myrib.delete('input', {'prefix': '100.0.0.0/8', 'neighbor': '172.0.0.3'})
    results4 = myrib.get('input', {'prefix': '100.0.0.0/8', 'neighbor': '172.0.0.3'}, True)
    pretty_print(results4)

    print "+++++++++++++++++++++++++++++++++"

    print 'Test - Delete key prefix next_hop - Expected 0 Entry'
    myrib.delete('input', {'prefix': '80.0.0.0/8', 'next_hop': '172.0.0.3'})
    results4 = myrib.get('input', {'prefix': '80.0.0.0/8', 'next_hop': '172.0.0.3'}, True)
    pretty_print(results4)

    print "+++++++++++++++++++++++++++++++++"
