from __future__ import annotations

import calendar
import itertools
import json
import operator
import re
import time
from functools import update_wrapper
from functools import wraps

from .compat import compat_basestring
from .compat import compat_chr
from .compat import compat_collections_chain_map as ChainMap
from .compat import compat_contextlib_suppress
from .compat import compat_filter as filter
from .compat import compat_int
from .compat import compat_integer_types
from .compat import compat_itertools_zip_longest as zip_longest
from .compat import compat_map as map
from .compat import compat_numeric_types
from .compat import compat_str
from .utils import ExtractorError
from .utils import error_to_compat_str
from .utils import float_or_none
from .utils import int_or_none
from .utils import js_to_json
from .utils import remove_quotes
from .utils import str_or_none
from .utils import unified_timestamp
from .utils import variadic
from .utils import write_string


# name JS functions
class function_with_repr:
    # from yt_dlp/utils.py, but in this module
    # repr_ is always set
    def __init__(self, func, repr_):
        update_wrapper(self, func)
        self.func, self.__repr = func, repr_

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)

    def __repr__(self):
        return self.__repr


# name JS operators
def wraps_op(op):
    def update_and_rename_wrapper(w):
        f = update_wrapper(w, op)
        # fn names are str in both Py 2/3
        f.__name__ = 'JS_' + f.__name__
        return f

    return update_and_rename_wrapper


# NB In principle NaN cannot be checked by membership.
# Here all NaN values are actually this one, so _NaN is _NaN,
# although _NaN != _NaN. Ditto Infinity.

_NaN = float('nan')
_Infinity = float('inf')


class JS_Undefined:
    pass


def _js_bit_op(op, is_shift=False):
    def zeroise(x, is_shift_arg=False):
        if isinstance(x, compat_integer_types):
            return (x % 32) if is_shift_arg else (x & 0xFFFFFFFF)
        try:
            x = float(x)
            if is_shift_arg:
                x = int(x % 32)
            elif x < 0:
                x = -compat_int(-x % 0xFFFFFFFF)
            else:
                x = compat_int(x % 0xFFFFFFFF)
        except (ValueError, TypeError):
            # also here for int(NaN), including float('inf') % 32
            x = 0
        return x

    @wraps_op(op)
    def wrapped(a, b):
        return op(zeroise(a), zeroise(b, is_shift)) & 0xFFFFFFFF

    return wrapped


def _js_arith_op(op, div=False):
    @wraps_op(op)
    def wrapped(a, b):
        if JS_Undefined in (a, b):
            return _NaN
        # null, "" --> 0
        a, b = (
            float_or_none((x.strip() if isinstance(x, compat_basestring) else x) or 0, default=_NaN) for x in (a, b)
        )
        if _NaN in (a, b):
            return _NaN
        try:
            return op(a, b)
        except ZeroDivisionError:
            return _NaN if not (div and (a or b)) else _Infinity

    return wrapped


_js_arith_add = _js_arith_op(operator.add)


def _js_add(a, b):
    if not (isinstance(a, compat_basestring) or isinstance(b, compat_basestring)):
        return _js_arith_add(a, b)
    if not isinstance(a, compat_basestring):
        a = _js_toString(a)
    elif not isinstance(b, compat_basestring):
        b = _js_toString(b)
    return operator.concat(a, b)


_js_mod = _js_arith_op(operator.mod)
__js_exp = _js_arith_op(operator.pow)


def _js_exp(a, b):
    if not b:
        return 1  # even 0 ** 0 !!
    return __js_exp(a, b)


def _js_to_primitive(v):
    return (
        ','.join(map(_js_toString, v))
        if isinstance(v, list)
        else '[object Object]'
        if isinstance(v, dict)
        else compat_str(v)
        if not isinstance(v, (compat_numeric_types, compat_basestring))
        else v
    )


# more exact: yt-dlp/yt-dlp#12110
def _js_toString(v):
    return (
        'undefined'
        if v is JS_Undefined
        else 'Infinity'
        if v == _Infinity
        else 'NaN'
        if v is _NaN
        else 'null'
        if v is None
        # bool <= int: do this first
        else ('false', 'true')[v]
        if isinstance(v, bool)
        else re.sub(r'(?<=\d)\.?0*$', '', f'{v:.7f}')
        if isinstance(v, compat_numeric_types)
        else _js_to_primitive(v)
    )


_nullish = frozenset((None, JS_Undefined))


def _js_eq(a, b):
    # NaN != any
    if _NaN in (a, b):
        return False
    # Object is Object
    if isinstance(a, type(b)) and isinstance(b, (dict, list)):
        return operator.is_(a, b)
    # general case
    if a == b:
        return True
    # null == undefined
    a_b = set((a, b))
    if a_b & _nullish:
        return a_b <= _nullish
    a, b = _js_to_primitive(a), _js_to_primitive(b)
    if not isinstance(a, compat_basestring):
        a, b = b, a
    # Number to String: convert the string to a number
    # Conversion failure results in ... false
    if isinstance(a, compat_basestring):
        return float_or_none(a) == b
    return a == b


def _js_neq(a, b):
    return not _js_eq(a, b)


def _js_id_op(op):
    @wraps_op(op)
    def wrapped(a, b):
        if _NaN in (a, b):
            return op(_NaN, None)
        if not isinstance(a, (compat_basestring, compat_numeric_types)):
            a, b = b, a
        # strings are === if ==
        # why 'a' is not 'a': https://stackoverflow.com/a/1504848
        if isinstance(a, (compat_basestring, compat_numeric_types)):
            return a == b if op(0, 0) else a != b
        return op(a, b)

    return wrapped


def _js_comp_op(op):
    @wraps_op(op)
    def wrapped(a, b):
        if JS_Undefined in (a, b):
            return False
        if isinstance(a, compat_basestring):
            b = compat_str(b or 0)
        elif isinstance(b, compat_basestring):
            a = compat_str(a or 0)
        return op(a or 0, b or 0)

    return wrapped


def _js_ternary(cndn, if_true=True, if_false=False):
    """Simulate JS's ternary operator (cndn?if_true:if_false)"""
    if cndn in (False, None, 0, '', JS_Undefined, _NaN):
        return if_false
    return if_true


def _js_unary_op(op):
    @wraps_op(op)
    def wrapped(a, _):
        return op(a)

    return wrapped


# https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Operators/typeof
def _js_typeof(expr):
    with compat_contextlib_suppress(TypeError, KeyError):
        return {
            JS_Undefined: 'undefined',
            _NaN: 'number',
            _Infinity: 'number',
            True: 'boolean',
            False: 'boolean',
            None: 'object',
        }[expr]
    for t, n in (
        (compat_basestring, 'string'),
        (compat_numeric_types, 'number'),
    ):
        if isinstance(expr, t):
            return n
    if callable(expr):
        return 'function'
    # TODO: Symbol, BigInt
    return 'object'


# (op, definition) in order of binding priority, tightest first
# avoid dict to maintain order
# definition None => Defined in JSInterpreter._operator
_OPERATORS = (
    ('>>', _js_bit_op(operator.rshift, True)),
    ('<<', _js_bit_op(operator.lshift, True)),
    ('+', _js_add),
    ('-', _js_arith_op(operator.sub)),
    ('*', _js_arith_op(operator.mul)),
    ('%', _js_mod),
    ('/', _js_arith_op(operator.truediv, div=True)),
    ('**', _js_exp),
)

_LOG_OPERATORS = (
    ('|', _js_bit_op(operator.or_)),
    ('^', _js_bit_op(operator.xor)),
    ('&', _js_bit_op(operator.and_)),
)

_SC_OPERATORS = (
    ('?', None),
    ('??', None),
    ('||', None),
    ('&&', None),
)

_UNARY_OPERATORS_X = (
    ('void', _js_unary_op(lambda _: JS_Undefined)),
    ('typeof', _js_unary_op(_js_typeof)),
    # avoid functools.partial here since Py2 update_wrapper(partial) -> no __module__
    ('!', _js_unary_op(lambda x: _js_ternary(x, if_true=False, if_false=True))),
)

_COMP_OPERATORS = (
    ('===', _js_id_op(operator.is_)),
    ('!==', _js_id_op(operator.is_not)),
    ('==', _js_eq),
    ('!=', _js_neq),
    ('<=', _js_comp_op(operator.le)),
    ('>=', _js_comp_op(operator.ge)),
    ('<', _js_comp_op(operator.lt)),
    ('>', _js_comp_op(operator.gt)),
)

_OPERATOR_RE = '|'.join(map(lambda x: re.escape(x[0]), _OPERATORS + _LOG_OPERATORS + _SC_OPERATORS))

_NAME_RE = r'[a-zA-Z_$][\w$]*'
_MATCHING_PARENS = dict(zip(*zip('()', '{}', '[]')))
_QUOTES = '\'"/'
_NESTED_BRACKETS = r'[^[\]]+(?:\[[^[\]]+(?:\[[^\]]+\])?\])?'


class JS_Break(ExtractorError):
    def __init__(self):
        ExtractorError.__init__(self, 'Invalid break')


class JS_Continue(ExtractorError):
    def __init__(self):
        ExtractorError.__init__(self, 'Invalid continue')


class JS_Throw(ExtractorError):
    def __init__(self, e):
        self.error = e
        ExtractorError.__init__(self, 'Uncaught exception ' + error_to_compat_str(e))


class LocalNameSpace(ChainMap):
    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            return JS_Undefined

    def __setitem__(self, key, value):
        for scope in self.maps:
            if key in scope:
                scope[key] = value
                return
        self.maps[0][key] = value

    def __delitem__(self, key):
        raise NotImplementedError('Deleting is not supported')

    def __repr__(self):
        return f'LocalNameSpace({self.maps!r})'


class Debugger:
    ENABLED = False

    @staticmethod
    def write(*args, **kwargs):
        level = kwargs.get('level', 100)

        def truncate_string(s, left, right=0):
            if s is None or len(s) <= left + right:
                return s
            return '...'.join((s[: left - 3], s[-right:] if right else ''))

        write_string(
            '[debug] JS: {}{}\n'.format(
                '  ' * (100 - level), ' '.join(truncate_string(compat_str(x), 50, 50) for x in args)
            )
        )

    @classmethod
    def wrap_interpreter(cls, f):
        if not cls.ENABLED:
            return f

        @wraps(f)
        def interpret_statement(self, stmt, local_vars, allow_recursion, *args, **kwargs):
            if cls.ENABLED and stmt.strip():
                cls.write(stmt, level=allow_recursion)
            try:
                ret, should_ret = f(self, stmt, local_vars, allow_recursion, *args, **kwargs)
            except Exception as e:
                if cls.ENABLED:
                    if isinstance(e, ExtractorError):
                        e = e.orig_msg
                    cls.write('=> Raises:', e, '<-|', stmt, level=allow_recursion)
                raise
            if cls.ENABLED and stmt.strip():
                if should_ret or repr(ret) != stmt:
                    cls.write(['->', '=>'][bool(should_ret)], repr(ret), '<-|', stmt, level=allow_recursion)
            return ret, should_ret

        return interpret_statement


class JSInterpreter:
    __named_object_counter = 0

    _OBJ_NAME = '__youtube_dl_jsinterp_obj'

    OP_CHARS = None

    def __init__(self, code, objects=None):
        self.code, self._functions = code, {}
        self._objects = {} if objects is None else objects
        if type(self).OP_CHARS is None:
            type(self).OP_CHARS = self.OP_CHARS = self.__op_chars()

    class Exception(ExtractorError):
        def __init__(self, msg, *args, **kwargs):
            expr = kwargs.pop('expr', None)
            msg = str_or_none(msg, default='"None"')
            if expr is not None:
                msg = f'{msg.rstrip()} in: {expr!r:.100}'
            super(JSInterpreter.Exception, self).__init__(msg, *args, **kwargs)

    class JS_Object:
        def __getitem__(self, key):
            if hasattr(self, key):
                return getattr(self, key)
            raise KeyError(key)

        def dump(self):
            """Serialise the instance"""
            raise NotImplementedError

    class JS_RegExp(JS_Object):
        RE_FLAGS = {
            # special knowledge: Python's re flags are bitmask values, current max 128
            # invent new bitmask values well above that for literal parsing
            # JS 'u' flag is effectively always set (surrogate pairs aren't seen),
            # but \u{...} and \p{...} escapes aren't handled); no additional JS 'v'
            # features are supported
            # TODO: execute matches with these flags (remaining: d, y)
            'd': 1024,  # Generate indices for substring matches
            'g': 2048,  # Global search
            'i': re.I,  # Case-insensitive search
            'm': re.M,  # Multi-line search
            's': re.S,  # Allows . to match newline characters
            'u': re.U,  # Treat a pattern as a sequence of unicode code points
            'v': re.U,  # Like 'u' with extended character class and \p{} syntax
            'y': 4096,  # Perform a "sticky" search that matches starting at the current position in the target string
        }

        def __init__(self, pattern_txt, flags=0):
            if isinstance(flags, compat_str):
                flags, _ = self.regex_flags(flags)
            self.__self = None
            pattern_txt = str_or_none(pattern_txt) or '(?:)'
            # escape unintended embedded flags
            pattern_txt = re.sub(
                r'(\(\?)([aiLmsux]*)(-[imsx]+:|(?<!\?)\))',
                lambda m: ''.join(
                    (re.escape(m.group(1)), m.group(2), re.escape(m.group(3)))
                    if m.group(3) == ')'
                    else ('(?:', m.group(2), m.group(3))
                ),
                pattern_txt,
            )
            # Avoid https://github.com/python/cpython/issues/74534
            self.source = pattern_txt.replace('[[', r'[\[')
            self.__flags = flags

        def __instantiate(self):
            if self.__self:
                return
            self.__self = re.compile(self.source, self.__flags)
            # Thx: https://stackoverflow.com/questions/44773522/setattr-on-python2-sre-sre-pattern
            for name in dir(self.__self):
                # Only these? Obviously __class__, __init__.
                # PyPy creates a __weakref__ attribute with value None
                # that can't be setattr'd but also can't need to be copied.
                if name in ('__class__', '__init__', '__weakref__'):
                    continue
                if name == 'flags':
                    setattr(self, name, getattr(self.__self, name, self.__flags))
                else:
                    setattr(self, name, getattr(self.__self, name))

        def __getattr__(self, name):
            self.__instantiate()
            if name == 'pattern':
                self.pattern = self.source
                return self.pattern
            elif hasattr(self.__self, name):
                v = getattr(self.__self, name)
                setattr(self, name, v)
                return v
            elif name in ('groupindex', 'groups'):
                return 0 if name == 'groupindex' else {}
            else:
                flag_attrs = (  # order by 2nd elt
                    ('hasIndices', 'd'),
                    ('global', 'g'),
                    ('ignoreCase', 'i'),
                    ('multiline', 'm'),
                    ('dotAll', 's'),
                    ('unicode', 'u'),
                    ('unicodeSets', 'v'),
                    ('sticky', 'y'),
                )
                for k, c in flag_attrs:
                    if name == k:
                        return bool(self.RE_FLAGS[c] & self.__flags)
                else:
                    if name == 'flags':
                        return ''.join((c if self.RE_FLAGS[c] & self.__flags else '') for _, c in flag_attrs)

            raise AttributeError(f'{self} has no attribute named {name}')

        @classmethod
        def regex_flags(cls, expr):
            flags = 0
            if not expr:
                return flags, expr
            for idx, ch in enumerate(expr):
                if ch not in cls.RE_FLAGS:
                    break
                flags |= cls.RE_FLAGS[ch]
            return flags, expr[idx + 1 :]

        def dump(self):
            return '(/{}/{})'.format(re.sub(r'(?<!\\)/', r'\/', self.source), self.flags)

        @staticmethod
        def escape(string_):
            return re.escape(string_)

    class JS_Date(JS_Object):
        _t = None

        @staticmethod
        def __ymd_etc(*args, **kw_is_utc):
            # args: year, monthIndex, day, hours, minutes, seconds, milliseconds
            is_utc = kw_is_utc.get('is_utc', False)

            args = list(args[:7])
            args += [0] * (9 - len(args))
            args[1] += 1  # month 0..11 -> 1..12
            ms = args[6]
            for i in range(6, 9):
                args[i] = -1  # don't know
            if is_utc:
                args[-1] = 1
            # TODO: [MDN] When a segment overflows or underflows its expected
            # range, it usually "carries over to" or "borrows from" the higher segment.
            try:
                mktime = calendar.timegm if is_utc else time.mktime
                return mktime(time.struct_time(args)) * 1000 + ms
            except (OverflowError, ValueError):
                return None

        @classmethod
        def UTC(cls, *args):
            t = cls.__ymd_etc(*args, is_utc=True)
            return _NaN if t is None else t

        @staticmethod
        def parse(date_str, **kw_is_raw):
            is_raw = kw_is_raw.get('is_raw', False)

            t = unified_timestamp(str_or_none(date_str), False)
            return int(t * 1000) if t is not None else t if is_raw else _NaN

        @staticmethod
        def now(**kw_is_raw):
            is_raw = kw_is_raw.get('is_raw', False)

            t = time.time()
            return int(t * 1000) if t is not None else t if is_raw else _NaN

        def __init__(self, *args):
            if not args:
                args = [self.now(is_raw=True)]
            if len(args) == 1:
                if isinstance(args[0], JSInterpreter.JS_Date):
                    self._t = int_or_none(args[0].valueOf(), default=None)
                else:
                    arg_type = _js_typeof(args[0])
                    if arg_type == 'string':
                        self._t = self.parse(args[0], is_raw=True)
                    elif arg_type == 'number':
                        self._t = int(args[0])
            else:
                self._t = self.__ymd_etc(*args)

        def toString(self):
            try:
                return time.strftime('%a %b %0d %Y %H:%M:%S %Z%z', self._t).rstrip()
            except TypeError:
                return 'Invalid Date'

        def valueOf(self):
            return _NaN if self._t is None else self._t

        def dump(self):
            return f'(new Date({self.toString()}))'

    @classmethod
    def __op_chars(cls):
        op_chars = set(';,[')
        for op in cls._all_operators():
            if op[0].isalpha():
                continue
            op_chars.update(op[0])
        return op_chars

    def _named_object(self, namespace, obj):
        self.__named_object_counter += 1
        name = '%s%d' % (self._OBJ_NAME, self.__named_object_counter)
        if callable(obj) and not isinstance(obj, function_with_repr):
            obj = function_with_repr(obj, f'F<{self.__named_object_counter}>')
        namespace[name] = obj
        return name

    @classmethod
    def _separate(cls, expr, delim=',', max_split=None, skip_delims=None):
        if not expr:
            return
        # collections.Counter() is ~10% slower in both 2.7 and 3.9
        counters = dict((k, 0) for k in _MATCHING_PARENS.values())
        start, splits, pos, delim_len = 0, 0, 0, len(delim) - 1
        in_quote, escaping, after_op, in_regex_char_group = None, False, True, False
        skipping = 0
        if skip_delims:
            skip_delims = variadic(skip_delims)
        skip_txt = None
        for idx, char in enumerate(expr):
            if skip_txt and idx <= skip_txt[1]:
                continue
            paren_delta = 0
            if not in_quote:
                if char == '/' and expr[idx : idx + 2] == '/*':
                    # skip a comment
                    skip_txt = expr[idx:].find('*/', 2)
                    skip_txt = [idx, idx + skip_txt + 1] if skip_txt >= 2 else None
                    if skip_txt:
                        continue
                if char in _MATCHING_PARENS:
                    counters[_MATCHING_PARENS[char]] += 1
                    paren_delta = 1
                elif char in counters:
                    counters[char] -= 1
                    paren_delta = -1
            if not escaping:
                if char in _QUOTES and in_quote in (char, None):
                    if in_quote or after_op or char != '/':
                        in_quote = None if in_quote and not in_regex_char_group else char
                elif in_quote == '/' and char in '[]':
                    in_regex_char_group = char == '['
            escaping = not escaping and in_quote and char == '\\'
            after_op = not in_quote and (char in cls.OP_CHARS or paren_delta > 0 or (after_op and char.isspace()))

            if char != delim[pos] or any(counters.values()) or in_quote:
                pos = skipping = 0
                continue
            elif skipping > 0:
                skipping -= 1
                continue
            elif pos == 0 and skip_delims:
                here = expr[idx:]
                for s in skip_delims:
                    if here.startswith(s) and s:
                        skipping = len(s) - 1
                        break
                if skipping > 0:
                    continue
            if pos < delim_len:
                pos += 1
                continue
            if skip_txt and skip_txt[0] >= start and skip_txt[1] <= idx - delim_len:
                yield expr[start : skip_txt[0]] + expr[skip_txt[1] + 1 : idx - delim_len]
            else:
                yield expr[start : idx - delim_len]
            skip_txt = None
            start, pos = idx + 1, 0
            splits += 1
            if max_split and splits >= max_split:
                break
        if skip_txt and skip_txt[0] >= start:
            yield expr[start : skip_txt[0]] + expr[skip_txt[1] + 1 :]
        else:
            yield expr[start:]

    @classmethod
    def _separate_at_paren(cls, expr, delim=None):
        if delim is None:
            delim = expr and _MATCHING_PARENS[expr[0]]
        separated = list(cls._separate(expr, delim, 1))
        if len(separated) < 2:
            raise cls.Exception('No terminating paren {delim} in {expr!r:.5500}'.format(**locals()))
        return separated[0][1:].strip(), separated[1].strip()

    @staticmethod
    def _all_operators(_cached=[]):
        if not _cached:
            _cached.extend(
                itertools.chain(
                    # Ref: https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Operators/Operator_Precedence
                    _SC_OPERATORS,
                    _LOG_OPERATORS,
                    _COMP_OPERATORS,
                    _OPERATORS,
                    _UNARY_OPERATORS_X,
                )
            )
        return _cached

    def _separate_at_op(self, expr, max_split=None):
        for op, _ in self._all_operators():
            # hackety: </> have higher priority than <</>>, but don't confuse them
            skip_delim = (op + op) if op in '<>*?' else None
            if op == '?':
                skip_delim = (skip_delim, '?.')
            separated = list(self._separate(expr, op, skip_delims=skip_delim))
            if len(separated) < 2:
                continue

            right_expr = separated.pop()
            # handle operators that are both unary and binary, minimal BODMAS
            if op in ('+', '-'):
                # simplify/adjust consecutive instances of these operators
                undone = 0
                separated = [s.strip() for s in separated]
                while len(separated) > 1 and not separated[-1]:
                    undone += 1
                    separated.pop()
                if op == '-' and undone % 2 != 0:
                    right_expr = op + right_expr
                elif op == '+':
                    while len(separated) > 1 and set(separated[-1]) <= self.OP_CHARS:
                        right_expr = separated.pop() + right_expr
                    if separated[-1][-1:] in self.OP_CHARS:
                        right_expr = separated.pop() + right_expr
                # hanging op at end of left => unary + (strip) or - (push right)
                separated.append(right_expr)
                dm_ops = ('*', '%', '/', '**')
                dm_chars = set(''.join(dm_ops))

                def yield_terms(s):
                    skip = False
                    for i, term in enumerate(s[:-1]):
                        if skip:
                            skip = False
                            continue
                        if not (dm_chars & set(term)):
                            yield term
                            continue
                        for dm_op in dm_ops:
                            bodmas = list(self._separate(term, dm_op, skip_delims=skip_delim))
                            if len(bodmas) > 1 and not bodmas[-1].strip():
                                bodmas[-1] = (op if op == '-' else '') + s[i + 1]
                                yield dm_op.join(bodmas)
                                skip = True
                                break
                        else:
                            if term:
                                yield term

                    if not skip and s[-1]:
                        yield s[-1]

                separated = list(yield_terms(separated))
                right_expr = separated.pop() if len(separated) > 1 else None
                expr = op.join(separated)
            if right_expr is None:
                continue
            return op, separated, right_expr

    def _operator(self, op, left_val, right_expr, expr, local_vars, allow_recursion):
        if op in ('||', '&&'):
            if (op == '&&') ^ _js_ternary(left_val):
                return left_val  # short circuiting
        elif op == '??':
            if left_val not in (None, JS_Undefined):
                return left_val
        elif op == '?':
            right_expr = _js_ternary(left_val, *self._separate(right_expr, ':', 1))

        right_val = self.interpret_expression(right_expr, local_vars, allow_recursion) if right_expr else left_val
        opfunc = op and next((v for k, v in self._all_operators() if k == op), None)
        if not opfunc:
            return right_val

        try:
            # print('Eval:', opfunc.__name__, left_val, right_val)
            return opfunc(left_val, right_val)
        except Exception as e:
            raise self.Exception(
                'Failed to evaluate {left_val!r:.50} {op} {right_val!r:.50}'.format(**locals()), expr, cause=e
            )

    def _index(self, obj, idx, allow_undefined=None):
        if idx == 'length' and isinstance(obj, list):
            return len(obj)
        try:
            return obj[int(idx)] if isinstance(obj, list) else obj[compat_str(idx)]
        except (TypeError, KeyError, IndexError, ValueError) as e:
            # allow_undefined is None gives correct behaviour
            if allow_undefined or (allow_undefined is None and not isinstance(e, TypeError)):
                return JS_Undefined
            raise self.Exception('Cannot get index {idx!r:.100}'.format(**locals()), expr=repr(obj), cause=e)

    def _dump(self, obj, namespace):
        if obj is JS_Undefined:
            return 'undefined'
        try:
            return json.dumps(obj)
        except TypeError:
            return self._named_object(namespace, obj)

    # used below
    _VAR_RET_THROW_RE = re.compile(r"""(?x)
        (?:(?P<var>var|const|let)\s+|(?P<ret>return)(?:\s+|(?=["'])|$)|(?P<throw>throw)\s+)
        """)
    _COMPOUND_RE = re.compile(r"""(?x)
        (?P<try>try)\s*\{|
        (?P<if>if)\s*\(|
        (?P<switch>switch)\s*\(|
        (?P<for>for)\s*\(|
        (?P<while>while)\s*\(
        """)
    _FINALLY_RE = re.compile(r'finally\s*\{')
    _SWITCH_RE = re.compile(r'switch\s*\(')

    def _eval_operator(self, op, left_expr, right_expr, expr, local_vars, allow_recursion):
        left_val = self.interpret_expression(left_expr, local_vars, allow_recursion)
        return self._operator(op, left_val, right_expr, expr, local_vars, allow_recursion)

    @Debugger.wrap_interpreter
    def interpret_statement(self, stmt, local_vars, allow_recursion=100):
        if allow_recursion < 0:
            raise self.Exception('Recursion limit reached')
        allow_recursion -= 1

        # print('At: ' + stmt[:60])
        should_return = False
        # fails on (eg) if (...) stmt1; else stmt2;
        sub_statements = list(self._separate(stmt, ';')) or ['']
        expr = stmt = sub_statements.pop().strip()

        for sub_stmt in sub_statements:
            ret, should_return = self.interpret_statement(sub_stmt, local_vars, allow_recursion)
            if should_return:
                return ret, should_return

        m = self._VAR_RET_THROW_RE.match(stmt)
        if m:
            expr = stmt[len(m.group(0)) :].strip()
            if m.group('throw'):
                raise JS_Throw(self.interpret_expression(expr, local_vars, allow_recursion))
            should_return = 'return' if m.group('ret') else False
        if not expr:
            return None, should_return

        if expr[0] in _QUOTES:
            inner, outer = self._separate(expr, expr[0], 1)
            if expr[0] == '/':
                flags, outer = self.JS_RegExp.regex_flags(outer)
                inner = self.JS_RegExp(inner[1:], flags=flags)
            else:
                inner = json.loads(js_to_json(inner + expr[0]))  # , strict=True))
            if not outer:
                return inner, should_return
            expr = self._named_object(local_vars, inner) + outer

        new_kw, _, obj = expr.partition('new ')
        if not new_kw:
            for klass, konstr in (
                ('Date', lambda *x: self.JS_Date(*x).valueOf()),
                ('RegExp', self.JS_RegExp),
                ('Error', self.Exception),
            ):
                if not obj.startswith(klass + '('):
                    continue
                left, right = self._separate_at_paren(obj[len(klass) :])
                argvals = self.interpret_iter(left, local_vars, allow_recursion)
                expr = konstr(*argvals)
                if expr is None:
                    raise self.Exception('Failed to parse {klass} {left!r:.100}'.format(**locals()), expr=expr)
                expr = self._dump(expr, local_vars) + right
                break
            else:
                raise self.Exception('Unsupported object {obj:.100}'.format(**locals()), expr=expr)

        # apply unary operators (see new above)
        for op, _ in _UNARY_OPERATORS_X:
            if not expr.startswith(op):
                continue
            operand = expr[len(op) :]
            if not operand or (op.isalpha() and operand[0] != ' '):
                continue
            separated = self._separate_at_op(operand, max_split=1)
            if separated:
                next_op, separated, right_expr = separated
                separated.append(right_expr)
                operand = next_op.join(separated)
            return self._eval_operator(op, operand, '', expr, local_vars, allow_recursion), should_return

        if expr.startswith('{'):
            inner, outer = self._separate_at_paren(expr)
            # try for object expression (Map)
            sub_expressions = [list(self._separate(sub_expr.strip(), ':', 1)) for sub_expr in self._separate(inner)]
            if all(len(sub_expr) == 2 for sub_expr in sub_expressions):
                return dict(
                    (
                        key_expr if re.match(_NAME_RE, key_expr) else key_expr,
                        self.interpret_expression(val_expr, local_vars, allow_recursion),
                    )
                    for key_expr, val_expr in sub_expressions
                ), should_return
            # or statement list
            inner, should_abort = self.interpret_statement(inner, local_vars, allow_recursion)
            if not outer or should_abort:
                return inner, should_abort or should_return
            else:
                expr = self._dump(inner, local_vars) + outer

        if expr.startswith('('):
            m = re.match(r'\((?P<d>[a-z])%(?P<e>[a-z])\.length\+(?P=e)\.length\)%(?P=e)\.length', expr)
            if m:
                # short-cut eval of frequently used `(d%e.length+e.length)%e.length`, worth ~6% on `pytest -k test_nsig`
                outer = None
                inner, should_abort = self._offset_e_by_d(m.group('d'), m.group('e'), local_vars)
            else:
                inner, outer = self._separate_at_paren(expr)
                inner, should_abort = self.interpret_statement(inner, local_vars, allow_recursion)
            if not outer or should_abort:
                return inner, should_abort or should_return
            else:
                expr = self._dump(inner, local_vars) + outer

        if expr.startswith('['):
            inner, outer = self._separate_at_paren(expr)
            name = self._named_object(
                local_vars,
                [self.interpret_expression(item, local_vars, allow_recursion) for item in self._separate(inner)],
            )
            expr = name + outer

        m = self._COMPOUND_RE.match(expr)
        md = m.groupdict() if m else {}
        if md.get('if'):
            cndn, expr = self._separate_at_paren(expr[m.end() - 1 :])
            if expr.startswith('{'):
                if_expr, expr = self._separate_at_paren(expr)
            else:
                # may lose ... else ... because of ll.368-374
                if_expr, expr = self._separate_at_paren(f' {expr};', delim=';')
            else_expr = None
            m = re.match(r'else\s*(?P<block>\{)?', expr)
            if m:
                if m.group('block'):
                    else_expr, expr = self._separate_at_paren(expr[m.end() - 1 :])
                else:
                    # handle subset ... else if (...) {...} else ...
                    # TODO: make interpret_statement do this properly, if possible
                    exprs = list(self._separate(expr[m.end() :], delim='}', max_split=2))
                    if len(exprs) > 1:
                        if re.match(r'\s*if\s*\(', exprs[0]) and re.match(r'\s*else\b', exprs[1]):
                            else_expr = exprs[0] + '}' + exprs[1]
                            expr = (exprs[2] + '}') if len(exprs) == 3 else None
                        else:
                            else_expr = exprs[0]
                            exprs.append('')
                            expr = '}'.join(exprs[1:])
                    else:
                        else_expr = exprs[0]
                        expr = None
                    else_expr = else_expr.lstrip() + '}'
            cndn = _js_ternary(self.interpret_expression(cndn, local_vars, allow_recursion))
            ret, should_abort = self.interpret_statement(if_expr if cndn else else_expr, local_vars, allow_recursion)
            if should_abort:
                return ret, True

        elif md.get('try'):
            try_expr, expr = self._separate_at_paren(expr[m.end() - 1 :])
            err = None
            try:
                ret, should_abort = self.interpret_statement(try_expr, local_vars, allow_recursion)
                if should_abort:
                    return ret, True
            except Exception as e:
                # XXX: This works for now, but makes debugging future issues very hard
                err = e

            pending = (None, False)
            m = re.match(r'catch\s*(?P<err>\(\s*{_NAME_RE}\s*\))?\{{'.format(**globals()), expr)
            if m:
                sub_expr, expr = self._separate_at_paren(expr[m.end() - 1 :])
                if err:
                    catch_vars = {}
                    if m.group('err'):
                        catch_vars[m.group('err')] = err.error if isinstance(err, JS_Throw) else err
                    catch_vars = local_vars.new_child(m=catch_vars)
                    err, pending = None, self.interpret_statement(sub_expr, catch_vars, allow_recursion)

            m = self._FINALLY_RE.match(expr)
            if m:
                sub_expr, expr = self._separate_at_paren(expr[m.end() - 1 :])
                ret, should_abort = self.interpret_statement(sub_expr, local_vars, allow_recursion)
                if should_abort:
                    return ret, True

            ret, should_abort = pending
            if should_abort:
                return ret, True

            if err:
                raise err

        elif md.get('for') or md.get('while'):
            init_or_cond, remaining = self._separate_at_paren(expr[m.end() - 1 :])
            if remaining.startswith('{'):
                body, expr = self._separate_at_paren(remaining)
            else:
                switch_m = self._SWITCH_RE.match(remaining)  # FIXME
                if switch_m:
                    switch_val, remaining = self._separate_at_paren(remaining[switch_m.end() - 1 :])
                    body, expr = self._separate_at_paren(remaining, '}')
                    body = f'switch({switch_val}){{{body}}}'
                else:
                    body, expr = remaining, ''
            if md.get('for'):
                start, cndn, increment = self._separate(init_or_cond, ';')
                self.interpret_expression(start, local_vars, allow_recursion)
            else:
                cndn, increment = init_or_cond, None
            while _js_ternary(self.interpret_expression(cndn, local_vars, allow_recursion)):
                try:
                    ret, should_abort = self.interpret_statement(body, local_vars, allow_recursion)
                    if should_abort:
                        return ret, True
                except JS_Break:
                    break
                except JS_Continue:
                    pass
                if increment:
                    self.interpret_expression(increment, local_vars, allow_recursion)

        elif md.get('switch'):
            switch_val, remaining = self._separate_at_paren(expr[m.end() - 1 :])
            switch_val = self.interpret_expression(switch_val, local_vars, allow_recursion)
            body, expr = self._separate_at_paren(remaining, '}')
            items = body.replace('default:', 'case default:').split('case ')[1:]
            for default in (False, True):
                matched = False
                for item in items:
                    case, stmt = (i.strip() for i in self._separate(item, ':', 1))
                    if default:
                        matched = matched or case == 'default'
                    elif not matched:
                        matched = case != 'default' and switch_val == self.interpret_expression(
                            case, local_vars, allow_recursion
                        )
                    if not matched:
                        continue
                    try:
                        ret, should_abort = self.interpret_statement(stmt, local_vars, allow_recursion)
                        if should_abort:
                            return ret
                    except JS_Break:
                        break
                if matched:
                    break

        if md:
            ret, should_abort = self.interpret_statement(expr, local_vars, allow_recursion)
            return ret, should_abort or should_return

        # Comma separated statements
        sub_expressions = list(self._separate(expr))
        if len(sub_expressions) > 1:
            for sub_expr in sub_expressions:
                ret, should_abort = self.interpret_statement(sub_expr, local_vars, allow_recursion)
                if should_abort:
                    return ret, True
            return ret, False

        for m in re.finditer(
            r"""(?x)
                (?P<pre_sign>\+\+|--)(?P<var1>{_NAME_RE})|
                (?P<var2>{_NAME_RE})(?P<post_sign>\+\+|--)""".format(**globals()),
            expr,
        ):
            var = m.group('var1') or m.group('var2')
            start, end = m.span()
            sign = m.group('pre_sign') or m.group('post_sign')
            ret = local_vars[var]
            local_vars[var] = _js_add(ret, 1 if sign[0] == '+' else -1)
            if m.group('pre_sign'):
                ret = local_vars[var]
            expr = expr[:start] + self._dump(ret, local_vars) + expr[end:]

        if not expr:
            return None, should_return

        m = re.match(
            r"""(?x)
            (?P<assign>
                (?P<out>{_NAME_RE})(?P<out_idx>(?:\[{_NESTED_BRACKETS}\])+)?\s*
                (?P<op>{_OPERATOR_RE})?
                =(?!=)(?P<expr>.*)$
            )|(?P<return>
                (?!if|return|true|false|null|undefined|NaN|Infinity)(?P<name>{_NAME_RE})$
            )|(?P<attribute>
                (?P<var>{_NAME_RE})(?:
                    (?P<nullish>\?)?\.(?P<member>[^(]+)|
                    \[(?P<member2>{_NESTED_BRACKETS})\]
                )\s*
            )|(?P<indexing>
                (?P<in>{_NAME_RE})(?P<in_idx>\[.+\])$
            )|(?P<function>
                (?P<fname>{_NAME_RE})\((?P<args>.*)\)$
            )""".format(**globals()),
            expr,
        )
        md = m.groupdict() if m else {}
        if md.get('assign'):
            left_val = local_vars.get(m.group('out'))

            if not m.group('out_idx'):
                local_vars[m.group('out')] = self._operator(
                    m.group('op'), left_val, m.group('expr'), expr, local_vars, allow_recursion
                )
                return local_vars[m.group('out')], should_return
            elif left_val in (None, JS_Undefined):
                raise self.Exception('Cannot index undefined variable ' + m.group('out'), expr=expr)

            indexes = md['out_idx']
            while indexes:
                idx, indexes = self._separate_at_paren(indexes)
                idx = self.interpret_expression(idx, local_vars, allow_recursion)
                if indexes:
                    left_val = self._index(left_val, idx)
            if isinstance(idx, float):
                idx = int(idx)
            if isinstance(left_val, list) and len(left_val) <= int_or_none(idx, default=-1):
                # JS Array is a sparsely assignable list
                # TODO: handle extreme sparsity without memory bloat, eg using auxiliary dict
                left_val.extend((idx - len(left_val) + 1) * [JS_Undefined])
            left_val[idx] = self._operator(
                m.group('op'),
                self._index(left_val, idx) if m.group('op') else None,
                m.group('expr'),
                expr,
                local_vars,
                allow_recursion,
            )
            return left_val[idx], should_return

        elif expr.isdigit():
            return int(expr), should_return

        elif expr == 'break':
            raise JS_Break()
        elif expr == 'continue':
            raise JS_Continue()
        elif expr == 'undefined':
            return JS_Undefined, should_return
        elif expr == 'NaN':
            return _NaN, should_return
        elif expr == 'Infinity':
            return _Infinity, should_return

        elif md.get('return'):
            ret = local_vars[m.group('name')]
            # challenge may try to force returning the original value
            # use an optional internal var to block this
            if should_return == 'return':
                if '_ytdl_do_not_return' not in local_vars:
                    return ret, True
                return (ret, True) if ret != local_vars['_ytdl_do_not_return'] else (ret, False)
            else:
                return ret, should_return

        with compat_contextlib_suppress(ValueError):
            ret = json.loads(js_to_json(expr))  # strict=True)
            if not md.get('attribute'):
                return ret, should_return

        if md.get('indexing'):
            val = local_vars[m.group('in')]
            indexes = m.group('in_idx')
            while indexes:
                idx, indexes = self._separate_at_paren(indexes)
                idx = self.interpret_expression(idx, local_vars, allow_recursion)
                val = self._index(val, idx)
            return val, should_return

        separated = self._separate_at_op(expr)
        if separated:
            op, separated, right_expr = separated
            return self._eval_operator(
                op, op.join(separated), right_expr, expr, local_vars, allow_recursion
            ), should_return

        if md.get('attribute'):
            variable, member, nullish = m.group('var', 'member', 'nullish')
            if not member:
                member = self.interpret_expression(m.group('member2'), local_vars, allow_recursion)
            arg_str = expr[m.end() :]
            if arg_str.startswith('('):
                arg_str, remaining = self._separate_at_paren(arg_str)
            else:
                arg_str, remaining = None, arg_str

            def assertion(cndn, msg):
                """assert, but without risk of getting optimized out"""
                if not cndn:
                    memb = member
                    raise self.Exception('{memb} {msg}'.format(**locals()), expr=expr)

            def eval_method(variable, member):
                if (variable, member) == ('console', 'debug'):
                    if Debugger.ENABLED:
                        Debugger.write(self.interpret_expression(f'[{arg_str}]', local_vars, allow_recursion))
                    return
                types = {
                    'String': compat_str,
                    'Math': float,
                    'Array': list,
                    'Date': self.JS_Date,
                    'RegExp': self.JS_RegExp,
                    # 'Error': self.Exception,  # has no std static methods
                }
                obj = local_vars.get(variable)
                if obj in (JS_Undefined, None):
                    obj = types.get(variable, JS_Undefined)
                if obj is JS_Undefined:
                    try:
                        if variable not in self._objects:
                            self._objects[variable] = self.extract_object(variable, local_vars)
                        obj = self._objects[variable]
                    except self.Exception:
                        if not nullish:
                            raise

                if nullish and obj is JS_Undefined:
                    return JS_Undefined

                # Member access
                if arg_str is None:
                    return self._index(obj, member, nullish)

                # Function call
                argvals = [self.interpret_expression(v, local_vars, allow_recursion) for v in self._separate(arg_str)]

                # Fixup prototype call
                if isinstance(obj, type):
                    new_member, rest = member.partition('.')[0::2]
                    if new_member == 'prototype':
                        new_member, func_prototype = rest.partition('.')[0::2]
                        assertion(argvals, 'takes one or more arguments')
                        assertion(isinstance(argvals[0], obj), f'must bind to type {obj}')
                        if func_prototype == 'call':
                            obj = argvals.pop(0)
                        elif func_prototype == 'apply':
                            assertion(len(argvals) == 2, 'takes two arguments')
                            obj, argvals = argvals
                            assertion(isinstance(argvals, list), 'second argument must be a list')
                        else:
                            raise self.Exception('Unsupported Function method ' + func_prototype, expr)
                        member = new_member

                if obj is compat_str:
                    if member == 'fromCharCode':
                        assertion(argvals, 'takes one or more arguments')
                        return ''.join(compat_chr(int(n)) for n in argvals)
                    raise self.Exception('Unsupported string method ' + member, expr=expr)
                elif obj is float:
                    if member == 'pow':
                        assertion(len(argvals) == 2, 'takes two arguments')
                        return argvals[0] ** argvals[1]
                    raise self.Exception('Unsupported Math method ' + member, expr=expr)
                elif obj is self.JS_Date:
                    return getattr(obj, member)(*argvals)

                if member == 'split':
                    assertion(len(argvals) <= 2, 'takes at most two arguments')
                    if len(argvals) > 1:
                        limit = argvals[1]
                        assertion(isinstance(limit, int) and limit >= 0, 'integer limit >= 0')
                        if limit == 0:
                            return []
                    else:
                        limit = 0
                    if len(argvals) == 0:
                        argvals = [JS_Undefined]
                    elif isinstance(argvals[0], self.JS_RegExp):
                        # avoid re.split(), similar but not enough

                        def where():
                            for m in argvals[0].finditer(obj):
                                yield m.span(0)
                            yield (None, None)

                        def splits(limit=limit):
                            i = 0
                            for j, jj in where():
                                if j == jj == 0:
                                    continue
                                if j is None and i >= len(obj):
                                    break
                                yield obj[i:j]
                                if jj is None or limit == 1:
                                    break
                                limit -= 1
                                i = jj

                        return list(splits())
                    return (
                        obj.split(argvals[0], limit - 1)
                        if argvals[0] and argvals[0] != JS_Undefined
                        else list(obj)[: limit or None]
                    )
                elif member == 'join':
                    assertion(isinstance(obj, list), 'must be applied on a list')
                    assertion(len(argvals) <= 1, 'takes at most one argument')
                    return (',' if len(argvals) == 0 or argvals[0] in (None, JS_Undefined) else argvals[0]).join(
                        ('' if x in (None, JS_Undefined) else _js_toString(x)) for x in obj
                    )
                elif member == 'reverse':
                    assertion(not argvals, 'does not take any arguments')
                    obj.reverse()
                    return obj
                elif member == 'slice':
                    assertion(isinstance(obj, (list, compat_str)), 'must be applied on a list or string')
                    # From [1]:
                    # .slice() - like [:]
                    # .slice(n) - like [n:] (not [slice(n)]
                    # .slice(m, n) - like [m:n] or [slice(m, n)]
                    # [1] https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/slice
                    assertion(len(argvals) <= 2, 'takes between 0 and 2 arguments')
                    if len(argvals) < 2:
                        argvals += (None,)
                    return obj[slice(*argvals)]
                elif member == 'splice':
                    assertion(isinstance(obj, list), 'must be applied on a list')
                    assertion(argvals, 'takes one or more arguments')
                    index, how_many = map(int, ([*argvals, len(obj)])[:2])
                    if index < 0:
                        index += len(obj)
                    res = [obj.pop(index) for _ in range(index, min(index + how_many, len(obj)))]
                    obj[index:index] = argvals[2:]
                    return res
                elif member in ('shift', 'pop'):
                    assertion(isinstance(obj, list), 'must be applied on a list')
                    assertion(not argvals, 'does not take any arguments')
                    return obj.pop(0 if member == 'shift' else -1) if len(obj) > 0 else JS_Undefined
                elif member == 'unshift':
                    assertion(isinstance(obj, list), 'must be applied on a list')
                    # not enforced: assertion(argvals, 'takes one or more arguments')
                    obj[0:0] = argvals
                    return len(obj)
                elif member == 'push':
                    # not enforced: assertion(argvals, 'takes one or more arguments')
                    obj.extend(argvals)
                    return len(obj)
                elif member == 'forEach':
                    assertion(argvals, 'takes one or more arguments')
                    assertion(len(argvals) <= 2, 'takes at most 2 arguments')
                    f, this = ([*argvals, ''])[:2]
                    return [f((item, idx, obj), {'this': this}, allow_recursion) for idx, item in enumerate(obj)]
                elif member == 'indexOf':
                    assertion(argvals, 'takes one or more arguments')
                    assertion(len(argvals) <= 2, 'takes at most 2 arguments')
                    idx, start = ([*argvals, 0])[:2]
                    try:
                        return obj.index(idx, start)
                    except ValueError:
                        return -1
                elif member == 'charCodeAt':
                    assertion(isinstance(obj, compat_str), 'must be applied on a string')
                    # assertion(len(argvals) == 1, 'takes exactly one argument') # but not enforced
                    idx = argvals[0] if len(argvals) > 0 and isinstance(argvals[0], int) else 0
                    if idx >= len(obj):
                        return None
                    return ord(obj[idx])
                elif member in ('replace', 'replaceAll'):
                    assertion(isinstance(obj, compat_str), 'must be applied on a string')
                    assertion(len(argvals) == 2, 'takes exactly two arguments')
                    # TODO: argvals[1] callable, other Py vs JS edge cases
                    if isinstance(argvals[0], self.JS_RegExp):
                        # access JS member with Py reserved name
                        count = 0 if self._index(argvals[0], 'global') else 1
                        assertion(
                            member != 'replaceAll' or count == 0, 'replaceAll must be called with a global RegExp'
                        )
                        return argvals[0].sub(argvals[1], obj, count=count)
                    count = ('replaceAll', 'replace').index(member)
                    return re.sub(re.escape(argvals[0]), argvals[1], obj, count=count)

                idx = int(member) if isinstance(obj, list) else member
                return obj[idx](argvals, allow_recursion=allow_recursion)

            if remaining:
                ret, should_abort = self.interpret_statement(
                    self._named_object(local_vars, eval_method(variable, member)) + remaining,
                    local_vars,
                    allow_recursion,
                )
                return ret, should_return or should_abort
            else:
                return eval_method(variable, member), should_return

        elif md.get('function'):
            fname = m.group('fname')
            argvals = [
                self.interpret_expression(v, local_vars, allow_recursion) for v in self._separate(m.group('args'))
            ]
            if fname in local_vars:
                return local_vars[fname](argvals, allow_recursion=allow_recursion), should_return
            elif fname not in self._functions:
                self._functions[fname] = self.extract_function(fname)
            return self._functions[fname](argvals, allow_recursion=allow_recursion), should_return

        raise self.Exception('Unsupported JS expression ' + (expr[:40] if expr != stmt else ''), expr=stmt)

    def interpret_expression(self, expr, local_vars, allow_recursion):
        ret, should_return = self.interpret_statement(expr, local_vars, allow_recursion)
        if should_return:
            raise self.Exception('Cannot return from an expression', expr)
        return ret

    def interpret_iter(self, list_txt, local_vars, allow_recursion):
        for v in self._separate(list_txt):
            yield self.interpret_expression(v, local_vars, allow_recursion)

    def extract_object(self, objname, *global_stack):
        _FUNC_NAME_RE = rf'''(?:{_NAME_RE}|"{_NAME_RE}"|'{_NAME_RE}')'''
        obj = {}
        fields = next(
            filter(
                None,
                (
                    obj_m.group('fields')
                    for obj_m in re.finditer(
                        r"""(?xs)
                    {0}\s*\.\s*{1}|{1}\s*=\s*\{{\s*
                        (?P<fields>({2}\s*:\s*function\s*\(.*?\)\s*\{{.*?}}(?:,\s*)?)*)
                    }}\s*;
                """.format(_NAME_RE, re.escape(objname), _FUNC_NAME_RE),
                        self.code,
                    )
                ),
            ),
            None,
        )
        if not fields:
            raise self.Exception('Could not find object ' + objname)
        # Currently, it only supports function definitions
        for f in re.finditer(
            rf"""(?x)
                    (?P<key>{_FUNC_NAME_RE})\s*:\s*function\s*\((?P<args>(?:{_NAME_RE}|,)*)\){{(?P<code>[^}}]+)}}
                """,
            fields,
        ):
            argnames = self.build_arglist(f.group('args'))
            name = remove_quotes(f.group('key'))
            obj[name] = function_with_repr(self.build_function(argnames, f.group('code'), *global_stack), f'F<{name}>')

        return obj

    @staticmethod
    def _offset_e_by_d(d, e, local_vars):
        """Short-cut eval: (d%e.length+e.length)%e.length"""
        try:
            d = local_vars[d]
            e = local_vars[e]
            e = len(e)
            return _js_mod(_js_mod(d, e) + e, e), False
        except Exception:
            return None, True

    def extract_function_code(self, funcname):
        """@returns argnames, code"""
        func_m = re.search(
            r"""(?xs)
                (?:
                    function\s+{name}|
                    [{{;,]\s*{name}\s*=\s*function|
                    (?:var|const|let)\s+{name}\s*=\s*function
                )\s*
                \((?P<args>[^)]*)\)\s*
                (?P<code>{{.+}})""".format(name=re.escape(funcname)),
            self.code,
        )
        if func_m is None:
            raise self.Exception('Could not find JS function "{funcname}"'.format(**locals()))
        code, _ = self._separate_at_paren(func_m.group('code'))  # refine the match
        return self.build_arglist(func_m.group('args')), code

    def extract_function(self, funcname, *global_stack):
        return function_with_repr(
            self.extract_function_from_code(*itertools.chain(self.extract_function_code(funcname), global_stack)),
            f'F<{funcname}>',
        )

    def extract_function_from_code(self, argnames, code, *global_stack):
        local_vars = {}

        start = None
        while True:
            mobj = re.search(r'function\((?P<args>[^)]*)\)\s*{', code[start:])
            if mobj is None:
                break
            start, body_start = ((start or 0) + x for x in mobj.span())
            body, remaining = self._separate_at_paren(code[body_start - 1 :])
            name = self._named_object(
                local_vars,
                self.extract_function_from_code(
                    [x.strip() for x in mobj.group('args').split(',')], body, local_vars, *global_stack
                ),
            )
            code = code[:start] + name + remaining

        return self.build_function(argnames, code, local_vars, *global_stack)

    def call_function(self, funcname, *args, **kw_global_vars):
        return self.extract_function(funcname)(args, kw_global_vars)

    @classmethod
    def build_arglist(cls, arg_text):
        if not arg_text:
            return []

        def valid_arg(y):
            y = y.strip()
            if not y:
                raise cls.Exception(f'Missing arg in "{arg_text}"')
            return y

        return [valid_arg(x) for x in cls._separate(arg_text)]

    def build_function(self, argnames, code, *global_stack):
        global_stack = list(global_stack) or [{}]
        argnames = tuple(argnames)

        def resf(args, kwargs=None, allow_recursion=100):
            kwargs = kwargs or {}
            global_stack[0].update(zip_longest(argnames, args, fillvalue=JS_Undefined))
            global_stack[0].update(kwargs)
            var_stack = LocalNameSpace(*global_stack)
            ret, should_abort = self.interpret_statement(code.replace('\n', ' '), var_stack, allow_recursion - 1)
            if should_abort:
                return ret

        return resf
