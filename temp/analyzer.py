#!/usr/bin/env python3
"""
Repository analyzer and skeleton generator.

Analyzes .py and .json files and writes one metadata JSON file.
Can then recreate a lightweight repository skeleton from that metadata.

Python: 3.8+
No third-party dependencies.

Examples:
    # Analyze a repository
    python repo_meta.py analyze /path/to/repo --output repo_meta.json

    # Recreate the skeleton from metadata
    python repo_meta.py generate repo_meta.json --output-dir ./generated_repo

    # Analyze and generate in one command
    python repo_meta.py roundtrip /path/to/repo --meta repo_meta.json \
        --output-dir ./generated_repo
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union


METADATA_VERSION = 1
SUPPORTED_SUFFIXES = {".py", ".json"}
IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".tox", "node_modules", "dist", "build",
}


def safe_relative_path(path: Path, root: Path) -> str:
    """Return a POSIX relative path and reject paths outside the repository."""
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"Path {path} is outside repository root {root}") from exc


def unparse_node(node: ast.AST) -> str:
    """Render an AST node; use astunparse as an optional Python 3.8 fallback."""
    unparse = getattr(ast, "unparse", None)
    if unparse is not None:
        return unparse(node)
    try:
        import astunparse
        return astunparse.unparse(node).strip()
    except ImportError:
        # Minimal fallback for common names and annotations.
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Constant):
            return repr(node.value)
        if isinstance(node, ast.Attribute):
            return unparse_node(node.value) + "." + node.attr
        if isinstance(node, ast.Subscript):
            return unparse_node(node.value) + "[" + unparse_node(node.slice) + "]"
        if hasattr(ast, "Index") and isinstance(node, ast.Index):
            return unparse_node(node.value)
        if isinstance(node, ast.Tuple):
            return ", ".join(unparse_node(item) for item in node.elts)
        if isinstance(node, ast.List):
            return "[" + ", ".join(unparse_node(item) for item in node.elts) + "]"
        if isinstance(node, ast.Call):
            args = [unparse_node(arg) for arg in node.args]
            args.extend((kw.arg + "=" if kw.arg else "**") + unparse_node(kw.value) for kw in node.keywords)
            return unparse_node(node.func) + "(" + ", ".join(args) + ")"
        raise ValueError("Cannot render AST node without astunparse: " + type(node).__name__)


def annotation_to_text(node: Optional[ast.AST]) -> Optional[str]:
    """Convert an annotation AST node to readable source text."""
    if node is None:
        return None
    try:
        return unparse_node(node)
    except Exception:
        return None


def expression_to_text(node: Optional[ast.AST]) -> Optional[str]:
    if node is None:
        return None
    try:
        return unparse_node(node)
    except Exception:
        return None


def get_docstring(node: ast.AST) -> Optional[str]:
    value = ast.get_docstring(node, clean=False)
    return value if value else None


def get_arguments(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> List[Dict[str, Any]]:
    """Extract parameters, including positional-only, keyword-only, *args and **kwargs."""
    args = node.args
    result: List[Dict[str, Any]] = []

    positional = list(args.posonlyargs) + list(args.args)
    defaults_start = len(positional) - len(args.defaults)

    for index, arg in enumerate(positional):
        default_node = args.defaults[index - defaults_start] if index >= defaults_start else None
        if index < len(args.posonlyargs):
            kind = "positional_only"
        else:
            kind = "positional_or_keyword"
        result.append({
            "name": arg.arg,
            "kind": kind,
            "annotation": annotation_to_text(arg.annotation),
            "default": expression_to_text(default_node),
        })

    if args.vararg:
        result.append({
            "name": args.vararg.arg,
            "kind": "var_positional",
            "annotation": annotation_to_text(args.vararg.annotation),
            "default": None,
        })

    for arg, default_node in zip(args.kwonlyargs, args.kw_defaults):
        result.append({
            "name": arg.arg,
            "kind": "keyword_only",
            "annotation": annotation_to_text(arg.annotation),
            "default": expression_to_text(default_node),
        })

    if args.kwarg:
        result.append({
            "name": args.kwarg.arg,
            "kind": "var_keyword",
            "annotation": annotation_to_text(args.kwarg.annotation),
            "default": None,
        })

    return result


def get_imports(tree: ast.Module) -> List[Dict[str, Any]]:
    imports: List[Dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.append({
                "kind": "import",
                "module": None,
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
    imports.sort(key=lambda item: item["line"])
    return imports


def get_decorators(node: ast.AST) -> List[str]:
    return [
        unparse_node(decorator)
        for decorator in getattr(node, "decorator_list", [])
    ]


def get_function_metadata(
    node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
    *,
    class_method: bool = False,
) -> Dict[str, Any]:
    return {
        "name": node.name,
        "kind": "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
        "line": node.lineno,
        "end_line": getattr(node, "end_lineno", None),
        "decorators": get_decorators(node),
        "arguments": get_arguments(node),
        "return_type": annotation_to_text(node.returns),
        "signature": function_signature(node),
        "docstring": get_docstring(node),
        "is_method": class_method,
    }


def function_signature(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> str:
    """Render a readable function signature without its implementation."""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    parameters = []
    args = node.args
    positional = list(args.posonlyargs) + list(args.args)
    defaults_start = len(positional) - len(args.defaults)
    for index, arg in enumerate(positional):
        item = arg.arg
        annotation = annotation_to_text(arg.annotation)
        if annotation:
            item += ": " + annotation
        if index >= defaults_start:
            default = expression_to_text(args.defaults[index - defaults_start])
            if default is not None:
                item += " = " + default
        parameters.append(item)
        if args.posonlyargs and index == len(args.posonlyargs) - 1:
            parameters.append("/")
    if args.vararg:
        item = "*" + args.vararg.arg
        annotation = annotation_to_text(args.vararg.annotation)
        if annotation:
            item += ": " + annotation
        parameters.append(item)
    elif args.kwonlyargs:
        parameters.append("*")
    for arg, default_node in zip(args.kwonlyargs, args.kw_defaults):
        item = arg.arg
        annotation = annotation_to_text(arg.annotation)
        if annotation:
            item += ": " + annotation
        default = expression_to_text(default_node)
        if default is not None:
            item += " = " + default
        parameters.append(item)
    if args.kwarg:
        item = "**" + args.kwarg.arg
        annotation = annotation_to_text(args.kwarg.annotation)
        if annotation:
            item += ": " + annotation
        parameters.append(item)
    return_type = annotation_to_text(node.returns)
    result = "{} {}({})".format(prefix, node.name, ", ".join(parameters))
    if return_type:
        result += " -> " + return_type
    return result



def get_class_metadata(node: ast.ClassDef) -> Dict[str, Any]:
    methods = []
    nested_classes = []
    class_attributes = []

    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(get_function_metadata(child, class_method=True))
        elif isinstance(child, ast.ClassDef):
            nested_classes.append(get_class_metadata(child))
        elif isinstance(child, (ast.Assign, ast.AnnAssign)):
            targets: List[ast.AST] = child.targets if isinstance(child, ast.Assign) else [child.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    class_attributes.append({
                        "name": target.id,
                        "annotation": annotation_to_text(child.annotation)
                        if isinstance(child, ast.AnnAssign) else None,
                        "value": expression_to_text(child.value),
                        "line": child.lineno,
                    })

    return {
        "name": node.name,
        "line": node.lineno,
        "end_line": getattr(node, "end_lineno", None),
        "decorators": get_decorators(node),
        "bases": [expression_to_text(base) for base in node.bases],
        "keywords": [
            {"name": keyword.arg, "value": expression_to_text(keyword.value)}
            for keyword in node.keywords
        ],
        "docstring": get_docstring(node),
        "methods": methods,
        "nested_classes": nested_classes,
        "class_attributes": class_attributes,
    }


def analyze_python_file(path: Path, relative_path: str) -> Dict[str, Any]:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="utf-8", errors="replace")

    record: Dict[str, Any] = {
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
    except SyntaxError as exc:
        record["parse_error"] = {
            "message": exc.msg,
            "line": exc.lineno,
            "offset": exc.offset,
        }
        return record

    record["module_docstring"] = get_docstring(tree)
    record["imports"] = get_imports(tree)

    # Only top-level definitions are recorded here. Methods are recorded under classes.
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            record["classes"].append(get_class_metadata(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            record["functions"].append(get_function_metadata(node))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    record["module_variables"].append({
                        "name": target.id,
                        "annotation": annotation_to_text(node.annotation)
                        if isinstance(node, ast.AnnAssign) else None,
                        "value": expression_to_text(node.value),
                        "line": node.lineno,
                    })

    return record


def iter_repository_files(root: Path, include_hidden: bool = False):
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            directory for directory in dirs
            if directory not in IGNORED_DIRS
            and (include_hidden or not directory.startswith("."))
        )
        for filename in sorted(files):
            path = Path(current) / filename
            if path.is_symlink():
                continue
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if not include_hidden and any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            yield path


def analyze_repository(root: Path, include_hidden: bool = False) -> Dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Repository root is not a directory: {root}")

    files: List[Dict[str, Any]] = []
    for path in iter_repository_files(root, include_hidden=include_hidden):
        relative_path = safe_relative_path(path, root)
        if path.suffix.lower() == ".py":
            files.append(analyze_python_file(path, relative_path))
        else:
            # Deliberately do not read/store JSON contents.
            files.append({
                "path": relative_path,
                "type": "json",
                "filename": path.name,
                "placeholder": {},
            })

    files.sort(key=lambda item: item["path"])
    return {
        "metadata_version": METADATA_VERSION,
        "source_root_name": root.name,
        "purpose": "Repository structure and Python interface skeleton metadata",
        "supported_file_types": [".py", ".json"],
        "options": {
            "python_body_mode": "stub",
            "json_generation_mode": "empty_object",
            "ignored_directories": sorted(IGNORED_DIRS),
        },
        "summary": {
            "file_count": len(files),
            "python_file_count": sum(item["type"] == "python" for item in files),
            "json_file_count": sum(item["type"] == "json" for item in files),
        },
        "files": files,
    }


def render_annotation(annotation: Optional[str]) -> str:
    return f": {annotation}" if annotation else ""


def render_parameter(param: Dict[str, Any]) -> str:
    name = param["name"]
    kind = param.get("kind")
    annotation = render_annotation(param.get("annotation"))
    default = param.get("default")
    default_text = f" = {default}" if default is not None else ""

    if kind == "var_positional":
        return f"*{name}{annotation}"
    if kind == "var_keyword":
        return f"**{name}{annotation}"
    return f"{name}{annotation}{default_text}"


def render_function(function: Dict[str, Any], indent: str = "") -> List[str]:
    lines: List[str] = []
    for decorator in function.get("decorators", []):
        lines.append(f"{indent}@{decorator}")

    kind = function.get("kind", "function")
    prefix = "async def" if kind == "async_function" else "def"
    args = function.get("arguments", [])

    # Rebuild separators for positional-only and keyword-only parameters.
    rendered_args: List[str] = []
    seen_positional_only = False
    seen_keyword_only = False
    has_var_positional = any(p.get("kind") == "var_positional" for p in args)

    for param in args:
        param_kind = param.get("kind")
        if param_kind == "positional_only":
            seen_positional_only = True
        elif seen_positional_only and rendered_args and rendered_args[-1] != "/":
            rendered_args.append("/")
            seen_positional_only = False
        if param_kind == "keyword_only" and not seen_keyword_only:
            if not has_var_positional:
                rendered_args.append("*")
            seen_keyword_only = True
        rendered_args.append(render_parameter(param))

    if seen_positional_only:
        rendered_args.append("/")

    return_type = function.get("return_type")
    return_part = f" -> {return_type}" if return_type else ""
    lines.append(f"{indent}{prefix} {function['name']}({', '.join(rendered_args)}){return_part}:")

    docstring = function.get("docstring")
    body_indent = indent + "    "
    if docstring:
        lines.extend(render_docstring(docstring, body_indent))
    lines.append(f"{body_indent}...")
    return lines


def render_docstring(docstring: str, indent: str) -> List[str]:
    """Emit a valid quoted docstring while retaining its text."""
    encoded = json.dumps(docstring, ensure_ascii=False)
    return [f"{indent}{encoded}"]


def render_class(class_info: Dict[str, Any], indent: str = "") -> List[str]:
    lines: List[str] = []
    for decorator in class_info.get("decorators", []):
        lines.append(f"{indent}@{decorator}")

    bases = class_info.get("bases", [])
    bases = [base for base in bases if base]
    base_part = f"({', '.join(bases)})" if bases else ""
    lines.append(f"{indent}class {class_info['name']}{base_part}:")

    body_indent = indent + "    "
    body: List[str] = []

    if class_info.get("docstring"):
        body.extend(render_docstring(class_info["docstring"], body_indent))

    for attr in class_info.get("class_attributes", []):
        annotation = render_annotation(attr.get("annotation"))
        value = attr.get("value")
        value_part = f" = {value}" if value is not None else ""
        body.append(f"{body_indent}{attr['name']}{annotation}{value_part}")

    for method in class_info.get("methods", []):
        if body:
            body.append("")
        body.extend(render_function(method, body_indent))

    for nested in class_info.get("nested_classes", []):
        if body:
            body.append("")
        body.extend(render_class(nested, body_indent))

    if not body:
        body.append(f"{body_indent}...")

    lines.extend(body)
    return lines


def render_python_skeleton(file_info: Dict[str, Any]) -> str:
    lines: List[str] = []
    module_docstring = file_info.get("module_docstring")
    if module_docstring:
        lines.extend(render_docstring(module_docstring, ""))

    for item in file_info.get("imports", []):
        if item["kind"] == "import":
            pieces = []
            for alias in item["names"]:
                text = alias["name"]
                if alias.get("asname"):
                    text += f" as {alias['asname']}"
                pieces.append(text)
            lines.append("import " + ", ".join(pieces))
        else:
            module = "." * item.get("level", 0) + (item.get("module") or "")
            pieces = []
            for alias in item["names"]:
                text = alias["name"]
                if alias.get("asname"):
                    text += f" as {alias['asname']}"
                pieces.append(text)
            lines.append(f"from {module} import " + ", ".join(pieces))

    if lines and (file_info.get("classes") or file_info.get("functions") or file_info.get("module_variables")):
        lines.append("")

    for variable in file_info.get("module_variables", []):
        annotation = render_annotation(variable.get("annotation"))
        value = variable.get("value")
        value_part = f" = {value}" if value is not None else ""
        lines.append(f"{variable['name']}{annotation}{value_part}")

    definitions: List[List[str]] = []
    definitions.extend([render_class(item) for item in file_info.get("classes", [])])
    definitions.extend([render_function(item) for item in file_info.get("functions", [])])

    if file_info.get("parse_error"):
        lines.append("# Original file could not be parsed; generated placeholder.")
        lines.append("# Parse error: " + file_info["parse_error"]["message"])

    for definition in definitions:
        if lines:
            lines.append("")
        lines.extend(definition)

    if not lines:
        lines = ['"""Generated skeleton; original file had no extractable interface."""', ""]

    return "\n".join(lines).rstrip() + "\n"


def validate_relative_path(raw_path: str) -> Path:
    """Reject absolute paths and traversal entries from untrusted metadata."""
    candidate = Path(raw_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Unsafe relative path in metadata: {raw_path}")
    if candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type in metadata: {raw_path}")
    return candidate


def generate_skeleton(metadata_path: Path, output_dir: Path, overwrite: bool = False) -> None:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("metadata_version") != METADATA_VERSION:
        raise ValueError(
            f"Unsupported metadata version: {metadata.get('metadata_version')}"
        )

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    for file_info in metadata.get("files", []):
        relative = validate_relative_path(file_info["path"])
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)

        if destination.exists() and not overwrite:
            raise FileExistsError(
                f"Refusing to overwrite existing file: {destination}. "
                "Use --overwrite to replace it."
            )

        if file_info.get("type") == "python" and relative.suffix.lower() == ".py":
            content = render_python_skeleton(file_info)
        elif file_info.get("type") == "json" and relative.suffix.lower() == ".json":
            # Empty JSON placeholder: original JSON data is not embedded in metadata.
            content = json.dumps(file_info.get("placeholder", {}), indent=2) + "\n"
        else:
            raise ValueError(f"Metadata file type does not match path: {relative}")

        destination.write_text(content, encoding="utf-8")

    manifest = {
        "generated_from_metadata": metadata_path.name,
        "metadata_version": METADATA_VERSION,
        "file_count": len(metadata.get("files", [])),
    }
    manifest_path = output_dir / "SKELETON_MANIFEST.json"
    if manifest_path.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing file: {manifest_path}. "
            "Use --overwrite to replace it."
        )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze Python/JSON repository files and recreate a skeleton."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser("analyze", help="Analyze a repository")
    analyze_parser.add_argument("repo", type=Path, help="Source repository directory")
    analyze_parser.add_argument(
        "--output", "-o", type=Path, default=Path("repository_meta.json"),
        help="Metadata JSON output path (default: repository_meta.json)",
    )
    analyze_parser.add_argument(
        "--include-hidden", action="store_true",
        help="Include hidden files/directories except standard ignored directories",
    )

    generate_parser = subparsers.add_parser(
        "generate", help="Generate a skeleton from metadata JSON"
    )
    generate_parser.add_argument("metadata", type=Path, help="Metadata JSON file")
    generate_parser.add_argument(
        "--output-dir", "-o", type=Path, required=True,
        help="Directory where the skeleton will be created",
    )
    generate_parser.add_argument(
        "--overwrite", action="store_true",
        help="Allow replacing existing generated files",
    )

    roundtrip_parser = subparsers.add_parser(
        "roundtrip", help="Analyze a repository and generate its skeleton"
    )
    roundtrip_parser.add_argument("repo", type=Path, help="Source repository directory")
    roundtrip_parser.add_argument(
        "--meta", type=Path, default=Path("repository_meta.json"),
        help="Metadata JSON output path",
    )
    roundtrip_parser.add_argument(
        "--output-dir", type=Path, required=True,
        help="Directory where the skeleton will be created",
    )
    roundtrip_parser.add_argument("--include-hidden", action="store_true")
    roundtrip_parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "analyze":
            metadata = analyze_repository(args.repo, args.include_hidden)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(
                f"Metadata written to {args.output} "
                f"({metadata['summary']['python_file_count']} Python, "
                f"{metadata['summary']['json_file_count']} JSON files)"
            )

        elif args.command == "generate":
            generate_skeleton(args.metadata, args.output_dir, args.overwrite)
            print(f"Skeleton generated at {args.output_dir}")

        elif args.command == "roundtrip":
            metadata = analyze_repository(args.repo, args.include_hidden)
            args.meta.parent.mkdir(parents=True, exist_ok=True)
            args.meta.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            generate_skeleton(args.meta, args.output_dir, args.overwrite)
            print(
                f"Metadata written to {args.meta}; skeleton generated at {args.output_dir}"
            )

        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
