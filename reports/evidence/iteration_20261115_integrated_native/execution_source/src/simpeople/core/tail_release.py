"""Conservative, observation-driven reclamation of straight native corridors.

Only passed cells can be removed. This module never grants new cells, changes a
goal, or writes a pose. A two-metre trailing buffer remains reserved; unexpected
motion after reclamation requires the adapter to stop before replanning.
"""
import math


def straight_geometry(grid,points,requested_speed,allow_diagonal=False):
    a,b=points[0],points[-1];length=math.dist(a[:2],b[:2])
    if length<4:return 'short_segment'
    if requested_speed>StraightTail.MAX_SPEED_MPS:return 'requested_speed'
    if not allow_diagonal and all(x!=y for x,y in zip(grid.nearest(a),grid.nearest(b))):return 'grid_lane_change'
    direction=[(b[i]-a[i])/length for i in range(2)];previous=-math.inf
    for p in points:
        dx,dy=p[0]-a[0],p[1]-a[1];progress=dx*direction[0]+dy*direction[1]
        lateral=abs(dx*direction[1]-dy*direction[0])
        if lateral>.05 or abs(p[2]-a[2])>.03 or progress<previous-1e-6:return 'nonstraight_or_reversing'
        previous=progress
    return None


def conservative_swept_cells(grid,points):
    """Exact line/expanded-cell intersection, including tiny diagonal grazes.

    Required cells must be reserved BEFORE motion. No ownership is changed here.
    Inclusive cell edges conservatively retain boundary-only intersections.
    """
    result=set();cell=grid.cell;margin=grid.margin;half=cell/2
    for a,b in zip(points,points[1:]):
        ranges=[range(math.floor((min(a[i],b[i])-margin)/cell+.5),
                      math.floor((max(a[i],b[i])+margin)/cell+.5)+1) for i in range(2)]
        for x in ranges[0]:
            for y in ranges[1]:
                enter,leave=0.,1.
                for i,index in enumerate([x,y]):
                    low=index*cell-half-margin;high=index*cell+half+margin;delta=b[i]-a[i]
                    if abs(delta)<1e-12:
                        if not low<=a[i]<=high:enter=2.;break
                    else:
                        u,v=(low-a[i])/delta,(high-a[i])/delta
                        enter=max(enter,min(u,v));leave=min(leave,max(u,v))
                if enter<=leave:result.add((x,y))
    return result


class StraightTail:
    TRAIL_M=2.0
    PATH_TOLERANCE_M=.35
    MAX_SPEED_MPS=3.0
    MAX_SAMPLE_DT=.1
    REGRESSION_M=.25

    def __init__(self,grid,points,cells,now,requested_speed,*,allow_diagonal=False):
        self.grid=grid;self.points=[list(p) for p in points];self.original=set(cells)
        self.diagonal_mode=allow_diagonal
        self.released=set();self.peak=0.;self.last_time=now;self.last_position=list(points[0]);self.disabled=None;self.frozen=None
        a,b=points[0],points[-1];length=math.dist(a[:2],b[:2]);self.length=length
        self.origin=a;self.direction=[(b[i]-a[i])/length for i in range(2)] if length else [0,0]
        self.disabled=straight_geometry(grid,points,requested_speed,allow_diagonal)
        if self.disabled is None and allow_diagonal and not conservative_swept_cells(grid,points)<=self.original:
            self.disabled='incomplete_swept_claim'
        # Bounding boxes rather than centres: a released grid cell must be
        # wholly behind the trailing plane, including its half-cell extent.
        half=grid.cell/2;extent=half*sum(abs(x) for x in self.direction)
        self.cell_end={c:self.project(grid.point(c))[0]+extent for c in cells}

    def project(self,p):
        dx,dy=p[0]-self.origin[0],p[1]-self.origin[1];ux,uy=self.direction
        return dx*ux+dy*uy,abs(dx*uy-dy*ux)

    def observe(self,position,now,ready=True):
        """Return proposed removals or a brake reason; caller fences ownership."""
        if self.disabled:return {'remove':set(),'disabled':self.disabled}
        dt=now-self.last_time
        if dt<=0:return {'remove':set()}
        progress,lateral=self.project(position)
        speed=math.dist(position[:2],self.last_position[:2])/dt
        reason=('not_ready' if not ready else 'sample_gap' if dt>self.MAX_SAMPLE_DT+1e-6 else
                'off_path' if lateral>self.PATH_TOLERANCE_M else
                'vertical_deviation' if abs(position[2]-self.origin[2])>.1 else
                'overshoot' if progress>self.length+.5 else
                'regression' if progress<self.peak-self.REGRESSION_M else
                'body_outside_claim' if not self.grid.footprint(position)<=self.original-self.released else None)
        # Freeze further reclamation on a forward sample spike. The adapter
        # must also verify that the body remains in this generation's claim.
        # Regression, lateral deviation and missing observations still brake.
        if reason is None and speed>self.MAX_SPEED_MPS+.1:
            # Experimental diagonal mode uses the SAME already-checked path
            # bound for freeze-only handling. It never releases from a spike;
            # the adapter independently requires the body inside owned cells.
            freeze_lateral=self.PATH_TOLERANCE_M if self.diagonal_mode else .05
            if progress>=self.peak and lateral<=freeze_lateral:self.frozen='forward_sample_spike'
            else:reason='observed_speed'
        self.last_time=now;self.last_position=list(position)
        if reason:
            self.disabled=reason
            return {'remove':set(),'brake':reason if self.released else None,'disabled':reason}
        self.peak=max(self.peak,progress)
        if self.frozen:return {'remove':set(),'frozen':self.frozen,'progress_m':progress,'speed_mps':speed}
        cut=progress-self.TRAIL_M
        remove={c for c,end in self.cell_end.items() if c not in self.released and end<cut-.05}
        return {'remove':remove,'progress_m':progress,'trailing_cut_m':cut,'speed_mps':speed,'lateral_error_m':lateral}

    def commit(self,cells):
        """Only removals actually applied to the owned lease become history."""
        if not set(cells)<=self.original-self.released:raise ValueError('invalid or repeated tail removal')
        self.released.update(cells)
