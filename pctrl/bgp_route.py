class BGPRoute:
    def __init__(self, prefix, neighbor, next_hop, origin, as_path, communities, med, atomic_aggregate):
        self.prefix = prefix
        self.neighbor = neighbor
        self.next_hop = next_hop
        self.origin = origin
        self.as_path = as_path
        self.communities = communities
        self.med = med
        self.atomic_aggregate = atomic_aggregate

    def __cmp__(self, other):
        # Comparison according to BGP decision process:
        # ---- 0. [Vendor Specific - Cisco has a "Weight"]
        # ---- 1. Highest Local Preference
        # 2. Lowest AS Path Length
        # ---- 3. Lowest Origin type - Internal preferred over external
        # 4. Lowest  MED
        # ---- 5. eBGP learned over iBGP learned - prefer to have traffic leave as early as possible
        # ---- 6. Lowest IGP cost to border routes
        # 7. Lowest Router ID (tie breaker!)
        #
        # We only implement steps 2, 4, 7

        if other is None:
            return -1

        # compare AS path length - shorter better
        if len(self.as_path) < len(other.as_path):
            return 1
        elif len(self.as_path) > len(other.as_path):
            return -1

        # compare MED, but only when advertised by the same AS
        elif self.as_path[0] == other.as_path[0]:
            if self.med < other.med:
                return -1
            elif self.med > other.med:
                return 1

        # compare router id under the assumption that the neighbor ip is also the id
        if self.neighbor < other.neighbor:
            return 1
        elif self.neighbor > other.neighbor:
            return -1

        return 0

    def __str__(self):
        return str(self.prefix)+'\t'+str(self.next_hop)+'\t'+str(self.as_path)+'\t'