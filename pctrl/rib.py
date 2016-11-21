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

        self.mappings[primary_keys] = defaultdict(BGPRoute)
        for mapping in mappings:
            keys = tuple(mapping['keys'])
            self.mappings[keys] = defaultdict(set)

    def add(self, entry):
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
                values.append(key_items.prefix)
            elif 'neighbor' == key:
                keys.append('neighbor')
                values.append(key_items.neighbor)
            elif 'next_hop' == key:
                keys.append('next_hop')
                values.append(key_items.next_hop)
            elif 'origin' == key:
                keys.append('origin')
                values.append(key_items.origin)
            elif 'as_path' == key:
                keys.append('as_path')
                values.append(key_items.as_path)
            elif 'communities' == key:
                keys.append('communities')
                values.append(key_items.communities)
            elif 'med' == key:
                keys.append('med')
                values.append(key_items.med)
            elif 'atomic_aggregate' == key:
                keys.append('atomic_aggregate')
                values.append(key_items.atomic_aggregate)

        keys = tuple(keys)
        values = tuple(values)

        entry_ids = list(self.mappings[keys][values])

        results = None
        if all_entries:
            results = list()
            for entry_id in entry_ids:
                if entry_id in self.entries:
                    results.append(self.entries[entry_id])
        else:
            for entry_id in entry_ids:
                if entry_id in self.entries:
                    results.append(self.entries[entry_id])
                    break

        return results

    def delete(self, key_items):
        keys = list()
        values = list()
        for key in key_items.keys():
            if 'prefix' == key:
                keys.append('prefix')
                values.append(key_items.prefix)
            elif 'neighbor' == key:
                keys.append('neighbor')
                values.append(key_items.neighbor)
            elif 'next_hop' == key:
                keys.append('next_hop')
                values.append(key_items.next_hop)
            elif 'origin' == key:
                keys.append('origin')
                values.append(key_items.origin)
            elif 'as_path' == key:
                keys.append('as_path')
                values.append(key_items.as_path)
            elif 'communities' == key:
                keys.append('communities')
                values.append(key_items.communities)
            elif 'med' == key:
                keys.append('med')
                values.append(key_items.med)
            elif 'atomic_aggregate' == key:
                keys.append('atomic_aggregate')
                values.append(key_items.atomic_aggregate)

        keys = tuple(keys)
        values = tuple(values)

        entry_ids = list(self.mappings[keys][values])

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

                if del_key == self.primary_keys:
                    del mapping[del_key]
                else:
                    mapping[del_key].remove(entry_id)

            del self.entries[entry_id]


def pretty_print(rib_entry, filter=None):
    if isinstance(rib_entry, list):
        for entry in rib_entry:
            print '|'
            for key, value in entry.iteritems():
                if not filter or (filter and key in filter):
                    print '-> ' + str(key) + ': ' + str(value)
    else:
        for key, value in rib_entry.iteritems():
            if not filter or (filter and key in filter):
                print '-> ' + str(key) + ': ' + str(value)


''' main '''
if __name__ == '__main__':
    myrib = LocalRIB(1, ['input'])

    routes = [
        {
            'table': 'input',
            'prefix': '100.0.0.0/8',
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
            'next_hop': '172.0.0.3',
            'origin': 'igp',
            'as_path': '7000,7100',
            'communities': '',
            'med': '',
            'atomic_aggregate': ''
        },
        {
            'table': 'input',
            'prefix': '70.0.0.0/8',
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
            'next_hop': '172.0.0.3',
            'origin': 'igp',
            'as_path': '7000,7100',
            'communities': '',
            'med': '',
            'atomic_aggregate': ''
        },
        {
            'table': 'input',
            'participant': 3,
            'prefix': '100.0.0.0/8',
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
            'next_hop': '172.0.0.3',
            'origin': 'igp',
            'as_path': '7000,7100',
            'communities': '',
            'med': '',
            'atomic_aggregate': ''
        },
        {
            'table': 'input',
            'prefix': '110.0.0.0/8',
            'next_hop': '172.0.0.1',
            'origin': 'igp',
            'as_path': '7000,7100',
            'communities': '',
            'med': '',
            'atomic_aggregate': ''
        },
    ]

    for route in routes:
        myrib.add(route['table'], route['participant'], route['prefix'], route)

    column_p = ['participant']
    results2 = myrib.get('input', column_p, None, {'prefix': '100.0.0.0/8'}, True)
    pretty_print(results2, ['participant'])

    print "+++++++++++++++++++++++++++++++++"

    results3 = myrib.get('input', ['participant', 'prefix', 'as_path'], None, {'prefix': '100.0.0.0/8'}, False)
    pretty_print(results3, ['participant', 'prefix', 'as_path'])

    print "+++++++++++++++++++++++++++++++++"

    results4 = myrib.get('input', None, ('participant', [2,3,4]), {'prefix': '100.0.0.0/8'}, True)
    pretty_print(results4)

    print "+++++++++++++++++++++++++++++++++"

    results4 = myrib.get('input', None, None, {'next_hop': '172.0.0.3', 'prefix': '100.0.0.0/8'}, True)
    pretty_print(results4)

    print "+++++++++++++++++++++++++++++++++"

    results4 = myrib.get('input', None, None, {'prefix': '100.0.0.0/8'}, True)
    pretty_print(results4)

    print "+++++++++++++++++++++++++++++++++"

    myrib.delete('input', {'participant': 4, 'prefix': '100.0.0.0/8'})
    results4 = myrib.get('input', None, None, {'prefix': '100.0.0.0/8'}, True)
    pretty_print(results4)

    print "+++++++++++++++++++++++++++++++++"

    results4 = myrib.get('input', None, None, {'participant': 1}, True)
    pretty_print(results4)

    print 'delete'

    myrib.delete('input', {'participant': 1})


    results4 = myrib.get('input', None, None, {'participant': 1}, True)
    pretty_print(results4)

    print "+++++++++++++++++++++++++++++++++"
