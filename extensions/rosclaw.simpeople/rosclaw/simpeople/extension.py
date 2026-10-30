"""Thin Kit lifecycle shell. Attaches to the current scene without replacing it."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid
import carb
import omni.ext
import omni.kit.app
import omni.timeline
import omni.usd

class SimPeopleExtension(omni.ext.IExt):
    def on_startup(self,ext_id):
        self.root=Path(__file__).resolve().parents[4]
        sys.path.insert(0,str(self.root/'src'))
        self.bridge=self.engine=self.journal=None;self.stage_id=None
        self.sub=omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(self.update,name='SimPeople main-thread supervisor')
        carb.log_info('SimPeople awaiting an open stage with a valid NavMesh. No stage is replaced.')

    def detach(self):
        if self.bridge:self.bridge.close();self.bridge=None
        if self.engine:
            for task in self.engine.tasks.values():
                self.engine.finish(task,'cancelled',{'code':'CANCELLED','message':'stage or extension closed'})
            self.journal.finish(self.engine,delivery='Kit extension')
            self.engine.backend.close()
        self.engine=self.journal=None

    def update(self,event):
        context=omni.usd.get_context();stage=context.get_stage()
        stage_id=context.get_stage_id() if stage else None
        if stage_id!=self.stage_id:
            self.detach();self.stage_id=stage_id
        if not stage:return
        if self.engine is None:
            from simpeople.backends.native.overlay import OverlayNativeBackend
            from simpeople.core.journal import Journal
            from simpeople.core.engine import Engine
            from simpeople.tools.bridge import Bridge
            settings=carb.settings.get_settings();prefix='/exts/rosclaw.simpeople/'
            file=settings.get(prefix+'semantics_file')
            semantics=json.loads(Path(file).read_text()) if file else {}
            backend=OverlayNativeBackend(self.root,semantics,settings.get(prefix+'allow_unverified'))
            directory=self.root/'runs'/('kit-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
            self.journal=Journal(directory,{'delivery':'Kit extension','stage_id':stage_id})
            self.engine=Engine(backend,self.journal)
            try:self.bridge=Bridge(self.engine,settings.get(prefix+'port') or 8768)
            except OSError as e:
                carb.log_error('SimPeople bridge could not start: '+str(e));self.detach();self.stage_id=None;return
        self.bridge.drain()
        timeline=omni.timeline.get_timeline_interface()
        self.engine.tick(timeline.get_current_time(),not timeline.is_playing())
        self.journal.sample(self.engine)

    def on_shutdown(self):
        self.sub=None;self.detach()
