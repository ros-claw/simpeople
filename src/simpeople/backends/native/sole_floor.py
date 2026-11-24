"""Small authored floor relief queried at actual deformed shoe vertices."""
import numpy as np


class SoleFloor:
    def __init__(self,boxes=()):
        self.surfaces=[]
        for box in boxes:
            if box['kind'] in ['glass','light','wet'] or box.get('rot_z'):continue
            c=np.array(box['center'],float);h=np.array(box['size'],float)/2;top=float(c[2]+h[2])
            if -.001<=top<=.08:self.surfaces.append((c[:2]-h[:2],c[:2]+h[:2],top,box['name']))

    def heights(self,xy):
        xy=np.asarray(xy,float).reshape(-1,2);height=np.zeros(len(xy))
        for low,high,top,_ in self.surfaces:
            inside=np.all(xy>=low,axis=1)&np.all(xy<=high,axis=1);height[inside]=np.maximum(height[inside],top)
        return height

    def correction(self,world_points,clearance=.003):
        p=np.asarray(world_points,float);return max(0.,float(np.max(self.heights(p[:,:2])+clearance-p[:,2])))

    def set_phrase(self,phrase):
        for slots in phrase.slots.values():
            for slot in slots:slot['anchor'][2]=float(self.heights(slot['anchor'][None,:2])[0])+.004
