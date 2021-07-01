import uvicorn
import jedi
import argparse
import functools
import socket
from contextlib import closing
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from typing import Optional, List
from pydantic import BaseModel

class Params(BaseModel):
    source: str
    line: int
    column: int
    path: Optional[str] = None

class Request(BaseModel):
    jsonrpc: float
    id: int
    method: str
    params: Params

class Response(BaseModel):
    jsonrpc: float
    id: int
    result: Optional[List] = None

#----- copied and adapted from anaconda-mode script
def script_method(f):
    @functools.wraps(f)
    def wrapper(request: Request, venv):
        result = f(jedi.Script(request.params.source,
                               path=request.params.path,
                               environment=venv),
                   request.params.line, request.params.column)
        return result
    return wrapper

def process_definitions(f):
    @functools.wraps(f)
    def wrapper(script, line, column):
        definitions = f(script, line, column)
        if len(definitions) == 1 and not definitions[0].module_path:
            return '%s is defined in %s compiled module' % (
                definitions[0].name, definitions[0].module_name)
        return [[str(definition.module_path),
                 definition.line,
                 definition.column,
                 definition.get_line_code().strip()]
                for definition in definitions
                if definition.module_path] or None
    return wrapper

@script_method
def complete(script, line, column):
    return [[definition.name, definition.type]
            for definition in script.complete(line, column)]

@script_method
def company_complete(script, line, column):
    return [[definition.name,
             definition.type,
             definition.docstring(),
             str(definition.module_path),
             definition.line]
            for definition in script.complete(line, column)]

@script_method
def show_doc(script, line, column):
    return [[definition.module_name, definition.docstring()]
            for definition in script.infer(line, column)]

@script_method
@process_definitions
def infer(script, line, column):
    return script.infer(line, column)

@script_method
@process_definitions
def goto(script, line, column):
    return script.goto(line, column)

@script_method
@process_definitions
def get_references(script, line, column):
    return script.get_references(line, column)

@script_method
def eldoc(script, line, column):
    signatures = script.get_signatures(line, column)
    if len(signatures) == 1:
        signature = signatures[0]
        return [signature.name,
                signature.index,
                [param.description[6:] for param in signature.params]]
#-----

def find_free_port():
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]

port = find_free_port()
print(f"anaconda_mode port {port}")

parser = argparse.ArgumentParser()
parser.add_argument("cachedir")
parser.add_argument("ip")
parser.add_argument("venv")
args = vars(parser.parse_args())
print(args)

venv = jedi.create_environment(args['venv'], safe=False)

app = FastAPI()

def results_driver(request: Request):
    methods = dict((method.__name__, method) for method in
                   [complete, company_complete, show_doc,
                    infer, goto, get_references, eldoc])
    method = methods.get(request.method)
    if method:
        return method(request, venv)

def handle_request(request: Request):
    result = results_driver(request)
    if result:
        return Response(**request.dict(), result=result)
    else:
        return Response(**request.dict())

@app.post("/", response_model=Response)
async def process_request(request: Request):
    response = handle_request(request)
    return jsonable_encoder(response)

uvicorn.run(app, host=args['ip'], port=port)
