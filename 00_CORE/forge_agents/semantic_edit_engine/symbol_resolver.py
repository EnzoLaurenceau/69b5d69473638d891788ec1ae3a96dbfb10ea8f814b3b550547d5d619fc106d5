from __future__ import annotations
import logging
import re
from enum import Enum
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

class SymbolKind(Enum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    VARIABLE = "variable"
    IMPORT = "import"
    PARAMETER = "parameter"
    UNKNOWN = "unknown"

class Language(Enum):
    # ── General ──
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    # ── Web / markup ──
    HTML = "html"
    CSS = "css"
    SCSS = "scss"
    VUE = "vue"
    SVELTE = "svelte"
    PHP = "php"
    MARKDOWN = "markdown"
    JSON = "json"
    YAML = "yaml"
    TOML = "toml"
    XML = "xml"
    # ── Game dev ──
    LUA = "lua"             # Roblox, LÖVE, game scripting
    GDSCRIPT = "gdscript"   # Godot
    CSHARP = "csharp"       # Unity
    CPP = "cpp"             # Unreal, engines
    GLSL = "glsl"           # OpenGL shaders (.glsl/.vert/.frag/.geom/.comp)
    HLSL = "hlsl"           # DirectX shaders
    WGSL = "wgsl"           # WebGPU shaders
    RUST = "rust"           # Bevy, engines
    DART = "dart"           # Flutter / Flame game engine
    # ── Scripting / infra ──
    SQL = "sql"
    SHELL = "shell"
    DOCKERFILE = "dockerfile"
    MAKEFILE = "makefile"
    CMAKE = "cmake"
    # ── Mobile ──
    KOTLIN = "kotlin"
    SWIFT = "swift"
    OBJC = "objc"
    JAVA = "java"
    # ── Other ──
    RUBY = "ruby"
    ELIXIR = "elixir"
    PERL = "perl"
    R = "r"
    TEXT = "text"           # any text file (fallback)
    UNKNOWN = "unknown"

@dataclass
class SymbolTarget:
    kind: SymbolKind
    name: str
    file_path: Path
    start_line: int
    end_line: int
    start_col: int
    end_col: int
    source_text: str
    parent_name: Optional[str] = None
    children_names: list[str] = field(default_factory=list)
    language: Language = Language.PYTHON

    def to_nmp(self) -> str:
        return f"SYMBOL|RESOLVE|{self.kind.value}|{self.name}|lines={self.start_line}-{self.end_line}"

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "name": self.name,
            "file_path": str(self.file_path),
            "start_line": self.start_line,
            "end_line": self.end_line,
            "source_text": self.source_text
        }

class SymbolResolver:
    def __init__(self):
        self._tree_sitter_available = False
        try:
            import tree_sitter
            self._tree_sitter_available = True
        except ImportError as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    def detect_language(self, file_path: Path) -> Language:
        ext = file_path.suffix.lower()
        name = file_path.name.lower()

        # ── Exact filenames first ──
        if name in ("dockerfile", "containerfile"): return Language.DOCKERFILE
        if name == "makefile" or name.endswith("makefile"): return Language.MAKEFILE
        if name == "cmakelists.txt" or name.endswith(".cmake"): return Language.CMAKE

        # ── By extension ──
        mapping = {
            # General
            ".py": Language.PYTHON,
            ".pyi": Language.PYTHON,
            # Web / JS ecosystem
            ".js": Language.JAVASCRIPT, ".jsx": Language.JAVASCRIPT,
            ".mjs": Language.JAVASCRIPT, ".cjs": Language.JAVASCRIPT,
            ".ts": Language.TYPESCRIPT, ".tsx": Language.TYPESCRIPT,
            ".mts": Language.TYPESCRIPT, ".cts": Language.TYPESCRIPT,
            # Web / markup
            ".html": Language.HTML, ".htm": Language.HTML,
            ".css": Language.CSS,
            ".scss": Language.SCSS, ".sass": Language.SCSS,
            ".less": Language.CSS,
            ".vue": Language.VUE,
            ".velte": Language.SVELTE, ".svelte": Language.SVELTE,
            ".astro": Language.HTML,
            ".php": Language.PHP,
            ".blade.php": Language.PHP,
            # Markdown / data
            ".md": Language.MARKDOWN, ".markdown": Language.MARKDOWN,
            ".mdx": Language.MARKDOWN,
            ".json": Language.JSON, ".jsonc": Language.JSON, ".json5": Language.JSON,
            ".yaml": Language.YAML, ".yml": Language.YAML,
            ".toml": Language.TOML,
            ".xml": Language.XML, ".svg": Language.XML, ".xhtml": Language.XML,
            ".xaml": Language.XML,
            # ── Game dev ──
            ".lua": Language.LUA,
            ".luau": Language.LUA,          # Roblox Luau
            ".gd": Language.GDSCRIPT,
            ".tscn": Language.TEXT,          # Godot scene (text)
            ".tres": Language.TEXT,          # Godot resource (text)
            ".cs": Language.CSHARP,
            ".csx": Language.CSHARP,
            # C/C++
            ".c": Language.CPP, ".cc": Language.CPP, ".cpp": Language.CPP,
            ".cxx": Language.CPP, ".h": Language.CPP, ".hpp": Language.CPP,
            ".hxx": Language.CPP, ".hh": Language.CPP,
            ".ino": Language.CPP,           # Arduino
            # Shaders
            ".glsl": Language.GLSL, ".vert": Language.GLSL, ".frag": Language.GLSL,
            ".geom": Language.GLSL, ".comp": Language.GLSL, ".tesc": Language.GLSL,
            ".tese": Language.GLSL,
            ".hlsl": Language.HLSL, ".fx": Language.HLSL, ".fxh": Language.HLSL,
            ".wgsl": Language.WGSL,
            ".shader": Language.GLSL,       # Unity shader (GLSL-like)
            ".cginc": Language.HLSL,        # Unity CG include
            # Rust / Bevy
            ".rs": Language.RUST,
            ".ron": Language.TEXT,           # Rusty Object Notation (Bevy scenes)
            # Dart / Flutter
            ".dart": Language.DART,
            # ── Mobile ──
            ".kt": Language.KOTLIN, ".kts": Language.KOTLIN,
            ".swift": Language.SWIFT,
            ".m": Language.OBJC, ".mm": Language.OBJC,
            ".java": Language.JAVA,
            ".gradle": Language.TEXT, ".gradle.kts": Language.KOTLIN,
            # ── Scripting / infra ──
            ".sql": Language.SQL,
            ".sh": Language.SHELL, ".bash": Language.SHELL, ".zsh": Language.SHELL,
            ".bat": Language.SHELL, ".cmd": Language.SHELL, ".ps1": Language.SHELL,
            # ── Other languages ──
            ".rb": Language.RUBY, ".erb": Language.RUBY,
            ".ex": Language.ELIXIR, ".exs": Language.ELIXIR,
            ".pl": Language.PERL, ".pm": Language.PERL,
            ".r": Language.R, ".rmd": Language.R,
            # ── Config / text ──
            ".txt": Language.TEXT, ".rst": Language.TEXT,
            ".ini": Language.TEXT, ".cfg": Language.TEXT,
            ".conf": Language.TEXT, ".env": Language.TEXT,
            ".csv": Language.TEXT, ".tsv": Language.TEXT,
            ".proto": Language.TEXT,        # Protobuf
            ".graphql": Language.TEXT, ".gql": Language.TEXT,
        }

        lang = mapping.get(ext)
        if lang is not None:
            return lang

        # Double extension check (.blade.php handled above, but .env.xxx etc)
        if file_path.suffixes:
            double = "".join(file_path.suffixes[-2:]).lower()
            lang = mapping.get(double)
            if lang is not None:
                return lang

        # Any other extension → treat as generic text (not UNKNOWN)
        # This ensures SEE NEVER returns UNKNOWN for real files.
        return Language.TEXT

    def resolve(self, name: str, file_path: Path, kind: SymbolKind = None) -> Optional[SymbolTarget]:
        if not file_path.exists():
            return None
        content = file_path.read_text(encoding="utf-8", errors="replace")
        lang = self.detect_language(file_path)

        # ── Python: resolve by def/class (existing logic) ──
        if lang == Language.PYTHON:
            pattern = rf"(?m)^(?:async\s+)?def\s+({re.escape(name)})\b|class\s+({re.escape(name)})\b"
            match = re.search(pattern, content)
            if match:
                idx = match.start()
                lines_before = content[:idx].count("\n") + 1
                raw_lines = content.splitlines(keepends=True)
                lines = [l.rstrip("\r\n") for l in raw_lines]
                indent = ""
                line_idx = lines_before - 1
                first_line = lines[line_idx]
                indent_match = re.match(r"^(\s*)", first_line)
                if indent_match:
                    indent = indent_match.group(1)

                block_indices = [line_idx]
                for i, l in enumerate(lines[line_idx+1:], start=line_idx+1):
                    if l.strip() and not l.startswith(indent + " ") and not l.startswith(indent + "\t") and not l.startswith(indent + ")"):
                        break
                    block_indices.append(i)

                source = "".join(raw_lines[i] for i in block_indices)
                skind = SymbolKind.CLASS if "class" in first_line else SymbolKind.FUNCTION
                return SymbolTarget(
                    kind=skind,
                    name=name,
                    file_path=file_path,
                    start_line=lines_before,
                    end_line=lines_before + len(block_indices) - 1,
                    start_col=len(indent),
                    end_col=len(first_line),
                    source_text=source,
                    language=lang
                )

        # ── JS/TS: resolve by function/class/export ──
        if lang in (Language.JAVASCRIPT, Language.TYPESCRIPT):
            pattern = rf"(?m)^(?:export\s+)?(?:async\s+)?(?:function|class|const|let|var)\s+({re.escape(name)})\b"
            match = re.search(pattern, content)
            if match:
                idx = match.start()
                lines_before = content[:idx].count("\n") + 1
                raw_lines = content.splitlines(keepends=True)
                lines = [l.rstrip("\r\n") for l in raw_lines]
                # JS block detection: find matching brace
                line_idx = lines_before - 1
                brace_count = 0
                end_idx = line_idx
                started = False
                for i, l in enumerate(lines[line_idx:], start=line_idx):
                    for ch in l:
                        if ch == '{':
                            brace_count += 1; started = True
                        elif ch == '}':
                            brace_count -= 1
                    if started and brace_count <= 0:
                        end_idx = i; break
                else:
                    end_idx = min(line_idx + 30, len(lines) - 1)

                source = "".join(raw_lines[i] for i in range(line_idx, end_idx + 1))
                return SymbolTarget(
                    kind=SymbolKind.FUNCTION,
                    name=name,
                    file_path=file_path,
                    start_line=lines_before,
                    end_line=end_idx + 1,
                    start_col=0, end_col=len(raw_lines[end_idx]),
                    source_text=source,
                    language=lang
                )

        # ── HTML: resolve by element id ──
        if lang == Language.HTML:
            # Try id="name" or id='name'
            pattern = rf'<(\w+)[^>]*\bid=["\']({re.escape(name)})["\']'
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                tag = match.group(1)
                idx = match.start()
                lines_before = content[:idx].count("\n") + 1
                # Find the matching closing tag
                close_pattern = rf'</{tag}>\s*'
                close_match = re.search(close_pattern, content[match.end():], re.IGNORECASE)
                if close_match:
                    end_char = match.end() + close_match.end()
                else:
                    end_char = min(idx + 2000, len(content))
                source = content[idx:end_char]
                end_line = lines_before + source.count("\n")
                return SymbolTarget(
                    kind=SymbolKind.VARIABLE,
                    name=name,
                    file_path=file_path,
                    start_line=lines_before,
                    end_line=end_line,
                    start_col=0, end_col=len(source.splitlines()[-1]),
                    source_text=source,
                    language=lang
                )

        # ── CSS: resolve by selector ──
        if lang == Language.CSS:
            pattern = rf"(?m)^({re.escape(name)})\s*\{{"
            match = re.search(pattern, content)
            if match:
                idx = match.start()
                lines_before = content[:idx].count("\n") + 1
                # Find matching closing brace
                brace_count = 0
                end_char = idx
                started = False
                for i, ch in enumerate(content[idx:], start=idx):
                    if ch == '{': brace_count += 1; started = True
                    elif ch == '}': brace_count -= 1
                    if started and brace_count <= 0:
                        end_char = i + 1; break
                source = content[idx:end_char]
                end_line = lines_before + source.count("\n")
                return SymbolTarget(
                    kind=SymbolKind.VARIABLE,
                    name=name,
                    file_path=file_path,
                    start_line=lines_before,
                    end_line=end_line,
                    start_col=0, end_col=len(source.splitlines()[-1]),
                    source_text=source,
                    language=lang
                )

        # ── Lua: function/method ──
        if lang == Language.LUA:
            # function name(...) or function table:name(...) or name = function(...)
            patterns = [
                rf"(?m)^function\s+(?:\w+[.:])?({re.escape(name)})\s*\(",
                rf"(?m)^local\s+function\s+({re.escape(name)})\s*\(",
                rf"(?m)^({re.escape(name)})\s*=\s*function\s*\(",
            ]
            for pat in patterns:
                match = re.search(pat, content)
                if match:
                    idx = match.start()
                    lines_before = content[:idx].count("\n") + 1
                    raw_lines = content.splitlines(keepends=True)
                    line_idx = lines_before - 1
                    # Lua blocks end with 'end'
                    end_idx = len(raw_lines) - 1
                    depth = 0
                    for i, l in enumerate(raw_lines[line_idx:], start=line_idx):
                        stripped = l.strip()
                        if re.match(r'^(local\s+)?function\b|if\b.*\bthen$|for\b.*\bdo$|while\b.*\bdo$|repeat\b', stripped):
                            depth += 1
                        if stripped == 'end' or stripped.startswith('end ') or stripped.endswith(' end'):
                            depth -= 1
                            if depth <= 0:
                                end_idx = i; break
                    source = "".join(raw_lines[j] for j in range(line_idx, end_idx + 1))
                    return SymbolTarget(kind=SymbolKind.FUNCTION, name=name, file_path=file_path,
                        start_line=lines_before, end_line=end_idx + 1, start_col=0, end_col=0,
                        source_text=source, language=lang)

        # ── GDScript: func/var/signal/class_name ──
        if lang == Language.GDSCRIPT:
            pattern = rf"(?m)^func\s+({re.escape(name)})\b"
            match = re.search(pattern, content)
            if match:
                idx = match.start()
                lines_before = content[:idx].count("\n") + 1
                raw_lines = content.splitlines(keepends=True)
                line_idx = lines_before - 1
                # GDScript: indented block under func
                base_indent = len(raw_lines[line_idx]) - len(raw_lines[line_idx].lstrip())
                end_idx = len(raw_lines) - 1
                for i, l in enumerate(raw_lines[line_idx + 1:], start=line_idx + 1):
                    if l.strip() and (len(l) - len(l.lstrip())) <= base_indent:
                        end_idx = i - 1; break
                else:
                    end_idx = len(raw_lines) - 1
                source = "".join(raw_lines[j] for j in range(line_idx, end_idx + 1))
                return SymbolTarget(kind=SymbolKind.FUNCTION, name=name, file_path=file_path,
                    start_line=lines_before, end_line=end_idx + 1, start_col=0, end_col=0,
                    source_text=source, language=lang)

        # ── C#/Java/Kotlin/Swift/Dart: braces-based ──
        if lang in (Language.CSHARP, Language.JAVA, Language.KOTLIN, Language.SWIFT, Language.DART):
            # class/struct/func/def/interface/enum/void/int/etc name
            pattern = rf"(?m)(?:public|private|protected|internal|static|partial|override|virtual|abstract|async|suspend|open|final|override|lateinit|inline|external|sealed|data|annotation|lateinit)?\s*(?:class|struct|interface|enum|fun|func|def|function|void|int|float|double|string|bool|var|let|const|val|lazy|async|suspend|get|set|operator|infix|companion)\s+({re.escape(name)})\b"
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                idx = match.start()
                lines_before = content[:idx].count("\n") + 1
                raw_lines = content.splitlines(keepends=True)
                line_idx = lines_before - 1
                brace_count = 0; end_idx = line_idx; started = False
                for i, l in enumerate(raw_lines[line_idx:], start=line_idx):
                    for ch in l:
                        if ch == '{': brace_count += 1; started = True
                        elif ch == '}': brace_count -= 1
                    if started and brace_count <= 0:
                        end_idx = i; break
                source = "".join(raw_lines[j] for j in range(line_idx, end_idx + 1))
                return SymbolTarget(kind=SymbolKind.FUNCTION, name=name, file_path=file_path,
                    start_line=lines_before, end_line=end_idx + 1, start_col=0, end_col=0,
                    source_text=source, language=lang)

        # ── C/C++/Rust: braces-based (simpler pattern) ──
        if lang in (Language.CPP, Language.RUST, Language.OBJC):
            # C++: return_type name(  or  void name(  or  class/struct name {
            # Rust: fn name(  or  pub fn name(  or  struct/enum/impl/trait name
            patterns = [
                rf"(?m)^(?:pub\s+)?(?:fn|func|function|async\s+fn)\s+({re.escape(name)})\s*[<(]",
                rf"(?m)^(?:pub\s+)?(?:struct|enum|impl|trait|class|union|type)\s+({re.escape(name)})\b",
                rf"(?m)^(?:static\s+)?(?:inline\s+)?(?:const\s+)?(?:void|int|float|double|char|bool|auto|unsigned|long|short|size_t|ssize_t|uint\d+_t|int\d+_t|float_\w+|double_\w+|std::\w+|[A-Z]\w+)\s+[*&]*({re.escape(name)})\s*\(",
                rf"(?m)^#define\s+({re.escape(name)})\b",
            ]
            for pat in patterns:
                match = re.search(pat, content)
                if match:
                    idx = match.start()
                    lines_before = content[:idx].count("\n") + 1
                    raw_lines = content.splitlines(keepends=True)
                    line_idx = lines_before - 1
                    brace_count = 0; end_idx = line_idx; started = False
                    for i, l in enumerate(raw_lines[line_idx:], start=line_idx):
                        for ch in l:
                            if ch == '{': brace_count += 1; started = True
                            elif ch == '}': brace_count -= 1
                        if started and brace_count <= 0:
                            end_idx = i; break
                    else:
                        # No braces found — might be a declaration or macro
                        end_idx = line_idx
                    source = "".join(raw_lines[j] for j in range(line_idx, end_idx + 1))
                    skind = SymbolKind.CLASS if any(k in raw_lines[line_idx] for k in ('class', 'struct', 'impl', 'trait', 'enum')) else SymbolKind.FUNCTION
                    return SymbolTarget(kind=skind, name=name, file_path=file_path,
                        start_line=lines_before, end_line=end_idx + 1, start_col=0, end_col=0,
                        source_text=source, language=lang)

        # ── GLSL/HLSL/WGSL shaders ──
        if lang in (Language.GLSL, Language.HLSL, Language.WGSL):
            # void main()  or  vec4 name(  or  float name(  or  [vertex/fragment/compute] shader functions
            pattern = rf"(?m)^(?:void|vec[234]|mat[234]|float|int|uint|bool|half|fixed|[io]ut)?\s*({re.escape(name)})\s*\("
            match = re.search(pattern, content)
            if match:
                idx = match.start()
                lines_before = content[:idx].count("\n") + 1
                raw_lines = content.splitlines(keepends=True)
                line_idx = lines_before - 1
                brace_count = 0; end_idx = line_idx; started = False
                for i, l in enumerate(raw_lines[line_idx:], start=line_idx):
                    for ch in l:
                        if ch == '{': brace_count += 1; started = True
                        elif ch == '}': brace_count -= 1
                    if started and brace_count <= 0:
                        end_idx = i; break
                source = "".join(raw_lines[j] for j in range(line_idx, end_idx + 1))
                return SymbolTarget(kind=SymbolKind.FUNCTION, name=name, file_path=file_path,
                    start_line=lines_before, end_line=end_idx + 1, start_col=0, end_col=0,
                    source_text=source, language=lang)

        # ── Vue SFC: resolve by component name or <script>/<template>/<style> ──
        if lang == Language.VUE:
            if name in ("script", "template", "style"):
                tag = name
                pattern = rf"<{tag}[^>]*>"
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    idx = match.start()
                    lines_before = content[:idx].count("\n") + 1
                    close = re.search(rf"</{tag}>", content[match.end():], re.IGNORECASE)
                    end_char = match.end() + close.end() if close else len(content)
                    source = content[idx:end_char]
                    end_line = lines_before + source.count("\n")
                    return SymbolTarget(kind=SymbolKind.UNKNOWN, name=name, file_path=file_path,
                        start_line=lines_before, end_line=end_line, start_col=0, end_col=0,
                        source_text=source, language=lang)

        # ── SCSS: resolve by selector or mixin ──
        if lang == Language.SCSS:
            patterns = [
                rf"(?m)^@mixin\s+({re.escape(name)})\b",
                rf"(?m)^@function\s+({re.escape(name)})\b",
                rf"(?m)^({re.escape(name)})\s*[\{{]",
            ]
            for pat in patterns:
                match = re.search(pat, content)
                if match:
                    idx = match.start()
                    lines_before = content[:idx].count("\n") + 1
                    brace_count = 0; end_char = idx; started = False
                    for i, ch in enumerate(content[idx:], start=idx):
                        if ch == '{': brace_count += 1; started = True
                        elif ch == '}': brace_count -= 1
                        if started and brace_count <= 0:
                            end_char = i + 1; break
                    source = content[idx:end_char]
                    end_line = lines_before + source.count("\n")
                    return SymbolTarget(kind=SymbolKind.VARIABLE, name=name, file_path=file_path,
                        start_line=lines_before, end_line=end_line, start_col=0, end_col=0,
                        source_text=source, language=lang)

        # ── PHP: function/class ──
        if lang == Language.PHP:
            pattern = rf"(?m)^function\s+({re.escape(name)})\s*\(|class\s+({re.escape(name)})\b"
            match = re.search(pattern, content)
            if match:
                idx = match.start()
                lines_before = content[:idx].count("\n") + 1
                raw_lines = content.splitlines(keepends=True)
                line_idx = lines_before - 1
                brace_count = 0; end_idx = line_idx; started = False
                for i, l in enumerate(raw_lines[line_idx:], start=line_idx):
                    for ch in l:
                        if ch == '{': brace_count += 1; started = True
                        elif ch == '}': brace_count -= 1
                    if started and brace_count <= 0:
                        end_idx = i; break
                source = "".join(raw_lines[j] for j in range(line_idx, end_idx + 1))
                skind = SymbolKind.CLASS if "class" in raw_lines[line_idx] else SymbolKind.FUNCTION
                return SymbolTarget(kind=skind, name=name, file_path=file_path,
                    start_line=lines_before, end_line=end_idx + 1, start_col=0, end_col=0,
                    source_text=source, language=lang)

        # ── Ruby: def/class/module ──
        if lang == Language.RUBY:
            pattern = rf"(?m)^(?:def|class|module)\s+({re.escape(name)})\b"
            match = re.search(pattern, content)
            if match:
                idx = match.start()
                lines_before = content[:idx].count("\n") + 1
                raw_lines = content.splitlines(keepends=True)
                line_idx = lines_before - 1
                depth = 0; end_idx = line_idx
                for i, l in enumerate(raw_lines[line_idx:], start=line_idx):
                    stripped = l.strip()
                    if re.match(r'^(def|class|module|if|unless|case|begin|do)\b', stripped):
                        depth += 1
                    if re.match(r'^end\b', stripped):
                        depth -= 1
                        if depth <= 0:
                            end_idx = i; break
                source = "".join(raw_lines[j] for j in range(line_idx, end_idx + 1))
                return SymbolTarget(kind=SymbolKind.FUNCTION, name=name, file_path=file_path,
                    start_line=lines_before, end_line=end_idx + 1, start_col=0, end_col=0,
                    source_text=source, language=lang)

        # ── Elixir: def/defmodule/defmacro ──
        if lang == Language.ELIXIR:
            pattern = rf"(?m)^def(?:module|p|macro)?\s+({re.escape(name)})\b"
            match = re.search(pattern, content)
            if match:
                idx = match.start()
                lines_before = content[:idx].count("\n") + 1
                raw_lines = content.splitlines(keepends=True)
                line_idx = lines_before - 1
                # Elixir: do...end blocks
                depth = 0; end_idx = line_idx
                for i, l in enumerate(raw_lines[line_idx:], start=line_idx):
                    if re.search(r'\bdo\b', l): depth += 1
                    if re.search(r'\bend\b', l):
                        depth -= 1
                        if depth <= 0:
                            end_idx = i; break
                source = "".join(raw_lines[j] for j in range(line_idx, end_idx + 1))
                return SymbolTarget(kind=SymbolKind.FUNCTION, name=name, file_path=file_path,
                    start_line=lines_before, end_line=end_idx + 1, start_col=0, end_col=0,
                    source_text=source, language=lang)

        # ── FALLBACK: return the whole file content ──
        # For any file type when name is "file" or empty, return everything.
        # This is the key to making SEE work on ANY file type.
        if not name or name == "file":
            return SymbolTarget(
                kind=SymbolKind.UNKNOWN,
                name="file",
                file_path=file_path,
                start_line=1,
                end_line=len(content.splitlines()),
                start_col=0,
                end_col=0,
                source_text=content,
                language=lang
            )

        # ── Generic text search: find the named string/section ──
        if name in content:
            idx = content.index(name)
            lines_before = content[:idx].count("\n") + 1
            # Return a window around the match (±20 lines)
            raw_lines = content.splitlines(keepends=True)
            line_idx = lines_before - 1
            start = max(0, line_idx - 5)
            end = min(len(raw_lines), line_idx + 20)
            source = "".join(raw_lines[i] for i in range(start, end))
            return SymbolTarget(
                kind=SymbolKind.UNKNOWN,
                name=name,
                file_path=file_path,
                start_line=start + 1,
                end_line=end,
                start_col=0, end_col=0,
                source_text=source,
                language=lang
            )

        return None

_resolver = SymbolResolver()

def get_symbol_resolver() -> SymbolResolver:
    return _resolver

def resolve_symbol(name: str, file_path: Path, kind: SymbolKind = None) -> Optional[SymbolTarget]:
    return get_symbol_resolver().resolve(name, file_path, kind)
