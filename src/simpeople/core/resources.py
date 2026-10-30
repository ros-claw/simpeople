"""Episode-scoped, FIFO leases used by seats and reserved passages."""
from collections import defaultdict, deque

class Resources:
    def __init__(self):
        self.owners={}
        self.waiters=defaultdict(deque)

    def acquire(self, resource, actor):
        if self.owners.get(resource)==actor: return True
        queue=self.waiters[resource]
        if actor not in queue: queue.append(actor)
        if resource not in self.owners and queue[0]==actor:
            queue.popleft(); self.owners[resource]=actor
            return True
        return False

    def release(self, actor, resource=None):
        for key in list(self.owners):
            if self.owners[key]==actor and (resource is None or key==resource): del self.owners[key]
        for key, queue in self.waiters.items():
            if (resource is None or key==resource) and actor in queue: queue.remove(actor)

    def snapshot(self):
        return {'owners':dict(self.owners),'queues':{k:list(v) for k,v in self.waiters.items() if v}}
