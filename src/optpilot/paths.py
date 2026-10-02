"""Path boundaries for user-supplied evidence and artifact identifiers."""

from pathlib import Path


def safe_child_path(root: Path, name: str, label: str) -> Path:
    """Resolve one portable path component without allowing it to escape root."""
    if (not isinstance(name, str) or not name.strip() or name in {'.', '..'} or
            any(character in name for character in ('/', '\\', ':')) or
            any(ord(character) < 32 for character in name)):
        raise ValueError(f'{label} must be a single nonempty path component')
    root = Path(root).resolve()
    child = (root / name).resolve()
    if child.parent != root:
        raise ValueError(f'{label} must remain inside its storage directory')
    return child
