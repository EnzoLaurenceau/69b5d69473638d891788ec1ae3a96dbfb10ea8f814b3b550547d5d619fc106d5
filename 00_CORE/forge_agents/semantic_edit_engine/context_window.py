from __future__ import annotations
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class SmartContext:
    target_symbol: str
    symbol_source: str
    imports: list[str]
    references: list[str]
    local_context: str
    dependencies: list[str]
    related_tests: list[str]
    file_path: str
    total_tokens: int
    full_file_tokens: int
    savings_pct: float

    def to_prompt(self) -> str:
        prompt = f"TARGET SYMBOL: {self.target_symbol}\n"
        prompt += f"SOURCE:\n```python\n{self.symbol_source}\n```\n"
        if self.imports:
            prompt += f"IMPORTS:\n" + "\n".join(self.imports) + "\n"
        if self.local_context:
            prompt += f"LOCAL CONTEXT:\n{self.local_context}\n"
        return prompt

class IntelligentContextWindow:
    def __init__(self, max_context_tokens: int = 2000):
        self.max_context_tokens = max_context_tokens

    def build(self, symbol_name: str, file_path: Path, project_root: Path = None) -> SmartContext:
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        content = file_path.read_text(encoding="utf-8")
        
        from .symbol_resolver import get_symbol_resolver
        resolver = get_symbol_resolver()
        target = resolver.resolve(symbol_name, file_path)
        
        source = target.source_text if target else content[:1000]
        
        imports = [l for l in content.splitlines() if l.startswith("import ") or l.startswith("from ")]
        
        local_context = ""
        lines = content.splitlines()
        if target:
            start = max(0, target.start_line - 5)
            end = min(len(lines), target.end_line + 5)
            local_context = "\n".join(lines[start:target.start_line-1]) + "\n...[TARGET]...\n" + "\n".join(lines[target.end_line:end])

        total_tok = (len(source) + len(local_context)) // 4
        full_tok = len(content) // 4
        savings = (1.0 - (total_tok / max(1, full_tok))) * 100

        return SmartContext(
            target_symbol=symbol_name,
            symbol_source=source,
            imports=imports[:10],
            references=[],
            local_context=local_context,
            dependencies=[],
            related_tests=[],
            file_path=str(file_path),
            total_tokens=total_tok,
            full_file_tokens=full_tok,
            savings_pct=savings
        )

_window = IntelligentContextWindow()

def get_context_window() -> IntelligentContextWindow:
    return _window

def build_context(symbol_name: str, file_path: Path, project_root: Path = None) -> SmartContext:
    return get_context_window().build(symbol_name, file_path, project_root)
