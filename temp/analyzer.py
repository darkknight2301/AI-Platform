#!/usr/bin/env python3
"""
Repository metadata analyzer and Python skeleton generator.

Compatible with Python 3.8. Uses only the standard library.

Commands:
    python3.8 repo_meta.py analyze /path/to/repo --output repository_meta.json
    python3.8 repo_meta.py generate repository_meta.json --output-dir ./generated_repo
    python3.8 repo_meta.py roundtrip /path/to/repo --meta repository_meta.json \
        --output-dir ./generated_repo

Behavior:
- Recursively scans .py and .json files.
- Extracts Python imports, classes, methods, functions, annotations, defaults,
  decorators, docstrings, and simple variables.
- Stores JSON file paths and names only; original JSON content is not read.
- Generates Python interface skeletons and empty JSON objects.
- Rejects unsafe paths in metadata and does not overwrite files unless requested.
"""

import argparse
import ast
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


METADATA_VERSION = 1
SUPPORTED_SUFFIXES = (".py", ".json")
IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".tox", "node_modules", "dist", "build",
}


# ---------- AST rendering (Python 3.8; no ast.unparse dependency) ----------

def render_ast(node):
    """Render common Python AST nodes without ast.unparse (Python 3.8)."""
    if node is None:
        return None

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant):
        return repr(node.value)
    if isinstance(node, ast.Str):  # Python 3.8 string literal
        return repr(node.s)
    if isinstance(node, ast.Num):  # Python 3.8 numeric literal
        return repr(node.n)
    if isinstance(node, ast.Bytes):
        return repr(node.s)
    if isinstance(node, ast.NameConstant):
        return repr(node.value)
    if isinstance(node, ast.Attribute):
        return render_ast(node.value) + "." + node.attr
    if isinstance(node, ast.Subscript):
        return render_ast(node.value) + "[" + render_ast(node.slice) + "]"
    if isinstance(node, ast.Index):  # Python 3.8
        return render_ast(node.value)
    if isinstance(node, ast.Slice):
        lower = render_ast(node.lower) if node.lower is not None else ""
        upper = render_ast(node.upper) if node.upper is not None else ""
        step = render_ast(node.step) if node.step is not None else ""
        result = lower + ":" + upper
        if node.step is not None:
            result += ":" + step
        return result
    if isinstance(node, ast.Tuple):
        values = ", ".join(render_ast(item) for item in node.elts)
        if len(node.elts) == 1:
            values += ","
        return "(" + values + ")"
    if isinstance(node, ast.List):
        return "[" + ", ".join(render_ast(item) for item in node.elts) + "]"
    if isinstance(node, ast.Set):
        return "{" + ", ".join(render_ast(item) for item in node.elts) + "}"
    if isinstance(node, ast.Dict):
        pairs = []
        for key, value in zip(node.keys, node.values):
            key_text = render_ast(key) if key is not None else "**"
            if key is None:
                pairs.append("**" + render_ast(value))
            else:
                pairs.append(key_text + ": " + render_ast(value))
        return "{" + ", ".join(pairs) + "}"
    if isinstance(node, ast.UnaryOp):
        operators = {
            ast.UAdd: "+", ast.USub: "-", ast.Not: "not ",
            ast.Invert: "~",
        }
        return operators.get(type(node.op), "") + render_ast(node.operand)
    if isinstance(node, ast.BinOp):
        operators = {
            ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
            ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**",
            ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^",
            ast.LShift: "<<", ast.RShift: ">>", ast.MatMult: "@",
        }
        return render_ast(node.left) + " " + operators.get(type(node.op), "?") + " " + render_ast(node.right)
    if isinstance(node, ast.BoolOp):
        operator = " and " if isinstance(node.op, ast.And) else " or "
        return operator.join(render_ast(value) for value in node.values)
    if isinstance(node, ast.Compare):
        operators = {
            ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=",
            ast.Gt: ">", ast.GtE: ">=", ast.Is: "is", ast.IsNot: "is not",
            ast.In: "in", ast.NotIn: "not in",
        }
        pieces = [render_ast(node.left)]
        for op, comparator in zip(node.ops, node.comparators):
            pieces.append(operators.get(type(op), "?"))
            pieces.append(render_ast(comparator))
        return " ".join(pieces)
    if isinstance(node, ast.IfExp):
        return render_ast(node.body) + " if " + render_ast(node.test) + " else " + render_ast(node.orelse)
    if isinstance(node, ast.Call):
        args = [render_ast(arg) for arg in node.args]
        for keyword in node.keywords:
            if keyword.arg is None:
                args.append("**" + render_ast(keyword.value))
            else:
                args.append(keyword.arg + "=" + render_ast(keyword.value))
        return render_ast(node.func) + "(" + ", ".join(args) + ")"
    if isinstance(node, ast.Lambda):
        args = render_arguments(node.args)
        return "lambda " + args + ": " + render_ast(node.body)
    if isinstance(node, ast.JoinedStr):
        # Render f-strings, including common conversions and format specs.
        pieces = []
        for value in node.values:
            if isinstance(value, ast.Str):
                text = value.s
                pieces.append(text.replace("{", "{{").replace("}", "}}"))
            elif isinstance(value, ast.FormattedValue):
                expression = render_ast(value.value)
                if value.conversion == ord("s"):
                    expression += "!s"
                elif value.conversion == ord("r"):
                    expression += "!r"
                elif value.conversion == ord("a"):
                    expression += "!a"
                if value.format_spec is not None:
                    expression += ":" + render_ast(value.format_spec)
                pieces.append("{" + expression + "}")
            else:
                raise ValueError("Unsupported f-string node: " + type(value).__name__)
        # repr chooses a safe quote style; prefix with f.
        return "f" + repr("".join(pieces))
    if isinstance(node, ast.FormattedValue):
        return "{" + render_ast(node.value) + "}"
    if isinstance(node, ast.ListComp):
        return "[" + render_ast(node.elt) + " " + render_comprehensions(node.generators) + "]"
    if isinstance(node, ast.SetComp):
        return "{" + render_ast(node.elt) + " " + render_comprehensions(node.generators) + "}"
    if isinstance(node, ast.GeneratorExp):
        return "(" + render_ast(node.elt) + " " + render_comprehensions(node.generators) + ")"
    if isinstance(node, ast.DictComp):
        return "{" + render_ast(node.key) + ": " + render_ast(node.value) + " " + render_comprehensions(node.generators) + "}"
    if isinstance(node, ast.Await):
        return "await " + render_ast(node.value)
    if isinstance(node, ast.Yield):
        return "yield" + ((" " + render_ast(node.value)) if node.value is not None else "")
    if isinstance(node, ast.YieldFrom):
        return "yield from " + render_ast(node.value)
    if isinstance(node, ast.Starred):
        return "*" + render_ast(node.value)
    if isinstance(node, ast.NamedExpr):
        return "(" + render_ast(node.target) + " := " + render_ast(node.value) + ")"

    raise ValueError("Unsupported AST node without ast.unparse: " + type(node).__name__)


def render_comprehensions(generators):
    pieces = []
    for generator in generators:
        piece = "async for " if generator.is_async else "for "
        piece += render_ast(generator.target) + " in " + render_ast(generator.iter)
        for condition in generator.ifs:
            piece += " if " + render_ast(condition)
        pieces.append(piece)
    return " ".join(pieces)


def render_arguments(args):
    """Render lambda/function argument declarations from ast.arguments."""
    result = []
    positional = list(args.posonlyargs) + list(args.args)
    defaults_start = len(positional) - len(args.defaults)

    for index, arg in enumerate(positional):
        text = arg.arg
        if arg.annotation is not None:
            text += ": " + render_ast(arg.annotation)
        if index >= defaults_start:
            text += " = " + render_ast(args.defaults[index - defaults_start])
        result.append(text)
        if args.posonlyargs and index == len(args.posonlyargs) - 1:
            result.append("/")

    if args.vararg is not None:
        text = "*" + args.vararg.arg
        if args.vararg.annotation is not None:
            text += ": " + render_ast(args.vararg.annotation)
        result.append(text)
    elif args.kwonlyargs:
        result.append("*")

    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        text = arg.arg
        if arg.annotation is not None:
            text += ": " + render_ast(arg.annotation)
        if default is not None:
            text += " = " + render_ast(default)
        result.append(text)

    if args.kwarg is not None:
        text = "**" + args.kwarg.arg
        if args.kwarg.annotation is not None:
            text += ": " + render_ast(args.kwarg.annotation)
        result.append(text)

    return ", ".join(result)


# ---------- Python source analysis ----------

def get_docstring(node):
    try:
        return ast.get_docstring(node, clean=False)
    except (TypeError, AttributeError):
        return None


def get_decorators(node):
    result = []
    for decorator in getattr(node, "decorator_list", []):
        try:
            result.append(render_ast(decorator))
        except ValueError:
            result.append("<unsupported:" + type(decorator).__name__ + ">")
    return result


def get_imports(tree):
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.append({
                "kind": "import",
                "module": None,
                "level": 0,
                "names": [
                    {"name": alias.name, "asname": alias.asname}
                    for alias in node.names
                ],
                "line": node.lineno,
            })
        elif isinstance(node, ast.ImportFrom):
            imports.append({
                "kind": "from",
                "module": node.module,
                "level": node.level,
                "names": [
                    {"name": alias.name, "asname": alias.asname}
                    for alias in node.names
                ],
                "line": node.lineno,
            })
    return sorted(imports, key=lambda item: item["line"])


def get_function_metadata(node, is_method=False):
    args = node.args
    parameters = []
    positional = list(args.posonlyargs) + list(args.args)
    defaults_start = len(positional) - len(args.defaults)

    for index, arg in enumerate(positional):
        if index < len(args.posonlyargs):
            kind = "positional_only"
        else:
            kind = "positional_or_keyword"
        default = args.defaults[index - defaults_start] if index >= defaults_start else None
        parameters.append({
            "name": arg.arg,
            "kind": kind,
            "annotation": render_ast(arg.annotation) if arg.annotation is not None else None,
            "default": render_ast(default) if default is not None else None,
        })

    if args.vararg is not None:
        parameters.append({
            "name": args.vararg.arg,
            "kind": "var_positional",
            "annotation": render_ast(args.vararg.annotation) if args.vararg.annotation is not None else None,
            "default": None,
        })

    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        parameters.append({
            "name": arg.arg,
            "kind": "keyword_only",
            "annotation": render_ast(arg.annotation) if arg.annotation is not None else None,
            "default": render_ast(default) if default is not None else None,
        })

    if args.kwarg is not None:
        parameters.append({
            "name": args.kwarg.arg,
            "kind": "var_keyword",
            "annotation": render_ast(args.kwarg.annotation) if args.kwarg.annotation is not None else None,
            "default": None,
        })

    return_type = render_ast(node.returns) if node.returns is not None else None
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    signature_args = render_arguments(args)
    signature = prefix + " " + node.name + "(" + signature_args + ")"
    if return_type:
        signature += " -> " + return_type

    return {
        "name": node.name,
        "kind": "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
        "line": node.lineno,
        "end_line": getattr(node, "end_lineno", None),
        "decorators": get_decorators(node),
        "arguments": parameters,
        "return_type": return_type,
        "signature": signature,
        "docstring": get_docstring(node),
        "is_method": is_method,
    }


def get_class_metadata(node):
    methods = []
    nested_classes = []
    class_attributes = []

    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(get_function_metadata(child, is_method=True))
        elif isinstance(child, ast.ClassDef):
            nested_classes.append(get_class_metadata(child))
        elif isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name):
                    try:
                        value = render_ast(child.value)
                    except ValueError:
                        value = None
                    class_attributes.append({
                        "name": target.id, "annotation": None,
                        "value": value, "line": child.lineno,
                    })
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            try:
                value = render_ast(child.value) if child.value is not None else None
            except ValueError:
                value = None
            class_attributes.append({
                "name": child.target.id,
                "annotation": render_ast(child.annotation),
                "value": value,
                "line": child.lineno,
            })

    bases = []
    for base in node.bases:
        try:
            bases.append(render_ast(base))
        except ValueError:
            bases.append("<unsupported:" + type(base).__name__ + ">")

    keywords = []
    for keyword in node.keywords:
        try:
            value = render_ast(keyword.value)
        except ValueError:
            value = None
        keywords.append({"name": keyword.arg, "value": value})

    return {
        "name": node.name,
        "line": node.lineno,
        "end_line": getattr(node, "end_lineno", None),
        "decorators": get_decorators(node),
        "bases": bases,
        "keywords": keywords,
        "docstring": get_docstring(node),
        "methods": methods,
        "nested_classes": nested_classes,
        "class_attributes": class_attributes,
    }


def analyze_python_file(path, relative_path):
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="utf-8", errors="replace")

    record = {
        "path": relative_path,
        "type": "python",
        "module_docstring": None,
        "imports": [],
        "classes": [],
        "functions": [],
        "module_variables": [],
        "parse_error": None,
    }

    try:
        tree = ast.parse(source, filename=relative_path)
    except SyntaxError as error:
        record["parse_error"] = {
            "message": error.msg,
            "line": error.lineno,
            "offset": error.offset,
        }
        return record

    record["module_docstring"] = get_docstring(tree)
    record["imports"] = get_imports(tree)

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            record["classes"].append(get_class_metadata(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            record["functions"].append(get_function_metadata(node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        value = render_ast(node.value)
                    except ValueError:
                        value = None
                    record["module_variables"].append({
                        "name": target.id, "annotation": None,
                        "value": value, "line": node.lineno,
                    })
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            try:
                value = render_ast(node.value) if node.value is not None else None
            except ValueError:
                value = None
            record["module_variables"].append({
                "name": node.target.id,
                "annotation": render_ast(node.annotation),
                "value": value,
                "line": node.lineno,
            })

    return record


# ---------- Repository scanning and metadata ----------

def is_ignored_path(relative_path, include_hidden):
    parts = Path(relative_path).parts
    for part in parts:
        if part in IGNORED_DIRS:
            return True
        if not include_hidden and part.startswith("."):
            return True
    return False


def scan_files(root, include_hidden=False):
    for current, directories, filenames in os.walk(str(root), followlinks=False):
        current_path = Path(current)
        relative_directory = current_path.relative_to(root)
        directories[:] = sorted(
            name for name in directories
            if name not in IGNORED_DIRS
            and (include_hidden or not name.startswith("."))
        )
        for filename in sorted(filenames):
            path = current_path / filename
            if path.is_symlink() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            relative = path.relative_to(root).as_posix()
            if is_ignored_path(relative, include_hidden):
                continue
            yield path, relative


def analyze_repository(root, include_hidden=False):
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError("Repository root is not a directory: " + str(root))

    files = []
    for path, relative in scan_files(root, include_hidden):
        if path.suffix.lower() == ".py":
            files.append(analyze_python_file(path, relative))
        else:
            # Do not read JSON file content; preserve path and basename only.
            files.append({
                "path": relative,
                "type": "json",
                "filename": path.name,
            })

    files.sort(key=lambda item: item["path"])
    python_count = sum(1 for item in files if item["type"] == "python")
    json_count = sum(1 for item in files if item["type"] == "json")

    return {
        "metadata_version": METADATA_VERSION,
        "source_root_name": root.name,
        "purpose": "Repository structure and Python interface metadata",
        "supported_file_types": [".py", ".json"],
        "generation_options": {
            "python_body_mode": "stub",
            "json_generation_mode": "empty_object",
            "ignored_directories": sorted(IGNORED_DIRS),
        },
        "summary": {
            "file_count": len(files),
            "python_file_count": python_count,
            "json_file_count": json_count,
        },
        "files": files,
    }


def analyze_input(input_path, include_hidden=False):
    """Analyze either a repository directory or one .py/.json file.

    For a single file, its parent directory is the root so metadata stores the
    filename as a relative path (without copying the absolute source path).
    """
    input_path = Path(input_path).resolve()
    if input_path.is_dir():
        return analyze_repository(input_path, include_hidden)

    if not input_path.is_file():
        raise FileNotFoundError("Input path does not exist: " + str(input_path))

    if input_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(
            "Unsupported input file type: " + input_path.suffix
            + ". Supported types are .py and .json."
        )

    root = input_path.parent
    relative = input_path.name
    if input_path.suffix.lower() == ".py":
        file_info = analyze_python_file(input_path, relative)
    else:
        # Do not read JSON contents; only preserve the file path and basename.
        file_info = {
            "path": relative,
            "type": "json",
            "filename": input_path.name,
        }

    python_count = 1 if file_info["type"] == "python" else 0
    json_count = 1 if file_info["type"] == "json" else 0
    return {
        "metadata_version": METADATA_VERSION,
        "source_root_name": root.name,
        "purpose": "Single-file structure and Python interface metadata",
        "supported_file_types": [".py", ".json"],
        "generation_options": {
            "python_body_mode": "stub",
            "json_generation_mode": "empty_object",
            "ignored_directories": sorted(IGNORED_DIRS),
        },
        "summary": {
            "file_count": 1,
            "python_file_count": python_count,
            "json_file_count": json_count,
        },
        "files": [file_info],
    }


# ---------- Skeleton generation ----------

def quote_docstring(text, indent):
    return [indent + repr(text)]


def render_function_stub(info, indent=""):
    lines = []
    for decorator in info.get("decorators", []):
        lines.append(indent + "@" + decorator)

    args = info.get("arguments", [])
    rendered = []
    seen_posonly = False
    inserted_kwonly_marker = False
    has_varargs = any(item.get("kind") == "var_positional" for item in args)

    for item in args:
        kind = item.get("kind")
        if kind == "positional_only":
            seen_posonly = True
        elif seen_posonly:
            if rendered and rendered[-1] != "/":
                rendered.append("/")
            seen_posonly = False

        if kind == "keyword_only" and not inserted_kwonly_marker:
            if not has_varargs:
                rendered.append("*")
            inserted_kwonly_marker = True

        name = item["name"]
        annotation = item.get("annotation")
        default = item.get("default")
        if kind == "var_positional":
            name = "*" + name
        elif kind == "var_keyword":
            name = "**" + name
        if annotation:
            name += ": " + annotation
        if default is not None and kind not in ("var_positional", "var_keyword"):
            name += " = " + default
        rendered.append(name)

    if seen_posonly:
        rendered.append("/")

    return_type = info.get("return_type")
    prefix = "async def" if info.get("kind") == "async_function" else "def"
    signature = indent + prefix + " " + info["name"] + "(" + ", ".join(rendered) + ")"
    if return_type:
        signature += " -> " + return_type
    lines.append(signature + ":")

    body_indent = indent + "    "
    if info.get("docstring"):
        lines.extend(quote_docstring(info["docstring"], body_indent))
    lines.append(body_indent + "...")
    return lines


def render_class_stub(info, indent=""):
    lines = []
    for decorator in info.get("decorators", []):
        lines.append(indent + "@" + decorator)

    bases = info.get("bases", [])
    base_text = "(" + ", ".join(bases) + ")" if bases else ""
    lines.append(indent + "class " + info["name"] + base_text + ":")
    body_indent = indent + "    "
    body = []

    if info.get("docstring"):
        body.extend(quote_docstring(info["docstring"], body_indent))

    for attribute in info.get("class_attributes", []):
        line = body_indent + attribute["name"]
        if attribute.get("annotation"):
            line += ": " + attribute["annotation"]
        if attribute.get("value") is not None:
            line += " = " + attribute["value"]
        body.append(line)

    for method in info.get("methods", []):
        if body:
            body.append("")
        body.extend(render_function_stub(method, body_indent))

    for nested in info.get("nested_classes", []):
        if body:
            body.append("")
        body.extend(render_class_stub(nested, body_indent))

    if not body:
        body.append(body_indent + "...")

    lines.extend(body)
    return lines


def render_python_skeleton(info):
    lines = []
    if info.get("module_docstring"):
        lines.extend(quote_docstring(info["module_docstring"], ""))

    for item in info.get("imports", []):
        aliases = []
        for alias in item.get("names", []):
            text = alias["name"]
            if alias.get("asname"):
                text += " as " + alias["asname"]
            aliases.append(text)
        if item["kind"] == "import":
            lines.append("import " + ", ".join(aliases))
        else:
            module = "." * item.get("level", 0) + (item.get("module") or "")
            lines.append("from " + module + " import " + ", ".join(aliases))

    if lines and (info.get("module_variables") or info.get("classes") or info.get("functions")):
        lines.append("")

    for variable in info.get("module_variables", []):
        line = variable["name"]
        if variable.get("annotation"):
            line += ": " + variable["annotation"]
        if variable.get("value") is not None:
            line += " = " + variable["value"]
        lines.append(line)

    definitions = []
    definitions.extend(render_class_stub(item) for item in info.get("classes", []))
    definitions.extend(render_function_stub(item) for item in info.get("functions", []))

    for definition in definitions:
        if lines:
            lines.append("")
        lines.extend(definition)

    if info.get("parse_error"):
        lines.append("# Original Python file could not be parsed.")
        lines.append("# Parse error: " + info["parse_error"]["message"])

    if not lines:
        lines = ['"""Generated Python skeleton."""', ""]

    return "\n".join(lines).rstrip() + "\n"


def safe_relative_path(raw_path):
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Unsafe relative path in metadata: " + raw_path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("Unsupported file extension in metadata: " + raw_path)
    return path


def generate_skeleton(metadata_path, output_dir, overwrite=False):
    metadata_path = Path(metadata_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("metadata_version") != METADATA_VERSION:
        raise ValueError("Unsupported metadata version: " + str(metadata.get("metadata_version")))

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    for info in metadata.get("files", []):
        relative = safe_relative_path(info["path"])
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)

        if destination.exists() and not overwrite:
            raise FileExistsError(
                "Refusing to overwrite existing file: " + str(destination)
                + " (use --overwrite to replace it)"
            )

        if info.get("type") == "python" and relative.suffix.lower() == ".py":
            content = render_python_skeleton(info)
        elif info.get("type") == "json" and relative.suffix.lower() == ".json":
            content = "{}\n"
        else:
            raise ValueError("Metadata type does not match path: " + str(relative))

        destination.write_text(content, encoding="utf-8")

    manifest_path = output_dir / "SKELETON_MANIFEST.json"
    if manifest_path.exists() and not overwrite:
        raise FileExistsError(
            "Refusing to overwrite existing file: " + str(manifest_path)
            + " (use --overwrite to replace it)"
        )
    manifest = {
        "generated_from_metadata": metadata_path.name,
        "metadata_version": METADATA_VERSION,
        "file_count": len(metadata.get("files", [])),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


# ---------- CLI ----------

def make_parser():
    parser = argparse.ArgumentParser(
        description="Analyze Python/JSON repositories and generate interface skeletons."
    )
    commands = parser.add_subparsers(dest="command")

    analyze_parser = commands.add_parser("analyze", help="Analyze a source repository or a single .py/.json file")
    analyze_parser.add_argument("repo", help="Source directory or one .py/.json file")
    analyze_parser.add_argument(
        "--output", "-o", default="repository_meta.json",
        help="Metadata output file (default: repository_meta.json)",
    )
    analyze_parser.add_argument("--include-hidden", action="store_true")

    generate_parser = commands.add_parser("generate", help="Generate skeleton from metadata")
    generate_parser.add_argument("metadata", help="Metadata JSON path")
    generate_parser.add_argument("--output-dir", "-o", required=True)
    generate_parser.add_argument("--overwrite", action="store_true")

    roundtrip_parser = commands.add_parser("roundtrip", help="Analyze and generate skeleton")
    roundtrip_parser.add_argument("repo", help="Source directory or one .py/.json file")
    roundtrip_parser.add_argument("--meta", default="repository_meta.json")
    roundtrip_parser.add_argument("--output-dir", required=True)
    roundtrip_parser.add_argument("--include-hidden", action="store_true")
    roundtrip_parser.add_argument("--overwrite", action="store_true")

    return parser


def write_metadata(metadata, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv=None):
    parser = make_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 2

    try:
        if args.command == "analyze":
            metadata = analyze_input(args.repo, args.include_hidden)
            write_metadata(metadata, args.output)
            print(
                "Metadata written to {0} ({1} Python, {2} JSON files)".format(
                    args.output,
                    metadata["summary"]["python_file_count"],
                    metadata["summary"]["json_file_count"],
                )
            )
        elif args.command == "generate":
            generate_skeleton(args.metadata, args.output_dir, args.overwrite)
            print("Skeleton generated at " + str(args.output_dir))
        elif args.command == "roundtrip":
            metadata = analyze_input(args.repo, args.include_hidden)
            write_metadata(metadata, args.meta)
            generate_skeleton(args.meta, args.output_dir, args.overwrite)
            print("Metadata written to {0}; skeleton generated at {1}".format(
                args.meta, args.output_dir
            ))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
