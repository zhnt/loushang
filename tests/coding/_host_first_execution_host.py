"""Deterministic provider/tool probes around the production managed entry."""
import asyncio
import json
import os
import runpy
from pathlib import Path
from time import monotonic

from loushang.agent import synthetic_model_transport
from loushang.agent.types import AgentToolResult
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, ToolCall, Usage
from loushang.coding.managed_local import CodingManagedLocalCommandV1
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import DirectExecution

home = Path(os.environ['LOUSHANG_HOME'])


async def probe(call, context):
    cwd = Path(context.cwd)
    label = call.arguments['label']
    with (home / 'entered.jsonl').open('a') as output:
        output.write(json.dumps({'pid': os.getpid(), 'cwd': str(cwd), 'label': label}) + '\n')
    deadline = monotonic() + 60
    while not (home / 'release').exists():
        assert monotonic() < deadline, 'Host First model gate expired'
        await asyncio.sleep(.01)
    marker = (cwd / 'marker').read_text()
    with (cwd / 'effects.jsonl').open('a') as output:
        output.write(json.dumps({'label': label, 'cwd': str(cwd), 'marker': marker}) + '\n')
    return AgentToolResult(content=[TextPart(type='text', text=f'{label}:{marker}:{cwd}')], details={})


@synthetic_model_transport
async def stream(model, context, options=None):
    latest = context.messages[-1]
    tool = latest.role == 'user'
    text = latest.content if isinstance(latest.content, str) else ''.join(p.text for p in latest.content if isinstance(p, TextPart))
    message = AssistantMessage(endpoint='anthropic-messages', role='assistant',
        content=[ToolCall(type='toolCall', id='probe', name='workspace_probe', arguments={'label': text})] if tool else [TextPart(type='text', text=text)],
        api='anthropic-messages', provider='faux', model='faux-model', response_id=None,
        usage=Usage(input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}),
        stop_reason='toolUse' if tool else 'stop', error_message=None, timestamp=0.)
    output = AssistantMessageEventStream()
    output.push({'type': 'start', 'partial': message})
    output.push({'type': 'done', 'reason': message.stop_reason, 'message': message})
    return output


original = CodingManagedLocalCommandV1.__init__


def initialize(self, launch, **kwargs):
    tool = ToolDefinition(name='workspace_probe', label='Workspace probe', description='Read the selected workspace marker',
        parameters={'type': 'object', 'properties': {'label': {'type': 'string'}}, 'required': ['label'], 'additionalProperties': False},
        execution=DirectExecution(probe))
    original(self, launch, **{**kwargs, 'model': Model(id='faux-model', name='Faux', provider='faux', endpoint='anthropic-messages',
        capabilities=Capabilities(input=('text',), context_window=128000, max_tokens=4096)), 'stream_fn': stream, 'tools': [tool]})


CodingManagedLocalCommandV1.__init__ = initialize
runpy.run_module('loushang.coding.managed_process', run_name='__main__')
