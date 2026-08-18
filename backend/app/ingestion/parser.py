import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# --- File classification -----------------------------------------------------

LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".md": "markdown",
    ".mdx": "markdown",
    ".rst": "markdown",
    ".txt": "text",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".svg",
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".so", ".dylib", ".dll", ".exe", ".bin", ".class", ".jar", ".pyc",
    ".mp3", ".mp4", ".mov", ".avi", ".wav",
    ".db", ".sqlite", ".sqlite3",
}

DEFAULT_IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}

MAX_FILE_SIZE_BYTES = 1_500_000  # skip huge generated files


def is_binary_path(path: str) -> bool:
    lowered = path.lower()
    return any(lowered.endswith(ext) for ext in BINARY_EXTENSIONS)


def detect_language(path: str) -> str | None:
    for ext, lang in LANGUAGE_BY_EXTENSION.items():
        if path.lower().endswith(ext):
            return lang
    return None


# --- Secret scanning ----------------------------------------------------------

SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Generic API Key", re.compile(r"(?i)api[_-]?key['\"]?\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,}['\"]")),
    ("OpenAI Key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("Private Key Block", re.compile(r"-----BEGIN (RSA|EC|DSA|OPENSSH|PGP) PRIVATE KEY-----")),
    ("GitHub Token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("Generic Secret Assignment", re.compile(r"(?i)(secret|password|passwd|token)['\"]?\s*[:=]\s*['\"][^'\"\s]{8,}['\"]")),
    ("Slack Token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
]


@dataclass
class SecretFinding:
    file_path: str
    pattern_name: str
    line_number: int


def scan_for_secrets(path: str, content: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(SecretFinding(file_path=path, pattern_name=name, line_number=line_no))
    return findings


def redact_secrets(content: str) -> str:
    redacted = content
    for _, pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


# --- Code chunk extraction ----------------------------------------------------

@dataclass
class CodeChunk:
    chunk_type: str  # "function" | "class" | "docstring" | "doc" | "import_block" | "code"
    symbol_name: str | None
    content: str
    start_line: int
    end_line: int
    metadata: dict = field(default_factory=dict)


_TS_AVAILABLE = False
try:
    import tree_sitter_languages  # type: ignore

    _TS_AVAILABLE = True
except ImportError:
    logger.info("tree-sitter-languages not available; using regex-based parsing fallback")


# Regex fallback patterns per language. Each captures a top-level definition and its body
# is delimited heuristically by indentation (Python) or brace matching (C-like languages).
_PY_DEF_RE = re.compile(r"^(?P<indent>[ \t]*)(?:async\s+)?def\s+(?P<name>\w+)\s*\(", re.MULTILINE)
_PY_CLASS_RE = re.compile(r"^(?P<indent>[ \t]*)class\s+(?P<name>\w+)", re.MULTILINE)
_JS_FUNC_RE = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(?P<name>\w+)\s*\(|"
    r"^(?:export\s+)?(?:const|let)\s+(?P<name2>\w+)\s*=\s*(?:async\s*)?\(?[^=]*\)?\s*=>",
    re.MULTILINE,
)
_JS_CLASS_RE = re.compile(r"^(?:export\s+)?(?:default\s+)?class\s+(?P<name>\w+)", re.MULTILINE)
_JAVA_METHOD_RE = re.compile(
    r"^\s*(?:public|private|protected|static|\s)*[\w<>\[\]]+\s+(?P<name>\w+)\s*\([^;]*\)\s*\{", re.MULTILINE
)
_JAVA_CLASS_RE = re.compile(r"^\s*(?:public\s+)?(?:abstract\s+)?class\s+(?P<name>\w+)", re.MULTILINE)
_GO_FUNC_RE = re.compile(r"^func\s+(?:\([^)]*\)\s*)?(?P<name>\w+)\s*\(", re.MULTILINE)
_IMPORT_RE = re.compile(
    r"^(?:import\s+.+|from\s+\S+\s+import\s+.+|const\s+.+=\s*require\(.+\)|import\s*\{.*\}\s*from\s*.+)$",
    re.MULTILINE,
)


def _find_block_end_by_indent(lines: list[str], start_idx: int, base_indent: int) -> int:
    """Python: find the last line belonging to a def/class block, using indentation."""
    end = start_idx
    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        if line.strip() == "":
            end = i
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        if indent <= base_indent:
            break
        end = i
    return end


def _find_block_end_by_brace(lines: list[str], start_idx: int) -> int:
    """C-like languages: find the matching closing brace, counting from the start line."""
    depth = 0
    started = False
    for i in range(start_idx, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if "{" in lines[i]:
            started = True
        if started and depth <= 0:
            return i
    return len(lines) - 1


def _extract_python_chunks(content: str) -> list[CodeChunk]:
    lines = content.splitlines()
    chunks: list[CodeChunk] = []

    for regex, ctype in [(_PY_CLASS_RE, "class"), (_PY_DEF_RE, "function")]:
        for match in regex.finditer(content):
            start_line = content[: match.start()].count("\n")
            base_indent = len(match.group("indent"))
            end_line = _find_block_end_by_indent(lines, start_line, base_indent)
            body = "\n".join(lines[start_line : end_line + 1])
            docstring_match = re.search(r'"""(.*?)"""|\'\'\'(.*?)\'\'\'', body, re.DOTALL)
            chunks.append(
                CodeChunk(
                    chunk_type=ctype,
                    symbol_name=match.group("name"),
                    content=body,
                    start_line=start_line + 1,
                    end_line=end_line + 1,
                    metadata={"has_docstring": bool(docstring_match)},
                )
            )
    return chunks


def _extract_brace_lang_chunks(content: str, func_re: re.Pattern, class_re: re.Pattern) -> list[CodeChunk]:
    lines = content.splitlines()
    chunks: list[CodeChunk] = []
    for regex, ctype in [(class_re, "class"), (func_re, "function")]:
        for match in regex.finditer(content):
            start_line = content[: match.start()].count("\n")
            end_line = _find_block_end_by_brace(lines, start_line)
            name = match.groupdict().get("name") or match.groupdict().get("name2") or "anonymous"
            body = "\n".join(lines[start_line : end_line + 1])
            chunks.append(
                CodeChunk(
                    chunk_type=ctype,
                    symbol_name=name,
                    content=body,
                    start_line=start_line + 1,
                    end_line=end_line + 1,
                )
            )
    return chunks


def extract_imports(content: str) -> list[str]:
    return [m.group(0).strip() for m in _IMPORT_RE.finditer(content)]


def chunk_source_file(path: str, content: str, language: str | None) -> list[CodeChunk]:
    """
    Extract function/class/doc chunks from a source file.

    Prefers tree-sitter when available (not wired up in this MVP fallback path);
    otherwise uses per-language regex heuristics. Falls back to fixed-size chunking
    for unsupported languages or files with no matched definitions.
    """
    chunks: list[CodeChunk] = []

    if language == "python":
        chunks = _extract_python_chunks(content)
    elif language in ("javascript", "typescript"):
        chunks = _extract_brace_lang_chunks(content, _JS_FUNC_RE, _JS_CLASS_RE)
    elif language == "java":
        chunks = _extract_brace_lang_chunks(content, _JAVA_METHOD_RE, _JAVA_CLASS_RE)
    elif language == "go":
        chunks = _extract_brace_lang_chunks(content, _GO_FUNC_RE, re.compile(r"(?!)"))  # Go has no classes
    elif language == "markdown":
        return _chunk_markdown(content)

    imports = extract_imports(content)
    if imports:
        chunks.insert(
            0,
            CodeChunk(
                chunk_type="import_block",
                symbol_name=None,
                content="\n".join(imports),
                start_line=1,
                end_line=1,
                metadata={"import_count": len(imports)},
            ),
        )

    if not chunks:
        # Fallback: fixed-size sliding chunks so the file is still searchable.
        chunks = _fixed_size_chunks(content)

    return chunks


def _chunk_markdown(content: str, max_chars: int = 3000) -> list[CodeChunk]:
    """Chunk markdown/docs by heading sections."""
    sections = re.split(r"(?m)^(#{1,6}\s+.+)$", content)
    chunks: list[CodeChunk] = []
    line_cursor = 1
    # sections alternates [pre-text, heading, body, heading, body, ...]
    buffer_heading = None
    for part in sections:
        if part.startswith("#"):
            buffer_heading = part.strip("# ").strip()
            continue
        text = part.strip()
        if text:
            line_count = text.count("\n") + 1
            chunks.append(
                CodeChunk(
                    chunk_type="doc",
                    symbol_name=buffer_heading,
                    content=text[:max_chars],
                    start_line=line_cursor,
                    end_line=line_cursor + line_count,
                )
            )
            line_cursor += line_count
    return chunks or _fixed_size_chunks(content)


def _fixed_size_chunks(content: str, lines_per_chunk: int = 60) -> list[CodeChunk]:
    lines = content.splitlines()
    chunks: list[CodeChunk] = []
    for i in range(0, len(lines), lines_per_chunk):
        block = lines[i : i + lines_per_chunk]
        if not any(line.strip() for line in block):
            continue
        chunks.append(
            CodeChunk(
                chunk_type="code",
                symbol_name=None,
                content="\n".join(block),
                start_line=i + 1,
                end_line=min(i + lines_per_chunk, len(lines)),
            )
        )
    return chunks
