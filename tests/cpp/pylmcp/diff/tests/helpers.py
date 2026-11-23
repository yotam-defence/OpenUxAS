from pylmcp import Object
from pylmcp.message import Message


def kv_frame(key="k", value="v", entity=100, service=0):
    return Message(Object("KeyValuePair", Key=key, Value=value),
                   entity, service).pack()
