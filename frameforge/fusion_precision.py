"""Precision in the captured image-node subset, not full preference inheritance."""
import math
import struct


DEPTH_NAMES = {0: 'Default (8-bit)', 1: '8-bit integer', 2: '16-bit integer',
               3: '16-bit float', 4: '32-bit float'}


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def quantize_value(value, depth):
    value = f32(value)
    if depth in (0, 1):
        return f32(math.floor(min(1, max(0, value))*255+.5)/255)
    if depth == 2:
        return f32(round(f32(min(1, max(0, value))*65535))/65535)
    if depth == 3:
        if value == 0:
            return value
        magnitude = min(abs(value), 65504)
        step = 2**max(-24, math.floor(math.log2(magnitude))-10)
        return math.copysign(math.floor(magnitude/step)*step, value)
    return value


def quantize_image(source, output, depth):
    if depth == 4:
        return [f'[{source}]null[{output}]']
    channels = (('r', 'r'), ('g', 'g'), ('b', 'b'), ('a', 'alpha'))
    if depth in (0, 1):
        expressions = ':'.join(f"{c}='round(clip({sample}(X,Y),0,1)*255)/255'" for c, sample in channels)
        return [f'[{source}]geq={expressions}[{output}]']
    if depth == 2:
        scaled = output+'_scaled'
        multiply = ':'.join(f"{c}='clip({sample}(X,Y),0,1)*65535'" for c, sample in channels)
        expressions = []
        for c, sample in channels:
            value = f'{sample}(X,Y)'
            expressions.append(f"{c}='if(eq(mod({value},1),0.5),2*round({value}/2),round({value}))/65535'")
        return [f'[{source}]geq={multiply}[{scaled}]', f'[{scaled}]geq='+':'.join(expressions)+f'[{output}]']
    if depth == 3:
        expressions = []
        for c, sample in channels:
            expr = (f'st(0,{sample}(X,Y));if(eq(ld(0),0),ld(0),'
                    'st(1,min(abs(ld(0)),65504));'
                    'st(2,pow(2,max(-24,floor(log(ld(1))/log(2))-10)));'
                    '(gt(ld(0),0)-lt(ld(0),0))*floor(ld(1)/ld(2))*ld(2))')
            expressions.append(f"{c}='{expr}'")
        return [f'[{source}]geq='+':'.join(expressions)+f'[{output}]']
    raise ValueError('Invalid Fusion image depth')
