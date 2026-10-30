"""Reversible Kit session ownership, without editing the user's scene layers."""
import uuid
from pxr import Sdf, Usd
import omni.usd
from .adapter import NativeBackend


class OverlayNativeBackend(NativeBackend):
    def __init__(self,*args,**kwargs):
        stage=omni.usd.get_context().get_stage()
        self.session_layer=stage.GetSessionLayer()
        self.owned_layer=Sdf.Layer.CreateAnonymous('SimPeopleSession.usda')
        self.session_layer.subLayerPaths.insert(0,self.owned_layer.identifier)
        self.closed=False
        try:
            super().__init__(*args,namespace='/SimPeople_'+uuid.uuid4().hex,**kwargs)
        except Exception:
            self.session_layer.subLayerPaths.remove(self.owned_layer.identifier)
            raise

    def spawn(self,*args,**kwargs):
        with Usd.EditContext(self.stage,self.owned_layer):
            return super().spawn(*args,**kwargs)

    def despawn(self,*args,**kwargs):
        with Usd.EditContext(self.stage,self.owned_layer):
            return super().despawn(*args,**kwargs)

    def move_prop(self,*args,**kwargs):
        with Usd.EditContext(self.stage,self.owned_layer):
            return super().move_prop(*args,**kwargs)

    def inspect_scene(self):
        return {**super().inspect_scene(),'managed_namespace':self.namespace,
                'authoring_layer':self.owned_layer.identifier,'authoring_mode':'session_overlay'}

    def close(self):
        if self.closed:return
        self.closed=True
        # Remove only our own session sublayer, including registered prop overrides.
        # A stage switch can already have removed the old native controllers.
        for handle in list(self.instances):
            try:self.stop(handle)
            except Exception:pass
        super().close()
        # Behavior can author transient pose specs into its own output layer.
        # The unique namespace did not exist before attachment; remove only that
        # subtree from the local layer stack, never from referenced asset layers.
        for layer in self.stage.GetLayerStack():
            if layer is self.owned_layer:continue
            if layer.GetPrimAtPath(self.namespace):
                edits=Sdf.BatchNamespaceEdit();edits.Add(self.namespace,Sdf.Path.emptyPath)
                if not layer.Apply(edits):raise RuntimeError('could not clean native pose namespace')
        layers=list(self.session_layer.subLayerPaths)
        if self.owned_layer.identifier in layers:
            layers.remove(self.owned_layer.identifier)
            self.session_layer.subLayerPaths=layers
        self.instances.clear();self.observations.clear()
