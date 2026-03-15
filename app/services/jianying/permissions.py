from typing import Dict, List


TEMPLATES: Dict[str, Dict[str, List[str]]] = {
    "readonly": {
        "allow": ["utility.parse_media", "utility.find_effects"],
        "deny": [],
    },
    "creator": {
        "allow": [
            "draft.create",
            "track.create",
            "video.add_segment",
            "audio.add_segment",
            "text.add_segment",
        ],
        "deny": ["video.add_effect", "audio.add_effect"],
    },
    "full": {
        "allow": [],
        "deny": [],
    },
}


def get_permission_template(name: str) -> Dict[str, List[str]]:
    return TEMPLATES.get(name, {"allow": [], "deny": []})
