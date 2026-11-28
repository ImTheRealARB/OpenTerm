"""The built-in names of OpenTerm Script, as Python data.

This is a copy of `frontend/src/script/names.ts` (the TypeScript side is the master list: add a built-in there first).
`backend/tests/test_ts_mirrors.py` fails when the two lists drift apart, so edit both together.
`lib.*` (the chart's indicator catalog) is not listed here: it is TS only in v1, and the Python port refuses it at compile time.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Builtin:
    """One built-in name. `kind` is "var" (read without a call, like `close`) or "fn" (called with parentheses)."""

    name: str
    kind: str
    params: tuple = ()  # ((param name, default source text or None), ...)
    variadic: bool = False  # takes extra positional arguments after `params`
    ret: str = "any"
    stateful: bool = False  # keeps state per call site (ta.*)
    top_level: bool = False  # only allowed at the top level of the script


COLORS = {
    "red": "#f23645",
    "green": "#089981",
    "blue": "#2962ff",
    "orange": "#ff9800",
    "yellow": "#ffeb3b",
    "purple": "#9c27b0",
    "teal": "#00897b",
    "aqua": "#00bcd4",
    "lime": "#00e676",
    "fuchsia": "#e040fb",
    "maroon": "#880e4f",
    "navy": "#311b92",
    "olive": "#808000",
    "silver": "#b2b5be",
    "gray": "#787b86",
    "white": "#ffffff",
    "black": "#363a45"
}

PLOT_STYLES = ('line', 'stepline', 'histogram', 'columns', 'circles', 'area')
SHAPE_STYLES = ('triangleup', 'triangledown', 'circle', 'cross', 'diamond', 'arrowup', 'arrowdown', 'labelup', 'labeldown')
SHAPE_LOCATIONS = ('abovebar', 'belowbar', 'absolute')
TABLE_POSITIONS = ('top_left', 'top_right', 'bottom_left', 'bottom_right')
SOURCES = ('open', 'high', 'low', 'close', 'volume', 'hl2', 'hlc3', 'ohlc4')

# Accepted timeframe spellings, each mapped to its normal form.
TIMEFRAMES = {
    '1': '1m',
    '5': '5m',
    '15': '15m',
    '30': '30m',
    '60': '1h',
    '120': '2h',
    '240': '4h',
    '1m': '1m',
    '5m': '5m',
    '15m': '15m',
    '30m': '30m',
    '1h': '1h',
    '2h': '2h',
    '4h': '4h',
    '1D': '1D',
    'D': '1D',
    '1W': '1W',
    'W': '1W',
    '1M': '1M',
    'M': '1M',
}

# Caps (spec 1.7). Both engines use these numbers.
LIMITS = {
    'sourceChars': 20000,
    'nodes': 3000,
    'stepsPerRun': 5000000,
    'stepsPerBar': 100000,
    'arrayElements': 100000,
    'mapEntries': 50000,
    'lookback': 5000,
    'outputs': 64,
    'drawingsPerKind': 500,
    'alerts': 500,
}

# Every built-in, in the same order as names.ts.
_ROWS = [
    ('indicator', 'fn', (('title', None), ('overlay', 'false'), ('max_labels', '500')), False, 'void', False, True),
    ('open', 'var', (), False, 'number', False, False),
    ('high', 'var', (), False, 'number', False, False),
    ('low', 'var', (), False, 'number', False, False),
    ('close', 'var', (), False, 'number', False, False),
    ('volume', 'var', (), False, 'number', False, False),
    ('time', 'var', (), False, 'number', False, False),
    ('hl2', 'var', (), False, 'number', False, False),
    ('hlc3', 'var', (), False, 'number', False, False),
    ('ohlc4', 'var', (), False, 'number', False, False),
    ('bar_index', 'var', (), False, 'number', False, False),
    ('last_bar_index', 'var', (), False, 'number', False, False),
    ('barstate.isfirst', 'var', (), False, 'bool', False, False),
    ('barstate.islast', 'var', (), False, 'bool', False, False),
    ('na', 'var', (), False, 'number', False, False),
    ('na', 'fn', (('x', None),), False, 'bool', False, False),
    ('nz', 'fn', (('x', None), ('y', '0')), False, 'number', False, False),
    ('math.pi', 'var', (), False, 'number', False, False),
    ('math.e', 'var', (), False, 'number', False, False),
    ('math.abs', 'fn', (('x', None),), False, 'number', False, False),
    ('math.ceil', 'fn', (('x', None),), False, 'number', False, False),
    ('math.floor', 'fn', (('x', None),), False, 'number', False, False),
    ('math.round', 'fn', (('x', None), ('digits', '0')), False, 'number', False, False),
    ('math.sqrt', 'fn', (('x', None),), False, 'number', False, False),
    ('math.pow', 'fn', (('x', None), ('y', None)), False, 'number', False, False),
    ('math.exp', 'fn', (('x', None),), False, 'number', False, False),
    ('math.log', 'fn', (('x', None),), False, 'number', False, False),
    ('math.log10', 'fn', (('x', None),), False, 'number', False, False),
    ('math.max', 'fn', (('a', None), ('b', None)), True, 'number', False, False),
    ('math.min', 'fn', (('a', None), ('b', None)), True, 'number', False, False),
    ('math.avg', 'fn', (('a', None), ('b', None)), True, 'number', False, False),
    ('math.sign', 'fn', (('x', None),), False, 'number', False, False),
    ('ta.sma', 'fn', (('src', None), ('length', None)), False, 'number', True, False),
    ('ta.ema', 'fn', (('src', None), ('length', None)), False, 'number', True, False),
    ('ta.wma', 'fn', (('src', None), ('length', None)), False, 'number', True, False),
    ('ta.rma', 'fn', (('src', None), ('length', None)), False, 'number', True, False),
    ('ta.vwma', 'fn', (('src', None), ('length', None)), False, 'number', True, False),
    ('ta.rsi', 'fn', (('src', None), ('length', None)), False, 'number', True, False),
    ('ta.stdev', 'fn', (('src', None), ('length', None)), False, 'number', True, False),
    ('ta.variance', 'fn', (('src', None), ('length', None)), False, 'number', True, False),
    ('ta.highest', 'fn', (('src', None), ('length', None)), False, 'number', True, False),
    ('ta.lowest', 'fn', (('src', None), ('length', None)), False, 'number', True, False),
    ('ta.change', 'fn', (('src', None), ('length', '1')), False, 'number', True, False),
    ('ta.mom', 'fn', (('src', None), ('length', None)), False, 'number', True, False),
    ('ta.roc', 'fn', (('src', None), ('length', None)), False, 'number', True, False),
    ('ta.cum', 'fn', (('src', None),), False, 'number', True, False),
    ('ta.tr', 'fn', (), False, 'number', True, False),
    ('ta.atr', 'fn', (('length', None),), False, 'number', True, False),
    ('ta.crossover', 'fn', (('a', None), ('b', None)), False, 'bool', True, False),
    ('ta.crossunder', 'fn', (('a', None), ('b', None)), False, 'bool', True, False),
    ('ta.cross', 'fn', (('a', None), ('b', None)), False, 'bool', True, False),
    ('ta.rising', 'fn', (('src', None), ('length', None)), False, 'bool', True, False),
    ('ta.falling', 'fn', (('src', None), ('length', None)), False, 'bool', True, False),
    ('ta.barssince', 'fn', (('cond', None),), False, 'number', True, False),
    ('ta.valuewhen', 'fn', (('cond', None), ('src', None), ('occurrence', '0')), False, 'number', True, False),
    ('ta.linreg', 'fn', (('src', None), ('length', None), ('offset', '0')), False, 'number', True, False),
    ('ta.macd', 'fn', (('src', None), ('fast', None), ('slow', None), ('signal', None)), False, 'tuple:3', True, False),
    ('ta.bb', 'fn', (('src', None), ('length', None), ('mult', None)), False, 'tuple:3', True, False),
    ('ta.stoch', 'fn', (('src', None), ('high', None), ('low', None), ('length', None)), False, 'number', True, False),
    ('input.int', 'fn', (('defval', None), ('title', None), ('min', 'na'), ('max', 'na'), ('step', '1')), False, 'number', False, True),
    ('input.float', 'fn', (('defval', None), ('title', None), ('min', 'na'), ('max', 'na'), ('step', 'na')), False, 'number', False, True),
    ('input.bool', 'fn', (('defval', None), ('title', None)), False, 'bool', False, True),
    ('input.string', 'fn', (('defval', None), ('title', None), ('options', 'na')), False, 'string', False, True),
    ('input.source', 'fn', (('defval', None), ('title', None)), False, 'number', False, True),
    ('input.symbol', 'fn', (('defval', None), ('title', None)), False, 'string', False, True),
    ('input.timeframe', 'fn', (('defval', None), ('title', None)), False, 'string', False, True),
    ('request', 'fn', (('symbol', None), ('timeframe', None), ('expr', None)), False, 'any', False, False),
    ('plot', 'fn', (('series', None), ('title', '""'), ('color', 'na'), ('linewidth', '1'), ('style', '"line"')), False, 'plot', False, False),
    ('hline', 'fn', (('price', None), ('title', '""'), ('color', 'na'), ('linestyle', '"dashed"')), False, 'void', False, True),
    ('fill', 'fn', (('plot1', None), ('plot2', None), ('color', 'na')), False, 'void', False, False),
    ('bgcolor', 'fn', (('color', None),), False, 'void', False, False),
    ('plotshape', 'fn', (('cond', None), ('title', '""'), ('style', '"triangleup"'), ('location', '"abovebar"'), ('color', 'na'), ('text', '""')), False, 'void', False, False),
    ('label.new', 'fn', (('x', None), ('y', None), ('text', '""'), ('color', 'na'), ('style', '"label_down"'), ('textcolor', 'na')), False, 'label', False, False),
    ('label.delete', 'fn', (('id', None),), False, 'void', False, False),
    ('label.set_text', 'fn', (('id', None), ('text', None)), False, 'void', False, False),
    ('label.set_xy', 'fn', (('id', None), ('x', None), ('y', None)), False, 'void', False, False),
    ('line.new', 'fn', (('x1', None), ('y1', None), ('x2', None), ('y2', None), ('color', 'na'), ('width', '1')), False, 'line', False, False),
    ('line.delete', 'fn', (('id', None),), False, 'void', False, False),
    ('line.set_xy2', 'fn', (('id', None), ('x', None), ('y', None)), False, 'void', False, False),
    ('box.new', 'fn', (('left', None), ('top', None), ('right', None), ('bottom', None), ('color', 'na'), ('bgcolor', 'na')), False, 'box', False, False),
    ('box.delete', 'fn', (('id', None),), False, 'void', False, False),
    ('table.new', 'fn', (('position', None), ('columns', None), ('rows', None)), False, 'table', False, False),
    ('table.cell', 'fn', (('id', None), ('column', None), ('row', None), ('text', '""'), ('color', 'na'), ('bgcolor', 'na')), False, 'void', False, False),
    ('alert', 'fn', (('message', None),), False, 'void', False, False),
    ('alertcondition', 'fn', (('cond', None), ('title', None), ('message', '""')), False, 'void', False, True),
    ('color.red', 'var', (), False, 'color', False, False),
    ('color.green', 'var', (), False, 'color', False, False),
    ('color.blue', 'var', (), False, 'color', False, False),
    ('color.orange', 'var', (), False, 'color', False, False),
    ('color.yellow', 'var', (), False, 'color', False, False),
    ('color.purple', 'var', (), False, 'color', False, False),
    ('color.teal', 'var', (), False, 'color', False, False),
    ('color.aqua', 'var', (), False, 'color', False, False),
    ('color.lime', 'var', (), False, 'color', False, False),
    ('color.fuchsia', 'var', (), False, 'color', False, False),
    ('color.maroon', 'var', (), False, 'color', False, False),
    ('color.navy', 'var', (), False, 'color', False, False),
    ('color.olive', 'var', (), False, 'color', False, False),
    ('color.silver', 'var', (), False, 'color', False, False),
    ('color.gray', 'var', (), False, 'color', False, False),
    ('color.white', 'var', (), False, 'color', False, False),
    ('color.black', 'var', (), False, 'color', False, False),
    ('color.new', 'fn', (('color', None), ('transp', None)), False, 'color', False, False),
    ('color.rgb', 'fn', (('r', None), ('g', None), ('b', None), ('transp', '0')), False, 'color', False, False),
    ('str.tostring', 'fn', (('x', None), ('decimals', '-1')), False, 'string', False, False),
    ('str.length', 'fn', (('s', None),), False, 'number', False, False),
    ('str.contains', 'fn', (('s', None), ('part', None)), False, 'bool', False, False),
    ('array.new', 'fn', (('size', '0'), ('init', 'na')), False, 'array', False, False),
    ('array.from', 'fn', (), True, 'array', False, False),
    ('array.push', 'fn', (('id', None), ('value', None)), False, 'void', False, False),
    ('array.pop', 'fn', (('id', None),), False, 'any', False, False),
    ('array.shift', 'fn', (('id', None),), False, 'any', False, False),
    ('array.unshift', 'fn', (('id', None), ('value', None)), False, 'void', False, False),
    ('array.get', 'fn', (('id', None), ('index', None)), False, 'any', False, False),
    ('array.set', 'fn', (('id', None), ('index', None), ('value', None)), False, 'void', False, False),
    ('array.size', 'fn', (('id', None),), False, 'number', False, False),
    ('array.clear', 'fn', (('id', None),), False, 'void', False, False),
    ('array.sum', 'fn', (('id', None),), False, 'number', False, False),
    ('array.avg', 'fn', (('id', None),), False, 'number', False, False),
    ('array.min', 'fn', (('id', None),), False, 'number', False, False),
    ('array.max', 'fn', (('id', None),), False, 'number', False, False),
    ('array.includes', 'fn', (('id', None), ('value', None)), False, 'bool', False, False),
    ('array.indexof', 'fn', (('id', None), ('value', None)), False, 'number', False, False),
    ('array.sort', 'fn', (('id', None), ('descending', 'false')), False, 'void', False, False),
    ('array.reverse', 'fn', (('id', None),), False, 'void', False, False),
    ('map.new', 'fn', (), False, 'map', False, False),
    ('map.put', 'fn', (('id', None), ('key', None), ('value', None)), False, 'void', False, False),
    ('map.get', 'fn', (('id', None), ('key', None)), False, 'any', False, False),
    ('map.contains', 'fn', (('id', None), ('key', None)), False, 'bool', False, False),
    ('map.remove', 'fn', (('id', None), ('key', None)), False, 'void', False, False),
    ('map.size', 'fn', (('id', None),), False, 'number', False, False),
    ('map.keys', 'fn', (('id', None),), False, 'array', False, False),
    ('map.values', 'fn', (('id', None),), False, 'array', False, False),
]

BUILTINS: list[Builtin] = [Builtin(*row) for row in _ROWS]

# Lookup by name. `na` is both a value and a function: the function form wins here (the checker handles both).
BY_NAME: dict[str, Builtin] = {b.name: b for b in BUILTINS}

# Names a method call may use after a value: `a.push(x)` is `array.push(a, x)`.
METHOD_NAMESPACES = ("array", "map", "label", "line", "box", "table")

# The first part of every dotted built-in (`ta`, `math`, ...). A variable may not take one of these names.
NAMESPACES = frozenset(b.name.split(".")[0] for b in BUILTINS if "." in b.name) | {"lib", "strategy"}
