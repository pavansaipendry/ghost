import os
import toml

_DEFAULT_CONFIG = {
    "window": {"width": 500, "height": 700, "x": -1, "y": -1, "opacity": 0.35},
    "display": {
        "font_size": 15,
        "font_family": "-apple-system, BlinkMacSystemFont, 'Helvetica Neue', sans-serif",
        "mono_font": "'SF Mono', 'Menlo', 'Monaco', monospace",
    },
    "keys": {"modifier": "ctrl"},
}

_config = None

_STATE_PATH = os.path.expanduser("~/.ghost_state.toml")


def load_config():
    global _config
    config_path = os.path.join(os.path.dirname(__file__), "settings.toml")
    if os.path.exists(config_path):
        _config = toml.load(config_path)
    else:
        _config = dict(_DEFAULT_CONFIG)

    # Merge saved window state (position/size from last session)
    state = load_state()
    if state.get("window"):
        for key in ("x", "y", "width", "height", "opacity"):
            if key in state["window"]:
                _config.setdefault("window", {})[key] = state["window"][key]

    return _config


def get_config():
    if _config is None:
        return load_config()
    return _config


def load_state():
    """Load persisted window state."""
    if os.path.exists(_STATE_PATH):
        try:
            return toml.load(_STATE_PATH)
        except Exception:
            return {}
    return {}


def save_state(window_state):
    """Save window state (position, size, opacity) for next session."""
    try:
        state = {"window": window_state}
        with open(_STATE_PATH, "w") as f:
            toml.dump(state, f)
    except Exception:
        pass
