#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""codeLook: 极致压缩项目代码快照，按 10KB 物理字节切片。"""
from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LANG_MAP = {
    'py': 'python', 'rs': 'rust', 'js': 'javascript', 'ts': 'typescript',
    'html': 'html', 'css': 'css', 'json': 'json', 'toml': 'toml',
    'yaml': 'yaml', 'yml': 'yaml', 'md': 'markdown',
    'sh': 'bash', 'bat': 'batch', 'cmd': 'batch', 'sql': 'sql',
    'txt': 'text'
}
# 强制忽略的超级毒瘤目录，防扫描爆体积
DEFAULT_EXCLUDE = {'.git', 'node_modules', 'target', '__pycache__', 'venv', 'venv_linux', 'dist', 'build'}

def find_project_root(start: Path) -> Path | None:
    current = start.resolve()
    if current.is_file(): current = current.parent
    while True:
        if (current / '.git').exists() or (current / 'Cargo.toml').exists() or (current / 'package.json').exists():
            return current
        if current.parent == current: return None
        current = current.parent

def load_config(path: Path) -> dict:
    try:
        import yaml
    except ImportError:
        print("[ERROR] 需要 PyYAML: pip install pyyaml", file=sys.stderr)
        sys.exit(1)
    with path.open('r', encoding='utf-8-sig') as f:
        return yaml.safe_load(f) or {}

def normalize_extensions(raw) -> set[str]:
    out = set()
    for e in (raw or []):
        e = str(e).strip().lstrip('.')
        if e: out.add(e.lower())
    return out

def should_exclude(rel: str, patterns: list[str]) -> bool:
    parts = rel.split('/')
    targets = [rel] + ['/'.join(parts[:i]) for i in range(1, len(parts)+1)] + parts
    for pattern in patterns:
        for t in targets:
            if fnmatch.fnmatchcase(t, pattern): return True
    return False

def prefix_match(prefix: str, rel: str) -> bool:
    return not prefix or rel == prefix or rel.startswith(prefix + '/')

def collect_files(root: Path, exclude: list[str], default_exts: set[str], skip_dirs: list[str], content_rules: list) -> set[str]:
    """只收集真正需要读取内容的文件路径"""
    content_files = set()
    for p in root.rglob('*'):
        if not p.is_file(): continue
        rel = p.relative_to(root).as_posix()
        if should_exclude(rel, exclude): continue
        
        # 判断是否在 skip_content_dirs 中
        in_skip = any(prefix_match(s, rel) for s in skip_dirs)
        if in_skip: continue
        
        # 匹配扩展名
        exts = default_exts
        for prefix, rule_exts in content_rules:
            if prefix_match(prefix, rel): exts = rule_exts
        
        if p.suffix.lower().lstrip('.') in exts:
            content_files.add(rel)
    return content_files

def compact_text(text: str) -> str:
    """极致压缩：去掉行尾空白与全空行"""
    return '\n'.join(ln.rstrip() for ln in text.split('\n') if ln.strip())

def read_file_text(path: Path, compact: bool) -> str:
    try:
        raw = path.read_text(encoding='utf-8', errors='replace')
        return compact_text(raw) if compact else raw.rstrip('\n')
    except Exception as exc:
        return f"<读取失败: {exc}>"

def build_content_tree(content_files: set[str], root_name: str) -> str:
    """构建紧凑的读取目录树"""
    if not content_files: return f"{root_name}/\n(无内容)"
    tree = {}
    for rel in sorted(content_files):
        parts = rel.split('/')
        node = tree
        for p in parts[:-1]: node = node.setdefault(p, {})
        node.setdefault('__files__', []).append(parts[-1])
    
    lines = [f"{root_name}/"]
    def render(node, depth):
        indent = '  ' * depth
        for d in sorted(k for k in node if k != '__files__'):
            lines.append(f"{indent}{d}/")
            render(node[d], depth + 1)
        for f in sorted(node.get('__files__', [])):
            lines.append(f"{indent}{f}")
    render(tree, 1)
    return '\n'.join(lines)

def build_output(root: Path, content_files: set[str], compact: bool, max_file_bytes: int) -> str:
    tree_str = build_content_tree(content_files, root.name)
    lines = ["=== TREE ===", tree_str, ""]
    
    for rel in sorted(content_files):
        path = root / rel
        ext = path.suffix.lower().lstrip('.')
        lang = LANG_MAP.get(ext, ext)
        
        try:
            if path.stat().st_size > max_file_bytes:
                lines.append(f"@@FILE {rel} #{lang} [SKIPPED: > {max_file_bytes} bytes]")
                continue
        except OSError:
            continue
            
        text = read_file_text(path, compact)
        lines.append(f"@@FILE {rel} #{lang}")
        lines.append(text)
        
    return '\n'.join(lines) + '\n'

def split_text(text: str, limit_bytes: int) -> list[str]:
    """按 UTF-8 物理字节精确切片"""
    if limit_bytes <= 0: return [text]
    lines = text.split('\n')
    chunks, current, current_bytes = [], [], 0
    for line in lines:
        lb = len(line.encode('utf-8')) + 1  # +1 for '\n'
        if current and current_bytes + lb > limit_bytes:
            chunks.append('\n'.join(current) + '\n')
            current, current_bytes = [line], lb
        else:
            current.append(line)
            current_bytes += lb
    if current: chunks.append('\n'.join(current) + '\n')
    return chunks or ['\n']

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project-root', default='')
    parser.add_argument('--config', default=str(SCRIPT_DIR / 'look.yaml'))
    parser.add_argument('--split-size', type=int, default=10240) # 默认 10KB
    parser.add_argument('--max-file', type=int, default=30000)   # 单文件最大 30KB
    parser.add_argument('--no-compact', action='store_true')
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else find_project_root(SCRIPT_DIR)
    if not project_root:
        print("[ERROR] 未找到项目根，请使用 --project-root 指定", file=sys.stderr)
        return 1
        
    config_path = Path(args.config).resolve()
    config = load_config(config_path) if config_path.is_file() else {}
    
    exclude = list(config.get('exclude_dirs') or [])
    for d in DEFAULT_EXCLUDE:
        if d not in exclude: exclude.append(d)
        
    skip_dirs = [str(s).strip().strip('/') for s in (config.get('skip_content_dirs') or [])]
    default_exts = normalize_extensions(config.get('default_extensions') or [])
    content_rules = []
    for r in (config.get('content_rules') or []):
        if isinstance(r, dict):
            content_rules.append((str(r.get('prefix') or '').strip('/'), normalize_extensions(r.get('extensions'))))

    compact = not args.no_compact and config.get('compact', True)
    
    content_files = collect_files(project_root, exclude, default_exts, skip_dirs, content_rules)
    output_text = build_output(project_root, content_files, compact, args.max_file)
    
    split_size = args.split_size if args.split_size > 0 else config.get('split_size', 10240)
    seg_dir = (SCRIPT_DIR / config.get('segments_dir', 'segments')).resolve()
    seg_dir.mkdir(parents=True, exist_ok=True)
    
    for f in seg_dir.glob('*.txt'):
        try: f.unlink()
        except OSError: pass

    chunks = split_text(output_text, split_size)
    for i, chunk in enumerate(chunks, 1):
        (seg_dir / f"seg-{i:03d}.txt").write_text(chunk, encoding='utf-8', newline='\n')
        
    total_bytes = sum(len(c.encode('utf-8')) for c in chunks)
    print(f"[OK] 文件数: {len(content_files)} | 总大小: {total_bytes} 字节 ({total_bytes/1024:.1f} KB)")
    print(f"[OK] 切片数: {len(chunks)} 个 (每片 <= {split_size} 字节) -> {seg_dir}")

if __name__ == '__main__':
    sys.exit(main())