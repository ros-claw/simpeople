"""FIFO resource leases and bounded admission, released only by fenced cleanup."""
from .admission import Admission,INSIDE

class Resources:
    def __init__(self,max_waiters=32,on_event=None,clock=None):
        self.admission=Admission(max_waiters,on_event);self.clock=clock or (lambda:0.)
    @staticmethod
    def key(actor,token):return tuple(token) if token is not None else ('legacy',actor)
    @property
    def owners(self):
        return {q:self.admission.tickets[k]['actor_id'] for q,r in self.admission.resources.items() for k in r['order'] if self.admission.tickets[k]['status'] in INSIDE}
    @property
    def owner_tokens(self):
        return {q:(None if len(self.admission.tickets[k]['lease_token'])==2 and self.admission.tickets[k]['lease_token'][0]=='legacy' else self.admission.tickets[k]['lease_token']) for q,r in self.admission.resources.items() for k in r['order'] if self.admission.tickets[k]['status'] in INSIDE}
    def acquire(self,resource,actor,token=None):
        key=self.key(actor,token);previous=self.admission.find(resource,key)
        if token is None and previous and previous['status'] not in {'waiting','admitted','serving','exiting'}:
            self.admission.keys.pop((resource,key),None)
        ticket=self.admission.request_admission(resource,key,self.clock(),actor_id=actor)
        if ticket['status']=='rejected':
            from .errors import SimPeopleError
            raise SimPeopleError('ADMISSION_FULL','resource admission is full',resource_id=resource,ticket=ticket)
        return ticket['status'] in INSIDE
    def ticket(self,resource,actor,token=None):return self.admission.find(resource,self.key(actor,token))
    def release(self,actor,resource=None,token=None):
        key=self.key(actor,token)
        for q,group in self.admission.snapshot(resource).items():
            for row in group['tickets']:
                if row['actor_id']==actor and row['lease_token'] in {('legacy',actor),key}:
                    self.admission.release(row['lease_token'],self.clock(),resource_id=q,physical_clear=True)
    def snapshot(self):
        groups=self.admission.snapshot()
        return {'owners':self.owners,'queues':{q:[t['actor_id'] for t in r['tickets'] if t['status']=='waiting'] for q,r in groups.items() if any(t['status']=='waiting' for t in r['tickets'])},
                'owner_tokens':self.owner_tokens,'admission':groups}
