"""Small independent evaluator for cooked camera arithmetic, with fake native reads.

This executes the emitted bytecode (including its selected-target loop), then
tests can project corners using an independent pinhole-camera oracle. It is not
a replacement for an actual-game camera acceptance run.
"""
import math
import numpy as np


def vector(value):
    if isinstance(value, dict): return np.array([float(value[k]) for k in ('X', 'Y', 'Z')])
    return np.asarray(value, dtype=float)


class CameraVM:
    def __init__(self, document, function, size, caster, targets, camera, viewport=(1280, 720)):
        self.document, self.function, self.size = document, function, size
        self.caster, self.camera = caster, camera
        self.event = {'m_pCamera': camera, 'm_TargetUnitList': targets}
        self.values = {function['LoadedProperties'][0]['Name']: self.event}
        self.viewport = dict(zip(('X', 'Y'), viewport))
        self.emitted = []

    @staticmethod
    def kind(node): return node['$type'].split('.')[-1].split(',')[0]

    @staticmethod
    def path(pointer): return pointer['New']['Path'][0]

    def run(self):
        code = self.function['ScriptBytecode']; positions = {}; position = 0
        for i, node in enumerate(code): positions[position] = i; position += self.size(node)
        pc = 0
        for _ in range(10000):
            node = code[pc]; kind = self.kind(node)
            if kind in ('EX_Return', 'EX_EndOfScript'): return self.emitted
            if kind == 'EX_Jump': pc = positions[node['CodeOffset']]; continue
            if kind == 'EX_JumpIfNot' and not self.evaluate(node['BooleanExpression']):
                pc = positions[node['CodeOffset']]; continue
            if kind != 'EX_JumpIfNot': self.evaluate(node)
            pc += 1
        raise AssertionError('Camera bytecode did not terminate')

    def evaluate(self, node, context=None):
        kind = self.kind(node)
        if kind == 'EX_Let':
            result = self.evaluate(node['Expression'], context)
            self.values[self.path(node['Value'])] = result; return result
        if kind == 'EX_LocalVariable': return self.values[self.path(node['Variable'])]
        if kind == 'EX_InstanceVariable': return context[self.path(node['Variable'])]
        if kind == 'EX_StructMemberContext':
            return self.evaluate(node['StructExpression'], context)[self.path(node['StructMemberExpression'])]
        if kind == 'EX_Context_FailSilent':
            obj = self.evaluate(node['ObjectExpression'], context)
            return self.evaluate(node['ContextExpression'], obj) if obj is not None else None
        if kind == 'EX_ArrayGetByRef': return self.evaluate(node['ArrayVariable'], context)[self.evaluate(node['ArrayIndex'], context)]
        if kind in ('EX_IntConst', 'EX_ByteConst', 'EX_IntConstByte', 'EX_FloatConst', 'EX_DoubleConst', 'EX_NameConst', 'EX_StringConst'): return node['Value']
        if kind == 'EX_IntZero': return 0
        if kind in ('EX_NoObject', 'EX_Nothing'): return None
        if kind in ('EX_True', 'EX_False'): return kind == 'EX_True'
        if kind in ('EX_VectorConst', 'EX_RotationConst'): return {k: float(v) for k, v in node['Value'].items() if not k.startswith('$')}
        if kind == 'EX_SoftObjectConst': return self.evaluate(node['Value'], context)
        if kind == 'EX_ArrayConst': return [self.evaluate(item, context) for item in node['Elements']]
        if kind == 'EX_StructConst': return [self.evaluate(item, context) for item in node['Value']]
        if kind == 'EX_LocalVirtualFunction':
            assert node['VirtualFunctionName'] == 'SeqBattleEvent'
            self.emitted.append(self.evaluate(node['Parameters'][1], context)); return None
        if kind not in ('EX_CallMath', 'EX_FinalFunction'): raise AssertionError(kind)
        name = self.document['Imports'][-node['StackNode']-1]['ObjectName']
        if name == 'GetComponentBounds':
            sprite = self.evaluate(node['Parameters'][0], context)
            for param, value in zip(node['Parameters'][1:], (sprite['origin'], sprite['extent'], 0.)):
                self.values[self.path(param['Variable'])] = value
            return None
        if name == 'BreakTransform':
            transform = self.evaluate(node['Parameters'][0], context)
            for param, value in zip(node['Parameters'][1:], (transform['location'], transform['rotation'], transform['scale'])):
                self.values[self.path(param['Variable'])] = value
            return None
        args = [self.evaluate(item, context) for item in node['Parameters']]
        if name == 'IsValid': return args[0] is not None
        if name == 'Array_IsValidIndex': return 0 <= args[1] < len(args[0])
        if name == 'GetBattleUnitByUnitIdWithVision':
            assert args == [7777, False]; return self.caster
        if name == 'GetCineCameraComponent': return context['Cine']
        if name == 'GetDefaultCameraTransform': return context['defaultTransform']
        if name == 'GetDefaultCurrentFocalLength': return context['defaultFocal']
        if name == 'GetCurrentFocalLength': return context['Cine']['CurrentFocalLength']
        if name == 'DoesSocketExist': return args[0] in context.get('sockets', {})
        if name == 'GetSocketLocation': return context['sockets'][args[0]]
        if name == 'GetScaledCapsuleRadius': return context['radius']
        if name == 'GetScaledCapsuleHalfHeight': return context['halfHeight']
        if name == 'GetViewportSize': return self.viewport
        if name in ('K2_GetActorLocation', 'K2_GetComponentLocation'): return context['location']
        if name == 'K2_GetComponentRotation': return context['rotation']
        if name in ('GetForwardVector', 'GetRightVector', 'GetUpVector'):
            p, y = math.radians(args[0]['Pitch']), math.radians(args[0]['Yaw'])
            assert args[0]['Roll'] == 0
            values = {'GetForwardVector': [math.cos(p)*math.cos(y), math.cos(p)*math.sin(y), math.sin(p)],
                'GetRightVector': [-math.sin(y), math.cos(y), 0],
                'GetUpVector': [-math.sin(p)*math.cos(y), -math.sin(p)*math.sin(y), math.cos(p)]}
            return dict(zip(('X', 'Y', 'Z'), values[name]))
        if name in ('Conv_FloatToDouble', 'Conv_DoubleToFloat'): return float(args[0])
        if name in ('FMin', 'FMax'): return (min if name == 'FMin' else max)(args)
        if name.startswith('GreaterEqual_'): return args[0] >= args[1]
        if name.startswith('Greater_'): return args[0] > args[1]
        if name == 'Dot_VectorVector': return float(vector(args[0]) @ vector(args[1]))
        if name == 'VSize': return float(np.linalg.norm(vector(args[0])))
        if name == 'MakeVector': return dict(zip(('X', 'Y', 'Z'), args))
        if name == 'Vector_GetAbs': return dict(zip(('X', 'Y', 'Z'), np.abs(vector(args[0]))))
        if name in ('Add_VectorVector', 'Subtract_VectorVector', 'Multiply_VectorFloat'):
            v = vector(args[0])
            result = v + vector(args[1]) if name == 'Add_VectorVector' else v - vector(args[1]) if name == 'Subtract_VectorVector' else v * args[1]
            return dict(zip(('X', 'Y', 'Z'), result))
        if name.startswith('Add_'): return args[0] + args[1]
        if name.startswith('Subtract_'): return args[0] - args[1]
        if name.startswith('Multiply_'): return args[0] * args[1]
        if name.startswith('Divide_'): return args[0] / args[1]
        raise AssertionError(name)
