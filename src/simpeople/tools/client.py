import json
import urllib.request
import urllib.error
import urllib.parse
from simpeople.core.errors import SimPeopleError

def call(method,params=None,endpoint='http://127.0.0.1:8768'):
    parsed=urllib.parse.urlparse(endpoint)
    if parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost','::1'}:
        raise SimPeopleError('ENDPOINT_INVALID','bridge endpoint must be loopback HTTP')
    data=json.dumps({'method':method,'params':params or {}},allow_nan=False).encode()
    req=urllib.request.Request(endpoint.rstrip('/')+'/rpc',data=data,headers={'Content-Type':'application/json'})
    try:
        # A machine-wide HTTP proxy must never receive local simulation commands.
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req,timeout=35) as r:result=json.load(r)
    except urllib.error.HTTPError as e:
        result=json.load(e)
    except (urllib.error.URLError,TimeoutError) as e:
        raise SimPeopleError('BACKEND_UNAVAILABLE',str(e)) from e
    if 'error' in result:
        err=result['error'];raise SimPeopleError(err['code'],err.get('message',''),**err.get('details',{}))
    return result['result']
