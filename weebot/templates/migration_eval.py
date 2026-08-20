"""Restricted AST evaluator for migration transformation scripts.

Replaces the legacy exec()-based migration runner with an allowlist interpreter
that permits only safe assignments, literals, and a small set of builtins.
"""

from __future__ import annotations

import ast
from typing import Any

_ALLOWED_BUILTINS = {"str", "int", "len", "sorted"}
_ALLOWED_METHODS = {"get", "upper", "lower", "strip", "split", "join", "replace"}
_ALLOWED_NAMES = {"parameters", "result"} | _ALLOWED_BUILTINS


class _Validator(ast.NodeVisitor):
    """Walks an AST and raises ValueError for any disallowed construct."""

    def visit_Import(self, node: ast.Import) -> None:  # noqa: D102
        raise ValueError("Import statements are not allowed in migration scripts")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: D102
        raise ValueError("Import statements are not allowed in migration scripts")

    def visit_Name(self, node: ast.Name) -> None:  # noqa: D102
        if node.id not in _ALLOWED_NAMES:
            raise ValueError(f"Unknown name {node.id!r} is not allowed")

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: D102
        if node.attr.startswith("__") and node.attr.endswith("__"):
            raise ValueError(f"Dunder access {node.attr!r} is not allowed")
        if node.attr not in _ALLOWED_METHODS:
            raise ValueError(f"Attribute access {node.attr!r} is not allowed")
        self.visit(node.value)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: D102
        if isinstance(node.func, ast.Name):
            if node.func.id not in _ALLOWED_BUILTINS:
                raise ValueError(f"Function call {node.func.id!r} is not allowed")
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr not in _ALLOWED_METHODS:
                raise ValueError(f"Method call {node.func.attr!r} is not allowed")
            self.visit(node.func.value)
        else:
            raise ValueError("Unsupported function call")
        for arg in node.args:
            self.visit(arg)
        for kw in node.keywords:
            self.visit(kw.value)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: D102
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                raise ValueError("Assignments must be to result[...] or parameters[...]")
            if not isinstance(target.value, ast.Name):
                raise ValueError("Assignments must be to result[...] or parameters[...]")
            if target.value.id not in {"result", "parameters"}:
                raise ValueError("Assignments must be to result[...] or parameters[...]")
            self.visit(target.slice)
        self.visit(node.value)

    def visit_Expr(self, node: ast.Expr) -> None:  # noqa: D102
        self.visit(node.value)

    def visit_Module(self, node: ast.Module) -> None:  # noqa: D102
        for stmt in node.body:
            self.visit(stmt)

    def visit_BinOp(self, node: ast.BinOp) -> None:  # noqa: D102
        self.visit(node.left)
        self.visit(node.right)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:  # noqa: D102
        self.visit(node.operand)

    def visit_Subscript(self, node: ast.Subscript) -> None:  # noqa: D102
        self.visit(node.value)
        self.visit(node.slice)

    def visit_List(self, node: ast.List) -> None:  # noqa: D102
        for elt in node.elts:
            self.visit(elt)

    def visit_Dict(self, node: ast.Dict) -> None:  # noqa: D102
        for k in node.keys:
            if k is None:
                raise ValueError("Dictionary unpacking is not allowed")
            self.visit(k)
        for v in node.values:
            self.visit(v)

    def visit_Tuple(self, node: ast.Tuple) -> None:  # noqa: D102
        for elt in node.elts:
            self.visit(elt)

    def visit_Compare(self, node: ast.Compare) -> None:  # noqa: D102
        self.visit(node.left)
        for comparator in node.comparators:
            self.visit(comparator)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:  # noqa: D102
        for value in node.values:
            self.visit(value)

    def visit_IfExp(self, node: ast.IfExp) -> None:  # noqa: D102
        self.visit(node.test)
        self.visit(node.body)
        self.visit(node.orelse)

    def visit_Keyword(self, node: ast.keyword) -> None:  # noqa: D102
        self.visit(node.value)

    def visit_Constant(self, node: ast.Constant) -> None:  # noqa: D102
        pass

    def generic_visit(self, node: ast.AST) -> None:  # noqa: D102
        raise ValueError(f"Unsupported expression type: {type(node).__name__}")


def evaluate_migration_script(script: str, parameters: dict, result: dict) -> dict:
    """Evaluate a migration transformation script using a restricted AST interpreter.

    Args:
        script: The Python script to evaluate.
        parameters: Dictionary of input parameters.
        result: Dictionary to mutate and return.

    Returns:
        The mutated ``result`` dictionary.

    Raises:
        ValueError: If the script contains any disallowed construct.
    """
    tree = ast.parse(script, mode="exec")
    _Validator().visit(tree)

    _builtins: dict[str, Any] = {"str": str, "int": int, "len": len, "sorted": sorted}

    def _eval(node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id == "parameters":
                return parameters
            if node.id == "result":
                return result
            if node.id in _builtins:
                return _builtins[node.id]
            raise ValueError(f"Unknown name: {node.id}")
        if isinstance(node, ast.Subscript):
            obj = _eval(node.value)
            key = _eval(node.slice)
            return obj[key]
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                func = _builtins.get(node.func.id)
                if func is None:
                    raise ValueError(f"Unknown function: {node.func.id}")
                args = [_eval(arg) for arg in node.args]
                kwargs = {kw.arg: _eval(kw.value) for kw in node.keywords}
                return func(*args, **kwargs)
            if isinstance(node.func, ast.Attribute):
                obj = _eval(node.func.value)
                method_name = node.func.attr
                args = [_eval(arg) for arg in node.args]
                kwargs = {kw.arg: _eval(kw.value) for kw in node.keywords}
                return getattr(obj, method_name)(*args, **kwargs)
            raise ValueError("Unsupported call")
        if isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.Pow):
                return left**right
            raise ValueError(f"Unsupported binary operator: {type(node.op).__name__}")
        if isinstance(node, ast.UnaryOp):
            operand = _eval(node.operand)
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.UAdd):
                return +operand
            if isinstance(node.op, ast.Not):
                return not operand
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        if isinstance(node, ast.List):
            return [_eval(elt) for elt in node.elts]
        if isinstance(node, ast.Dict):
            return {_eval(k): _eval(v) for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.Tuple):
            return tuple(_eval(elt) for elt in node.elts)
        if isinstance(node, ast.Compare):
            left = _eval(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = _eval(comparator)
                if isinstance(op, ast.Eq):
                    comp = left == right
                elif isinstance(op, ast.NotEq):
                    comp = left != right
                elif isinstance(op, ast.Lt):
                    comp = left < right
                elif isinstance(op, ast.LtE):
                    comp = left <= right
                elif isinstance(op, ast.Gt):
                    comp = left > right
                elif isinstance(op, ast.GtE):
                    comp = left >= right
                elif isinstance(op, ast.Is):
                    comp = left is right
                elif isinstance(op, ast.IsNot):
                    comp = left is not right
                elif isinstance(op, ast.In):
                    comp = left in right
                elif isinstance(op, ast.NotIn):
                    comp = left not in right
                else:
                    raise ValueError(f"Unsupported comparison: {type(op).__name__}")
                if not comp:
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            values = [_eval(v) for v in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
            raise ValueError(f"Unsupported bool op: {type(node.op).__name__}")
        if isinstance(node, ast.IfExp):
            test = _eval(node.test)
            if test:
                return _eval(node.body)
            return _eval(node.orelse)
        if isinstance(node, ast.Expr):
            return _eval(node.value)
        if isinstance(node, ast.Assign):
            value = _eval(node.value)
            for target in node.targets:
                container = _eval(target.value)
                key = _eval(target.slice)
                container[key] = value
            return value
        if isinstance(node, ast.Module):
            for stmt in node.body:
                _eval(stmt)
            return result
        raise ValueError(f"Unsupported expression type: {type(node).__name__}")

    return _eval(tree)
