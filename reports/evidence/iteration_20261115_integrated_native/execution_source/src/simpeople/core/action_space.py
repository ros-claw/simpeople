"""Conservative floor space for full-body clips; no animation manipulation."""
import math


def action_cells(grid, center, radius):
    c=grid.cell;extent=radius+grid.margin
    return {(x,y) for x in range(math.floor((center[0]-extent)/c),math.ceil((center[0]+extent)/c)+1)
                  for y in range(math.floor((center[1]-extent)/c),math.ceil((center[1]+extent)/c)+1)
                  if math.dist(grid.point((x,y))[:2],center[:2])<=extent+c*.71}
