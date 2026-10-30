"""Loopback HTTP transport. Worker threads enqueue data, never touch Kit/USD."""
from concurrent.futures import Future, TimeoutError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from queue import Queue, Empty, Full
import threading
import time
from simpeople.core.errors import SimPeopleError

class Bridge:
    def __init__(self,engine,port=8768):
        self.engine=engine;self.queue=Queue(maxsize=256);self.closed=False
        bridge=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_POST(self):
                if self.path!='/rpc':return self.reply(404,{'error':{'code':'NOT_FOUND'}})
                if self.headers.get('Origin'):
                    return self.reply(403,{'error':{'code':'ORIGIN_REJECTED'}})
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=1_000_000:raise SimPeopleError('INVALID_REQUEST','invalid body size')
                    request=json.loads(self.rfile.read(size))
                    if not isinstance(request,dict) or not isinstance(request.get('params',{}),dict):
                        raise SimPeopleError('INVALID_REQUEST','object required')
                    future=Future()
                    bridge.queue.put_nowait((request,future,time.time()))
                    result=future.result(timeout=30)
                    self.reply(200,result)
                except Full:self.reply(503,{'error':{'code':'QUEUE_FULL','message':'retry with same request_id'}})
                except TimeoutError:self.reply(504,{'error':{'code':'BRIDGE_TIMEOUT','message':'outcome unknown; retry same request_id'}})
                except SimPeopleError as e:self.reply(400,{'error':e.as_dict()})
                except (ValueError,TypeError) as e:self.reply(400,{'error':{'code':'INVALID_REQUEST','message':str(e)}})
            def reply(self,status,value):
                data=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
                try:
                    self.send_response(status);self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
                except (BrokenPipeError,ConnectionResetError):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def drain(self):
        # Bound work per frame so command traffic cannot starve animation.
        for _ in range(32):
            try:request,future,received=self.queue.get_nowait()
            except Empty:break
            self.engine.event('command_applied',method=request.get('method'),received_wall_time=received)
            try:response={'result':self.engine.call(request.get('method',''),request.get('params',{}))}
            except SimPeopleError as e:response={'error':e.as_dict()}
            except (KeyError,TypeError,ValueError) as e:response={'error':{'code':'INVALID_REQUEST','message':str(e)}}
            except Exception as e:response={'error':{'code':'INTERNAL_ERROR','message':str(e)}}
            if not future.done():future.set_result(response)

    def close(self):
        self.closed=True;self.server.shutdown();self.server.server_close()
        while not self.queue.empty():
            _,f,_=self.queue.get_nowait()
            if not f.done():f.set_result({'error':{'code':'BACKEND_UNAVAILABLE','message':'bridge shut down'}})
