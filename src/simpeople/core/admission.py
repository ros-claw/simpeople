"""Bounded, episode-scoped FIFO tickets. No clock expiry releases occupancy."""
import copy
import uuid
from .errors import SimPeopleError

ACTIVE={'waiting','admitted','serving','exiting'}
INSIDE={'admitted','serving','exiting'}

class Admission:
    def __init__(self,max_outside=8,on_event=None):
        if isinstance(max_outside,bool) or not isinstance(max_outside,int) or max_outside<0:raise ValueError('invalid outside limit')
        self.max_outside=max_outside;self.on_event=on_event;self.resources={};self.tickets={};self.keys={};self.sequence=0

    def configure(self,resource_id,capacity):
        if isinstance(capacity,bool) or not isinstance(capacity,int) or capacity<1:raise ValueError('invalid capacity')
        current=self.resources.setdefault(resource_id,{'capacity':capacity,'order':[]})
        if current['capacity']!=capacity:raise ValueError('capacity cannot change during an episode')

    def emit(self,kind,ticket,**extra):
        if not self.on_event:return
        token=ticket['lease_token'];scope={}
        if len(token)>=4:scope={'actor_instance_id':token[1],'task_id':token[3]}
        self.on_event(kind,actor_id=ticket['actor_id'],resource_id=ticket['resource_id'],
                      ticket=self.describe(ticket['ticket_id']),**scope,**extra)

    def request_admission(self,resource_id,lease_token,requested_sim_time,*,actor_id,capacity=1):
        self.configure(resource_id,capacity);token=tuple(lease_token);key=(resource_id,token)
        if key in self.keys:return self.describe(self.keys[key])
        self.sequence+=1
        row={'ticket_id':uuid.uuid4().hex,'resource_id':resource_id,'actor_id':actor_id,'lease_token':token,
             'requested_sim_time':float(requested_sim_time),'sequence':self.sequence,'status':'waiting',
             'admitted_sim_time':None,'ended_sim_time':None,'end_reason':None}
        rid=row['ticket_id'];self.tickets[rid]=row;self.keys[key]=rid;resource=self.resources[resource_id]
        active=[self.tickets[k] for k in resource['order']]
        if len(active)>=capacity+self.max_outside:
            row.update(status='rejected',ended_sim_time=float(requested_sim_time),end_reason='admission_full')
            self.emit('admission_requested',row);self.emit('admission_ended',row)
            return self.describe(rid)
        resource['order'].append(rid);self.emit('admission_requested',row)
        self.promote(resource_id,requested_sim_time)
        if row['status']=='waiting':self.emit('admission_queued',row)
        return self.describe(rid)

    def promote(self,resource_id,now):
        resource=self.resources[resource_id]
        inside=sum(self.tickets[k]['status'] in INSIDE for k in resource['order'])
        for rid in resource['order']:
            row=self.tickets[rid]
            if inside>=resource['capacity']:break
            if row['status']=='waiting':
                row.update(status='admitted',admitted_sim_time=float(now));inside+=1;self.emit('admission_granted',row)

    def describe(self,ticket_id):
        row=copy.deepcopy(self.tickets[ticket_id]);resource=self.resources[row['resource_id']];order=resource['order']
        row.update(capacity=resource['capacity'],outside_capacity=self.max_outside,
                   rank=order.index(ticket_id) if ticket_id in order else None,
                   inside=row['status'] in INSIDE,cancelled=row['status']=='cancelled')
        return row

    def find(self,resource_id,token):
        rid=self.keys.get((resource_id,tuple(token)))
        return self.describe(rid) if rid else None

    def transition(self,ticket_id,status,now):
        row=self.tickets[ticket_id]
        allowed={'admitted':{'serving','exiting'},'serving':{'exiting'},'exiting':set()}
        if row['status']==status:return
        if status not in allowed.get(row['status'],set()):raise ValueError('invalid ticket transition')
        row['status']=status;row[status+'_sim_time']=float(now)
        self.emit('admission_phase_changed',row)

    def release(self,lease_token,now,*,resource_id=None,physical_clear=False,reason='completed'):
        token=tuple(lease_token)
        for row in list(self.tickets.values()):
            if row['lease_token']!=token or row['status'] not in ACTIVE or resource_id is not None and row['resource_id']!=resource_id:continue
            if row['status'] in INSIDE and not physical_clear:
                raise SimPeopleError('RESOURCE_OCCUPIED','physical clearance is required to release an admitted lease',ticket_id=row['ticket_id'])
            row.update(status='completed' if reason=='completed' else 'cancelled',end_reason=reason,ended_sim_time=float(now))
            self.resources[row['resource_id']]['order'].remove(row['ticket_id']);self.emit('admission_ended',row)
            self.promote(row['resource_id'],now)

    def snapshot(self,resource_id=None):
        return {key:{'capacity':value['capacity'],'outside_capacity':self.max_outside,
                     'tickets':[self.describe(k) for k in value['order']]} for key,value in self.resources.items() if resource_id is None or key==resource_id}
