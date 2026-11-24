"""Search around older admission fences without granting any exception.

The final destination is a planning hypothesis for preexisting drainers. Before
executing a first leg the adapter must still verify the complete physical escape
and use its unchanged admission predicate. An edge here is never a lease.
"""


class FairEdges:
    def __init__(self, grid, edges, gate, route_id, goal_cells):
        self.grid = grid
        self.edges = edges
        self.gate = gate
        self.route_id = route_id
        self.goal_cells = set(goal_cells)
        self.cache = {}

    def allows(self, start, end):
        if self.route_id not in self.gate.pending:
            return False
        return not self.gate.blockers(self.route_id, self.grid.sweep(start, end), self.goal_cells)

    def get(self, node, default=None):
        if node not in self.grid.nodes:
            return default
        if node not in self.cache:
            start = self.grid.point(node)
            self.cache[node] = [other for other in self.edges.get(node, ())
                                if self.allows(start, self.grid.point(other))]
        return self.cache[node]
