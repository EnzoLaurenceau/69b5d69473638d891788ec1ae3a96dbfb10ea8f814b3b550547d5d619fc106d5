"""
gitnexus_to_vault.py — Sync GitNexus code graph to Obsidian vault
=================================================================

Creates markdown files from the code graph for the vault.

Usage:
    python gitnexus_to_vault.py              # Sync all
    python gitnexus_to_vault.py --module forge_agents  # Sync specific module
    python gitnexus_to_vault.py --symbols forge_call,ForgeState  # Sync specific symbols
"""

from __future__ import annotations
import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).resolve().parent.parent
VAULT_DIR = FORGE_ROOT / "vault" / "code-graph"
GITNEXUS_DIR = FORGE_ROOT / ".gitnexus"

# Ensure vault dirs exist
VAULT_DIR.mkdir(parents=True, exist_ok=True)
(VAULT_DIR / "modules").mkdir(exist_ok=True)
(VAULT_DIR / "symbols").mkdir(exist_ok=True)


def _now() -> str:
    return datetime.now().isoformat()


def load_gitnexus_db() -> dict:
    """Load GitNexus SQLite database."""
    db_path = GITNEXUS_DIR / "gitnexus.db"
    if not db_path.exists():
        return {"error": "GitNexus database not found", "path": str(db_path)}
    
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        
        # Get all symbols
        symbols = []
        try:
            rows = conn.execute("SELECT * FROM symbols LIMIT 1000").fetchall()
            symbols = [dict(row) for row in rows]
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        
        # Get all relationships
        relationships = []
        try:
            rows = conn.execute("SELECT * FROM relationships LIMIT 1000").fetchall()
            relationships = [dict(row) for row in rows]
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        
        conn.close()
        
        return {
            "symbols": symbols,
            "relationships": relationships,
            "symbol_count": len(symbols),
            "relationship_count": len(relationships),
        }
    except Exception as e:
        return {"error": str(e)}


def get_symbol_details(symbol_name: str) -> dict:
    """Get detailed information about a specific symbol."""
    db_path = GITNEXUS_DIR / "gitnexus.db"
    if not db_path.exists():
        return {"error": "GitNexus database not found"}
    
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        
        # Get symbol
        symbol = conn.execute(
            "SELECT * FROM symbols WHERE name = ?", (symbol_name,)
        ).fetchone()
        
        if not symbol:
            conn.close()
            return {"error": f"Symbol '{symbol_name}' not found"}
        
        symbol = dict(symbol)
        
        # Get callers (symbols that call this one)
        callers = []
        try:
            rows = conn.execute(
                "SELECT s.* FROM relationships r JOIN symbols s ON r.source = s.name WHERE r.target = ? AND r.type = 'calls'",
                (symbol_name,)
            ).fetchall()
            callers = [dict(row) for row in rows]
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        
        # Get callees (symbols that this one calls)
        callees = []
        try:
            rows = conn.execute(
                "SELECT s.* FROM relationships r JOIN symbols s ON r.target = s.name WHERE r.source = ? AND r.type = 'calls'",
                (symbol_name,)
            ).fetchall()
            callees = [dict(row) for row in rows]
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        
        # Get imports
        imports = []
        try:
            rows = conn.execute(
                "SELECT s.* FROM relationships r JOIN symbols s ON r.target = s.name WHERE r.source = ? AND r.type = 'imports'",
                (symbol_name,)
            ).fetchall()
            imports = [dict(row) for row in rows]
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        
        conn.close()
        
        return {
            "symbol": symbol,
            "callers": callers,
            "callees": callees,
            "imports": imports,
        }
    except Exception as e:
        return {"error": str(e)}


def get_module_symbols(module_name: str) -> list:
    """Get all symbols in a module."""
    db_path = GITNEXUS_DIR / "gitnexus.db"
    if not db_path.exists():
        return []
    
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        
        # Get symbols by file path
        rows = conn.execute(
            "SELECT * FROM symbols WHERE file LIKE ?",
            (f"%{module_name}%",)
        ).fetchall()
        
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []


def generate_symbol_markdown(symbol_name: str) -> str:
    """Generate markdown for a symbol."""
    details = get_symbol_details(symbol_name)
    
    if "error" in details:
        return f"# {symbol_name}\n\n> Error: {details['error']}\n"
    
    symbol = details["symbol"]
    callers = details["callers"]
    callees = details["callees"]
    imports = details["imports"]
    
    md = f"""# {symbol_name}

> Auto-generated from GitNexus code graph
> Last updated: {_now()}

## Métadonnées

- **Type**: {symbol.get('type', 'unknown')}
- **Fichier**: {symbol.get('file', 'unknown')}
- **Lignes**: {symbol.get('line_start', '?')}-{symbol.get('line_end', '?')}
- **Module**: {symbol.get('module', 'unknown')}

## Description

{symbol.get('docstring', 'Pas de documentation.')}

## Callers ({len(callers)})

"""
    if callers:
        for caller in callers:
            md += f"- `{caller['name']}` ({caller.get('file', 'unknown')})\n"
    else:
        md += "- Aucun caller trouvé\n"
    
    md += f"\n## Callees ({len(callees)})\n\n"
    
    if callees:
        for callee in callees:
            md += f"- `{callee['name']}` ({callee.get('file', 'unknown')})\n"
    else:
        md += "- Aucun callee trouvé\n"
    
    md += f"\n## Imports ({len(imports)})\n\n"
    
    if imports:
        for imp in imports:
            md += f"- `{imp['name']}`\n"
    else:
        md += "- Aucun import trouvé\n"
    
    md += f"""

## Impact Analysis

Modifier ce symbole affecte:
- **{len(callers)} callers** directement
- Potentiellement tous les modules qui importent ce fichier

## Liens

- [[../index|Code Graph Index]]
- [[../forge/index|Forge Index]]

#code-graph #symbole #{symbol.get('type', 'unknown')}
"""
    
    return md


def generate_module_markdown(module_name: str) -> str:
    """Generate markdown for a module."""
    symbols = get_module_symbols(module_name)
    
    md = f"""# Module: {module_name}

> Auto-generated from GitNexus code graph
> Last updated: {_now()}

## Statistiques

- **Symboles**: {len(symbols)}
- **Fichier**: {symbols[0].get('file', 'unknown') if symbols else 'unknown'}

## Symboles

| Nom | Type | Lignes | Description |
|-----|------|--------|-------------|
"""
    
    for sym in symbols:
        name = sym.get('name', 'unknown')
        sym_type = sym.get('type', 'unknown')
        lines = f"{sym.get('line_start', '?')}-{sym.get('line_end', '?')}"
        desc = (sym.get('docstring', '') or '')[:50]
        if len(sym.get('docstring', '') or '') > 50:
            desc += '...'
        md += f"| `{name}` | {sym_type} | {lines} | {desc} |\n"
    
    md += f"""

## Graphique de Dépendances

```mermaid
graph LR
"""
    
    # Add relationships
    for sym in symbols[:10]:  # Limit to first 10 for readability
        name = sym.get('name', 'unknown')
        md += f"  {name}\n"
    
    md += "```\n\n"
    
    md += """## Liens

- [[../index|Code Graph Index]]
- [[../forge/index|Forge Index]]

#code-graph #module
"""
    
    return md


def generate_index_markdown() -> str:
    """Generate the main index for code graph."""
    db = load_gitnexus_db()
    
    if "error" in db:
        return f"# 🕸️ Code Graph — GitNexus Index\n\n> Error: {db['error']}\n"
    
    md = f"""# 🕸️ Code Graph — GitNexus Index

> Auto-generated from GitNexus code graph
> Last updated: {_now()}

## Statistiques

- **Symboles indexés**: {db.get('symbol_count', 0)}
- **Relations**: {db.get('relationship_count', 0)}

## Modules Indexés

"""
    
    # Group symbols by module
    modules = {}
    for sym in db.get('symbols', []):
        module = sym.get('module', 'unknown')
        if module not in modules:
            modules[module] = []
        modules[module].append(sym)
    
    for module, symbols in sorted(modules.items()):
        md += f"- [[modules/{module}|{module}]] ({len(symbols)} symboles)\n"
    
    md += "\n## Symboles Clés\n\n"
    
    # Show top symbols by type
    types = {}
    for sym in db.get('symbols', []):
        sym_type = sym.get('type', 'unknown')
        if sym_type not in types:
            types[sym_type] = []
        types[sym_type].append(sym)
    
    for sym_type, symbols in sorted(types.items()):
        md += f"### {sym_type.title()} ({len(symbols)})\n\n"
        for sym in symbols[:5]:  # Show first 5 of each type
            name = sym.get('name', 'unknown')
            md += f"- [[symbols/{name}|{name}]]\n"
        if len(symbols) > 5:
            md += f"- ... et {len(symbols) - 5} autres\n"
        md += "\n"
    
    md += """## Commandes Utiles

```bash
# Rechercher un symbole
python 00_CORE/forge_agents/nanomachine.py invoke_gitnexus "forge_call"

# Contexte d'un symbole
python 00_CORE/forge_agents/nanomachine.py gitnexus_context "forge_call"

# Impact analysis
python 00_CORE/forge_agents/nanomachine.py gitnexus_impact "forge_call" --direction upstream
```

## Liens

- [[../forge/index|Forge Index]]
- [[../agents/index|Agent Performance]]
- [[../personal/index|Personnel]]

#code-graph #index
"""
    
    return md


def sync_all():
    """Sync all GitNexus data to vault."""
    print("Syncing GitNexus to vault...")
    
    db = load_gitnexus_db()
    if "error" in db:
        print(f"Error: {db['error']}")
        return
    
    # Generate index
    index_md = generate_index_markdown()
    (VAULT_DIR / "index.md").write_text(index_md, encoding="utf-8")
    print(f"  ✓ index.md ({db.get('symbol_count', 0)} symbols)")
    
    # Generate module pages
    modules = {}
    for sym in db.get('symbols', []):
        module = sym.get('module', 'unknown')
        if module not in modules:
            modules[module] = []
        modules[module].append(sym)
    
    for module, symbols in modules.items():
        md = generate_module_markdown(module)
        (VAULT_DIR / "modules" / f"{module}.md").write_text(md, encoding="utf-8")
        print(f"  ✓ modules/{module}.md ({len(symbols)} symbols)")
    
    # Generate symbol pages (limit to 50 for performance)
    symbols_generated = 0
    for sym in db.get('symbols', [])[:50]:
        name = sym.get('name', 'unknown')
        md = generate_symbol_markdown(name)
        (VAULT_DIR / "symbols" / f"{name}.md").write_text(md, encoding="utf-8")
        symbols_generated += 1
    
    print(f"  ✓ symbols/ ({symbols_generated} files)")
    print(f"\nSync complete: {symbols_generated + len(modules) + 1} files created")


def sync_module(module_name: str):
    """Sync a specific module."""
    print(f"Syncing module: {module_name}")
    
    symbols = get_module_symbols(module_name)
    if not symbols:
        print(f"No symbols found for module: {module_name}")
        return
    
    md = generate_module_markdown(module_name)
    (VAULT_DIR / "modules" / f"{module_name}.md").write_text(md, encoding="utf-8")
    print(f"  ✓ modules/{module_name}.md ({len(symbols)} symbols)")
    
    # Generate symbol pages
    for sym in symbols:
        name = sym.get('name', 'unknown')
        md = generate_symbol_markdown(name)
        (VAULT_DIR / "symbols" / f"{name}.md").write_text(md, encoding="utf-8")
        print(f"  ✓ symbols/{name}.md")


def sync_symbols(symbol_names: list):
    """Sync specific symbols."""
    print(f"Syncing symbols: {symbol_names}")
    
    for name in symbol_names:
        md = generate_symbol_markdown(name)
        (VAULT_DIR / "symbols" / f"{name}.md").write_text(md, encoding="utf-8")
        print(f"  ✓ symbols/{name}.md")


def main():
    parser = argparse.ArgumentParser(description="Sync GitNexus to Obsidian vault")
    parser.add_argument("--module", help="Sync specific module")
    parser.add_argument("--symbols", nargs="*", help="Sync specific symbols")
    args = parser.parse_args()
    
    if args.module:
        sync_module(args.module)
    elif args.symbols:
        sync_symbols(args.symbols)
    else:
        sync_all()


if __name__ == "__main__":
    main()
