class SimPeopleError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.details = details

    def as_dict(self):
        stage=self.details.get('stage')
        if stage is None:
            stage=('transport' if self.code in {'BACKEND_UNAVAILABLE','BRIDGE_TIMEOUT','QUEUE_FULL'} else
                   'cleanup' if self.code in {'STOP_FAILED','CANCELLED','QUEUE_EXIT_BLOCKED'} else
                   'admission' if self.code in {'RESOURCE_BUSY','ACTOR_BUSY','CONTROLLER_BUSY','ADMISSION_FULL','RESOURCE_OCCUPIED'} else
                   'navigation' if self.code in {'TARGET_BLOCKED','TARGET_UNREACHABLE'} else
                   'execution' if self.code in {'BACKEND_TASK_FAILED','BACKEND_ERROR','TIMEOUT','INTERNAL_ERROR'} else 'validation')
        retry=self.details.get('retry_class','rescope' if self.code in {'SESSION_MISMATCH','EPISODE_MISMATCH','CONTROLLER_STALE'} else
                               'inspect_outcome' if stage in {'execution','cleanup','transport'} else
                               'wait_or_cancel' if stage=='admission' else 'repair_request')
        return {'code':self.code,'message':str(self),'details':self.details,'stage':stage,'retry_class':retry}
